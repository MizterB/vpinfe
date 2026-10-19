"""Which build of Visual Pinball wrote an ini, and so which settings that build has."""

from __future__ import annotations

import re

from .setting_types import LINE, SPANS

_REV = re.compile(r"[0-9]+")


def rev_of(version: str | None) -> int | None:
    """The Rev of a build in the line the settings were read from, out of the
    `[Version] VPinball` an ini records. None for a build of any other line, and for none.
    """
    said = (version or "").strip()
    rest = said[len(LINE):]
    if not LINE or not said.startswith(LINE) or not _REV.fullmatch(rest):
        return None
    return int(rest)


def declares(qualified: str, rev: int | None, plugin_present: bool = False) -> bool:
    """Whether the build at `rev` has this setting. True for every setting we hold no span
    for, and for a build whose Rev we do not know.

    An ini older than the program that reads it lacks the settings added since, so a
    setting of a plugin the program has is not held back for a Rev below its first. A setting
    the program dropped stays dropped whatever plugin carries it.
    """
    span = SPANS.get(qualified)
    if span is None or rev is None:
        return True
    if span.until is not None and rev >= span.until:
        return False
    return rev >= span.since or plugin_present
