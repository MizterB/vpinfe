"""Asking Discovery about releases: the chips over the grid, the search that finds a name,
and the page of one author's, maker's or theme's work.

The question itself is `common.online.vps_question`'s. This draws it and takes the
user's changes to it; the grid and the saved views are Discovery's.
"""

from __future__ import annotations

import datetime
import html
from collections.abc import Awaitable, Callable, Mapping, Sequence
from functools import partial
from typing import Any

from nicegui import ui

from common.i18n import t
from common.online import vps_find, vps_question
from manager.kit import dialog as frame
from manager.kit import dropdown, panel, thumbnails, verbs

SINCE_DAYS = (("manager.discovery.ask.week", 7), ("manager.discovery.ask.fortnight", 14),
              ("manager.discovery.ask.month", 30))
WALL_AT_FIRST = 60
FORMAT_DEFAULT = "VPX"

SUBJECT_KEY = {"author": "by", "maker": "maker", "theme": "theme"}
SUBJECT_WORD = {"author": "word.author", "maker": "word.manufacturer",
                "theme": "manager.discovery.ask.theme"}

Change = Callable[[dict[str, Any]], Awaitable[None]]


def since(days: int) -> str:
    return (datetime.date.today() - datetime.timedelta(days=days)).isoformat()


def parts(question: Mapping[str, Any],
          kinds: Mapping[str, str]) -> list[tuple[str, str, str]]:
    """What the question asks, as (key, value, words) - one for each chip."""
    said = []
    if question.get("kind"):
        said.append(("kind", question["kind"], t(kinds.get(question["kind"], "word.kind"))))
    said += [("by", name, t("manager.discovery.ask.by", name=name))
             for name in question.get("by") or ()]
    if question.get("maker"):
        said.append(("maker", question["maker"], question["maker"]))
    if question.get("theme"):
        said.append(("theme", question["theme"], question["theme"]))
    if question.get("mod"):
        said.append(("mod", question["mod"], t(
            "manager.discovery.ask.originals" if question["mod"] == "originals"
            else "manager.discovery.ask.mods")))
    said += [("feature", word, word) for word in question.get("feature") or ()]
    said += [("format", word, word) for word in question.get("format") or ()]
    if question.get("since"):
        said.append(("since", question["since"],
                     t("manager.discovery.ask.since", date=question["since"])))
    if question.get("held"):
        said.append(("held", question["held"], t(
            "manager.discovery.ask.have" if question["held"] == "have"
            else "manager.discovery.ask.missing")))
    if question.get("owned"):
        said.append(("owned", question["owned"], t(
            "manager.discovery.ask.owned_yes" if question["owned"] == "yes"
            else "manager.discovery.ask.owned_no")))
    return said


def without(question: Mapping[str, Any], key: str, value: str) -> dict[str, Any]:
    """The question with one thing taken out of it."""
    out = dict(question)
    if key in vps_question.LIST_KEYS:
        out[key] = [one for one in out.get(key) or () if one != value]
    else:
        out.pop(key, None)
    return vps_question.clean(out)


def with_value(question: Mapping[str, Any], key: str, value: str) -> dict[str, Any]:
    """The question with one more thing in it: a list gains the value, any other key
    takes it in place of what it had. Asking for tables brings Format with it, so the
    default is on the chips where it can be taken off."""
    out = dict(question)
    if key in vps_question.LIST_KEYS:
        out[key] = [*[one for one in out.get(key) or () if one != value], value]
    else:
        out[key] = value
    if key == "kind" and value == "tableFiles" and not out.get("format"):
        out["format"] = [FORMAT_DEFAULT]
    elif key == "kind" and value != "tableFiles" and out.get("format") == [FORMAT_DEFAULT]:
        del out["format"]
    return vps_question.clean(out)


def chips(question: Mapping[str, Any], kinds: Mapping[str, str], change: Change) -> None:
    """The question as chips, each with its way out. Drawn into the current container."""
    for key, value, said in parts(question, kinds):
        with ui.element("span").classes("manager-ask-chip"):
            ui.label(said)
            panel.chip_end(partial(take_out, question, key, value, change), t("word.remove"))


async def take_out(question: Mapping[str, Any], key: str, value: str, change: Change) -> None:
    await change(without(question, key, value))


async def pick_from(title: str, options: Mapping[str, str]) -> str | None:
    """Choose one of `options` (value to words) by typing to narrow them."""
    with frame.opened(title, ignore_outside_click=True) as box:
        chooser = dropdown.Select(dict(options), with_input=True, value=None,
                                  look=dropdown.OUTLINED).classes("w-full")
        chooser.on_value_change(lambda event: box.submit(event.value) if event.value else None)
        with frame.footer():
            frame.cancel(lambda: box.submit(None))
    frame.focus(box, chooser)
    answered = await box
    return str(answered) if answered else None


def add_menu(menu: ui.menu, question: Mapping[str, Any], kinds: Mapping[str, str],
             listed: Sequence[str], people: Sequence[Mapping[str, Any]],
             vocabulary: Mapping[str, Sequence[str]], change: Change, *,
             counted: bool = True) -> None:
    """Everything that can be added to the question, rebuilt each time the menu opens.
    Have, Missing and In Library mean nothing until the library has been counted."""
    async def set_to(key: str, value: str) -> None:
        await change(with_value(question, key, value))

    async def ask_for(key: str, title: str, options: Mapping[str, str]) -> None:
        chosen = await pick_from(title, options)
        if chosen:
            await set_to(key, chosen)

    menu.clear()
    with menu:
        ui.item_label(t("word.kind")).props("header").classes("manager-menu-header")
        for listing in listed:
            ui.menu_item(t(kinds[listing]), lambda one=listing: set_to("kind", one)) \
                .classes("manager-menu-item")
        ui.separator()
        ui.menu_item(t("manager.discovery.ask.by_pick"), lambda: ask_for(
            "by", t("manager.discovery.ask.by_pick"),
            {one["name"]: t("manager.discovery.ask.person", name=one["name"],
                            count=one["releases"]) for one in people})) \
            .classes("manager-menu-item")
        ui.menu_item(t("manager.discovery.ask.originals"),
                     lambda: set_to("mod", "originals")).classes("manager-menu-item")
        ui.menu_item(t("manager.discovery.ask.mods"),
                     lambda: set_to("mod", "mods")).classes("manager-menu-item")
        if vocabulary.get("feature"):
            ui.menu_item(t("manager.discovery.ask.feature_pick"), lambda: ask_for(
                "feature", t("manager.discovery.ask.feature_pick"),
                {word: word for word in vocabulary["feature"]})).classes("manager-menu-item")
        if vocabulary.get("format"):
            ui.menu_item(t("manager.discovery.ask.format_pick"), lambda: ask_for(
                "format", t("manager.discovery.ask.format_pick"),
                {word: word for word in vocabulary["format"]})).classes("manager-menu-item")
        ui.separator()
        ui.item_label(t("manager.discovery.ask.added")).props("header") \
            .classes("manager-menu-header")
        for word, days in SINCE_DAYS:
            ui.menu_item(t(word), lambda d=days: set_to("since", since(d))) \
                .classes("manager-menu-item")
        for heading, key, choices in (
                ("manager.discovery.ask.releases", "held",
                 (("have", "manager.discovery.ask.have"),
                  ("missing", "manager.discovery.ask.missing"))),
                ("manager.discovery.ask.group.game", "owned",
                 (("yes", "manager.discovery.ask.owned_yes"),
                  ("no", "manager.discovery.ask.owned_no")))):
            if not counted:
                break
            ui.separator()
            ui.item_label(t(heading)).props("header").classes("manager-menu-header")
            for value, word in choices:
                ui.menu_item(t(word), lambda k=key, v=value: set_to(k, v)) \
                    .classes("manager-menu-item")


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
