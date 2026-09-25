"""The order a ranked view of a Community list puts what it relates to in."""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any

from common.timestamps import iso_to_epoch


def views_of(listing: dict[str, Any]) -> list[dict[str, Any]]:
    """The views of a declared list that rank. A list that relates to nothing ranks
    nothing here, whatever its views say."""
    if not listing.get("relation"):
        return []
    return [one for one in listing.get("views") or [] if one.get("ranks")]


def _value(raw: Any, kind: str) -> float | None:
    if raw is None or raw == "" or isinstance(raw, bool):
        return None
    if kind == "date":
        return iso_to_epoch(raw)
    try:
        number = float(raw)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def ranks(rows: Iterable[dict[str, Any]], listing: dict[str, Any],
          view: dict[str, Any]) -> dict[str, int]:
    """Each related id's rank, 1 the best. A row with no value in the view's first sort
    field ranks nowhere, rows that sort the same share a rank, and an id on several rows
    takes the best of them."""
    kinds = {one["field"]: str(one.get("kind") or "text")
             for one in listing.get("columns") or []}
    field = str((listing.get("relation") or {}).get("field") or "")
    sort = list(view.get("sort") or [])
    keyed: list[tuple[tuple, str]] = []
    for row in rows:
        said = str(row.get(field) or "").strip()
        values = [_value(row.get(one["field"]), kinds.get(one["field"], "")) for one in sort]
        if not said or not values or values[0] is None:
            continue
        keyed.append((tuple((value is None,
                             0.0 if value is None else -value if one.get("desc") else value)
                            for value, one in zip(values, sort, strict=True)), said))
    keyed.sort(key=lambda pair: pair[0])
    found: dict[str, int] = {}
    rank, last = 0, None
    for key, said in keyed:
        if key != last:
            rank, last = rank + 1, key
        found.setdefault(said, rank)
    return found
