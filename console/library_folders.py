"""What the Folders page and the Library Importer's button share: the state words and the
importer's import action.

What the disk says is read on every draw and never stored. A stored answer is wrong the
moment a mount drops, and a mount dropping is the case plural locations exist to report.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from common import path_state
from common.i18n import t
from console import offload
from console.data import Library
from console.on_page import on_page

IMPORTER = "library_importer"

STATE_WORDS = {path_state.OK: "word.ready", path_state.READ_ONLY: "word.read_only",
               path_state.NOT_CONNECTED: "word.not_connected",
               path_state.MISSING: "word.not_found", path_state.WRONG_KIND: "word.not_found",
               path_state.NOT_ANSWERING: "word.not_answering"}
# What each state costs, for its chip. Anything not listed is a location that cannot be read.
STATE_TIERS = {path_state.OK: "on", path_state.READ_ONLY: "warn"}

ASKING = {"updates": {"ask_where_new_games_go": True}}
NOT_ASKING = {"updates": {"ask_where_new_games_go": False}}


def state_of(row: dict[str, Any]) -> str:
    """The fewest true words. Why is in the row's reason."""
    word = STATE_WORDS.get(str(row.get("state") or ""))
    return t(word) if word else ""


async def import_action(library: Library) -> dict | None:
    """The Library Importer's import, when that extension is running - a button that
    refuses is worse than none, so an extension that is off or gone offers nothing."""
    try:
        found = await offload.io(library.extensions)
    except Exception:  # noqa: BLE001 - a list that will not load is no action
        return None
    importer = next((one for one in found if one.get("name") == IMPORTER), {})
    return next((one for one in importer.get("actions") or [] if one.get("key") == "import"),
                None)


@on_page
async def open_importer(action: dict, rerender: Callable[[], None] | None) -> None:
    """The import dialog, then the page redrawn: it can add a library folder, and the list
    and its count are read when the page draws."""
    from console import ext_action

    if await ext_action.open_action(IMPORTER, action) and rerender is not None:
        rerender()
