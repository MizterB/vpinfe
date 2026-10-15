"""The cabinet drawn as its parts, and this device's screens dragged onto them.

One control wherever a screen is chosen for a part: the caller passes the screens, what is
on each part now and the acts it reports to, and the control writes nothing itself. A part
takes one screen and a screen sits on one part, so putting a screen where another is sends
that one to where this one came from. A part that can be drawn inside the playfield's window
holds `INSIDE` there, which is no screen and displaces nothing.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import partial
from typing import Any

from nicegui import ui

from common.i18n import t
from manager.kit import panel, verbs
from manager.kit.on_page import on_page
from manager.settings.screens import Screen

BACKGLASS = "backglass"
SCOREVIEW = "scoreview"
PLAYFIELD = "playfield"
TOPPER = "topper"
INSIDE = "inside"

# A screen's number, INSIDE, or None for no screen.
Placement = int | str | None

# Which way the playfield's own page points, as the person sees it on the cabinet.
UP = "up"
LEFT = "left"
RIGHT = "right"
DOWN = "down"
ARROWS = (UP, LEFT, RIGHT, DOWN)

# How far the UI is turned to face the player when its top points that way.
_TURN = {UP: 0, LEFT: 90, DOWN: 180, RIGHT: 270}
_ICON = {UP: verbs.FACES_UP, LEFT: verbs.FACES_LEFT, RIGHT: verbs.FACES_RIGHT,
         DOWN: verbs.FACES_DOWN}
_WORDS = {UP: "manager.screens.arrow_up", LEFT: "manager.screens.arrow_left",
          RIGHT: "manager.screens.arrow_right", DOWN: "manager.screens.arrow_down"}

# A strip this much wider than it is tall is a DMD, and nothing else is.
_STRIP = 2.5

_CARRIES = "vpinfe-screen:"
_DRAG_END = "(e) => e.currentTarget.classList.remove('manager-screen-dragging')"
# Stopped here, or the page's own drop handler reads it as files and says nothing was
# uploaded.
_DRAG_OVER = ("(e) => { if (!Array.from(e.dataTransfer.types || []).includes('text/plain')) "
              "return; e.preventDefault(); e.stopPropagation(); "
              "e.currentTarget.classList.add('manager-drop-hot'); }")
_DRAG_LEAVE = ("(e) => { if (!e.currentTarget.contains(e.relatedTarget)) "
               "e.currentTarget.classList.remove('manager-drop-hot'); }")
_DROP = ("(e) => { e.preventDefault(); e.stopPropagation(); "
         "e.currentTarget.classList.remove('manager-drop-hot'); "
         "const held = e.dataTransfer.getData('text/plain'); "
         f"if (held.startsWith('{_CARRIES}')) emit(Number(held.slice({len(_CARRIES)}))); }}")


def _drag_start(number: int) -> str:
    return (f"(e) => {{ e.dataTransfer.setData('text/plain', '{_CARRIES}{number}'); "
            "e.dataTransfer.effectAllowed = 'move'; "
            "e.currentTarget.classList.add('manager-screen-dragging'); }")


@dataclass(frozen=True)
class Part:
    key: str
    label: str
    hint: str = ""
    # Whether the menu offers to draw it inside the playfield's window.
    inside: bool = False


def vpinfe_parts() -> tuple[Part, ...]:
    """The four parts VPinFE opens a window for. A topper is opened only where it has a
    screen."""
    return (Part(TOPPER, t("manager.screens.topper")),
            Part(BACKGLASS, t("manager.screens.backglass")),
            Part(SCOREVIEW, t("manager.screens.scoreview"),
                 t("manager.screens.scoreview.help")),
            Part(PLAYFIELD, t("manager.screens.playfield")))


def vpx_parts() -> tuple[Part, ...]:
    """Visual Pinball's: VPinFE's four, each but the playfield able to be drawn inside the
    playfield."""
    return (Part(TOPPER, t("manager.screens.topper"), inside=True),
            Part(BACKGLASS, t("manager.screens.backglass"), inside=True),
            Part(SCOREVIEW, t("manager.screens.scoreview"),
                 t("manager.screens.scoreview.help"), inside=True),
            Part(PLAYFIELD, t("manager.screens.playfield")))


def placed(on: Mapping[str, Placement], part: str,
           number: Placement) -> dict[str, Placement]:
    """`number` on `part`, and what `part` held on the part `number` came from."""
    after = dict(on)
    after[part] = number
    if isinstance(number, int):
        for other, held in on.items():
            if other != part and held == number:
                after[other] = on.get(part)
    return after


def changes(before: Mapping[str, Placement],
            after: Mapping[str, Placement]) -> dict[str, Placement]:
    return {part: number for part, number in after.items() if before.get(part) != number}


def arrow_at(rotation: Any) -> str | None:
    """The arrow a stored rotation is drawn as."""
    turn = str(rotation if rotation is not None else "").strip()
    return next((arrow for arrow, degrees in _TURN.items() if str(degrees) == turn), None)


def turn(arrow: str, screen: Screen | None) -> dict[str, str]:
    """The playfield's `orientation` and `rotation` for an arrow on this screen."""
    tall = screen is not None and screen.height > screen.width
    sideways = arrow in (LEFT, RIGHT)
    return {"orientation": "portrait" if tall != sideways else "landscape",
            "rotation": str(_TURN[arrow])}


def guess(screens: Sequence[Screen]) -> dict[str, int]:
    """A part for each screen whose size tells it from the rest, and no part for the others.

    A strip is the Score View, the biggest of what is left the Playfield, the next the
    Backglass and the one after that the Topper. Two screens of one size are not told apart
    by their size, so neither is placed, and a lone screen is the Playfield.
    """
    if len(screens) == 1:
        return {PLAYFIELD: screens[0].number}
    sizes = [(screen.width, screen.height) for screen in screens]
    alone = [screen for screen in screens if sizes.count((screen.width, screen.height)) == 1]
    strips = [screen for screen in alone if screen.width >= _STRIP * screen.height]
    found: dict[str, int] = {}
    if len(strips) == 1:
        found[SCOREVIEW] = strips[0].number
    rest = sorted((screen for screen in alone if screen not in strips),
                  key=lambda screen: screen.width * screen.height, reverse=True)
    for part, screen in zip((PLAYFIELD, BACKGLASS, TOPPER), rest, strict=False):
        found[part] = screen.number
    return found


def _mini(screen: Screen, *, big: bool = False) -> None:
    width = 54 if big else 28
    height = max(14 if big else 8, round(width * screen.height / screen.width))
    ui.label(str(screen.number)).classes("manager-screen-mini") \
        .style(f"width:{width}px;height:{height}px")


def _no_mini() -> None:
    ui.label("").classes("manager-screen-mini manager-screen-mini--none")


def _size_of(screen: Screen) -> None:
    ui.label(screen.size).classes("manager-menu-size")


class Picture:
    """The parts and the screens, drawn from what the caller says is where.

    `move` is told every part whose screen changed - two, when a screen swaps places - and
    answers whether the change was kept; the picture follows it only if it was. `point` is
    told the arrow picked and the playfield's screen, and `show` runs Show numbers with what
    is where; the picture offers each only when it is given. `arrows` is False for a
    device on a desk, which has no cabinet to point anywhere in.

    `differs` names the parts held otherwise than the thing this picture is compared with
    (`arrow_differs` the playfield's arrow), and `match` puts them right; both are drawn
    only when something differs.
    """

    def __init__(self, screens: Sequence[Screen], on: Mapping[str, Placement], *,
                 move: Callable[[dict[str, Placement]], Awaitable[bool]],
                 parts: Sequence[Part] = (), arrow: str | None = None, arrows: bool = True,
                 point: Callable[[str, Screen], Awaitable[bool]] | None = None,
                 show: Callable[[dict[str, Placement]], Awaitable[Any]] | None = None,
                 differs: Sequence[str] = (), arrow_differs: bool = False,
                 match: Callable[[], Awaitable[Any]] | None = None,
                 ) -> None:
        self.screens = list(screens)
        self.on = dict(on)
        self.differs = tuple(differs)
        self.arrow_differs = arrow_differs
        self.match = match
        self.parts = tuple(parts) or vpinfe_parts()
        self.arrow = arrow
        self.arrows = arrows
        self.move = move
        self.point = point
        self.show = show
        self.showing = False
        self.container = ui.element("div").classes("w-full")
        self.draw()

    def screen(self, number: Placement) -> Screen | None:
        return next((one for one in self.screens if one.number == number), None)

    def draw(self) -> None:
        if self.container.is_deleted:
            return
        self.container.clear()
        with self.container:
            with ui.element("div").classes("manager-screens-head"):
                ui.label(t("manager.screens.hint_cabinet" if self.arrows
                           else "manager.screens.hint_desktop")).classes("manager-help")
                if self.show is not None:
                    self._show_numbers()
            with ui.element("div").classes("manager-screens"):
                self._cabinet()
                with ui.column().classes("manager-screens-side gap-2"):
                    with ui.element("div").classes("manager-screens-tray"):
                        for screen in self.screens:
                            self._card(screen)
                        if not self.screens:
                            ui.label(t("manager.screens.none_found")).classes("manager-help")
                    if self.arrows and self.show is not None and self.on.get(PLAYFIELD):
                        ui.label(t("manager.screens.arrow_help")).classes(
                            "manager-help manager-screens-arrow-help")
                    self._differs()

    def _show_numbers(self) -> None:
        panel.action(t("manager.screens.showing" if self.showing
                       else "manager.screens.show_numbers"),
                     self._show, icon=verbs.SHOW_NUMBERS,
                     hint=t("manager.screens.show_numbers.help"),
                     enabled=not self.showing and bool(self.screens))()

    @on_page
    async def _show(self) -> None:
        if self.show is None:
            return
        self.showing = True
        self.draw()
        try:
            await self.show(dict(self.on))
        finally:
            self.showing = False
            self.draw()

    def _differs(self) -> None:
        said = [part.label for part in self.parts if part.key in self.differs]
        if self.arrow_differs:
            said.append(t("manager.screens.playfield_arrow"))
        if not said:
            return
        with ui.element("div").classes("manager-screens-differs"):
            with ui.column().classes("gap-0 min-w-0 grow"):
                ui.label(t("manager.screens.different")).classes("manager-screens-differs-title")
                ui.label(", ".join(said)).classes("manager-help")
            if self.match is not None:
                panel.action(t("manager.screens.match_vpinfe"), self._match,
                             icon=verbs.REVERT, hint=t("manager.screens.match_vpinfe.help"))()

    @on_page
    async def _match(self) -> None:
        if self.match is not None:
            await self.match()

    def _cabinet(self) -> None:
        with ui.element("div").classes("manager-cab"):
            for part in self.parts:
                self._part(part)

    def _part(self, part: Part) -> None:
        number = self.on.get(part.key)
        screen = self.screen(number)
        inside = number == INSIDE
        with ui.element("div").classes(f"manager-part manager-part--{part.key}"):
            with ui.element("div").classes("manager-part-slot-wrap"):
                slot = ui.element("div").classes(
                    "manager-part-slot" + (" manager-part-slot--filled" if screen else
                                           " manager-part-slot--inside" if inside else
                                           " manager-part-slot--missing" if number else ""))
                slot.on("dragover", js_handler=_DRAG_OVER)
                slot.on("dragleave", js_handler=_DRAG_LEAVE)
                slot.on("drop", lambda event, key=part.key: self._dropped(key, event),
                        js_handler=_DROP)
                if isinstance(number, int):
                    slot.props("draggable=true")
                    slot.on("dragstart", js_handler=_drag_start(number))
                    slot.on("dragend", js_handler=_DRAG_END)
                with slot:
                    self._slot_face(part, number, screen)
                    self._menu(part, number)
            name = ui.label(part.label).classes(
                "manager-part-name" + (" manager-part-name--differs"
                                       if part.key in self.differs else ""))
            if part.key in self.differs:
                name.tooltip(t("manager.screens.different"))
            elif part.hint:
                name.tooltip(part.hint)

    def _slot_face(self, part: Part, number: Placement, screen: Screen | None) -> None:
        if number is None:
            ui.label(t("manager.screens.no_screen")).classes("manager-part-slot-none")
            return
        if number == INSIDE:
            ui.label(t("manager.screens.inside")).classes("manager-part-slot-none")
            self._clear(part)
            return
        ui.label(str(number)).classes("manager-part-slot-num")
        if screen is None:
            ui.label(t("manager.screens.not_connected")).classes("manager-part-slot-size")
        else:
            ui.label(screen.said).classes("manager-part-slot-size truncate").tooltip(screen.size)
        if part.key == PLAYFIELD and self.arrows and screen is not None \
                and self.point is not None:
            for arrow in ARROWS:
                self._arrow(arrow)
        self._clear(part)

    def _clear(self, part: Part) -> None:
        clear = ui.icon(verbs.UNPLACE).classes("manager-part-slot-clear") \
            .props("tabindex=0 role=button")
        clear.props["aria-label"] = t("manager.screens.no_screen")
        clear.tooltip(t("manager.screens.no_screen"))
        clear.on("click.stop", lambda _e, key=part.key: self._put(key, None))
        clear.on("keydown.enter.stop", lambda _e, key=part.key: self._put(key, None))

    def _arrow(self, arrow: str) -> None:
        words = t(_WORDS[arrow])
        control = ui.icon(_ICON[arrow]).classes(
            f"manager-pf-dir manager-pf-dir--{arrow}"
            + (" manager-pf-dir--chosen" if self.arrow == arrow else "")) \
            .props("tabindex=0 role=button")
        control.props["aria-label"] = words
        control.tooltip(words)
        control.on("click.stop", lambda _e, one=arrow: self._aim(one))
        control.on("keydown.enter.stop", lambda _e, one=arrow: self._aim(one))

    def _menu(self, part: Part, number: Placement) -> None:
        with ui.menu().props("auto-close"):
            for screen in self.screens:
                panel.menu_entry(
                    screen.name or t("manager.screens.numbered", number=screen.number),
                    lambda _e=None, key=part.key, n=screen.number: self._put(key, n),
                    mark=partial(_mini, screen),
                    trail=partial(_size_of, screen),
                    classes="manager-menu-on" if screen.number == number else "")
            if part.inside:
                panel.menu_entry(t("manager.screens.inside"),
                                 lambda _e=None, key=part.key: self._put(key, INSIDE),
                                 mark=_no_mini,
                                 classes="manager-menu-on" if number == INSIDE else "")
            panel.menu_entry(t("manager.screens.no_screen"),
                             lambda _e=None, key=part.key: self._put(key, None),
                             mark=_no_mini)

    def _card(self, screen: Screen) -> None:
        using = [part.label for part in self.parts if self.on.get(part.key) == screen.number]
        card = ui.element("div").classes("manager-source-row manager-screen-card")
        card.props("draggable=true")
        card.on("dragstart", js_handler=_drag_start(screen.number))
        card.on("dragend", js_handler=_DRAG_END)
        with card:
            _mini(screen, big=True)
            with ui.column().classes("gap-0 min-w-0 grow"):
                ui.label(screen.said).classes("manager-screen-card-name truncate")
                if screen.name:
                    ui.label(screen.size).classes("manager-help truncate")
            ui.label(", ".join(using) if using else t("manager.screens.not_used")).classes(
                "manager-help manager-screen-use" + (" manager-screen-used" if using else ""))
            ui.icon(verbs.DRAG).classes("manager-screen-grip")

    @on_page
    async def _dropped(self, part: str, event: Any) -> None:
        if isinstance(event.args, int) and self.screen(event.args) is not None:
            await self._put(part, event.args)

    @on_page
    async def _put(self, part: str, number: Placement) -> None:
        after = placed(self.on, part, number)
        # A part that cannot be inside the playfield is not left there by a swap.
        after = {key: (None if held == INSIDE and not self._may_be_inside(key) else held)
                 for key, held in after.items()}
        moved = changes(self.on, after)
        if moved and await self.move(moved):
            self.on = after
        self.draw()

    def _may_be_inside(self, key: str) -> bool:
        return any(part.inside for part in self.parts if part.key == key)

    @on_page
    async def _aim(self, arrow: str) -> None:
        screen = self.screen(self.on.get(PLAYFIELD))
        if self.point is not None and screen is not None and await self.point(arrow, screen):
            self.arrow = arrow
        self.draw()
