"""What the import's report asks the person to look at, worked out as each game is made.

The report's other groups need no record of their own: a game that failed, one imported and
one left alone are already told by the run's rows and `already_here`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from . import plan as plan_for
from .cabinet import Cabinet

NEED_ROM = "need_rom"
NOT_MATCHED = "not_matched"
NO_WHEEL = "no_wheel"
DMD_ALONE = "dmd_alone"
NOT_BROUGHT = "not_brought"
# How many of a game's refused files are named before the rest are counted.
NAMED = 3


def items_for(ctx: Any, row: Mapping[str, Any], match: Any, cabinet: Cabinet) -> list[dict]:
    """The groups a made game belongs to, as `{group, key, game_id, name, reason}` with the
    game file's `table_id` where the group links to its settings.

    A game that failed belongs to none. A further build of a machine belongs only to the
    files that were not imported, which are its own. A game filled in rather than made
    is asked about its ROM, virtual DMD and refused files only, since its match and wheel
    are the person's own.
    """
    if not row["game_id"] or row["error"]:
        return []
    one = {"key": row["key"], "game_id": row["game_id"], "name": row["name"], "reason": ""}
    found = []
    refused = list(row.get("refused") or [])
    if refused:
        shown = ", ".join(refused[:NAMED])
        found.append({**one, "group": NOT_BROUGHT, "reason": shown if len(refused) <= NAMED
                      else ctx.t("report.refused_more", names=shown, count=len(refused) - NAMED)})
    if row.get("joined"):
        return found
    rom = str(row.get("rom") or "")
    if row["table"] and rom and not row.get("rom_there"):
        found.append({**one, "group": NEED_ROM, "reason": rom})
    if not row.get("existing"):
        if not row.get("matched"):
            reason = getattr(match, "reason", "")
            found.append({**one, "group": NOT_MATCHED,
                          "reason": ctx.t(f"why.{reason}") if reason in plan_for.WHY else ""})
        if not row.get("wheel"):
            found.append({**one, "group": NO_WHEEL})
    place = cabinet.dmd.get(rom.casefold()) if row["table"] and rom else None
    if place:
        found.append({**one, "group": DMD_ALONE, "table_id": row.get("table_id", ""),
                      "reason": ctx.t("report.dmd_place", left=place[0], top=place[1])})
    return found
