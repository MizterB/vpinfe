"""Asking Discovery about releases: the search that finds a name, and the page of one
author's, maker's or theme's work.

The question a page asks is `common.online.vps_question`'s. The grids filter on their
columns, and the saved views are Discovery's.
"""

from __future__ import annotations

import html
from collections.abc import Awaitable, Callable, Mapping, Sequence
from functools import partial
from typing import Any

from nicegui import ui

from common.i18n import t
from common.online import vps_find, vps_question
from manager.kit import panel, thumbnails, verbs

SINCE_DAYS = (("manager.discovery.ask.week", 7), ("manager.discovery.ask.fortnight", 14),
              ("manager.discovery.ask.month", 30))
WALL_AT_FIRST = 60
FORMAT_DEFAULT = "VPX"

SUBJECT_KEY = {"author": "by", "maker": "maker", "theme": "theme"}
SUBJECT_WORD = {"author": "word.author", "maker": "word.manufacturer",
                "theme": "manager.discovery.ask.theme"}


class Suggest:
    """The search box, with what its letters could mean listed under it as you type: a
    person under any name they are credited as, a maker, a theme, a game. Arrow keys move
    and Enter chooses."""

    def __init__(self, box: ui.input, find: Callable[[str], dict[str, list[dict[str, Any]]]],
                 choose: Callable[[str, dict[str, Any]], Awaitable[None]]) -> None:
        self.box, self.find, self.choose = box, find, choose
        self.items: list[tuple[str, dict[str, Any]]] = []
        self.at = -1
        self.list = ui.element("div").classes("manager-suggest")
        self.list.set_visibility(False)
        box.props("debounce=120 autocomplete=off")
        box.on_value_change(lambda event: self.typed(event.value or ""))
        box.on("keydown.down.prevent", lambda: self.move(1))
        box.on("keydown.up.prevent", lambda: self.move(-1))
        box.on("keydown.enter", self.enter)
        box.on("keydown.escape", self.hide)
        box.on("blur", self.hide)

    def typed(self, text: str) -> None:
        found = self.find(text)
        self.items = [(group, one) for group in vps_find.GROUPS for one in found.get(group, [])]
        self.at = -1
        self.draw()

    def hide(self) -> None:
        self.items, self.at = [], -1
        self.list.set_visibility(False)

    def move(self, step: int) -> None:
        if self.items:
            self.at = (self.at + step) % len(self.items)
            self.draw()

    async def enter(self) -> None:
        if 0 <= self.at < len(self.items):
            await self.pick(*self.items[self.at])

    async def pick(self, group: str, one: dict[str, Any]) -> None:
        self.hide()
        await self.choose(group, one)

    def draw(self) -> None:
        self.list.clear()
        self.list.set_visibility(bool(self.items))
        if not self.items:
            return
        last = ""
        with self.list:
            for position, (group, one) in enumerate(self.items):
                if group != last:
                    last = group
                    ui.label(t(f"manager.discovery.ask.group.{group}")) \
                        .classes("manager-suggest-head")
                with ui.element("div").classes(
                        "manager-suggest-row" + (" manager-suggest-row--on"
                                                 if position == self.at else "")) as row:
                    ui.label(one["name"]).classes("grow truncate")
                    if one.get("via"):
                        ui.label(t("manager.discovery.ask.as", name=one["via"])) \
                            .classes("manager-help")
                    if group != vps_find.GAME:
                        ui.label(str(one["count"])).classes("manager-help")
                # mousedown, not click: the box would lose focus first and hide the list
                # before the press reached the row.
                row.on("mousedown.prevent", lambda _e=None, g=group, o=one: self.pick(g, o))


def _tile(row: Mapping[str, Any], fits: int, held: int, on_open: Callable[[], Any]) -> None:
    with ui.element("div").classes("manager-wall-tile").props(
            "tabindex=0 role=button") as tile:
        src = str(row.get(thumbnails.FIELD) or "")
        with ui.element("div").classes("manager-wall-picture"):
            if src:
                ui.html(f'<img src="{html.escape(src)}" alt="" loading="lazy">')
        ui.label(str(row["name"])).classes("manager-wall-name truncate")
        if fits:
            ui.label(t("manager.discovery.ask.held_of", held=held, count=fits)).classes(
                "manager-wall-note manager-have" if held == fits else "manager-wall-note")
    tile.on("click", on_open).on("keydown.enter", on_open)


def opening_on(state: Mapping[str, Any], tab: str) -> dict[str, Any] | None:
    """The view a page sent this tab to, if it did. It stays through a redraw of the tab,
    and the tab calls `drop_opening` once the user picks another view."""
    one = state.get("opening")
    return one if one and one.get("tab") == tab else None


def drop_opening(state: dict[str, Any], tab: str) -> None:
    if opening_on(state, tab):
        state.pop("opening", None)


def subject_question(subject: Mapping[str, str]) -> dict[str, Any]:
    """What a subject page is about, as a question: the author, maker or theme alone."""
    kind, name = subject["type"], subject["name"]
    return {"by": [name]} if kind == "author" else {SUBJECT_KEY[kind]: name}


def page(*, subject: Mapping[str, str], state: dict[str, Any],
         people: Sequence[Mapping[str, Any]], rows: Sequence[Mapping[str, Any]],
         releases: Mapping[str, Any], kinds: Mapping[str, str], address: str,
         open_game: Callable[[Mapping[str, Any]], Awaitable[None]],
         leave: Callable[[], Awaitable[None]],
         see_all: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
    """The page of one author's, maker's or theme's work, drawn into the current container.

    What it shows is a question like any other, built from the subject and the page's own
    choices, so See All hands the grid the same one."""
    kind, name = subject["type"], subject["name"]
    base = subject_question(subject)
    own = state.setdefault("page", {})
    if own.get("for") != (kind, name):
        own.clear()
        own["for"] = (kind, name)
    by_id = {str(row["id"]): row for row in rows}
    holder = ui.column().classes("w-full grow min-h-0 gap-0")
    tallies: dict[str, Any] = {}

    def asked() -> dict[str, Any]:
        return vps_question.clean({
            **base, "kind": own.get("kind", ""), "owned": own.get("owned", ""),
            "held": own.get("held", ""), "mod": "originals" if own.get("originals") else "",
            "format": own.get("format", [])})

    def rebuild(**changes: Any) -> None:
        own.update(changes)
        draw()

    def to_kind(listing: str) -> None:
        rebuild(kind=listing, limit=WALL_AT_FIRST,
                format=[FORMAT_DEFAULT] if listing == "tableFiles" else [])

    def counted() -> dict[str, int]:
        """The releases each kind has under the page's other choices. Only Tables takes the
        Format choice; another kind asked for Format would count nothing."""
        formats = own.get("format", []) if own.get("kind") == "tableFiles" else [FORMAT_DEFAULT]
        key = (own.get("owned", ""), own.get("held", ""), bool(own.get("originals")),
               tuple(formats))
        if tallies.get("key") != key:
            others = {**asked(), "format": []}
            tallies["key"] = key
            tallies["counts"] = {
                listing: sum(vps_question.games_fitting(
                    {**others, "kind": listing, **({"format": formats}
                                                   if listing == "tableFiles" else {})},
                    people, rows, releases).values()) for listing in kinds}
        return tallies["counts"]

    def draw() -> None:
        per_kind = counted()
        tabs = {"": t("word.all"),
                **{listing: t("manager.discovery.ask.tab", kind=t(kinds[listing]), count=count)
                   for listing, count in per_kind.items() if count}}
        if own.get("kind") not in tabs and own.get("kind"):
            own["kind"], own["format"] = "", []
        picked = asked()
        found = vps_question.games_found(picked, people, rows, releases)
        fitting = {game: len(one) for game, one in found.items()}
        holder.clear()
        with holder:
            with ui.row().classes("w-full items-center gap-2 px-3 py-2 shrink-0"):
                panel.link(t("word.back"), to=address, on_click=leave)()
            with ui.element("div").classes("manager-card manager-subject mx-3 mb-2 shrink-0"):
                ui.label(name).classes("manager-subject-name")
                ui.label(t(SUBJECT_WORD[kind])).classes("manager-help")
                person = next((one for one in people if one["name"] == name), None)
                if kind == "author" and person and person["aliases"]:
                    ui.label(t("manager.discovery.ask.also",
                               names=", ".join(person["aliases"]))).classes("manager-help")
            with ui.row().classes("w-full items-center gap-3 px-3 pb-2 shrink-0"):
                panel.segmented(tabs, own.get("kind", "") if own.get("kind", "") in tabs
                                else "", lambda event: to_kind(event.value))
                ui.label(t("manager.discovery.ask.page_count",
                           count=sum(fitting.values()))) \
                    .classes("text-xs manager-label")
            with ui.row().classes("w-full items-center gap-4 px-3 pb-2 shrink-0"):
                ui.label(t("manager.discovery.ask.for")).classes("manager-label")
                panel.segmented({"": t("manager.discovery.ask.all_games"),
                                 "yes": t("manager.discovery.ask.owned_yes")},
                                own.get("owned", ""), lambda event: rebuild(owned=event.value))
                ui.label(t("manager.discovery.ask.show")).classes("manager-label")
                panel.segmented({"": t("word.all"),
                                 "missing": t("manager.discovery.ask.missing")},
                                own.get("held", ""), lambda event: rebuild(held=event.value))
                if kind == "author":
                    ui.label(t("manager.discovery.ask.originals")).classes("manager-label")
                    panel.switch(bool(own.get("originals")),
                                 lambda event: rebuild(originals=event.value))()
                if own.get("kind") == "tableFiles":
                    panel.segmented({FORMAT_DEFAULT: FORMAT_DEFAULT,
                                     "": t("manager.discovery.ask.all_formats")},
                                    FORMAT_DEFAULT if own.get("format") else "",
                                    lambda event: rebuild(
                                        format=[event.value] if event.value else []))
                with ui.element("div").classes("ml-auto"):
                    panel.action(t("manager.discovery.ask.see_all"),
                                 partial(see_all, picked), icon=verbs.OPEN_OUT,
                                 hint=t("manager.discovery.ask.see_all.help"))()
            wall(found)

    def wall(found: Mapping[str, Any]) -> None:
        mine = {game: one for game, one in found.items() if game in by_id}
        shown = sorted(mine, key=lambda game: max(
            (str(one.get("added") or "") for _listing, one in mine[game]), default=""),
            reverse=True)
        limit = int(own.get("limit", WALL_AT_FIRST))
        with ui.scroll_area().classes("w-full grow min-h-0 px-3"):
            if not shown:
                ui.label(t("manager.discovery.ask.nothing")).classes("manager-help")
            with ui.element("div").classes("manager-wall"):
                for game in shown[:limit]:
                    _tile(by_id[game], len(mine[game]),
                          sum(1 for _listing, one in mine[game] if one.get("held")),
                          partial(open_game, by_id[game]))
            if len(shown) > limit:
                panel.action(t("manager.discovery.ask.more", count=len(shown) - limit),
                             lambda: rebuild(limit=limit + WALL_AT_FIRST * 2),
                             icon=verbs.ADD, hint=t("manager.discovery.ask.more.help"))()

    draw()
