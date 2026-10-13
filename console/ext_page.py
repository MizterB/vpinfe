"""One extension's own page, in Settings under Extensions: whether it is on, what it is set
to, what it can be asked to do, what it holds and what it can reach.

Core draws all of it. The extension says what its settings are, what its actions are and
what it is holding; none of the treatment is its own, so an extension's page looks like
the Console rather than like whoever wrote it - and it keeps working if that extension
later runs somewhere else.

What it may reach is at the bottom, because that is a question somebody asks once and
nobody asks while using it.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from nicegui import run, ui

from common.extensions import host
from common.failures import why
from common.i18n import t
from console import busy, deeplink, ext_action, offload, panel, verbs
from console.api import ApiClient
from console.on_page import on_page

PREFIX = "extensions."

STATE_WORDS = {host.FAILED: "console.ext_page.failed",
               host.DISABLED: "console.ext_page.stopped"}


def key(name: str) -> str:
    """The Settings page that is this extension's."""
    # Lowercase: the address clean-up lowercases `page`, and a refused extension keeps its
    # folder's name as it was written.
    return (PREFIX + name).lower()


def address(name: str) -> str:
    """Where one extension's page is, for a link from anywhere in the Console."""
    return "/console?" + deeplink.query({"view": "settings", "settings_page": key(name)})


async def read(extension: dict) -> dict[str, Any]:
    """What its settings say, for the draw to use: nothing for one that is not running or
    has none, and `error` for one that would not answer."""
    surfaces = dict(extension.get("surfaces") or {})
    if extension.get("state") != host.LOADED or not surfaces.get("settings"):
        return {}
    base = f"/ext/{extension.get('name')}{surfaces['settings']}"
    try:
        return await offload.io(ApiClient().ext_get, base)
    except Exception as exc:  # noqa: BLE001 - the page says why, never 500s
        return {"error": why(exc)}


def build(extension: dict, settings: dict[str, Any], redraw: Callable[[], None],
          open_this_device: Callable[[], None]) -> None:
    """Draw the page for one extension, from what `read` found."""
    name = str(extension.get("name") or "")
    version = str(extension.get("version") or "")
    running = extension.get("state") == host.LOADED
    surfaces = dict(extension.get("surfaces") or {})
    client = ApiClient()

    panel.header(str(extension.get("display_name") or name),
                 str(extension.get("description") or ""),
                 _findings(extension, open_this_device),
                 caption=t("console.ext_page.version", version=version) if version else "")

    @on_page
    async def flip(event: Any) -> None:
        try:
            await offload.io(client.set_extension_enabled, name, bool(event.value))
        except Exception as exc:  # noqa: BLE001
            ui.notify(t("said.on_failed" if event.value else "said.off_failed"),
                      caption=why(exc), type="negative")
        redraw()

    entries: list[tuple[Any, ...]] = [
        (panel.HEADING, t("console.ext_page.settings")),
        (t("console.ext_page.enabled"),
         panel.switch(bool(extension.get("enabled", True)), flip))]
    if extension.get("reason_key") == host.STARTS_AT_RESTART:
        entries.append(panel.note(t(host.STARTS_AT_RESTART)))
    entries += _setting_rows(client, f"/ext/{name}{surfaces.get('settings', '')}",
                             settings, redraw)
    if extension.get("has_settings") and not running and not _cannot_run(extension):
        entries.append(panel.note(t("console.ext_page.settings_when_running")))

    offered = list(extension.get("actions") or []) if running else []
    if offered:
        entries += [(panel.HEADING, t("word.actions")),
                    (panel.FULL, lambda: _actions(offered, name))]
    if running and surfaces.get("state"):
        entries += [(panel.HEADING, str(surfaces.get("state_label")
                                        or t("console.ext_page.held"))),
                    (panel.FULL, lambda: _state(name, surfaces))]
    entries += _reach_rows(extension)
    panel.facts(ui, entries)


def _cannot_run(extension: dict) -> bool:
    """Not offered on this machine, so it never starts and its settings never show."""
    return extension.get("state") == host.OFF and extension.get("reason_key") in (
        host.WRONG_PLATFORM, host.LACKS_FEATURES)


def _findings(extension: dict, open_this_device: Callable[[], None]
              ) -> list[Callable[[], None]]:
    """What stops it, under the header. Nothing for one that is running or only switched
    off, which the switch already says."""
    state, said = extension.get("state"), str(extension.get("reason") or "")
    if _cannot_run(extension):
        fix = panel.action(t("console.ext_page.open_device"), open_this_device,
                           icon=verbs.GO, hint=t("console.ext_page.open_hint")) \
            if extension.get("reason_key") == host.LACKS_FEATURES else None
        return [_finding(t("console.ext_page.cannot_run"), said, fix)]
    if state in STATE_WORDS:
        return [_finding(t(STATE_WORDS[str(state)]), said)]
    return []


def _finding(line: str, detail: str,
             fix: Callable[[], None] | None = None) -> Callable[[], None]:
    def draw() -> None:
        with ui.element("div").classes("console-attention w-full"):
            ui.icon("error_outline").classes("console-attention-icon")
            with ui.column().classes("gap-0 min-w-0 grow"):
                ui.label(line).classes("console-attention-line")
                if detail:
                    ui.label(detail).classes("console-member-table")
            if fix is not None:
                fix()

    return draw


def _setting_rows(client: Any, base: str, found: dict[str, Any],
                  redraw: Callable[[], None]) -> list[tuple[Any, ...]]:
    """What the extension is configured with, saved as each field is left."""
    if found.get("error"):
        return [panel.intro(t("console.ext_page.list_failed"), hint=str(found["error"]))]
    entries: list[tuple[Any, ...]] = []
    if found.get("help"):
        entries.append(panel.intro(str(found["help"])))
    for field in found.get("fields") or []:
        name = str(field.get("key") or "")
        if not name:
            continue
        entries.append((str(field.get("label") or name),
                        _control(client, base, name, field, redraw)))
        if field.get("help"):
            entries.append(panel.note(str(field["help"])))
    return entries


def _control(client: Any, base: str, key: str, field: dict,
             redraw: Callable[[], None]) -> Any:
    """One setting, in the control its type asks for.

    A text field shows the extension's refusal under itself and keeps what was typed. A
    switch or a select has no place for one, so it says so in a notice and goes back to
    what is stored.
    """
    kind = str(field.get("type") or "string")
    value = field.get("value")

    @on_page
    async def save(new_value: Any, *, under: bool = False) -> str:
        try:
            await run.io_bound(client.ext_put, base, {"values": {key: new_value}})
        except Exception as exc:  # noqa: BLE001
            if under:
                return why(exc)
            ui.notify(t("said.save_failed"), caption=why(exc), type="negative")
            redraw()
            return ""
        redraw()
        return ""

    if kind == "switch":
        return panel.switch(bool(value), lambda event: save(bool(event.value)))
    if kind == "select":
        choices = {str(one[0]): str(one[1]) for one in field.get("choices") or []}
        return panel.select(choices, str(value or ""), lambda event: save(event.value))
    if kind == "secret":
        # Never handed the value. Saving an empty field would clear it.
        return panel.field("", lambda typed: save(typed, under=True) if typed else None,
                           refuses=True,
                           placeholder=t("console.ext_page.secret_set" if field.get("set")
                                         else "console.ext_page.secret_not_set"))
    return panel.field(str(value or ""), lambda typed: save(typed, under=True),
                       refuses=True, placeholder=str(field.get("placeholder") or ""))


def _actions(offered: list[dict], name: str) -> None:
    with ui.element("div").classes("console-slot-actions"):
        for action in offered:
            panel.action(str(action.get("label") or action.get("key") or ""),
                         lambda _e=None, action=action: ext_action.open_action(name, action),
                         icon=verbs.RUN, hint=str(action.get("description") or ""))()


def _state(name: str, surfaces: dict) -> None:
    """What the extension is holding, and the couple of things you can do to a row."""
    card = ui.element("div").classes("console-card w-full")
    base = f"/ext/{name}{surfaces['state']}"
    client = ApiClient()

    async def draw() -> None:
        try:
            found = await offload.io(client.ext_get, base)
        except Exception as exc:  # noqa: BLE001
            card.clear()
            with card:
                panel.line(t("console.ext_page.read_failed"), hint=why(exc))
            return
        card.clear()
        rows = list(found.get("rows") or [])
        with card:
            if not rows:
                # The empty state is the extension's to word: it knows what would be
                # here and why there is none.
                ui.label(str(found.get("empty") or t("console.ext_page.nothing_yet"))) \
                    .classes("console-help")
                return
            for row in rows:
                _row(client, base, row, draw)

    busy.fill(card, draw)


def _row(client: Any, base: str, row: dict, redraw: Callable[[], Awaitable[None]]) -> None:
    @on_page
    async def press(key: str) -> None:
        try:
            await run.io_bound(client.ext_post, f"{base}/{key}",
                               {"id": str(row.get("id") or "")})
        except Exception as exc:  # noqa: BLE001
            ui.notify(t("said.action_failed"), caption=why(exc), type="negative")
            return
        await redraw()

    with ui.row().classes("items-center gap-2 w-full console-member-row"):
        with ui.column().classes("gap-0 min-w-0 grow"):
            with ui.row().classes("items-center gap-2"):
                ui.label(str(row.get("label") or "")).classes("console-setting")
                # A mark on the one row that is different, never on all of them.
                if row.get("mark"):
                    ui.label(str(row["mark"])) \
                        .classes("console-member-chip console-chip-quiet")
            if row.get("detail"):
                ui.label(str(row["detail"])).classes("console-help")
        # Two at most, and that is the whole of what a row can offer.
        for action in list(row.get("actions") or [])[:2]:
            key = str(action.get("key") or "")
            ui.button(str(action.get("label") or ""), icon=verbs.RUN,
                      on_click=lambda _e=None, key=key: press(key)) \
                .props("flat dense no-caps")


# What a scope or capability is called on screen. The wire says `games:write`; a person
# reading a consent list should not have to work out what that lets somebody do.
PLAINLY = {
    "games:read": "console.ext_page.read_library",
    "games:write": "console.ext_page.games_write",
    "players:read": "console.ext_page.see_players",
    "filesystem:read": "console.ext_page.filesystem_read",
    "config:read": "console.ext_page.config_read",
    "config:write": "console.ext_page.config_write",
    "ui:mount": "console.ext_page.ui_mount",
    "config:own": "console.ext_page.config_own",
    "net:outbound": "console.ext_page.reach_internet",
    "proc:spawn": "console.ext_page.proc_spawn",
    "hardware:usb": "console.ext_page.hardware_usb",
    "fs:read": "console.ext_page.read_files",
    "fs:write": "console.ext_page.write_files",
}


def _plainly(name: str) -> str:
    """Its own name is the fallback, never a guess: an unknown scope shown as prose
    somebody invented is worse than one shown as it is."""
    key = PLAINLY.get(name)
    return t(key) if key else name


def _reach_rows(extension: dict) -> list[tuple[Any, ...]]:
    """What this extension may do, for whoever came looking.

    At the bottom and never on the list of what is installed: a scope is what somebody
    agrees to when installing something, and in front of everybody else it is jargon.
    """
    reaches = [_plainly(str(one)) for one in extension.get("scopes") or []]
    uses = [_plainly(str(one)) for one in extension.get("capabilities") or []]
    entries: list[tuple[Any, ...]] = []
    if reaches:
        entries.append((t("console.ext_page.library"), _chips(reaches)))
    if uses:
        entries.append((t("console.ext_page.this_device"), _chips(uses)))
    return [(panel.HEADING, t("console.ext_page.reach_title")), *entries] if entries else []


def _chips(words: list[str]) -> Callable[[], None]:
    def draw() -> None:
        with ui.element("div").classes("console-chips"):
            for word in words:
                ui.label(word).classes("console-tier console-tier--on")

    return draw
