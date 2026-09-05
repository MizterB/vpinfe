"""Every input action VPinFE understands, declared once.

Ten actions, each with one ordered list of bindings. The names say what the player
*meant* rather than which way a stick moved: three surfaces - the wheel, a vertical menu
and a scrolling page - already disagreed about what "left" pointed at, and every overlay
carried a fall-through case as the evidence.

A binding names its own input - `key:<name>`, `pad:<index>/button:<n>` - so an action
needs one list rather than a key per input. Richer selectors - modifiers, axes, hold,
chord - go in this same list, so adding them is a parser change rather than another
migration.
"""

from __future__ import annotations

from dataclasses import dataclass

SECTION = "input"

# Selector prefixes. A binding that starts with neither is not one we can read.
KEY_PREFIX = "key:"
PAD_PREFIX = "pad:"


@dataclass(frozen=True)
class InputAction:
    """One thing a player can ask for, and what is bound to it out of the box."""

    name: str
    bindings: tuple[str, ...]
    label: str
    # What this used to be called, so an existing [Input] section still resolves.
    legacy: tuple[str, ...] = ()
    # What kind of thing it does, for a page that has to show ten of these. Here rather
    # than on the settings schema because this registry is what knows what an action is
    # for - the schema is generated from it and would be restating the answer.
    group: str = ""

    @property
    def config_key(self) -> str:
        return self.name

    @property
    def legacy_joy_key(self) -> str:
        """The `joy*` key this action used to have, for the projections that still answer."""
        return next((k for k in self.legacy if k.startswith("joy")), "")

    @property
    def legacy_key_key(self) -> str:
        """The `key*` key this action used to have."""
        return next((k for k in self.legacy if k.startswith("key")), "")


INPUT_ACTIONS: tuple[InputAction, ...] = (
    InputAction(
        "previous",
        group="Moving through the library",
        bindings=("key:ArrowLeft", "key:ShiftLeft"),
        label="Previous",
        legacy=("joyleft", "keyleft"),
    ),
    InputAction(
        "next",
        group="Moving through the library",
        bindings=("key:ArrowRight", "key:ShiftRight"),
        label="Next",
        legacy=("joyright", "keyright"),
    ),
    # up/down and pageup/pagedown were the same intent under two names: carousel-desktop
    # used up/down for a page-sized jump, which is what paging is. Named for where the
    # selection goes, not the key: "page up" has no answer on a horizontal wheel, and
    # core answered it two ways.
    InputAction(
        "page_previous",
        group="Moving through the library",
        bindings=("key:PageUp", "key:ArrowUp"),
        label="Page Previous",
        legacy=("joypageup", "keypageup", "joyup", "keyup"),
    ),
    InputAction(
        "page_next",
        group="Moving through the library",
        bindings=("key:PageDown", "key:ArrowDown"),
        label="Page Next",
        legacy=("joypagedown", "keypagedown", "joydown", "keydown"),
    ),
    InputAction(
        "select",
        group="Playing",
        bindings=("key:Enter",),
        label="Select",
        legacy=("joyselect", "keyselect"),
    ),
    InputAction(
        "back",
        group="Playing",
        bindings=("key:b",),
        label="Back",
        legacy=("joyback", "keyback"),
    ),
    InputAction(
        "menu",
        group="Opening something",
        bindings=("key:m",),
        label="Menu",
        legacy=("joymenu", "keymenu"),
    ),
    InputAction(
        "collection_menu",
        group="Opening something",
        bindings=("key:c",),
        label="Collection Menu",
        legacy=("joycollectionmenu", "keycollectionmenu"),
    ),
    InputAction(
        "tutorial",
        group="Opening something",
        bindings=("key:t",),
        label="Tutorial",
        legacy=("joytutorial", "keytutorial"),
    ),
    InputAction(
        "exit",
        group="Playing",
        bindings=("key:Escape", "key:q"),
        label="Exit",
        legacy=("joyexit", "keyexit"),
    ),
)


def actions() -> tuple[InputAction, ...]:
    return INPUT_ACTIONS


def defaults() -> dict[str, tuple[str, ...]]:
    """The bindings a fresh install ships, keyed by action."""
    return {action.name: action.bindings for action in INPUT_ACTIONS}


def action_for_legacy_key(key: str) -> str:
    """The action an old `[Input]` key bound, or "" when it bound none."""
    wanted = str(key or "").strip().lower()
    for action in INPUT_ACTIONS:
        if wanted == action.name or wanted in action.legacy:
            return action.name
    return ""


def binding_for_legacy(key: str, value: str) -> list[str]:
    """The selectors an old `[Input]` value means.

    `keyleft = ArrowLeft,ShiftLeft` was a comma-separated list of key names; `joyleft = 3`
    was one gamepad button index and nothing said which pad. Both become selectors.
    """
    name = str(key or "").strip().lower()
    raw = str(value or "").strip()
    if not raw:
        return []
    if name.startswith("joy"):
        index = raw.split(",")[0].strip()
        return [f"{PAD_PREFIX}0/button:{index}"] if index else []
    return [f"{KEY_PREFIX}{part.strip()}" for part in raw.split(",") if part.strip()]


def keys_in(bindings) -> list[str]:
    """The keyboard key names in a binding list - what the UI's keyboard field shows."""
    return [b[len(KEY_PREFIX):] for b in bindings or ()
            if str(b).startswith(KEY_PREFIX) and "+" not in b and "@" not in b]


def pad_buttons_in(bindings) -> list[str]:
    """The plain gamepad button indexes - what the UI's controller field shows."""
    out = []
    for b in bindings or ():
        text = str(b)
        if not text.startswith(PAD_PREFIX) or "@" not in text and "/button:" not in text:
            continue
        if "chord(" in text or "@" in text or "/axis:" in text:
            continue
        out.append(text.rsplit("/button:", 1)[-1])
    return out


def describe(binding: str) -> str:
    """One binding as a person reads it.

    A selector is written for a parser - `pad:0/button:3` - and reading ten of them off a
    settings page is the thing that made bindings feel like configuration rather than a
    choice. Anything this cannot name is returned as it came, because inventing a name
    for a chord would be worse than showing the one that is stored.
    """
    text = str(binding or "").strip()
    # A chord, a hold or an axis is returned whole. These are exactly what the two field
    # projections already refuse to show, and half-naming one - "Left arrow" for
    # `key:ArrowLeft@hold` - would say something the binding does not do.
    if any(mark in text for mark in ("@", "+", "chord(", "/axis:")):
        return text
    if text.startswith(KEY_PREFIX):
        return _key_name(text[len(KEY_PREFIX):])
    if text.startswith(PAD_PREFIX):
        rest = text[len(PAD_PREFIX):]
        pad, _, what = rest.partition("/")
        # Pads are numbered from zero on the wire and from one on screen. A person with
        # one controller has "pad 1", not "pad 0".
        where = f"Pad {int(pad) + 1}" if pad.isdigit() else f"Pad {pad}"
        if what.startswith("button:"):
            return f"{where} button {what[len('button:'):]}"
        return f"{where} {what}" if what else where
    return text


# Key names as a keyboard has them printed. `event.code` is what a browser reports and
# what is stored; the rest is only ever shown.
_KEY_NAMES = {
    "ArrowLeft": "Left arrow", "ArrowRight": "Right arrow",
    "ArrowUp": "Up arrow", "ArrowDown": "Down arrow",
    "ShiftLeft": "Left Shift", "ShiftRight": "Right Shift",
    "ControlLeft": "Left Ctrl", "ControlRight": "Right Ctrl",
    "AltLeft": "Left Alt", "AltRight": "Right Alt",
    "MetaLeft": "Left Meta", "MetaRight": "Right Meta",
    "PageUp": "Page Up", "PageDown": "Page Down",
    "Escape": "Esc", "Enter": "Enter", "Space": "Space", "Tab": "Tab",
    "Backspace": "Backspace", "Delete": "Delete", "Home": "Home", "End": "End",
}


def _key_name(code: str) -> str:
    if code in _KEY_NAMES:
        return _KEY_NAMES[code]
    if code.startswith("Key") and len(code) == 4:
        return code[3]
    if code.startswith("Digit") and len(code) == 6:
        return code[5]
    if code.startswith("Numpad"):
        return f"Numpad {code[len('Numpad'):]}"
    # A single character is already its own name, and an unknown code is more use shown
    # than replaced with a guess.
    return code


def holders(bound) -> dict[str, list[str]]:
    """Every binding, and which actions hold it.

    Compared as stored. Two spellings of one key are two bindings until something
    normalizes them, and pretending otherwise here would report a clash that dispatch
    does not have.
    """
    seen: dict[str, list[str]] = {}
    for name, bindings in dict(bound or {}).items():
        for binding in bindings or ():
            text = str(binding).strip()
            if not text:
                continue
            # An action listing the same binding twice holds it once.
            if name not in seen.setdefault(text, []):
                seen[text].append(name)
    return seen


def collisions(bound) -> dict[str, list[str]]:
    """Bindings more than one action holds.

    Nothing refused one before, anywhere. Dispatch resolves a key to the *first* action
    that lists it in declaration order, so the second binding is not a conflict a player
    is asked about - it is a binding that silently does nothing, and the settings page
    that let them make it showed no sign.
    """
    return {binding: names for binding, names in holders(bound).items()
            if len(names) > 1}


def unrenderable(bindings) -> list[str]:
    """Bindings neither UI field can show - chords, holds, axes, a second pad.

    Kept and written back untouched: dropping them would delete a cabinet's
    hold-both-flippers binding the first time anyone opened settings and pressed Save.
    """
    shown = set(f"{KEY_PREFIX}{k}" for k in keys_in(bindings))
    shown |= set(f"{PAD_PREFIX}0/button:{b}" for b in pad_buttons_in(bindings))
    return [str(b) for b in bindings or () if str(b) not in shown]
