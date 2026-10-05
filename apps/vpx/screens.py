"""Visual Pinball's half of the screens answer: where its windows are, and what to tell it.

Values in, ini keys out. Nothing here reads or writes a file, and a screen is only the
facts `Seen` lists, so Setup, a change in Settings and VPX's own Displays page all get the
same keys from the same arrangement. A key someone set in VPX is never overwritten by a
derived one: those are written only where VPX holds nothing.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Protocol

PLAYFIELD = "playfield"
BACKGLASS = "backglass"
SCORE_VIEW = "score_view"
TOPPER = "topper"

# What a part holds when VPX draws it inside the playfield's window instead of on a screen.
INSIDE = "inside"

# A screen's number, INSIDE, or None for no screen.
Placement = int | str | None

DISPLAY = {PLAYFIELD: "Player.PlayfieldDisplay", BACKGLASS: "Backglass.BackglassDisplay",
           SCORE_VIEW: "ScoreView.ScoreViewDisplay", TOPPER: "Topper.TopperDisplay"}
# The playfield always shows, so it has no output mode.
OUTPUT = {BACKGLASS: "Backglass.BackglassOutput", SCORE_VIEW: "ScoreView.ScoreViewOutput",
          TOPPER: "Topper.TopperOutput"}
DISABLED, FLOATING, EMBEDDED = "0", "1", "2"
# The keys that place a part's window: where it sits, and how big. Drawn inside the
# playfield they are in the playfield window's pixels, and a floating window's values left
# in them cover the table.
REGION = {part: tuple(f"{key.removesuffix('Output')}{one}"
                      for one in ("WndX", "WndY", "Width", "Height"))
          for part, key in OUTPUT.items()}

VIEW_CAB_ROTATION = "TableOverride.ViewCabRotation"

# The Displays group's headings, by the part each is for, and the cabinet's own.
WINDOW_HEADINGS = {"playfield": PLAYFIELD, "backglass": BACKGLASS, "scoreview": SCORE_VIEW,
                   "topper": TOPPER}
CABINET_HEADING = "cabinet"
# The playfield screen's width and height in centimeters.
SCREEN_SIZE = ("Player.ScreenWidth", "Player.ScreenHeight")

# PUP over the backglass file's DMD art over the score display.
PRIORITIES = {"ScoreView.Priority.ScoreView": "1", "ScoreView.Priority.PUP": "3",
              "ScoreView.Priority.B2SLegacyDMD": "2"}
# Full DMD: the DMD drawn over the whole Score View, with the backglass's DMD strip hidden.
FULL_DMD = {"Plugin.B2SLegacy.ScoreViewDMDOverlay": "1",
            "Plugin.B2SLegacy.ScoreViewDMDAutoPos": "1", "Plugin.B2SLegacy.B2SHideGrill": "1"}

ZEDMD, PIN2DMD, PIXELCADE = "ZeDMD", "PIN2DMD", "Pixelcade"
DMD_KINDS = (ZEDMD, PIN2DMD, PIXELCADE)
DMD_UTIL = "Plugin.DMDUtil."
# Windows drives a panel through DmdExt, and DMDUtil beside it is unchecked.
DMD_UTIL_PLATFORMS = ("linux", "darwin")

# An embedded strip leaves a twentieth of the window's shorter side clear on each side.
_MARGIN = 20

# `name [x, y]`: where the screen sits on the desktop.
_POSITIONED = re.compile(r"(?P<name>.+?)\s*\[\s*(?P<x>-?\d+),\s*(?P<y>-?\d+)\s*\]")


class Seen(Protocol):
    """A connected screen."""

    @property
    def number(self) -> int: ...
    @property
    def name(self) -> str: ...
    @property
    def x(self) -> int: ...
    @property
    def y(self) -> int: ...
    @property
    def width(self) -> int: ...
    @property
    def height(self) -> int: ...


@dataclass(frozen=True)
class Written:
    """Ini keys to set, and the parts left out: those VPX has no name for the screen of, and
    those asked to go inside a playfield whose size is not known."""
    keys: dict[str, str]
    unnamed: tuple[str, ...] = ()
    # Parts asked to go inside a playfield whose window has no known size.
    unsized: tuple[str, ...] = ()


def display_id(screen: Seen, logged: Sequence[str] = ()) -> str:
    """The id VPX stores for this screen, or "" where nothing says what it calls it.

    The name VPX logged at the screen's position wins: SDL names a panel from its
    connector, and the model name the OS reports only stands in for that.
    """
    at = (screen.x, screen.y)
    for said in logged:
        found = _POSITIONED.fullmatch(said.strip())
        if found and (int(found["x"]), int(found["y"])) == at:
            return f"{found['name']} [{screen.x}, {screen.y}]"
    model = screen.name.strip()
    return f"{model} [{screen.x}, {screen.y}]" if model else ""


def screen_for(stored: str, screens: Sequence[Seen]) -> Seen | None:
    """The connected screen a stored id names. A position names one exactly; a name alone,
    as older builds store it, names one only where a single screen's model is in it."""
    said = str(stored or "").strip()
    if not said:
        return None
    found = _POSITIONED.fullmatch(said)
    if found:
        where = (int(found["x"]), int(found["y"]))
        return next((one for one in screens if (one.x, one.y) == where), None)
    named = [one for one in screens
             if one.name.strip() and one.name.strip().casefold() in said.casefold()]
    return named[0] if len(named) == 1 else None


def placed(values: Mapping[str, str], screens: Sequence[Seen]) -> dict[str, Placement]:
    """Where VPX has each part, from the values of its ini (a blank is ""). A window that
    is not Floating is on no screen, and a Floating one on a screen not connected is too."""
    def number(part: str) -> int | None:
        found = screen_for(values.get(DISPLAY[part]) or "", screens)
        return found.number if found is not None else None

    held: dict[str, Placement] = {PLAYFIELD: number(PLAYFIELD)}
    for part, key in OUTPUT.items():
        mode = (values.get(key) or "").strip()
        held[part] = (INSIDE if mode == EMBEDDED else number(part) if mode == FLOATING
                      else None)
    return held


def embedded_region(playfield: Seen) -> tuple[int, int, int, int]:
    """Where a part drawn inside the playfield's window sits: x, y, width and height in the
    window's pixels. A strip at the DMD's 4:1 along the window's bottom edge, centered, as
    wide as the window's shorter side less a margin each side."""
    span = min(playfield.width, playfield.height)
    margin = span // _MARGIN
    width = span - 2 * margin
    height = width // 4
    return (playfield.width - width) // 2, playfield.height - height - margin, width, height


def windows(moved: Mapping[str, Placement], screens: Sequence[Seen],
            logged: Sequence[str] = (), playfield: Seen | None = None) -> Written:
    """The Display and Output keys that put each moved part where it now is, and for a part
    drawn inside the playfield the region of `playfield`'s window it takes.

    A part whose screen VPX has no name for is left out whole: an Output of Floating with
    no Display opens on the primary display, which is no answer to the screen picked.
    Inside a playfield of no known size it is left out too, for want of a region.
    """
    keys: dict[str, str] = {}
    unnamed: list[str] = []
    unsized: list[str] = []
    for part, where in moved.items():
        if part not in DISPLAY:
            continue
        if where is None:
            keys.update({DISPLAY[PLAYFIELD]: ""} if part == PLAYFIELD
                        else {OUTPUT[part]: DISABLED})
        elif where == INSIDE:
            if part == PLAYFIELD:
                continue
            if playfield is None:
                unsized.append(part)
                continue
            keys[OUTPUT[part]] = EMBEDDED
            keys.update(zip(REGION[part], map(str, embedded_region(playfield)), strict=True))
        else:
            screen = next((one for one in screens if one.number == where), None)
            said = display_id(screen, logged) if screen is not None else ""
            if not said:
                unnamed.append(part)
                continue
            keys[DISPLAY[part]] = said
            if part != PLAYFIELD:
                keys[OUTPUT[part]] = FLOATING
    return Written(keys, tuple(unnamed), tuple(unsized))


def differs(vpinfe: Mapping[str, Placement], vpx: Mapping[str, Placement]) -> list[str]:
    """The parts VPX has somewhere other than VPinFE does. A topper differs only where
    VPinFE has a screen for one: with none, VPX's is as the person set it."""
    return [part for part in (TOPPER, BACKGLASS, SCORE_VIEW, PLAYFIELD)
            if vpinfe.get(part) != vpx.get(part)
            and (part != TOPPER or vpinfe.get(TOPPER) is not None)]


def followed(before: Mapping[str, Placement], moved: Mapping[str, Placement],
             vpx: Mapping[str, Placement]) -> dict[str, Placement]:
    """Of the parts VPinFE moved, those VPX has where VPinFE had them: a part VPX has
    set apart stays where it was put.

    A topper VPinFE no longer has a screen for stays too, unless a part that moved takes
    its screen, which leaves it with none.
    """
    found = {part: where for part, where in moved.items()
             if vpx.get(part) == before.get(part) and (part != TOPPER or where is not None)}
    held = vpx.get(TOPPER)
    if TOPPER not in found and isinstance(held, int) and held in found.values():
        found[TOPPER] = None
    return found


# The edge of the output that faces the player when VPinFE turns its page clockwise by
# this many degrees: the page's own bottom, carried round with it.
_FACING = {0.0: "bottom", 90.0: "left", 180.0: "top", 270.0: "right"}
# `ViewCabRotation` by the edge of the output that the flipper end of the table faces, for
# the output as VPX sees it, after the OS has turned it.
_PORTRAIT = {"bottom": 0.0, "left": 90.0, "top": 180.0, "right": 270.0}
_LANDSCAPE = {"right": 0.0, "bottom": 90.0, "left": 180.0, "top": 270.0}


def _edges(playfield: Seen | None) -> dict[str, float] | None:
    """The turn that faces each edge, or None where the shape is not one of the two: a
    square output is neither portrait nor landscape."""
    if playfield is None or playfield.width == playfield.height:
        return None
    return _PORTRAIT if playfield.height > playfield.width else _LANDSCAPE


def view_cab_rotation(playfield: Seen | None, rotation: str) -> str | None:
    """VPX's `ViewCabRotation` for a playfield whose page VPinFE turns by `rotation`, or
    None where the answer says nothing. The flipper end of the table goes to the edge that
    faces the player.
    """
    edges = _edges(playfield)
    turned = turn_of(rotation)
    facing = _FACING.get(turned) if turned is not None else None
    return str(edges[facing]) if edges is not None and facing is not None else None


def vpinfe_rotation(playfield: Seen | None, turn: str) -> str | None:
    """The VPinFE rotation that goes with VPX's `ViewCabRotation` on this output, or None
    where VPX holds a turn that faces none of the four edges."""
    edges = _edges(playfield)
    if edges is None:
        return None
    held = turn_of(turn)
    facing = next((edge for edge, value in edges.items() if value == held), None)
    return next((str(int(degrees)) for degrees, edge in _FACING.items() if edge == facing),
                None)


def turn_of(value: str | None) -> float | None:
    """A `ViewCabRotation` as a number: blank is VPX's own 0."""
    try:
        return float(str(value or "").strip() or 0)
    except ValueError:
        return None


def rotation_differs(vpinfe: str | None, current: str) -> bool:
    """Whether VPX turns the playfield other than the answer says. An answer that says
    nothing differs from nothing."""
    return vpinfe is not None and turn_of(current) != turn_of(vpinfe)


def rotation_follows(before: str | None, current: str) -> bool:
    """Whether VPX still holds what the answer gave it, so a new answer moves it: the
    value before, or VPX's own 0 where the answer gave none."""
    return turn_of(current) == (0.0 if before is None else turn_of(before))


def two_screens_without_dmd(on: Mapping[str, Placement]) -> bool:
    """Whether exactly two screens are in use and neither is the Score View's."""
    used = {on.get(part) for part in (PLAYFIELD, BACKGLASS, SCORE_VIEW)
            if isinstance(on.get(part), int)}
    return len(used) == 2 and not isinstance(on.get(SCORE_VIEW), int)


def render_priorities(on: Mapping[str, Placement]) -> dict[str, str]:
    """Blank priorities draw two screens with no DMD screen: B2S draws the backglass and the
    Score View plugin an embedded DMD."""
    return {} if two_screens_without_dmd(on) else dict(PRIORITIES)


def full_dmd(on: Mapping[str, Placement]) -> dict[str, str]:
    """Full DMD wherever a screen is the DMD. Never turned off: with the Score View gone
    the overlay has no window to draw on."""
    return dict(FULL_DMD) if isinstance(on.get(SCORE_VIEW), int) else {}


def derived(on: Mapping[str, Placement], current: Mapping[str, str]) -> dict[str, str]:
    """Render priorities and Full DMD for an arrangement, of those VPX holds no value for."""
    wanted = {**render_priorities(on), **full_dmd(on)}
    return {key: value for key, value in wanted.items()
            if not str(current.get(key) or "").strip()}


def answer(moved: Mapping[str, Placement], now: Mapping[str, Placement],
           screens: Sequence[Seen], logged: Sequence[str], current: Mapping[str, str],
           turn: tuple[str, str] | None = None) -> Written:
    """Every key the answer sets for the parts that `moved`, `now` being the whole
    arrangement after. `turn` is the playfield's (orientation, rotation) where the answer
    gives VPX one.

    A part left inside a playfield that moved is written again for the new window, and a
    part that leaves the inside has its region blanked.
    """
    playfield = next((one for one in screens if one.number == now.get(PLAYFIELD)), None)
    inside = ({part: INSIDE for part, where in now.items()
               if part in OUTPUT and where == INSIDE}
              if PLAYFIELD in moved and playfield is not None else {})
    written = windows({**inside, **moved}, screens, logged, playfield)
    keys = dict(written.keys)
    for part, where in moved.items():
        if (part in OUTPUT and where != INSIDE and part not in written.unnamed
                and str(current.get(OUTPUT[part]) or "").strip() == EMBEDDED):
            keys.update(dict.fromkeys(REGION[part], ""))
    if turn is not None and (value := view_cab_rotation(playfield, turn[1])) is not None:
        keys[VIEW_CAB_ROTATION] = value
    keys.update(derived(now, current))
    return replace(written, keys=keys)


def dmd_util(kind: str | None, *, platform: str | None = None) -> dict[str, str]:
    """`[Plugin.DMDUtil]` for a panel of this kind: the plugin on, and that kind on. No
    kind writes nothing."""
    where = sys.platform if platform is None else platform
    if kind not in DMD_KINDS or not where.startswith(DMD_UTIL_PLATFORMS):
        return {}
    return {f"{DMD_UTIL}Enable": "1", f"{DMD_UTIL}{kind}": "1"}


def dmd_kind(current: Mapping[str, str]) -> str:
    """The panel kind VPX's ini has on, or "" for none."""
    return next((kind for kind in DMD_KINDS
                 if str(current.get(f"{DMD_UTIL}{kind}") or "").strip() == "1"), "")
