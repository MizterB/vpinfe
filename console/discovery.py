"""Discovery: every game the catalog lists, against what the library holds.

One row per catalog entry. A kind VPS lists for the entry reads Have where the library
holds one and Missing where it does not; a kind VPS does not list is blank, and so is
every cell while the library has never been counted. A game that is not in the library
is Missing on every kind its entry lists.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from nicegui import ui

from common.failures import why
from common.i18n import t
from console import (
    busy,
    confirm,
    deeplink,
    game_tables,
    import_dialog,
    offload,
    panel,
    verbs,
    views,
    when,
)
from console import grid as grid_module
from console.data import Library
from console.on_page import on_page

logger = logging.getLogger("vpinfe.console.discovery")

SCOPE = "discovery"
GAMES_ADDRESS = "/console?" + deeplink.query({"view": "games"})
OWN_ADDRESS = "/console?" + deeplink.query({"view": "discovery"})

HAVE = "have"
MISSING = "missing"
YES = "yes"
NO = "no"

# VPS's own key for the kind, the field the row carries it in, and the word it is called.
KINDS: tuple[tuple[str, str, str], ...] = (
    ("tableFiles", "kind_table", "word.table"),
    ("b2sFiles", "kind_backglass", "asset.kind.backglass.label"),
    ("romFiles", "kind_rom", "asset.kind.rom.label"),
    ("pupPackFiles", "kind_pup_pack", "asset.kind.pup_pack.label"),
    ("altColorFiles", "kind_color", "console.discovery.color_kind"),
    ("altSoundFiles", "kind_altsound", "asset.kind.altsound.label"),
    ("povFiles", "kind_pov", "asset.kind.pov.label"),
    ("ruleFiles", "kind_rules", "guide.kind.rule_sheet.label"),
    ("wheelArtFiles", "kind_wheel", "media.kind.wheel.label"),
    ("topperFiles", "kind_topper", "media.kind.topper.label"),
)

_POLLS = 600
_POLL_S = 1.0


def _cell_class() -> str:
    return (f"params => params.value === '{HAVE}' ? 'console-have'"
            f" : params.value === '{MISSING}' ? 'console-lack' : ''")


def _yes_no() -> list[dict[str, Any]]:
    return [{"value": YES, "label": t("word.yes")}, {"value": NO, "label": t("word.no")}]


def _kind_column(listed_as: str, field: str, word: str) -> dict[str, Any]:
    label = t(word)
    options: dict[str, Any] = {
        ":cellClass": _cell_class(),
        **grid_module.choice_filter([{"value": HAVE, "label": t("console.view.have")},
                                     {"value": MISSING, "label": t("console.view.missing")}])}
    return grid_module.column(field, label,
                              help=t("console.discovery.kind.help", kind=label), **options)


COLUMNS = [
    grid_module.identifier("name", t("word.name"), 260, pinned="left",
                           help=t("console.discovery.name.help")),
    grid_module.column("in_library", t("console.discovery.in_library"),
                       help=t("console.discovery.in_library.help"),
                       **grid_module.choice_filter(_yes_no())),
    *(_kind_column(*kind) for kind in KINDS),
    grid_module.column("gap", t("console.discovery.gaps"),
                       help=t("console.discovery.gaps.help"),
                       **{":cellClass": _cell_class(),
                          **grid_module.choice_filter(
                              [{"value": MISSING, "label": t("console.view.missing")}])}),
    grid_module.column("manufacturer", t("word.manufacturer"), help=t("help.who_made_it")),
    grid_module.year_column("year", t("word.year"), help=t("help.year_released")),
    grid_module.column("game_type", t("console.games.type"),
                       help=t("console.games.type.help")),
    grid_module.list_column("themes", t("console.games.game_themes"), 200,
                            help=t("console.games.themes.help")),
]

_ALL = [definition["field"] for definition in COLUMNS]
_KIND_FIELDS = [field for _listed, field, _word in KINDS]
_BY_NAME = ({"colId": "name", "sort": "asc", "sortIndex": 0},)

VIEWS: dict[str, list[str] | views.Preset] = {
    "console.view.everything": views.Preset(
        columns=tuple(_ALL), sort=_BY_NAME,
        help=t("console.view.discovery_everything.help")),
    "console.view.not_held": views.Preset(
        columns=("name", "in_library", *_KIND_FIELDS, "manufacturer", "year"), sort=_BY_NAME,
        filters={"in_library": {"values": [NO]}},
        help=t("console.view.not_held.help")),
    "console.view.with_gaps": views.Preset(
        columns=("name", *_KIND_FIELDS, "gap", "manufacturer", "year"), sort=_BY_NAME,
        filters={"in_library": {"values": [YES]}, "gap": {"values": [MISSING]}},
        help=t("console.view.with_gaps.help")),
}


def _state(listed: bool, counted: bool, in_library: bool, held: bool) -> str:
    if not listed or not counted:
        return ""
    return HAVE if in_library and held else MISSING


def rows(found: dict[str, Any]) -> list[dict[str, Any]]:
    """One grid row per named catalog entry. `found` is what `GET /library/discovery` answers."""
    counted = bool(found.get("counted"))
    out = []
    for entry in found.get("rows") or []:
        if not (entry.get("name") or "").strip():
            continue
        listed = set(entry.get("listed") or [])
        held = set(entry.get("held") or [])
        in_library = bool(entry.get("in_library"))
        row: dict[str, Any] = {
            "id": entry["vps_id"],
            "name": entry.get("name") or "",
            "manufacturer": entry.get("manufacturer") or "",
            "year": game_tables.year_of(entry.get("year")),
            "game_type": entry.get("type") or "",
            "themes": list(entry.get("themes") or []),
            "url": entry.get("url") or "",
            "in_library": "" if not counted else (YES if in_library else NO),
            "is_in_library": in_library and counted,
            "listed": sorted(listed),
        }
        states = []
        for listed_as, field, _word in KINDS:
            row[field] = _state(listed_as in listed, counted, in_library, listed_as in held)
            states.append(row[field])
        row["gap"] = MISSING if MISSING in states else ""
        out.append(row)
    return out


def row_of(library: Library, vps_id: str) -> dict[str, Any] | None:
    return next((one for one in rows(library.catalog()) if one["id"] == vps_id), None)


def summary(shown: list[dict[str, Any]], counted: bool) -> str:
    if not counted:
        return t("console.discovery.summary", count=len(shown))
    return t("console.discovery.summary_counted", count=len(shown),
             held=sum(1 for one in shown if one["is_in_library"]))


def unmatched_games(library: Library) -> int:
    return sum(1 for game in library.game_rows() if game.get("vps_unmatched"))


def build(library: Library, state: dict[str, Any], on_select: Callable[[Any], Any],
          rerender: Callable[[], None]) -> None:
    body = ui.column().classes("w-full grow min-h-0 gap-0")
    busy.fill(body, lambda: _fill(library, body, state, on_select, rerender))


async def _read(library: Library) -> dict[str, Any]:
    if library.has_catalog():
        return library.catalog()
    return await offload.io(library.load_catalog)


def _unmatched_line(count: int, show: Callable[[], Awaitable[Any]] | None) -> None:
    with ui.row().classes("w-full items-center gap-2 px-3 pb-2 shrink-0"):
        text = t("console.discovery.unmatched", count=count)
        if show is None:
            ui.label(text).classes("text-xs console-label")
        else:
            panel.link(text, to=GAMES_ADDRESS, on_click=show)()


def _never_counted_line(count_now: Callable[[], Awaitable[Any]]) -> None:
    with ui.row().classes("w-full items-center gap-2 px-3 pb-2 shrink-0"):
        ui.label(t("console.discovery.never_counted")).classes("text-xs console-label")
        panel.link(t("console.discovery.count_now"), to=OWN_ADDRESS, on_click=count_now)()


async def _fill(library: Library, body: Any, state: dict[str, Any],
                on_select: Callable[[Any], Any], rerender: Callable[[], None]) -> None:
    # Imported here: `games` imports modules that import this one.
    from console.games import view_control

    try:
        found = await _read(library)
    except Exception as exc:  # noqa: BLE001 - this page says why, never 500s
        with body:
            panel.facts(ui, [panel.intro(t("console.discovery.read_failed"), hint=why(exc))])
        return
    counted = bool(found.get("counted"))
    built = rows(found)
    columns = list(COLUMNS)
    by_id = {row["id"]: row for row in built}
    on_screen: dict[str, Any] = {"ids": [row["id"] for row in built], "selected": 0}
    unmatched = await offload.io(unmatched_games, library)
    show_unmatched = state.get("show_unmatched")

    with body:
        with ui.row().classes(
                "w-full items-center gap-2 px-3 py-2 mb-2 shrink-0 console-panel console-grid-bar"):
            bar = panel.grid_bar()
            wire_views, _picker, showing, describe = view_control(
                library, SCOPE, VIEWS, _ALL, columns, bar=bar)
            describe()
            with bar.top, panel.bar_end():
                search = panel.search(t("console.discovery.search"))
            with bar.bottom, panel.bar_end():
                count = ui.label(summary(built, counted)).classes("text-xs console-label")
                show_selection = panel.selection_menu(
                    t("console.discovery.actions_selected"), lambda: picked(),
                    lambda chosen: acts(library, chosen, after,
                                        check=bool(grid_module.hidden_count(table))),
                    lambda: table.run_grid_method("deselectAll"))
                ui.label(_counted_text(found)).classes("text-xs console-label")
                panel.refresh(lambda: count_again(), t("console.discovery.count_again"))

        if not built:
            panel.facts(ui, [panel.intro(t("console.discovery.empty"))])
        if unmatched:
            _unmatched_line(unmatched, show_unmatched if callable(show_unmatched) else None)
        if not counted:
            _never_counted_line(lambda: count_again())

        def counted_text() -> str:
            if on_screen["selected"]:
                return grid_module.selection_said(
                    table, on_screen["selected"],
                    t("console.discovery.selected", picked=on_screen["selected"],
                      shown=len(on_screen["ids"])))
            return summary([by_id[one] for one in on_screen["ids"] if one in by_id], counted)

        def on_selected(chosen_rows: list[dict[str, Any]]) -> None:
            on_screen["selected"] = len(chosen_rows)
            show_selection(bool(chosen_rows))
            count.text = counted_text()

        def fill_menu(row: dict | None) -> None:
            one = by_id.get(str((row or {}).get("id") or ""))
            if one is None:
                menu.clear()
                return
            on = grid_module.menu_rows(table, one)
            panel.verb_menu(menu, one["name"] if len(on) == 1
                            else t("console.discovery.selected_n", count=len(on)),
                            panel.for_selection(
                                acts(library, on, after,
                                     check=len(on) > 1 and bool(grid_module.hidden_count(table))),
                                len(on)))

        async def on_header_context(col_id: str | None) -> None:
            await grid_module.header_menu(menu, table, columns, col_id)

        with ui.element("div").classes("w-full grow min-h-0 flex flex-col"):
            table: ui.aggrid = grid_module.build(columns, built, SCOPE,
                                                 on_select_rows=on_selected,
                                                 on_context=fill_menu,
                                                 on_header_context=on_header_context,
                                                 view_of=showing)
            menu: ui.context_menu = ui.context_menu()
        grid_module.on_row_focus(
            SCOPE, lambda event: on_select(by_id.get(grid_module.focused_row(event))))
        search.on_value_change(
            lambda: table.run_grid_method("setGridOption", "quickFilterText",
                                          search.value or ""))
        table.on("modelUpdated", lambda: _counted_in_view())
        wire_views(table)

    def picked() -> list[dict[str, Any]]:
        return [by_id[str(r["id"])] for r in grid_module.selection(table)
                if str(r.get("id")) in by_id]

    async def _counted_in_view() -> None:
        drawn = await ui.run_javascript(_SHOWN % table.id) or []
        on_screen["ids"] = [str(one) for one in drawn]
        count.text = counted_text()

    @on_page
    async def after() -> None:
        """The rows read again from the library, the grid and the pane put right."""
        if not library.has_catalog():
            await offload.io(library.load_catalog)
        fresh = rows(library.catalog())
        built[:] = fresh
        by_id.clear()
        by_id.update({row["id"]: row for row in fresh})
        table.run_grid_method("setGridOption", "rowData", fresh)
        chosen = state.get("entry")
        if chosen and state.get("workbench"):
            await on_select(by_id.get(chosen))

    @on_page
    async def count_again() -> None:
        """Count the library against the catalog, and read the answer when it is in."""
        if not await recount(library, state):
            return
        library.forget_catalog()
        rerender()

    state["redraw_discovery"] = after


_SHOWN = """(() => {
  const ids = [];
  getElement(%d).api.forEachNodeAfterFilterAndSort(node => ids.push(node.data.id));
  return ids;
})()"""


def _counted_text(found: dict[str, Any]) -> str:
    if not found.get("counted"):
        return ""
    return t("console.discovery.counted", when=when.ago(found["counted"], inline=True))


@on_page
async def recount(library: Library, state: dict[str, Any]) -> bool:
    """Start the count and wait for it. False where it failed, which is said on screen."""
    try:
        job = await offload.io(library.recount_catalog)
    except Exception as exc:  # noqa: BLE001
        ui.notify(t("console.discovery.count_failed"), caption=why(exc), type="negative")
        return False
    watch = state.get("watch_jobs")
    if callable(watch):
        watch()
    for _ in range(_POLLS):
        await asyncio.sleep(_POLL_S)
        try:
            found = await offload.io(library.job, str(job.get("id") or ""))
        except Exception:  # noqa: BLE001 - the footer line still reports it
            return False
        if found.get("state") == "running":
            continue
        if found.get("state") == "failed":
            ui.notify(t("console.discovery.count_failed"),
                      caption=str(found.get("error") or ""), type="negative")
            return False
        return True
    return False


def acts(library: Library, rows_on: list[dict[str, Any]],
         after: Callable[[], Awaitable[None]], *, check: bool = False) -> list[panel.Verb]:
    """What can be done to the entries a menu is open on. `check` is where the selection
    holds rows a search, a filter or a view leaves out, which `add` asks about first.

    Add waits for a count: before one, every entry reads as not in the library."""
    absent = [one for one in rows_on if one["in_library"] == NO]
    uncounted = any(not one["in_library"] for one in rows_on)
    hint = "" if absent else t(
        "console.discovery.count_first" if uncounted else "console.discovery.already_in")
    return [panel.Verb(
        t("console.discovery.add"),
        (lambda: add(library, absent, after, check=check)) if absent else None,
        hint=hint, icon=verbs.ADD)]


@on_page
async def add(library: Library, entries: list[dict[str, Any]],
              after: Callable[[], Awaitable[None]], *, check: bool = False) -> None:
    """Make a game with no tables from each entry, in the place new games go."""
    if len(entries) > 1 or check:
        if not await confirm.ask(
                t("console.discovery.add_many", count=len(entries)),
                detail=t("console.discovery.add_detail"),
                lines=[one["name"] for one in entries], confirm=t("console.discovery.add"),
                icon=verbs.ADD, danger=False):
            return
    where = await import_dialog.ask_where(library)
    if where is None:
        return
    made = 0
    for entry in entries:
        try:
            await offload.io(library.add_game_from_vps, entry["id"], where)
        except Exception as exc:  # noqa: BLE001 - one refusal does not end the rest
            logger.warning("console: could not add %s", entry["id"], exc_info=True)
            ui.notify(t("console.discovery.add_failed", name=entry["name"]),
                      caption=why(exc), type="negative")
            continue
        made += 1
    if made:
        ui.notify(t("console.discovery.added", count=made), type="positive")
        await after()


def _chip(text: str, level: str) -> None:
    ui.label(text).classes(f"console-tier console-tier--{level}")


async def details(context: dict[str, Any]) -> None:
    row = context["discovery"]
    counted = bool(context["library"].catalog().get("counted"))
    entries: list[tuple[Any, Any]] = [
        (t("word.manufacturer"), row["manufacturer"] or "-"),
        (t("word.year"), str(row["year"] or "-")),
        (t("console.games.type"), row["game_type"] or "-"),
        (t("console.games.game_themes"), ", ".join(row["themes"]) or "-")]
    if counted:
        entries.append((t("console.discovery.in_library"),
                        panel.state(t("word.yes"), "on") if row["is_in_library"]
                        else panel.state(t("word.no"), "warn")))
    if row["url"]:
        entries.append((t("console.discovery.on_vps"),
                        panel.link_out(t("console.discovery.open_on_vps"), to=row["url"],
                                       hint=t("console.vps_match.open_in_vps"))))
    with ui.column().classes("gap-0 console-form w-full min-w-0"):
        panel.facts(ui, entries)


def _record_line(record: dict[str, Any]) -> None:
    told = " · ".join(part for part in (
        str(record.get("version") or ""),
        ", ".join(str(name) for name in (record.get("authors") or [])[:2])) if part)
    with ui.row().classes("items-center gap-2 w-full no-wrap console-member-row"):
        ui.label(told or t("console.discovery.unnamed_file")).classes("grow min-w-0 truncate")
        if record.get("url"):
            panel.out(to=str(record["url"]), hint=t("console.vps_match.open_in_vps"))()


async def files(context: dict[str, Any]) -> None:
    """What the entry lists, a block per kind, each saying whether the library has one."""
    row, library = context["discovery"], context["library"]
    listed = [kind for kind in KINDS if kind[0] in row["listed"]]
    with ui.column().classes("gap-0 w-full min-w-0"):
        if not listed:
            panel.line(t("console.discovery.lists_nothing"))
            return
        for listed_as, field, word in listed:
            try:
                records = await offload.io(library.vps_releases, row["id"], listed_as)
            except Exception as exc:  # noqa: BLE001 - the other kinds still draw
                logger.warning("console: could not read %s for %s", listed_as, row["id"],
                               exc_info=True)
                records = []
                panel.line(t("console.discovery.files_failed"), hint=why(exc))
            with ui.row().classes("items-center gap-2 w-full no-wrap console-section-bar"):
                ui.label(t(word)).classes("console-fact-value grow min-w-0")
                if row[field] == HAVE:
                    _chip(t("console.view.have"), "on")
                elif row[field] == MISSING:
                    _chip(t("console.view.missing"), "warn")
            for record in records:
                _record_line(record)
