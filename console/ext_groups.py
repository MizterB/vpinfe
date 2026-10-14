"""The groups extensions put on a game's or a table's panel, in Play after High Scores.

The extension answers with one section of facts, fields and rows and core draws it as it
draws the rest of the panel. The panel never waits for it: each group is a region drawn
once its answer arrives, and one that has nothing to say, or does not answer, leaves no
trace in the panel.
"""

from __future__ import annotations

import logging
from functools import partial
from typing import Any
from urllib.parse import quote

from nicegui import ui

from common.failures import why
from console import busy, ext_row, offload, panel
from console.api import ApiClient

logger = logging.getLogger("vpinfe.console.ext_groups")


def route(extension: dict[str, Any], group: dict[str, Any], game_id: str,
          table_id: str = "") -> str:
    base = f"/ext/{extension.get('name')}{group['base']}/{quote(game_id, safe='')}"
    return f"{base}/{quote(table_id, safe='')}" if group["subject"] == "table" else base


def declared(context: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """(extension, group) for each group that belongs on this panel. A game's group is on
    a game's panel and on a table's; a table's group is only on a table's. Empty for a
    Private game: the extension is not told the library holds it."""
    if context["game"].get("private"):
        return []
    subjects = ("game", "table") if context["lens"] else ("game",)
    return [(extension, group)
            for extension in context["state"].get("extensions") or []
            for group in extension.get("groups") or []
            if group["subject"] in subjects]


def fill(context: dict[str, Any]) -> None:
    """A region for each group, in the container now open, each drawn when it is read."""
    for extension, group in declared(context):
        region = ui.column().classes("gap-0")
        busy.fill(region, partial(_show, region, extension, group, context, None))


async def _show(region: ui.element, extension: dict[str, Any], group: dict[str, Any],
                context: dict[str, Any], answer: dict[str, Any] | None) -> None:
    """The group, from `answer` where the write that came just before it gave one, else
    read again."""
    where = route(extension, group, str(context["game_id"]), str(context["lens"] or ""))
    if answer is None:
        try:
            answer = dict(await offload.io(ApiClient().ext_get, where))
        except Exception as exc:  # noqa: BLE001 - a group that does not answer is no group
            logger.warning("%s's %s group did not answer: %s", extension.get("name"),
                           group["subject"], why(exc))
            return
    if region.is_deleted:
        return
    region.clear()
    section = answer.get("section")
    if not section:
        return

    async def redraw(new: dict[str, Any] | None) -> None:
        await _show(region, extension, group, context, new)

    held = {"state": context["state"], "route": where, "redraw": redraw, "again": None}
    with region:
        panel.facts(ui, [(panel.HEADING, str(answer.get("title") or "")),
                         *ext_row.section_entries(section, held)])
