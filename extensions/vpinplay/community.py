"""VPinPlay's tables, listed under Community."""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from fastapi import APIRouter, HTTPException

from common.extensions.contract import words

logger = logging.getLogger(__name__)
t = words("vpinplay")

PAGE = 100
KEEP_SECONDS = 600
TIMEOUT_SECONDS = 15
# A bound on a list that should end, so a server that always says there is more cannot
# keep this asking.
MOST_PAGES = 50

COLUMNS = [
    {"field": "name", "under": ["manufacturer", "year"]},
    {"field": "manufacturer"},
    {"field": "year", "kind": "number"},
    {"field": "rating", "kind": "number"},
    {"field": "ratings", "kind": "number"},
    {"field": "plays", "kind": "number"},
    {"field": "hours", "kind": "number"},
    {"field": "players", "kind": "number"},
    {"field": "last_played", "kind": "date"},
    {"field": "vps_id"},
]
_SHOWN = ["name", "rating", "ratings", "plays", "hours", "players", "last_played"]


def _view(field: str, *then: str) -> dict[str, Any]:
    return {"key": field, "columns": _SHOWN,
            "sort": [{"field": one, "desc": True} for one in (field, *then)]}


VIEWS = [_view("rating", "ratings"), _view("plays"), _view("hours"), _view("last_played"),
         _view("players")]
RELATION = {"field": "vps_id", "keys": "vps_entry"}

_lock = threading.Lock()
_held: dict[str, Any] = {"at": 0.0, "endpoint": "", "rows": []}


def _utc(stamp: Any) -> str:
    said = str(stamp or "").strip()
    if not said or said.endswith("Z") or "+" in said[10:]:
        return said
    return said + "Z"


def _row(item: dict[str, Any]) -> dict[str, Any]:
    minutes = item.get("runTimeTotal") or 0
    return {"name": str(item.get("name") or ""),
            "manufacturer": str(item.get("manufacturer") or ""),
            "year": item.get("year") if isinstance(item.get("year"), int) else None,
            "rating": round(float(item.get("avgRating") or 0), 1) or None,
            "ratings": int(item.get("ratingCount") or 0),
            "plays": int(item.get("startCountTotal") or 0),
            "hours": round(float(minutes) / 60, 1) if minutes else 0,
            "players": int(item.get("playerCount") or 0),
            "last_played": _utc(item.get("lastRun")),
            "vps_id": str(item.get("vpsId") or "")}


def _page(endpoint: str, offset: int) -> dict[str, Any]:
    query = urllib.parse.urlencode({"limit": PAGE, "offset": offset, "sort_by": "name",
                                    "sort_order": 1})
    url = f"{endpoint.rstrip('/')}/api/v1/tables-plus/search?{query}"
    with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as answer:
        return json.loads(answer.read().decode("utf-8"))


def tables(endpoint: str) -> list[dict[str, Any]]:
    """Every table VPinPlay lists, kept for `KEEP_SECONDS`."""
    with _lock:
        if (_held["endpoint"] == endpoint and _held["rows"]
                and time.monotonic() - _held["at"] < KEEP_SECONDS):
            return list(_held["rows"])
    rows: list[dict[str, Any]] = []
    for page in range(MOST_PAGES):
        said = _page(endpoint, page * PAGE)
        rows += [_row(one) for one in said.get("items") or [] if isinstance(one, dict)]
        if not (said.get("pagination") or {}).get("hasNext"):
            break
    with _lock:
        _held.update(at=time.monotonic(), endpoint=endpoint, rows=rows)
    return list(rows)


def router(endpoint_of: Any) -> APIRouter:
    reading = APIRouter()

    @reading.get("/community/tables")
    def community_tables() -> dict:
        endpoint = endpoint_of()
        try:
            return {"rows": tables(endpoint)}
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            logger.warning("VPinPlay did not answer at %s: %s", endpoint, exc)
            raise HTTPException(status_code=502,
                                detail=t("error.no_answer", endpoint=endpoint,
                                         error=exc)) from exc

    return reading
