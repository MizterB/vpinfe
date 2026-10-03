"""Visual Pinball X's key actions, and what a `Mapping.<Name>` value says about their keys.

A value is alternatives joined by ` | `, each one parts joined by ` & ` that are down
together, each part `<device>;<id>`. Only the keys are read and written here, as sets of
`KeyboardEvent.code` names; an alternative that is anything else - a controller button -
is kept as it stands.

Blank means the program's default, so a value that says the default is written blank, and
nothing can be written for an action that has a default and no key.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import keys

SECTION = "Input"
PREFIX = "Mapping."
_ALTERNATIVES = " | "
_TOGETHER = " & "
_KEY_PART = re.compile(r"Key;(\d+)")

FLIPPERS = "flippers"
PLAY = "play"
GAME = "game"
MENU = "menu"
SERVICE = "service"
OTHER = "other"

# `Key;n` is SDL's scancode, which is the number of the USB usage of the key.
_LSHIFT, _RSHIFT, _LCTRL, _RCTRL, _LALT = 225, 229, 224, 228, 226


@dataclass(frozen=True)
class Action:
    """One action: its setting, the heading it is drawn under, and the key it ships on,
    as the program writes it. The setting is spelled out so a search for it finds this."""

    qualified: str
    heading: str
    default: str = ""

    @property
    def name(self) -> str:
        return self.qualified.removeprefix(f"{SECTION}.{PREFIX}")


def _key(scancode: int) -> str:
    return f"Key;{scancode}"


ACTIONS = (
    Action("Input.Mapping.LeftFlipper", FLIPPERS, _key(_LSHIFT)),
    Action("Input.Mapping.RightFlipper", FLIPPERS, _key(_RSHIFT)),
    Action("Input.Mapping.LeftStagedFlipper", FLIPPERS, _key(_LSHIFT)),
    Action("Input.Mapping.RightStagedFlipper", FLIPPERS, _key(_RSHIFT)),
    Action("Input.Mapping.LeftMagna", FLIPPERS, _key(_LCTRL)),
    Action("Input.Mapping.RightMagna", FLIPPERS, _key(_RCTRL)),
    Action("Input.Mapping.LaunchBall", PLAY, _key(40)),
    Action("Input.Mapping.Start", PLAY, _key(30)),
    Action("Input.Mapping.Credit1", PLAY, _key(34)),
    Action("Input.Mapping.Credit2", PLAY, _key(33)),
    Action("Input.Mapping.Credit3", PLAY, _key(32)),
    Action("Input.Mapping.Credit4", PLAY, _key(35)),
    Action("Input.Mapping.LeftNudge", PLAY, _key(29)),
    Action("Input.Mapping.RightNudge", PLAY, _key(56)),
    Action("Input.Mapping.CenterNudge", PLAY, _key(44)),
    Action("Input.Mapping.Tilt", PLAY, _key(23)),
    Action("Input.Mapping.ExtraBall", PLAY, _key(5)),
    Action("Input.Mapping.Lockbar", PLAY, _key(_LALT)),
    Action("Input.Mapping.ExitGame", GAME, _key(41)),
    Action("Input.Mapping.InGameUI", GAME, _key(69)),
    Action("Input.Mapping.Pause", GAME, _key(19)),
    Action("Input.Mapping.ShowRules", GAME),
    Action("Input.Mapping.VolumeDown", GAME, _key(45)),
    Action("Input.Mapping.VolumeUp", GAME, _key(46)),
    Action("Input.Mapping.PerfOverlay", GAME, _key(68)),
    Action("Input.Mapping.UIUp", MENU, _key(_LCTRL)),
    Action("Input.Mapping.UIDown", MENU, _key(_RCTRL)),
    Action("Input.Mapping.UILeft", MENU, _key(_LSHIFT)),
    Action("Input.Mapping.UIRight", MENU, _key(_RSHIFT)),
    Action("Input.Mapping.CoinDoor", SERVICE, _key(77)),
    Action("Input.Mapping.SlamTilt", SERVICE, _key(74)),
    Action("Input.Mapping.Reset", SERVICE, _key(60)),
    Action("Input.Mapping.Service1", SERVICE, _key(36)),
    Action("Input.Mapping.Service2", SERVICE, _key(37)),
    Action("Input.Mapping.Service3", SERVICE, _key(38)),
    Action("Input.Mapping.Service4", SERVICE, _key(39)),
    Action("Input.Mapping.Service5", SERVICE),
    Action("Input.Mapping.Service6", SERVICE, _key(75)),
    Action("Input.Mapping.Service7", SERVICE),
    Action("Input.Mapping.Service8", SERVICE),
    Action("Input.Mapping.VRCenter", OTHER, _key(93)),
    Action("Input.Mapping.ToggleStereo", OTHER, _key(67)),
    Action("Input.Mapping.GenTournament", OTHER, f"{_key(_LALT)}{_TOGETHER}{_key(30)}"),
    Action("Input.Mapping.DebugBalls", OTHER, _key(18)),
    Action("Input.Mapping.Debugger", OTHER, _key(7)),
    Action("Input.Mapping.Custom1", OTHER),
    Action("Input.Mapping.Custom2", OTHER),
    Action("Input.Mapping.Custom3", OTHER),
    Action("Input.Mapping.Custom4", OTHER),
)
HEADINGS = (FLIPPERS, PLAY, GAME, MENU, SERVICE, OTHER)
_BY_QUALIFIED = {one.qualified: one for one in ACTIONS}
_SCANCODES = {keys.code_of(number): number
              for number in (*range(4, 116), *range(224, 232)) if keys.code_of(number)}


def is_action(qualified: str) -> bool:
    return qualified in _BY_QUALIFIED


def default_of(qualified: str) -> str:
    """The value an action ships with, or "" for a setting that is none."""
    found = _BY_QUALIFIED.get(qualified)
    return found.default if found else ""


def is_mapping(qualified: str) -> bool:
    """Whether a setting key is a mapping of any action, this program's or a later one's."""
    return qualified.startswith(f"{SECTION}.{PREFIX}")


Chord = tuple[str, ...]


@dataclass(frozen=True)
class Held:
    """What a value maps an action to: `keys`, each a chord of one or more key codes in
    a settled order, and `kept`, the alternatives that are not keys, each as written."""

    keys: tuple[Chord, ...] = ()
    kept: tuple[str, ...] = ()


def _chord(alternative: str) -> Chord:
    """The key codes an alternative holds down together, or () if any part is not a key
    this table has a name for."""
    codes = []
    for part in alternative.split("&"):
        found = _KEY_PART.fullmatch(part.strip())
        code = keys.code_of(int(found[1])) if found else ""
        if not code:
            return ()
        codes.append(code)
    return tuple(sorted(set(codes)))


def _alternatives(value: str) -> list[str]:
    return [one.strip() for one in value.split("|") if one.strip()]


def parse(value: str, default: str = "") -> Held:
    """What `value` maps an action to; the default's keys where it is blank."""
    found = _alternatives(value) or _alternatives(default)
    chords = [(_chord(one), one) for one in found]
    return Held(tuple(chord for chord, _ in chords if chord),
                tuple(one for chord, one in chords if not chord))


def writable(chord: Chord) -> bool:
    """Whether the program has a scancode for every key of the chord."""
    return bool(chord) and all(code in _SCANCODES for code in chord)


def _term(chord: Chord) -> str:
    return _TOGETHER.join(_key(_SCANCODES[code]) for code in chord)


def value_of(chords: list[Chord], value: str, default: str = "") -> str:
    """The value that maps an action to `chords`, kept alternatives and all.

    The keys take the place the value's first key had; the rest of its keys go. Written
    blank where that says the default.
    """
    terms = [_term(one) for one in chords if writable(one)]
    out: list[str] = []
    placed = False
    for alternative in _alternatives(value) or _alternatives(default):
        if not _chord(alternative):
            out.append(alternative)
        elif not placed:
            out += terms
            placed = True
    if not placed:
        out += terms
    shipped = parse("", default)
    if (not any(not _chord(one) for one in out) and not shipped.kept
            and {tuple(sorted(set(one))) for one in chords} == set(shipped.keys)):
        return ""
    return _ALTERNATIVES.join(out)
