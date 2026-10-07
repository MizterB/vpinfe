"""Setup's Appearance step: how the Console looks, drawn as the miniatures Settings uses.

A choice repaints the page under the dialog as it is made, so the person sees the result
before pressing Next. The answer is written on Next, like every other step's.
"""

from __future__ import annotations

from typing import Any

from common.i18n import t
from console import offload, theme, theme_picker
from console.api import ApiClient

KEY = "look"


def _chosen(values: dict[str, Any]) -> str:
    return theme.mode_or_default(str(values.get(KEY) or ""))


def repaint(values: dict[str, Any]) -> None:
    """The page in the mode the person has just picked. Drawn only, not saved."""
    theme.repaint(_chosen(values))


def restore() -> None:
    """The page back in the look that is saved, for a Setup closed before the pick was."""
    theme.repaint(theme.configured_mode())


async def ask() -> dict[str, Any]:
    question = t("console.setup.look.title")
    return {
        "title": question,
        "help": t("console.setup.look.lead"),
        "fields": [{
            "key": KEY, "type": "choice", "label": question,
            "value": theme.configured_mode(),
            "choices": theme_picker.choices(),
        }],
        "changed": repaint,
    }


async def answer(values: dict[str, Any]) -> None:
    mode = _chosen(values)
    if mode != theme.configured_mode():
        await offload.io(ApiClient().put_config, {theme.MODE_SECTION: {theme.MODE_KEY: mode}})
