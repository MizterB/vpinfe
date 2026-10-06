"""The theme sources on Settings > Themes, and the dialog that adds one.

A source is a list of themes (`themes.registries`) or a single theme
(`themes.repositories`). The person pastes an address and the server's check says which
it is, so nobody has to know the kind first. Every change is written to the key its kind
names and then read again, so the Themes page lists what the sources now offer.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from functools import partial
from typing import Any

from nicegui import ui

from common import config_schema
from common.failures import why
from common.i18n import t
from common.online import theme_source_checks as checks
from console import arrange, offload, panel, undo, verbs
from console import dialog as frame
from console.data import Library
from console.on_page import on_page

logger = logging.getLogger("vpinfe.console.theme_sources")

SECTION = "themes"
LISTS, THEMES = "registries", "repositories"

# One event per group, because a move arrives as {from, to} and nothing else.
MOVED = {LISTS: "hub_theme_lists_moved", THEMES: "hub_theme_themes_moved"}

_DEBOUNCE_MS = 400

_CHIP_KEY = {checks.NOT_A_THEME: "not_theme"}


def default_list() -> str:
    found = config_schema.option(SECTION, LISTS)
    return str(found.default) if found is not None else ""


def _held(sources: dict[str, Any], group: str) -> list[str]:
    return [str(one["address"]) for one in sources.get(group) or []]


@on_page
async def _save(library: Library, group: str, addresses: list[str]) -> bool:
    try:
        await offload.io(library.put_config, {SECTION: {group: addresses}})
    except Exception as exc:  # noqa: BLE001 - the reason belongs on the page
        ui.notify(t("console.settings.save_failed"), caption=why(exc), type="negative")
        return False
    return True


@on_page
async def _read_again(library: Library) -> None:
    """The themes, read from the sources as they now are. Without it the Themes page keeps
    listing what the last read found until the next one."""
    checking = ui.notification(t("console.settings.checking_themes"), spinner=True,
                               timeout=None)
    try:
        await offload.io(library.themes, True)
    except Exception as exc:  # noqa: BLE001 - the rows say which source failed
        ui.notify(t("console.settings.check_failed"), caption=why(exc), type="negative")
    finally:
        checking.dismiss()


@on_page
async def _change(library: Library, group: str, addresses: list[str]) -> bool:
    if not await _save(library, group, addresses):
        return False
    await _read_again(library)
    return True


class Block:
    """The sources as the page drew them, and what the person can do to one."""

    def __init__(self, library: Library, sources: dict[str, Any],
                 rerender: Callable[[], None]) -> None:
        self.library = library
        self.rerender = rerender
        self.addresses = {LISTS: _held(sources, LISTS), THEMES: _held(sources, THEMES)}
        self.stale = False
        self._turn = asyncio.Lock()

    async def _commit(self, group: str, addresses: list[str]) -> bool:
        """Write one group, holding the turn. Once one has gone through, the rows on screen
        are the old ones until the page is drawn again, so a drop from them means nothing."""
        if not await _change(self.library, group, addresses):
            return False
        self.addresses[group] = addresses
        self.stale = True
        return True

    async def moved(self, group: str, event: Any) -> None:
        """One row put where it was dropped."""
        try:
            source, target = int(event["from"]), int(event["to"])
        except (KeyError, TypeError, ValueError):
            return
        async with self._turn:
            shown = list(self.addresses[group])
            if (self.stale or source == target
                    or not (0 <= source < len(shown) and 0 <= target < len(shown))):
                return
            shown.insert(target, shown.pop(source))
            await self._commit(group, shown)
        self.rerender()

    async def step(self, group: str, address: str, by: int) -> None:
        at = self.addresses[group].index(address)
        await self.moved(group, {"from": at, "to": at + by})

    @on_page
    async def remove(self, group: str, source: dict[str, Any]) -> None:
        address = str(source["address"])
        async with self._turn:
            held = list(self.addresses[group])
            if address not in held:
                return
            at = held.index(address)
            if not await self._commit(group, [one for one in held if one != address]):
                return

        @on_page
        async def back() -> None:
            async with self._turn:
                now = _held(await offload.io(self.library.theme_sources), group)
                if address not in now:
                    now.insert(min(at, len(now)), address)
                    await offload.io(self.library.put_config, {SECTION: {group: now}})
                    await _read_again(self.library)
            self.rerender()

        undo.offer(t("console.theme_sources.removed_list" if group == LISTS
                     else "console.theme_sources.removed_theme", name=str(source["name"])),
                   back)
        self.rerender()


async def moved(state: dict[str, Any], group: str, event: Any) -> None:
    """A drop in one of the groups, for the block the page drew last."""
    block = state.get("theme_sources")
    if block is not None:
        await block.moved(group, event.args)


def rows(block: Block, sources: dict[str, Any]) -> list[tuple[Any, Any]]:
    """What stands in for the two address fields: a row per group and the one Add."""
    lists, themes = sources.get(LISTS) or [], sources.get(THEMES) or []
    entries: list[tuple[Any, Any]] = [
        (t("console.theme_sources.lists"), _group(block, LISTS, lists)),
        panel.note(t("console.theme_sources.lists.help"))]
    if themes:
        entries += [(t("console.theme_sources.themes"), _group(block, THEMES, themes)),
                    panel.note(t("console.theme_sources.themes.help"))]
    entries.append((panel.ASIDE, panel.action(
        t("console.theme_sources.add"), partial(add_source, block.library, block.rerender),
        icon=verbs.ADD, hint=t("console.theme_sources.add.help"))))
    return entries


def _group(block: Block, group: str, found: list[dict[str, Any]]) -> Callable[[], None]:
    def draw() -> None:
        if not found:
            with ui.element("div").classes("console-fact-edit"):
                ui.label(t("console.theme_sources.no_lists")) \
                    .classes("console-fact-value truncate min-w-0")
                panel.action(t("console.theme_sources.add_default"),
                             partial(add_default, block.library, block.rerender),
                             icon=verbs.ADD, inline=True,
                             hint=t("console.theme_sources.add_default.help"))()
            return
        with ui.column().classes("gap-0 w-full").props(f'data-arrange="{MOVED[group]}"'):
            for at, one in enumerate(found):
                _row(block, group, one, at, len(found))
        if len(found) > 1:
            ui.run_javascript(arrange.SCRIPT)

    return draw


def _row(block: Block, group: str, source: dict[str, Any], at: int, of: int) -> None:
    address = str(source["address"])
    with ui.row().classes("items-center gap-2 w-full no-wrap console-member-row"):
        if of > 1:
            ui.icon("drag_indicator").classes("console-drag-handle") \
                .props("tabindex=0 role=button") \
                .tooltip(t("console.workbench.drag_hint"))
        with ui.column().classes("gap-0 grow min-w-0"):
            _name(source)
            if said := _detail(group, source):
                line = ui.label(said).classes("console-member-table")
                if took := source.get("took") or []:
                    line.tooltip(t("console.theme_sources.took", count=_count(
                        int(source["count"])), taken=len(took), names=", ".join(took)))
        if source.get("level"):
            chip = ui.label(_word(source)).classes(
                f"console-tier console-tier--{source['level']} shrink-0")
            if source.get("reason"):
                chip.tooltip(str(source["reason"]))
        if of > 1:
            _moves(block, group, address, at, of)

        async def remove() -> None:
            await block.remove(group, source)

        with ui.element("div").classes("console-row-action"):
            panel.icon_action(t("word.remove"), remove, icon=verbs.REMOVE,
                              hint=t("word.remove"))()


def _name(source: dict[str, Any]) -> None:
    name, link = str(source["name"]), str(source.get("link") or "")
    if link:
        panel.link_out(name, to=link)()
    else:
        ui.label(name).classes("console-fact-value truncate min-w-0")


def _moves(block: Block, group: str, address: str, at: int, of: int) -> None:
    """Move Up and Move Down, because a drag needs a way to do the same without a pointer."""
    _button, menu = panel.menu_button(verbs.MORE, t("console.theme_sources.move"))
    with menu:
        if at > 0:
            panel.menu_entry(t("console.theme_sources.move_up"),
                             lambda: block.step(group, address, -1),
                             mark=lambda: ui.icon(verbs.UP))
        if at < of - 1:
            panel.menu_entry(t("console.theme_sources.move_down"),
                             lambda: block.step(group, address, 1),
                             mark=lambda: ui.icon(verbs.DOWN))


def _count(count: int) -> str:
    return t("console.theme_sources.count_one" if count == 1
             else "console.theme_sources.count_many", count=count)


def _detail(group: str, source: dict[str, Any]) -> str:
    """The line under a source's name: how many themes a list has, or which version of its
    one theme, and where."""
    if group == LISTS:
        count = int(source.get("count") or 0)
        return _count(count) if count else ""
    where = str(source.get("display") or "")
    parts = [where if where != source["name"] else "",
             str(source.get("version") or ""),
             t("console.theme_sources.pinned", ref=source["pinned"])
             if source.get("pinned") else ""]
    return " · ".join(part for part in parts if part)


def _word(source: dict[str, Any]) -> str:
    """What the chip says. Only a source with something wrong has one."""
    state = str(source["state"])
    if state == checks.NEEDS_VPINFE:
        needs = str(source.get("needs") or "")
        return (t("console.theme_sources.state.needs_version", needs=needs) if needs
                else t("console.theme_sources.state.needs_vpinfe"))
    return t(f"console.theme_sources.state.{_CHIP_KEY.get(state, state)}")


@on_page
async def add_default(library: Library, done: Callable[[], None]) -> None:
    """The VPinFE Theme List put back, in one press."""
    held = _held(await offload.io(library.theme_sources), LISTS)
    stock = default_list()
    if stock not in held and await _change(library, LISTS, [*held, stock]):
        done()


async def add_source(library: Library, done: Callable[[], None]) -> None:
    """The dialog: one address, checked as it settles, and Add once the check allows it."""
    found: dict[str, Any] = {}
    asked = {"count": 0}
    shown: dict[str, Any] = {}

    def draw_address() -> None:
        control = frame.field(placeholder="https://")
        control.on_value_change(lambda: check(str(control.value or "").strip()))
        shown["address"] = control

    def draw_result() -> None:
        shown["result"] = ui.column().classes("gap-1 w-full")

    async def check(address: str) -> None:
        asked["count"] += 1
        mine = asked["count"]
        found.clear()
        shown["add"].disable()
        result = shown["result"]
        result.clear()
        if not address:
            return
        await asyncio.sleep(_DEBOUNCE_MS / 1000)
        if mine != asked["count"] or result.is_deleted:
            return
        with result:
            ui.label(t("console.theme_sources.checking")).classes("console-help")
        try:
            said = await offload.io(library.check_theme_source, address)
        except Exception as exc:  # noqa: BLE001 - the dialog says why
            said = {}
            reason = why(exc)
        else:
            reason = ""
        if mine != asked["count"] or result.is_deleted:
            return
        result.clear()
        with result:
            _verdict(said, reason)
        if said.get("addable"):
            found.update(said)
            shown["add"].enable()

    @on_page
    async def add() -> None:
        if not found:
            return
        box.close()
        group, address = str(found["group"]), str(found["address"])
        held = _held(await offload.io(library.theme_sources), group)
        if address not in held and await _change(library, group, [*held, address]):
            done()

    with frame.opened(t("console.theme_sources.add_title")) as box:
        panel.facts(ui, [
            (t("console.theme_sources.address"), draw_address),
            (panel.ASIDE, draw_result),
            panel.note(t("console.theme_sources.trust"))])
        with frame.footer():
            frame.cancel(box.close)
            shown["add"] = frame.answer(t("word.add"), add, icon=verbs.ADD)
    shown["add"].disable()
    frame.focus(box, shown["address"])
    frame.enter_presses(shown["add"])
    box.open()


def _verdict(said: dict[str, Any], failure: str) -> None:
    """What the address turned out to be, then anything the person should know before
    adding it."""
    if failure:
        ui.label(failure).classes("console-help text-negative")
        return
    state = str(said.get("state") or "")
    if state not in checks.REFUSED and state != checks.NOT_ANSWERING:
        _what_it_is(said)
    if state != checks.READY:
        with ui.row().classes("items-center gap-2 no-wrap"):
            if said.get("level"):
                ui.label(_word(said)).classes(
                    f"console-tier console-tier--{said['level']} shrink-0")
            ui.label(str(said.get("reason") or "")).classes("console-help")
    if state in checks.REFUSED:
        return
    if names := said.get("replaces") or []:
        ui.label(t("console.theme_sources.replaces", names=", ".join(names))) \
            .classes("console-help")
    if took := said.get("took") or []:
        ui.label(t("console.theme_sources.took_note_one" if len(took) == 1
                   else "console.theme_sources.took_note_many", count=len(took))) \
            .classes("console-help")
    if installs := said.get("installs") or []:
        ui.label(t("console.theme_sources.installs", names=", ".join(installs))) \
            .classes("console-help")


def _what_it_is(said: dict[str, Any]) -> None:
    if said.get("kind") == checks.LIST:
        count = int(said.get("count") or 0)
        lead = t("console.theme_sources.is_list_one" if count == 1
                 else "console.theme_sources.is_list", count=count)
        name = ""
    else:
        lead = t("console.theme_sources.is_theme")
        name = " ".join(part for part in (str(said.get("name") or ""),
                                          str(said.get("version") or "")) if part)
    with ui.row().classes("items-center gap-2 no-wrap"):
        ui.label(" · ".join(part for part in (lead, name) if part)) \
            .classes("console-fact-value")
        if said.get("link"):
            panel.link_out(str(said.get("display") or ""), to=str(said["link"]))()
