"""Folders to Add From on Settings > Library > Folders: one row per folder with its state,
a way to add one and a way to remove one with Undo."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from functools import partial
from typing import Any

from nicegui import ui

from common import config_schema, path_state
from common.failures import why
from common.i18n import t
from console import dialog as frame
from console import library_folders, offload, panel, undo, verbs
from console.data import Library
from console.on_page import on_page

SECTION, KEY = "media", "browse_dirs"


def listed(value: Any) -> list[str]:
    """The setting as the folders it names, whether the API sent a list or the line a
    config file holds."""
    items = value if isinstance(value, list) else str(value or "").split(",")
    return [one for one in (str(item).strip() for item in items) if one]


async def read(library: Library, values: dict[str, Any]) -> Block:
    """The folders `values` name, and what the disk says about each."""
    held = listed((values.get(SECTION) or {}).get(KEY))
    asks = [path_state.Ask(path) for path in held]
    found = await offload.io(path_state.look_all, asks) if asks else []
    return Block(library, held, dict(zip(held, found, strict=True)))


class Block:
    """The folders as the page drew them, and what the person can do to one."""

    def __init__(self, library: Library, held: list[str],
                 states: dict[str, path_state.PathState],
                 rerender: Callable[[], None] = lambda: None) -> None:
        self.library = library
        self.held = held
        self.states = states
        self.rerender = rerender
        self._turn = asyncio.Lock()

    @on_page
    async def _save(self, folders: list[str]) -> bool:
        try:
            await offload.io(self.library.put_config, {SECTION: {KEY: folders}})
        except Exception as exc:  # noqa: BLE001 - the reason belongs on the page
            ui.notify(t("said.save_failed"), caption=why(exc), type="negative")
            return False
        self.held = folders
        return True

    @on_page
    async def add(self, path: str) -> None:
        async with self._turn:
            if path in self.held or not await self._save([*self.held, path]):
                return
        self.rerender()

    @on_page
    async def remove(self, path: str) -> None:
        """Acts at once and offers Undo, which puts the folder back where it was."""
        async with self._turn:
            if path not in self.held:
                return
            at = self.held.index(path)
            if not await self._save([one for one in self.held if one != path]):
                return

        @on_page
        async def back() -> None:
            async with self._turn:
                values = await offload.io(self.library.config_values)
                now = listed((values.get(SECTION) or {}).get(KEY))
                if path not in now:
                    now.insert(min(at, len(now)), path)
                    await offload.io(self.library.put_config, {SECTION: {KEY: now}})
                    self.held = now
            self.rerender()

        undo.offer(t("console.browse_folders.removed", path=path), back)
        self.rerender()


def rows(block: Block) -> list[tuple[Any, Any]]:
    """What stands in the settings page for the setting itself: the line under its
    heading, one row per folder, and the way to add one."""
    option = config_schema.option(SECTION, KEY)
    found: list[tuple[Any, Any]] = [panel.lede(option.description)] if option else []
    if block.held:
        found.append((panel.FULL, partial(_list, block)))
    found.append((panel.FULL, partial(_buttons, block)))
    return found


def _list(block: Block) -> None:
    with ui.column().classes("gap-0 w-full"):
        for path in block.held:
            _row(block, path)


def _row(block: Block, path: str) -> None:
    with ui.row().classes("items-center gap-2 w-full no-wrap console-member-row"):
        ui.label(path).classes("console-fact-value grow truncate min-w-0").tooltip(path)
        if chip := state_chip(block.states.get(path)):
            word, level, tip = chip
            ui.label(word).classes(f"console-tier console-tier--{level} shrink-0") \
                .tooltip(tip)
        with ui.element("div").classes("console-row-action"):
            panel.icon_action(t("word.remove"), partial(block.remove, path),
                              icon=verbs.REMOVE, hint=t("word.remove"))()


def state_chip(found: path_state.PathState | None) -> tuple[str, str, str] | None:
    """(word, level, tooltip) for a folder that cannot be read: the rest need no mark. A
    folder files are only taken from does not have to be writable."""
    if found is None or found.state in (path_state.OK, path_state.READ_ONLY):
        return None
    word = library_folders.state_of({"state": found.state})
    return word, library_folders.STATE_TIERS.get(found.state, "bad"), found.reason


def _buttons(block: Block) -> None:
    panel.action(t("console.folders.add_folder"), partial(add_dialog, block),
                 icon=verbs.ADD, hint=t("console.browse_folders.add_help"))()


def refusal(wanted: str, listed_now: list[str]) -> str | None:
    """Why `wanted` cannot be added, or None."""
    if not wanted:
        return t("console.folders.needs_name")
    if wanted in listed_now:
        return t("console.browse_folders.already")
    return None


def add_dialog(block: Block) -> None:
    held: dict[str, Any] = {}

    def draw_folder() -> None:
        held["folder"] = panel.path_field(
            placeholder="/path/to/a/folder", wants="dir", width="w-full",
            browse=block.library.folders)

    async def keep() -> None:
        wanted = (held["folder"].value or "").strip()
        if reason := refusal(wanted, block.held):
            held["folder"].props["error"] = True
            held["folder"].props["error-message"] = reason
            return
        box.close()
        await block.add(wanted)

    with frame.opened(t("console.browse_folders.add_title")) as box:
        panel.facts(ui, [(t("word.folder"), draw_folder)])
        with frame.footer():
            frame.cancel(box.close)
            go = frame.answer(t("word.add"), keep, icon=verbs.ADD)
    frame.focus(box, held["folder"])
    frame.enter_presses(go)
    box.open()
