"""The field types an extension can ask for, as one list.

A dialog is drawn by the wizard control, a settings page by the Console's extension page.
Each draws the types below and refuses to draw any other, so a type an extension invents
is stopped when it is declared and not when somebody opens the page.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .store import RESERVED

# What `console/wizard.FIELD_TYPES` draws.
DIALOG_TYPES: frozenset[str] = frozenset({
    "string", "path", "select", "multi", "switch", "choice", "number", "checklist",
    "settle",
})

# What a settings page draws.
SETTINGS_TYPES: frozenset[str] = frozenset({"string", "secret", "switch", "select"})

ALL_TYPES: frozenset[str] = DIALOG_TYPES | SETTINGS_TYPES

# What a dialog's step may carry. The wizard reads more than this for the flows core draws
# itself; none of the rest is an extension's to send.
STEP_KEYS: frozenset[str] = frozenset({
    "step", "title", "help", "fields", "confirm", "steps", "welcome", "ready", "reason",
    "summary", "notes", "errors", "acts",
})


class FieldError(ValueError):
    """A declared field is not one core can draw."""


def settings_fields(name: str, fields: Iterable[Any]) -> list[dict]:
    """The settings an extension declared, in the form core keeps them: every key
    present once, every type one a settings page draws, a `default` that is text.

    A `switch` defaults to `"false"` and is stored as `"true"`/`"false"`, like every
    other setting: the file holds strings.
    """
    kept: list[dict] = []
    seen: set[str] = set()
    for one in fields:
        if not isinstance(one, dict):
            raise FieldError(f"{name} declares a setting that is not a dict")
        key = str(one.get("key") or "").strip()
        if not key:
            raise FieldError(f"{name} declares a setting with no key")
        if key in seen:
            raise FieldError(f"{name} declares the setting {key!r} twice")
        if key in RESERVED:
            raise FieldError(f"{name} declares a setting named {key!r}, which core keeps for "
                             f"itself. Reserved: {', '.join(sorted(RESERVED))}")
        seen.add(key)
        kind = str(one.get("type") or "string")
        if kind not in SETTINGS_TYPES:
            raise FieldError(
                f"{name} declares {key!r} as {kind!r}, which a settings page does not draw."
                f" Drawn: {', '.join(sorted(SETTINGS_TYPES))}")
        default = one.get("default", "")
        if kind == "secret" and default:
            raise FieldError(f"{name} gives the secret {key!r} a default")
        if kind == "switch":
            default = "true" if default in (True, "true") else "false"
        choices = [[str(item[0]), str(item[1])] for item in one.get("choices") or []]
        if kind == "select":
            if not choices:
                raise FieldError(f"{name} declares the select {key!r} with no choices")
            offered = [value for value, _label in choices]
            default = str(default) if default not in ("", None) else offered[0]
            if default not in offered:
                raise FieldError(f"{name} defaults the select {key!r} to {default!r}, "
                                 f"which is not one of its choices: {', '.join(offered)}")
        kept.append({"key": key, "type": kind, "default": "" if default is None
                     else str(default), "choices": choices})
    return kept


def dialog_fields(name: str, fields: Iterable[Any]) -> list[dict]:
    """The fields a dialog's `ask` answered with, checked to be ones the wizard draws."""
    kept = []
    for one in fields:
        kind = str((one or {}).get("type") or "string")
        if kind not in DIALOG_TYPES:
            raise FieldError(
                f"{name} asks for {(one or {}).get('key')!r} as {kind!r}, which a dialog "
                f"does not draw. Drawn: {', '.join(sorted(DIALOG_TYPES))}")
        kept.append(one)
    return kept


def dialog_step(name: str, step: dict) -> None:
    """Refuse a step that carries a key the wizard does not read, which it would drop
    without a word."""
    unknown = sorted(set(step) - STEP_KEYS)
    if unknown:
        raise FieldError(f"{name} answers a step with {', '.join(repr(one) for one in unknown)},"
                         f" which a dialog does not draw. Drawn: {', '.join(sorted(STEP_KEYS))}")
