"""Setup's Controls step: the buttons that move around VPinFE, on the table Settings > Input draws.

Each press is saved as it is made, so the step has nothing of its own to write. What belongs
to playing a table is left to Settings > Input: Take Picture is heard only during play, and a
game's own buttons are Visual Pinball's.
"""

from __future__ import annotations

import logging
from typing import Any

from nicegui import ui

from common import input_registry, setting_groups
from common.i18n import t
from console import input_page, offload, panel
from console.api import ApiClient
from console.data import Library
from console.setup_screens import write

logger = logging.getLogger("vpinfe.console.setup_controls")


def _asked_here(schema: list[dict]) -> list[dict]:
    """The schema with the input actions that are not about moving around VPinFE left out."""
    return [{**block, "options": [one for one in block.get("options") or []
                                  if one.get("group") != setting_groups.DURING_PLAY]}
            if block.get("name") == input_registry.SECTION else block for block in schema]


async def ask() -> dict[str, Any]:
    title = t("console.setup.controls.title")
    library = Library(ApiClient())
    try:
        schema = _asked_here(await offload.io(library.config_schema))
        values = await offload.io(library.config_values)
    except Exception:
        logger.warning("Could not read the buttons", exc_info=True)
        return {"title": title, "notes": [t("said.settings_unreadable")]}
    entries = input_page.rows(schema, values, write, pads_when_heard=True)
    if not entries:
        return {"title": title, "notes": [t("said.settings_unreadable")]}

    def draw(_values: dict[str, Any]) -> None:
        panel.facts(ui, entries)

    return {"title": title, "help": t("console.setup.controls.lead"), "draw": draw}


async def answer(_values: dict[str, Any]) -> None:
    """Each press is saved as it is made."""
