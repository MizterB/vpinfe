"""The mark that says an extension is not VPinFE's own.

One glyph and one tooltip, drawn wherever a third-party extension's name stands in for what
it added: the rail, a menu's block heading, a panel group, a Needs You group. An extension
VPinFE ships draws none of it.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from nicegui import ui

from common import accepted
from common.i18n import t

GLYPH = "gpp_maybe"


def unofficial(extension: dict[str, Any] | None) -> bool:
    """Whether VPinFE did not ship it. One that says nothing of where it came from is
    taken as shipped, so a bare record draws no mark."""
    return bool(extension) and str((extension or {}).get("origin") or accepted.SHIPPED) \
        != accepted.SHIPPED


def named(extension: dict[str, Any]) -> str:
    return str(extension.get("display_name") or extension.get("name") or "")


def tip(extension: dict[str, Any]) -> str:
    return t("console.ext_mark.tip", name=named(extension))


def by_name(extensions: Sequence[dict[str, Any]], name: str) -> dict[str, Any] | None:
    return next((one for one in extensions if one.get("name") == name), None)


def draw(extension: dict[str, Any] | None, *, classes: str = "") -> ui.icon | None:
    """The glyph with its tooltip, or nothing for an extension VPinFE shipped."""
    if extension is None or not unofficial(extension):
        return None
    icon = ui.icon(GLYPH).classes(f"console-ext-mark {classes}".strip())
    icon.tooltip(tip(extension))
    return icon


def drawer(extension: dict[str, Any] | None) -> Callable[[], None] | None:
    """`draw` for a caller that draws it later, inside a container of its own, or None
    where there is nothing to draw."""
    if extension is None or not unofficial(extension):
        return None

    def mark() -> None:
        draw(extension)

    return mark
