"""VPinPlay's tables, listed under Community, and what the list's page says about who
shares with VPinPlay."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any

from common.extensions.contract import Unavailable, why, words

from .accounts import SEND_NOW, USER_ID, page_for
from .sync import api_root

# An act that is an address: the Console draws it as a link and never calls back for it.
YOUR_PAGE = "your_page"

if TYPE_CHECKING:
    from .sending import Sender

t = words("vpinplay")

OPEN_SITE = "open_site"
# Core's name for Frontend › Players, where a line may send somebody.
PLAYERS = "players"

PAGE = 100
AT_ONCE = 8
TIMEOUT_SECONDS = 15

COLUMNS = [
    {"field": "vps_id", "kind": "game", "name_from": "name"},
    {"field": "manufacturer"},
    {"field": "year", "kind": "number"},
    {"field": "rating", "kind": "number"},
    {"field": "ratings", "kind": "number"},
    {"field": "plays", "kind": "number"},
    {"field": "hours", "kind": "number"},
    {"field": "players", "kind": "number"},
    {"field": "last_played", "kind": "date"},
]
_SHOWN = ["vps_id", "rating", "ratings", "plays", "hours", "players", "last_played"]


def _view(field: str, *then: str) -> dict[str, Any]:
    return {"key": field, "columns": _SHOWN, "ranks": True,
            "sort": [{"field": one, "desc": True} for one in (field, *then)]}


VIEWS = [_view("rating", "ratings"), _view("plays"), _view("hours"), _view("last_played"),
         _view("players")]


def _utc(stamp: Any) -> str:
    said = str(stamp or "").strip()
    if not said or said.endswith("Z") or "+" in said[10:]:
        return said
    return said + "Z"


def _row(item: dict[str, Any]) -> dict[str, Any]:
    minutes = item.get("runTimeTotal") or 0
    authors = item.get("authors")
    if isinstance(authors, str):
        authors = [authors] if authors.strip() else []
    return {"name": str(item.get("name") or ""),
            "manufacturer": str(item.get("manufacturer") or ""),
            "year": item.get("year") if isinstance(item.get("year"), int) else None,
            "rating": round(float(item.get("avgRating") or 0), 1) or None,
            "average": item.get("avgRating"),
            "authors": [str(one) for one in authors] if isinstance(authors, list) else [],
            "ratings": int(item.get("ratingCount") or 0),
            "plays": int(item.get("startCountTotal") or 0),
            "hours": round(float(minutes) / 60, 1) if minutes else 0,
            "players": int(item.get("playerCount") or 0),
            "last_played": _utc(item.get("lastRun")),
            "vps_id": str(item.get("vpsId") or "")}


def _page(endpoint: str, offset: int) -> dict[str, Any]:
    query = urllib.parse.urlencode({"limit": PAGE, "offset": offset, "sort_by": "name",
                                    "sort_order": 1})
    url = f"{api_root(endpoint)}/tables-plus/search?{query}"
    with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as answer:
        return json.loads(answer.read().decode("utf-8"))


def _rows(said: dict[str, Any]) -> list[dict[str, Any]]:
    return [_row(one) for one in said.get("items") or [] if isinstance(one, dict)]


def tables(endpoint: str) -> list[dict[str, Any]]:
    """Every table VPinPlay lists: the first page, then every page its total calls for.
    A service that gives no total is read a page at a time until it says there is no
    more."""
    said = _page(endpoint, 0)
    rows = _rows(said)
    total = (said.get("pagination") or {}).get("total")
    if isinstance(total, int):
        with ThreadPoolExecutor(max_workers=AT_ONCE) as pool:
            for page in pool.map(lambda offset: _page(endpoint, offset),
                                 range(PAGE, total, PAGE)):
                rows += _rows(page)
        return rows
    offset = 0
    while (said.get("pagination") or {}).get("hasNext") and said.get("items"):
        offset += PAGE
        said = _page(endpoint, offset)
        rows += _rows(said)
    return rows


def _host(endpoint: str) -> str:
    try:
        return urllib.parse.urlsplit(endpoint).hostname or endpoint
    except ValueError:
        return endpoint


def rows_from(endpoint_of: Callable[[], str],
              on_read: Callable[[list], None] | None = None) -> Callable[[], list]:
    """The list's `rows()`. `on_read(rows)` is told of every list read whole, and of no
    failed one."""
    def rows() -> list:
        try:
            root = api_root(endpoint_of())
        except ValueError as exc:
            raise Unavailable(why(exc)) from exc
        try:
            found = tables(root)
        except OSError as exc:
            raise Unavailable(why(exc, at=root)) from exc
        except ValueError as exc:
            raise Unavailable(t("error.unreadable", host=_host(root))) from exc
        if on_read is not None:
            on_read(found)
        return found

    return rows


def status(ctx: Any, sender: Sender) -> dict[str, str]:
    """Who shares, by initials. Otherwise why nobody does, linking to where it is fixed."""
    roster = ctx.players.roster()
    holding = [one for one in roster if ctx.players.account(one["id"]).get(USER_ID)]
    if not holding:
        return {"text": ctx.t("list.tables.status.no_account"), "to": PLAYERS}
    if not any(ctx.players.sharing(one["id"]) for one in holding):
        return {"text": ctx.t("list.tables.status.share_off"), "to": PLAYERS}
    sending = sender.sharing()
    if not sending:
        return {"text": ctx.t("list.tables.status.needs_initials"), "to": PLAYERS}
    return {"text": ctx.t("list.tables.status.sharing", players=ctx.t(
        "list.tables.status.list_join").join(one.initials for one in sending))}


def acts(ctx: Any, site: str, sender: Sender) -> dict[str, Any]:
    """Send Now while a sharing account has games waiting; the site; the owner's page
    while the owner holds a user id."""
    def send_now() -> str:
        went, waiting = sender.send_all()
        if waiting:
            return ctx.t("account.status.waiting", count=waiting)
        if not went:
            return ctx.t("account.nothing_waiting")
        return ctx.t("account.sent", count=went)

    offered: dict[str, Any] = {}
    if any(sender.waiting(one.player_id) for one in sender.sharing()):
        offered[SEND_NOW] = send_now
    offered[OPEN_SITE] = site
    owner = next((one for one in ctx.players.roster() if one.get("owner")), None)
    user_id = ctx.players.account(owner["id"]).get(USER_ID, "") if owner else ""
    if user_id:
        offered[YOUR_PAGE] = page_for(site, user_id)
    return offered
