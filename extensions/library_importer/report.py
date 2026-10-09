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


def items_for(ctx: Any, row: Mapping[str, Any], match: Any, cabinet: Cabinet) -> list[dict]:
    """The groups a made game belongs to, as `{group, key, game_id, name, reason}` with the
    game file's `table_id` where the group links to its settings.

    A game that failed and a further build of a machine belong to none. A game filled in
    rather than made is asked about its ROM and virtual DMD only, since its match and
    wheel are the person's own.
    """
    if not row["game_id"] or row["error"] or row.get("joined"):
        return []
    one = {"key": row["key"], "game_id": row["game_id"], "name": row["name"], "reason": ""}
    found = []
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
