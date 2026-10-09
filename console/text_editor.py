"""The text editor in a file's stage: the only place the Console draws `ui.codemirror`.

The text a person has typed and not saved is a draft, kept per file in the page's state
so it survives selecting something else. Leaving the view or reloading asks about every
draft, and the Assets grid marks the file.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from nicegui import ui
from nicegui.client import Client
from nicegui.elements.codemirror.constants import SUPPORTED_LANGUAGES, SUPPORTED_THEMES

from common.failures import why
from common.i18n import t
from console import appearance, confirm, offload, panel, verbs
from console import dialog as frame
from console.api import ApiError
from console.on_page import on_page

logger = logging.getLogger("vpinfe.console.text_editor")

# The asset kinds whose files this edits, and the language each is highlighted as.
LANGUAGES: dict[str, SUPPORTED_LANGUAGES | None] = {"script": "VBScript", "ini": "Properties files",
                                    "pov": "XML", "scv": None, "patch": "diff",
                                    "readme": "Markdown"}
WRAPPED = frozenset({"readme"})
CHANGED, NO_COPY = "changed", "no_copy"

DARK_EVENT = "hub_editor_dark"
_WATCH_DARK = ("Vue.watch(() => Quasar.Dark.isActive, dark => emitEvent("
               f"{json.dumps(DARK_EVENT)}, dark), {{immediate: true}});")
_THEMES: dict[bool, SUPPORTED_THEMES] = {True: "basicDark", False: "basicLight"}

# Per page: whether Quasar is drawing dark, which the editor's theme follows.
_DARK: dict[Client, bool] = {}


def draft_key(game_id: str, path: str) -> tuple[str, str]:
    return (game_id, path)


def edits(kind: str) -> bool:
    return kind in LANGUAGES


def wire() -> Callable[[Any], None]:
    """Follow the page's dark switch, once as the page is built: the handler for
    `DARK_EVENT`, which the page registers. A mode change repaints through Quasar without
    a rebuild, and the editors already open have to follow it."""
    client = ui.context.client
    _DARK[client] = appearance.QUASAR_DARK.get(appearance.DEFAULT_MODE) is not False

    def changed(event: Any) -> None:
        _DARK[client] = bool(event.args)
        for element in list(client.elements.values()):
            if isinstance(element, ui.codemirror):
                element.theme = _THEMES[_DARK[client]]

    ui.run_javascript(_WATCH_DARK)
    client.on_delete(lambda: _DARK.pop(client, None))
    return changed


def drafts_of(state: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    return state.setdefault("text_drafts", {})


def waiting(state: dict[str, Any]) -> list[str]:
    """The files with changes not saved, as the leave question lists them."""
    return sorted(str(one["name"]) for one in drafts_of(state).values())


def note(state: dict[str, Any]) -> None:
    """After a draft starts or ends: the grid's marks and the browser's reload question."""
    mark = state.get("mark_unsaved_files")
    if callable(mark):
        mark(set(drafts_of(state)))
    flag(state)


def flag(state: dict[str, Any]) -> None:
    """Whether the browser asks before a reload: any draft of either kind."""
    held = bool(state.get("unsaved_rules") or drafts_of(state))
    ui.run_javascript(f"window.__hubUnsaved = {json.dumps(held)};")


def drop_all(state: dict[str, Any]) -> None:
    drafts_of(state).clear()
    note(state)


def show_whole(label: str, text: str) -> None:
    """A file that is not edited, read whole in the full dialog."""
    with frame.opened("", full=True) as dialog:
        with ui.row().classes("items-center gap-2 w-full no-wrap"):
            ui.label(label).classes("console-dialog-title")
            ui.space()
            panel.icon_only(verbs.CLOSE, dialog.close, hint=t("word.close"))
        with ui.element("div").classes("console-editor"):
            with ui.element("div").classes("console-editor-box"):
                ui.codemirror(text, theme=_THEMES[_DARK.get(ui.context.client, True)]).disable()
    dialog.open()


@dataclass
class Held:
    """What the file has on disk as far as the page knows, and whether a save is going.
    One per file on a page, shared by the stage's editor and the enlarged one over it.
    `views` redraw each editor's strip."""

    base: str
    version: str
    saving: bool = False
    views: list[Callable[[], None]] = field(default_factory=list)

    def touch(self) -> None:
        for view in list(self.views):
            view()


def editor(context: dict[str, Any], path: str, label: str, found: dict[str, Any],
           locked: str, locked_help: str = "", *,
           held: Held | None = None) -> None:
    """The file's text in an editor with its strip under it. `found` is what the API read,
    and `locked` the reason it cannot be saved, or blank.

    Enlarge draws a second editor over the same draft, passing the stage's `held` (the text
    and version the file has on disk) so a save in either moves both. The stage's editor is
    not touched until the enlarged one closes, and then it is brought up to date.
    """
    state, library = context["state"], context["library"]
    game_id, kind = context["game_id"], context["kind"]
    enlarged = held is not None
    key = draft_key(game_id, path)
    drafts = drafts_of(state)
    draft = drafts.get(key)
    if held is None:
        held = Held(draft["base"] if draft else found["text"],
                    draft["version"] if draft else found["version"])
    name = str((context.get("game") or {}).get("name") or game_id) + " - " + label
    big: ui.button | None = None

    def current() -> str:
        return str(drafts[key]["text"]) if key in drafts else str(held.base)

    def show() -> None:
        if said.is_deleted:
            return
        dirty = key in drafts
        said.set_visibility(dirty)
        cancel.set_visibility(dirty or not locked)
        cancel.set_enabled(dirty and not held.saving)
        save.set_enabled(dirty and not held.saving)
        if big is not None:
            big.set_enabled(not held.saving)

    def catch_up() -> None:
        if not code.is_deleted and code.value != current():
            code.value = current()
        held.touch()

    def enlarge() -> None:
        with frame.opened("", full=True) as dialog:
            with ui.row().classes("items-center gap-2 w-full no-wrap"):
                with ui.column().classes("gap-0 min-w-0"):
                    ui.label(label).classes("console-dialog-title")
                    ui.label(str((context.get("game") or {}).get("name") or game_id)) \
                        .classes("console-help truncate")
                ui.space()
                panel.icon_only(verbs.CLOSE, dialog.close, hint=t("word.close"))
            editor(context, path, label, found, locked, locked_help, held=held)
        dialog.on("hide", catch_up)
        dialog.open()

    def changed(event: Any) -> None:
        text = str(event.value or "")
        was = key in drafts
        if text == held.base:
            drafts.pop(key, None)
        else:
            drafts[key] = {"text": text, "base": held.base, "version": held.version,
                           "name": name}
        held.touch()
        if was != (key in drafts):
            note(state)

    async def notify_failed(exc: Exception) -> None:
        ui.notify(t("console.workbench.save_failed"), caption=why(exc), type="negative")

    async def write(replace_changed: bool = False, keep_copy: bool = True) -> None:
        if locked or held.saving or key not in drafts:
            return
        text = drafts[key]["text"]
        held.saving = True
        held.touch()
        try:
            await send(text, replace_changed, keep_copy)
        finally:
            held.saving = False
            held.touch()

    async def send(text: str, replace_changed: bool, keep_copy: bool) -> None:
        try:
            done = await offload.io(library.save_asset_text, game_id, path, text,
                                    held.version, replace_changed, keep_copy)
        except ApiError as exc:
            refused = exc.details.get("refused")
            if refused == CHANGED:
                if await confirm.ask(t("console.text_editor.changed"),
                                     detail=t("console.text_editor.changed.help"),
                                     confirm=t("console.text_editor.save_anyway"),
                                     icon=verbs.SAVE, danger=False):
                    await send(text, True, keep_copy)
            elif refused == NO_COPY:
                if await confirm.ask(t("console.text_editor.no_copy"), detail=str(exc),
                                     confirm=t("console.text_editor.save_without"),
                                     icon=verbs.SAVE, danger=False):
                    await send(text, replace_changed, False)
            else:
                await notify_failed(exc)
            return
        except Exception as exc:  # noqa: BLE001 - the draft stays; the save can be tried again
            logger.debug("Could not save %s", path, exc_info=True)
            await notify_failed(exc)
            return
        held.base, held.version = text, done["version"]
        typed = drafts.get(key)
        if typed is not None and typed["text"] != text:
            typed["base"], typed["version"] = held.base, held.version
        else:
            drafts.pop(key, None)
        note(state)
        ui.notify(t("console.text_editor.saved"), type="positive")
        for after in (context.get("saved"), context.get("after_save")):
            if callable(after):
                await after()

    @on_page
    async def save_it() -> None:
        await write()

    @on_page
    async def cancel_it() -> None:
        if held.saving:
            return
        try:
            fresh = await offload.io(library.asset_text, game_id, path)
        except Exception as exc:  # noqa: BLE001 - the text it had is the text it goes back to
            logger.debug("Could not read %s again", path, exc_info=True)
            ui.notify(t("console.workbench.read_failed"), caption=why(exc), type="negative")
        else:
            held.base, held.version = fresh["text"], fresh["version"]
        drafts.pop(key, None)
        code.value = held.base
        held.touch()
        note(state)

    with ui.element("div").classes("console-editor"):
        with ui.element("div").classes("console-editor-box"):
            code = ui.codemirror(
                current(), language=LANGUAGES[kind],
                theme=_THEMES[_DARK.get(ui.context.client, True)],
                line_wrapping=kind in WRAPPED, on_change=changed,
                keymap={"Mod-s": save_it})
            if locked:
                code.disable()
        with ui.row().classes("items-center gap-2 w-full no-wrap console-editor-strip"):
            said = ui.label(t("word.not_saved")).classes("console-draft-state") \
                .tooltip(t("console.text_editor.not_saved.help"))
            if locked:
                panel.line(locked, hint=locked_help, classes="console-help truncate")
            with ui.row().classes("items-center gap-1 no-wrap ml-auto"):
                if not enlarged:
                    big = panel.icon_only(verbs.ENLARGE, enlarge, hint=t("word.enlarge"))
                cancel = panel.draft_button(t("word.cancel"), cancel_it, icon=verbs.CANCEL,
                                            hint=t("console.text_editor.cancel.help"))
                save = panel.draft_button(t("word.save"), save_it, icon=verbs.SAVE,
                                          hint=t("console.text_editor.save.help"),
                                          primary=True)
            if locked:
                save.set_visibility(False)
    held.views.append(show)
    show()
