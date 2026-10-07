"""The frontend themes this install knows, and which one plays.

Active first, then installed, then the rest, which is the order somebody scans in: what
am I running, what could I switch to without downloading, what else is there.

**Configure renders the theme's own schema, not ours.** A theme declares its options in
its own manifest and this install has no opinion about what they can be. What a person
chooses is kept *outside* the theme package - an update deletes the package, and values
written into it were reset by the next update every time.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from functools import partial
from typing import Any
from urllib.parse import urlparse

from nicegui import run, ui

from common.failures import why
from common.i18n import t
from console import (
    backup_rows,
    busy,
    confirm,
    grid,
    mediaview,
    offload,
    panel,
    renderers,
    settings,
    theme_card,
    theme_sources,
    thumbnails,
    verbs,
    views,
    when,
)
from console.data import Library
from console.on_page import on_page

logger = logging.getLogger("vpinfe.console.themes")

SCOPE = "console.themes.columns"

ACTIVE, UPDATE, INSTALLED, AVAILABLE = "active", "update", "installed", "available"

# What each state is called, and the tier of the ones worth noticing.
STATES = {
    ACTIVE: {"label": t("console.themes.active"), "tier": "on"},
    UPDATE: {"label": t("console.themes.update_available"), "tier": "warn"},
    INSTALLED: {"label": t("word.installed")},
    AVAILABLE: {"label": t("console.themes.not_installed")},
}

# What a theme says it is made for.
MADE_FOR = {"cab": t("console.themes.cabinet"), "desktop": t("console.themes.desktop"),
            "both": t("console.themes.both")}

COLUMNS: list[dict[str, Any]] = [
    grid.identifier("name", t("console.themes.theme"), 320, subtitle="said",
                    help=t("console.themes.theme.help"),
                    picture="preview", glyph=theme_card.GLYPH, frame=thumbnails.PREVIEW),
    grid.column("status", t("word.status"), 150, help=t("console.themes.status.help"),
                **grid.choice_filter([{"value": key, "label": one["label"]}
                                      for key, one in STATES.items()], formatted=True),
                **renderers.drawable("state", states=STATES)),
    grid.column("updated", t("console.themes.updated"), 150,
                help=t("console.themes.updated.help"), **when.cell("updated")),
    grid.column("made_for", t("console.themes.made_for"), 150,
                help=t("console.themes.made_for.help"),
                **grid.choice_filter([{"value": key, "label": label}
                                      for key, label in MADE_FOR.items()])),
    grid.column("author", t("word.author"), 140, help=t("console.themes.author.help")),
    grid.column("registry", t("console.themes.list"), 200,
                help=t("console.themes.list.help")),
    grid.column("repository", t("console.themes.repository"), 280,
                help=t("console.themes.repository.help")),
]
_ALL = [one["field"] for one in COLUMNS]
_SHOWN = ("name", "status", "updated", "made_for")

VIEWS: dict[str, list[str] | views.Preset] = {
    "console.view.themes_all": views.Preset(
        columns=_SHOWN, help=t("console.view.themes_all.help")),
    "console.view.themes_active": views.Preset(
        columns=_SHOWN, filters={"status": {"values": [ACTIVE]}},
        help=t("console.view.themes_active.help")),
    "console.view.themes_installed": views.Preset(
        columns=_SHOWN, filters={"status": {"values": [ACTIVE, UPDATE, INSTALLED]}},
        help=t("console.view.themes_installed.help")),
    "console.view.themes_available": views.Preset(
        columns=_SHOWN, filters={"status": {"values": [AVAILABLE]}},
        help=t("console.view.themes_available.help")),
}


def status(theme: dict[str, Any]) -> str:
    if theme.get("active"):
        return ACTIVE
    if theme.get("update_available"):
        return UPDATE
    return INSTALLED if theme.get("installed") else AVAILABLE


def repo_name(url: str) -> str:
    """`owner/repo` for a repository on GitHub or Forgejo, or a file in one; the address
    itself for anything else."""
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    in_one = len(parts) > 2 and (parsed.netloc == "raw.githubusercontent.com"
                                 or parts[2] == "raw")
    return "/".join(parts[:2]) if len(parts) == 2 or in_one else url


def repo_page(url: str) -> str:
    parsed = urlparse(url)
    named = repo_name(url)
    if named == url:
        return url
    host = "github.com" if parsed.netloc == "raw.githubusercontent.com" else parsed.netloc
    return f"{parsed.scheme or 'https'}://{host}/{named}"


def rows(themes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [when.said(_row(theme), "updated") for theme in themes]


def _row(theme: dict[str, Any]) -> dict[str, Any]:
    return {"id": theme["key"], "name": theme.get("name") or theme["key"],
            "preview": theme.get("preview") or "", "status": status(theme),
            "made_for": theme.get("type") if theme.get("type") in MADE_FOR else "",
            "author": str(theme.get("author") or ""),
            "registry": repo_name(str(theme["registry"])) if theme.get("registry") else "",
            "repository": repo_name(str(theme["url"])) if theme.get("url") else "",
            "updated": str(theme.get("updated") or ""),
            "said": theme_card.said(theme), grid.NO_MENU: _has_no_acts(theme)}


def _has_no_acts(theme: dict[str, Any]) -> bool:
    """True exactly when `acts` returns nothing."""
    return bool(theme.get("installed") and theme.get("active")
                and not theme.get("update_available"))


def build(library: Library, state: dict[str, Any],
          on_select: Callable[[dict | None], Any], redraw: Callable[[], None]) -> None:
    body = ui.column().classes("w-full grow min-h-0 gap-0")
    busy.fill(body, lambda: _fill(library, state, on_select, redraw, body, refresh=False))


async def _fill(library: Library, state: dict[str, Any],
                on_select: Callable[[dict | None], Any], redraw: Callable[[], None],
                body: Any, refresh: bool) -> None:
    # Deferred: `games` imports `workbench`, and `workbench` imports this module for its
    # sections.
    from .games import view_control

    try:
        found = await offload.io(library.themes, refresh)
    except Exception as exc:  # noqa: BLE001 - this page says why, never 500s
        body.clear()
        with body:
            panel.facts(ui, [panel.intro(t("console.themes.themes_failed"),
                                         hint=why(exc))])
        return

    built = rows(list(found.get("themes") or []))
    by_id = {row["id"]: row for row in built}
    sources = await _sources(library)
    body.clear()
    if not built:
        with body:
            _finding(sources)
            panel.facts(ui, _empty(library, redraw, sources))
        return
    with body:
        _finding(sources)
        with ui.row().classes("w-full items-center gap-2 px-3 py-2 mb-2 shrink-0 "
                              "console-panel console-grid-bar"):
            bar = panel.grid_bar()
            wire_views, _picker, showing, describe = view_control(
                library, SCOPE, VIEWS, _ALL, COLUMNS, bar=bar)
            describe()
            with bar.top, panel.bar_end():
                search = panel.search(t("console.themes.search_themes"))
            with bar.bottom, panel.bar_end():
                count = ui.label(_themes_said(len(built), len(built))) \
                    .classes("text-xs console-label")
                panel.refresh(lambda: _fill(library, state, on_select, redraw, body,
                                            refresh=True),
                              t("console.themes.check_updates"))
                panel.add_action([(t("console.themes.add_theme"),
                                   lambda: theme_sources.add_source(library, redraw))],
                                 empty=False)

        async def on_header_context(col_id: str | None) -> None:
            await grid.header_menu(menu, table, COLUMNS, col_id)

        by_key = {str(one["key"]): one for one in found.get("themes") or []}

        async def redrawn() -> None:
            redraw()

        def fill(row: dict | None) -> None:
            theme = by_key.get(str((row or {}).get("id") or ""))
            if theme is None:
                menu.clear()
                return
            panel.verb_menu(menu, str(theme.get("name") or theme["key"]),
                            acts(library, theme, redrawn))

        with ui.element("div").classes("w-full grow min-h-0 flex flex-col"):
            table = grid.build(COLUMNS, built, SCOPE, on_context=fill,
                               on_header_context=on_header_context, view_of=showing)
            menu = ui.context_menu()
        grid.on_row_focus(SCOPE, lambda event: on_select(by_id.get(grid.focused_row(event))))

        async def counted() -> None:
            seen = await table.run_grid_method("getDisplayedRowCount")
            count.text = _themes_said(seen if isinstance(seen, int) else len(by_id),
                                      len(by_id))

        table.on("modelUpdated", counted)

        async def refresh_rows() -> None:
            fresh = rows(list((await offload.io(library.themes, False)).get("themes") or []))
            by_id.clear()
            by_id.update({row["id"]: row for row in fresh})
            table.run_grid_method("setGridOption", "rowData", fresh)
            grid.redraw(table)

        state["refresh_themes"] = refresh_rows
        wire_views(table)
        search.on_value_change(
            lambda: table.run_grid_method("setGridOption", "quickFilterText",
                                          search.value or ""))


async def _sources(library: Library) -> dict[str, Any] | None:
    """The sources as they last answered, or None when they cannot be read. Their trouble
    is a finding on this page, so a failure to read them leaves the grid as it is."""
    try:
        return await offload.io(library.theme_sources)
    except Exception:  # noqa: BLE001
        logger.warning("console: the theme sources could not be read", exc_info=True)
        return None


def _finding(sources: dict[str, Any] | None) -> None:
    unread = sum(1 for group in (theme_sources.LISTS, theme_sources.THEMES)
                 for one in (sources or {}).get(group) or [] if one.get("level") == "bad")
    if not unread:
        return
    with ui.row().classes("w-full items-center gap-2 px-3 py-2 mb-2 shrink-0 console-panel"):
        ui.label(t("console.themes.sources_bad_one" if unread == 1
                   else "console.themes.sources_bad_many", count=unread)) \
            .classes("console-help text-warning")
        panel.link(t("console.themes.sources_review"), to=settings.address_for("themes"))()


def _empty(library: Library, redraw: Callable[[], None],
           sources: dict[str, Any] | None) -> list[tuple[Any, Any]]:
    """Nothing to list: no source to ask, or sources that offered nothing. Sources that
    could not be read (None) are neither, so only the first line is drawn."""
    add = (panel.ASIDE, panel.action(
        t("console.theme_sources.add"), partial(theme_sources.add_source, library, redraw),
        icon=verbs.ADD, hint=t("console.theme_sources.add.help")))
    if sources is None:
        return [panel.intro(t("console.themes.none_listed"))]
    if any(sources.get(group) for group in (theme_sources.LISTS, theme_sources.THEMES)):
        return [panel.intro(t("console.themes.none_listed")), add]
    return [panel.intro(t("console.themes.no_sources")), add,
            (panel.ASIDE, panel.action(
                t("console.theme_sources.add_default"),
                partial(theme_sources.add_default, library, redraw),
                icon=verbs.ADD, hint=t("console.theme_sources.add_default.help")))]


def _themes_said(shown: int, total: int) -> str:
    if shown == total:
        return t("console.themes.themes", count=total)
    return t("console.themes.themes_of", shown=shown, count=total)


def _found(context: dict[str, Any]) -> dict[str, Any]:
    return context["theme"]


async def changed(context: dict[str, Any]) -> None:
    """The grid's row and this panel, after an act changed the theme."""
    refresh = context["state"].get("refresh_themes")
    if callable(refresh):
        await refresh()
    await context["rebuild"]()


async def details(context: dict[str, Any]) -> None:
    theme = _found(context)
    library = context["library"]
    with ui.column().classes("gap-0 console-form w-full min-w-0"):
        with ui.element("div").classes("console-theme-hero"):
            if theme.get("preview"):
                ui.image(theme["preview"]).classes("w-full")
                ui.button(icon=verbs.ENLARGE,
                          on_click=lambda: mediaview.open_image(
                              str(theme["preview"]), str(theme.get("name") or ""))) \
                    .props("flat dense round size=sm") \
                    .classes("console-slot-zoom").tooltip(t("word.enlarge"))
            else:
                ui.icon(theme_card.GLYPH).classes("console-theme-hero-empty")
        entries: list[tuple[Any, Any]] = []
        if theme.get("description"):
            entries.append(panel.intro(str(theme["description"])))
        entries.append((t("word.status"), _status_value(context, library, theme)))
        if theme_card.version_said(theme):
            entries.append((t("word.version"), theme_card.version_said(theme)))
        if theme.get("author"):
            entries.append((t("word.author"), str(theme["author"])))
        if theme.get("updated"):
            entries.append((t("console.themes.updated"), when.ago(theme["updated"])))
        if theme.get("type") in MADE_FOR:
            entries.append((t("console.themes.made_for"), MADE_FOR[str(theme["type"])]))
        if theme.get("registry"):
            registry = str(theme["registry"])
            entries.append((t("console.themes.list"),
                            panel.link_out(repo_name(registry), to=repo_page(registry))))
        if theme.get("url"):
            entries.append((t("console.themes.repository"),
                            panel.link_out(repo_name(str(theme["url"])), to=str(theme["url"]))))
        else:
            entries += [(t("console.themes.repository"), t("word.none")),
                        panel.note(t("console.themes.no_source"))]
        copies = await backup_rows.listed(library, "theme", str(theme["key"]))
        if copies:
            entries.append((t("console.section.backups"), backup_rows.row(
                library, "theme", str(theme["key"]), str(theme.get("name") or theme["key"]),
                copies, lambda: changed(context), back_up_now=False)))
        changes = changes_worth_showing(theme)
        if changes:
            entries += [(panel.HEADING, t("console.themes.whats_new")),
                        panel.intro(changes)]
        panel.facts(ui, entries)


# Text a theme template ships as its changelog, which is not news about any theme.
_PLACEHOLDERS = frozenset({"what changed in this version?"})


def changes_worth_showing(theme: dict[str, Any]) -> str:
    said = str(theme.get("change_log") or "").strip()
    if not said or said.lower() in _PLACEHOLDERS:
        return ""
    return said if not theme.get("installed") or theme.get("update_available") else ""


def acts(library: Library, theme: dict[str, Any],
         after: Callable[[], Any]) -> list[panel.Verb]:
    """What can be done to one theme. The first of these is also drawn beside its
    status, as the one act that state is waiting on."""
    key = theme["key"]
    offered: list[panel.Verb] = []
    if not theme["installed"]:
        offered.append(panel.Verb(t("console.themes.install"),
                                  lambda: _install(library, key, after), icon=verbs.FETCH))
    elif theme["update_available"]:
        offered.append(panel.Verb(t("console.themes.update"),
                                  lambda: _install(library, key, after), icon=verbs.UPDATE))
    if theme["installed"] and not theme["active"]:
        offered.append(panel.Verb(t("word.make_active"),
                                  lambda: _activate(library, theme, after),
                                  icon=verbs.ACTIVATE))
        # Not on the active one: uninstalling it would leave the frontend with no theme
        # at all, and the way out of that is a config file.
        offered.append(panel.Verb(t("word.uninstall"),
                                  lambda: _uninstall(library, theme, after), danger=True))
    return offered


# The one act `_status_value` offers, named by its icon rather than by which of Install,
# Update or Make Active it is - `acts` already picked that.
_STATUS_HINTS = {
    verbs.FETCH: "console.themes.install.help",
    verbs.UPDATE: "console.themes.update.help",
    verbs.ACTIVATE: "console.themes.make_active.help",
}


def _status_value(context: dict[str, Any], library: Library,
                  theme: dict[str, Any]) -> Callable[[], None]:
    state_of = STATES[status(theme)]

    async def again() -> None:
        await changed(context)

    waiting = next((one for one in acts(library, theme, again) if not one.danger), None)

    def draw() -> None:
        with ui.row().classes("items-center gap-2 no-wrap"):
            panel.state(state_of["label"], state_of.get("tier", "off"))()
            if waiting is not None:
                panel.action(waiting.label, waiting.run, icon=waiting.icon, inline=True,
                             hint=t(_STATUS_HINTS.get(waiting.icon, "")))()
    return draw


async def settings_section(context: dict[str, Any]) -> None:
    theme = _found(context)
    library = context["library"]
    try:
        found = await offload.io(library.theme_options, theme["key"])
    except Exception as exc:  # noqa: BLE001
        panel.facts(ui, [panel.intro(t("console.themes.settings_failed"),
                                     hint=why(exc))])
        return
    options = list(found.get("options") or [])
    values = dict(found.get("values") or {})
    wanted = {option["key"]: values.get(option["key"], option.get("default"))
              for option in options}

    @on_page
    async def keep() -> bool:
        try:
            await run.io_bound(library.save_theme_options, theme["key"], dict(wanted))
        except Exception as exc:  # noqa: BLE001
            ui.notify(t("console.themes.save_failed"), caption=why(exc),
                      type="negative")
            return False
        return True

    with ui.column().classes("gap-0 console-form w-full"):
        entries: list[tuple[Any, Any]] = []
        if found.get("description"):
            entries.append(panel.intro(str(found["description"])))
        panel.facts(ui, entries + _rows(options, wanted, keep, browse=library.folders))


@on_page
async def _install(library: Library, key: str, again: Callable[[], Any]) -> None:
    downloading = ui.notification(t("console.themes.downloading", key=key),
                                  spinner=True, timeout=None)
    try:
        await run.io_bound(library.install_theme, key)
    except Exception as exc:  # noqa: BLE001
        ui.notify(t("console.themes.install_failed"), caption=why(exc), type="negative")
        return
    finally:
        downloading.dismiss()
    ui.notify(t("console.themes.installed", key=(key)), type="positive")
    await again()


@on_page
async def _activate(library: Library, theme: dict[str, Any], again: Callable[[], Any]) -> None:
    """Saved, and left for the next start: nothing restarts."""
    try:
        await run.io_bound(library.activate_theme, theme["key"])
    except Exception as exc:  # noqa: BLE001
        ui.notify(t("console.themes.activate_failed"), caption=why(exc),
                  type="negative")
        return
    ui.notify(t("console.themes.activated", name=theme["name"]),
            type="positive")
    await again()


@on_page
async def _uninstall(library: Library, theme: dict[str, Any],
                     again: Callable[[], Any]) -> None:
    if not await confirm.ask(
            t("console.themes.uninstall", name=theme["name"]),
            detail=t("console.themes.uninstall_detail"),
            confirm=t("word.uninstall"), icon=verbs.UNINSTALL):
        return
    try:
        await run.io_bound(library.remove_theme, theme["key"])
    except Exception as exc:  # noqa: BLE001
        ui.notify(t("said.action_failed"), caption=why(exc), type="negative")
        return
    ui.notify(t("console.themes.uninstalled", name=theme["name"]), type="positive")
    await again()


def _rows(options: list[dict[str, Any]], wanted: dict[str, Any],
          keep: Callable[[], Any],
          browse: Callable[..., dict] | None = None) -> list[tuple]:
    """The theme's options as settings rows, through the same grammar Settings uses.

    A theme's settings are settings. A control vocabulary of their own is a second
    answer to a question already answered, and the two drift the moment one gains a
    type - so the dispatch lives in one place and this only says what a theme option
    *is*.
    """
    rows: list[tuple] = []
    for option in options:
        key = option["key"]
        rows.append((str(option.get("name") or key),
                     settings.control_for(_as_option(option), _shown(option, wanted),
                                          _saver(option, wanted, keep), browse=browse)))
        said = " ".join(part for part in (str(option.get("description") or ""),
                                          _expected(option, _kind(option))) if part)
        rows.append(panel.note(said))
    return rows


def _shown(option: dict[str, Any], wanted: dict[str, Any]) -> Any:
    """What goes into the control. A json option holds an object, and a field handed one
    renders Python's idea of it - single quotes and all - which is not what the theme
    would read back."""
    value = wanted.get(option["key"])
    if _kind(option) == "json":
        return _as_text(value)
    return value


def _kind(option: dict[str, Any]) -> str:
    """The names the theme service normalizes to, not the ones they look like: it emits
    "boolean", and a renderer checking for "bool" draws a switch as a text field."""
    return str(option.get("type") or "text")


def _as_option(option: dict[str, Any]) -> dict[str, Any]:
    """A theme option in the shape the shared control dispatch reads.

    An unknown type becomes text rather than nothing: a theme declaring something this
    install has never heard of should be editable badly rather than not at all.
    """
    kind = _kind(option)
    if kind == "boolean":
        return {"type": "bool"}
    if kind == "number":
        return {"type": "number", "min": option.get("min"), "max": option.get("max"),
                "step": option.get("step")}
    if kind == "select":
        return {"type": "choice", "choices": _choices(option)}
    if kind in ("textarea", "json"):
        return {"type": "text", "lines": 4}
    return {"type": "text"}


def _saver(option: dict[str, Any], wanted: dict[str, Any],
           keep: Callable[[], Any]) -> Callable[[Any], Any]:
    """Into the theme's values, and written. A json option is parsed first, and one that
    does not parse is said and not written."""
    key = option["key"]

    async def save(value: Any) -> bool:
        if _kind(option) == "json":
            text = str(value or "").strip()
            try:
                wanted[key] = json.loads(text) if text else None
            except json.JSONDecodeError as exc:
                ui.notify(t("console.themes.not_json", name=option.get("name") or key),
                          caption=why(exc), type="warning")
                return False
        else:
            wanted[key] = value
        return bool(await keep())

    return save


def _choices(option: dict[str, Any]) -> Any:
    found = option.get("options") or []
    if found and isinstance(found[0], dict):
        return {one.get("value"): str(one.get("label") or one.get("value"))
                for one in found}
    return [one for one in found]


def _as_text(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, indent=2)
    return "" if value is None else str(value)


def _expected(option: dict[str, Any], kind: str) -> str:
    """What a valid answer looks like. The Manager UI says this under every option and
    it is the difference between a field and a guess.

    No full stop: each of these is a fragment naming a shape, not a sentence about it.
    """
    if kind == "boolean":
        return ""
    if kind == "number":
        low, high = option.get("min"), option.get("max")
        if low is not None and high is not None:
            return t("console.themes.type_range", low=(low), high=(high))
        return t("console.themes.expected_number")
    if kind == "select":
        return t("console.themes.type_choice", count=len(option.get("options") or []))
    if kind == "textarea":
        return t("console.themes.type_lines")
    if kind == "json":
        return t("console.themes.type_json")
    return t("console.themes.expected_text")
