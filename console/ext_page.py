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
from console import confirm, deeplink, ext_action, ext_links, offload, panel, verbs
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
                 caption=t("console.ext_page.version", version=version) if version else "",
                 menu=[panel.Verb(one["label"], to=one["url"], tip=one["tip"])
                       for one in ext_links.drawn(extension, ext_links.opened_at())])

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
                    (panel.FULL, lambda: _actions(offered, name, redraw))]
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
    """One setting, in the control its type asks for. A text field shows the extension's
    refusal under itself and keeps what was typed. A switch or a select has no place for
    one, so it says so in a notice and goes back to what is stored."""
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

    return control(client, field, save)


def control(client: Any, field: dict, save: Callable[..., Awaitable[str]]) -> Any:
    """A field in the control its type asks for, wherever it is kept: `save(value)` writes
    it, and `save(value, under=True)` answers why it was refused where a text field can show
    that. A secret saves `None` for Clear. The same for a setting and for an account."""
    kind = str(field.get("type") or "string")
    value = field.get("value")
    key = str(field.get("key") or "")
    label = str(field.get("label") or key)
    if kind == "switch":
        return panel.switch(bool(value), lambda event: save(bool(event.value)))
    if kind == "select":
        choices = {str(one[0]): str(one[1]) for one in field.get("choices") or []}
        return panel.select(choices, str(value or ""), lambda event: save(event.value))
    if kind == "multi":
        choices = {str(one[0]): str(one[1]) for one in field.get("choices") or []}
        return panel.multi_select(choices, list(value or []),
                                  lambda event: save(list(event.value or [])))
    if kind == "number":
        return panel.number(_figure(value), lambda event: save(event.value), whole=False,
                            low=field.get("min"), high=field.get("max"),
                            unit=str(field.get("unit") or ""), on_leave=True)
    if kind == "path":
        return _path_control(client, field, str(value or ""), lambda text: save(text, under=True))
    if kind == "secret":
        return _secret_control(label, bool(field.get("set")),
                               lambda typed: save(typed, under=True) if typed.strip() else None,
                               lambda: save(None))
    return panel.field(str(value or ""), lambda typed: save(typed, under=True),
                       refuses=True, placeholder=str(field.get("placeholder") or ""))


def _figure(stored: Any) -> float | None:
    try:
        return float(stored)
    except (TypeError, ValueError):
        return None


def _secret_control(label: str, is_set: bool, save_typed: Callable[[str], Any],
                    clear: Callable[[], Awaitable[Any]]) -> Callable[[], None]:
    """A secret is never handed back, so the box starts empty and says whether one is
    held. Saving an empty box would clear it, so only a typed value is saved; Clear is the
    way to empty it, and asks first."""
    @on_page
    async def forget() -> None:
        if await confirm.ask(t("console.ext_page.clear_question", label=label),
                             detail=t("console.ext_page.clear_detail"),
                             confirm=t("console.ext_page.clear"), icon=verbs.CLEAR):
            await clear()

    def draw() -> None:
        with ui.row().classes("items-center gap-2 no-wrap"):
            panel.field("", save_typed, refuses=True, secret=True,
                        placeholder=t("console.ext_page.secret_set" if is_set
                                      else "console.ext_page.secret_not_set"))()
            if is_set:
                panel.action(t("console.ext_page.clear"), forget, icon=verbs.CLEAR,
                             inline=True, hint=t("console.ext_page.clear_hint"))()

    return draw


def _path_control(client: Any, field: dict, value: str,
                  save_text: Callable[[str], Awaitable[str]]) -> Callable[[], None]:
    """A path, saved when the field is left, and at once when Browse chose it."""
    def draw() -> None:
        control = panel.path_field(str(field.get("placeholder") or ""),
                                   wants=str(field.get("wants") or "dir"), value=value,
                                   browse=client.folders)
        state = {"focused": False, "saved": value}

        async def leave() -> None:
            state["focused"] = False
            text = str(control.value or "").strip()
            if text == state["saved"]:
                return
            state["saved"] = text
            said = await save_text(text)
            control.props["error"] = bool(said)
            control.props["error-message"] = said
            control.update()

        control.on("focus", lambda: state.update(focused=True))
        control.on("blur", leave)
        control.on("keydown.enter", lambda: control.run_method("blur"))
        # A value that changes while the field is not focused was chosen in Browse.
        control.on_value_change(lambda: None if state["focused"] else leave())

    return draw


def _actions(offered: list[dict], name: str, redraw: Callable[[], None]) -> None:
    """Redraws once an action has run: it may have changed a setting shown above it."""
    @on_page
    async def run_one(action: dict) -> None:
        if await ext_action.open_action(name, action):
            redraw()

    with ui.element("div").classes("console-slot-actions"):
        for action in offered:
            panel.action(str(action.get("label") or action.get("key") or ""),
                         lambda _e=None, action=action: run_one(action),
                         icon=verbs.RUN, hint=str(action.get("description") or ""))()


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
    "os:updates": "console.ext_page.os_updates",
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
