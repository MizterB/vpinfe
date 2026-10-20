"""Discovery's front page, answered in one read: what VPS added lately, whose work the
library holds, and which of its games lack a kind VPS lists.

Drawn from the answer `library_vps_state.discovery` gives, so Home and the grid never
disagree about what is held. The VPS side is stored state; the media gaps a source can fill
come from the sources' index, which the caller reads.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection, Iterable, Mapping
from datetime import date, timedelta
from typing import Any

from common.online import arrivals, vps_source

ALL = "all"
YOURS = "yours"
# Rule sheets are in Releases, not on Home.
NOT_SHOWN = ("ruleFiles",)
# The kinds the New shelf has a chip for, in the order the chips run.
CHIP_KINDS = ("tableFiles", "b2sFiles", "wheelArtFiles", "topperFiles", "pupPackFiles")
# The kinds a game can lack, in the order the shelf's tabs run.
GAP_KINDS = ("b2sFiles", "romFiles", "povFiles", "wheelArtFiles", "topperFiles")

SHELF_SHOWN = 12
AUTHORS_SHOWN = 8
# The most games a tab shows that only VPS lists. A game a source has a file for is always shown.
GAPS_SHOWN = 8
# The media kind a source files under what VPS lists as a kind: one tab holds both. A media
# kind not named here has a tab of its own.
MEDIA_OF = {"b2sFiles": "backglass", "wheelArtFiles": "wheel", "topperFiles": "topper"}


def since(days: int, today: date | None = None) -> str:
    """The day `days` back, as a date: compared as text with each release's `added`."""
    return ((today or date.today()) - timedelta(days=days)).isoformat()


def arrivals_in(found: dict[str, Any], days: int, kept: Collection[str],
                today: date | None = None) -> list[dict[str, Any]]:
    """The releases of the kinds the library collects that VPS added in the last `days`,
    newest first, one per release. `was` is the version a release held before VPS last
    changed it, which is what a re-dated release says it was."""
    cutoff = since(days, today)
    names = [one["name"] for one in found.get("people") or []]
    shelf = []
    for row in found.get("rows") or []:
        game = (row.get("name") or "").strip()
        if not game:
            continue
        for listing, releases in (row.get("releases") or {}).items():
            if listing not in kept or listing in NOT_SHOWN:
                continue
            for release in releases:
                added = release.get("added") or ""
                if added < cutoff:
                    continue
                version = release.get("version") or ""
                before = arrivals.was(vps_source.ID, release["id"])
                shelf.append({
                    "vps_id": row["vps_id"], "game": game, "img_url": row.get("img_url") or "",
                    "in_library": bool(row.get("in_library")), "listing": listing,
                    "id": release["id"], "added": added, "version": version,
                    "was": before if before != version else "",
                    "held": bool(release.get("held")), "mod": bool(release.get("mod")),
                    "authors": [names[at] for at in release.get("by") or [] if at < len(names)]})
    shelf.sort(key=lambda one: (one["added"], one["game"].casefold()), reverse=True)
    return shelf


def on_chip(shelf: list[dict[str, Any]], chip: str) -> list[dict[str, Any]]:
    if chip == ALL:
        return shelf
    if chip == YOURS:
        return [one for one in shelf if one["in_library"]]
    return [one for one in shelf if one["listing"] == chip]


def authors_collected(found: dict[str, Any], shelf: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Whose work the library holds the most of, each with how many of those releases it
    holds and how many of theirs are on the shelf. Empty until the library is compared."""
    people = found.get("people") or []
    holding: Counter[int] = Counter()
    for row in found.get("rows") or []:
        for releases in (row.get("releases") or {}).values():
            for release in releases:
                if release.get("held"):
                    holding.update(release.get("by") or [])
    new: Counter[str] = Counter()
    for one in shelf:
        new.update(one["authors"])
    ranked = sorted((at for at in holding if at < len(people)),
                    key=lambda at: (-holding[at], people[at]["name"].casefold()))
    return [{"name": people[at]["name"], "held": holding[at], "new": new[people[at]["name"]]}
            for at in ranked[:AUTHORS_SHOWN]]


def lacking(found: dict[str, Any], listing: str,
            holders: Mapping[str, Iterable[str]] | None = None) -> list[dict[str, Any]]:
    """The library's games whose entry lists `listing` while none of it is held, the ones
    with the most on VPS first. `holders` is the library's game ids by entry, as
    `media_fill.holders` answers: a game is then listed once for each of them, and an entry no
    game is matched to is not listed. Without it each entry is one record with no game id."""
    out = []
    for row in found.get("rows") or []:
        if not row.get("in_library") or not (row.get("name") or "").strip() \
                or listing not in (row.get("listed") or []):
            continue
        if listing in (row.get("held") or []):
            continue
        for game_id in ("",) if holders is None else sorted(holders.get(row["vps_id"], ())):
            out.append({"vps_id": row["vps_id"], "game_id": game_id,
                        "name": (row.get("name") or "").strip(),
                        "img_url": row.get("img_url") or "",
                        "vps": len((row.get("releases") or {}).get(listing) or []),
                        "source": 0})
    out.sort(key=lambda one: (-one["vps"], one["name"].casefold(), one["game_id"]))
    return out


def lacking_media(found: dict[str, Any],
                  offered: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The games a source has a file for in a slot they have none in, `offered` being
    `media_fill.offered_listing`'s records for one kind: every one is listed, in the library
    or not as the last comparison saw it, since the games are the library's own. The picture
    is the comparison's where it knows the entry. The ones with most offered come first."""
    pictures = {row.get("vps_id"): row.get("img_url") or "" for row in found.get("rows") or []}
    out = [{"vps_id": one["vps_id"], "game_id": one["game_id"],
            "name": (one.get("name") or "").strip() or one["vps_id"],
            "img_url": pictures.get(one["vps_id"], ""), "vps": 0, "source": one["available"]}
           for one in offered]
    out.sort(key=lambda one: (-one["source"], one["name"].casefold(), one["game_id"]))
    return out


def _same_game(listed: Mapping[str, Any], offered: Mapping[str, Any]) -> bool:
    """Whether a record from VPS and one from a source are one game: the same library id, or
    where VPS's has none, the same entry."""
    if listed["game_id"]:
        return listed["game_id"] == offered["game_id"]
    return listed["vps_id"] == offered["vps_id"]


def gaps(listed: list[dict[str, Any]], offered: list[dict[str, Any]]) -> dict[str, Any]:
    """One tab: the games `lacking` lists and the games `lacking_media` lists, each game once.
    A game both name keeps its library id and carries both counts. Every game a source has a
    file for is shown; of the ones only VPS lists, the first `GAPS_SHOWN`. `game_ids` is every
    game the tab counts, which is what See All opens; `on_vps` is how many of them VPS lists."""
    for one in offered:
        one["vps"] = max((other["vps"] for other in listed if _same_game(other, one)), default=0)
    merged = [*offered, *(one for one in listed
                          if not any(_same_game(one, other) for other in offered))]
    merged.sort(key=lambda one: (-(one["vps"] + one["source"]), one["name"].casefold(),
                                 one["game_id"]))
    shown, only_vps = [], 0
    for one in merged:
        if one["source"] == 0:
            only_vps += 1
            if only_vps > GAPS_SHOWN:
                continue
        shown.append(one)
    return {"count": len(merged), "on_vps": len(listed),
            "game_ids": [one["game_id"] for one in merged if one["game_id"]], "games": shown}


def home(found: dict[str, Any], kept: Collection[str], days: int,
         today: date | None = None,
         media: Mapping[str, Iterable[Mapping[str, Any]]] | None = None,
         holders: Mapping[str, Iterable[str]] | None = None) -> dict[str, Any]:
    """Every shelf. `found` is `library_vps_state.discovery`'s answer, `kept` the VPS kinds
    the library collects, and `days` the window of the New shelf. `media` is the games a
    source can fill a slot of, by media kind, as `media_fill.offered_listing` answers. A kind
    VPS lists too (`MEDIA_OF`) is one tab with it, a game once; the other media kinds follow
    the VPS kinds, one tab each. Every game a source can fill is listed, none cut to a row.
    `holders` is the library's game ids by entry; with it a game VPS lists is one record for each
    game matched to the entry, so a tab counts games and `game_ids` names them all.

    New is cut to what a tile row shows, once for each chip, with the count each chip holds
    so a chip with nothing in it is left out by the page."""
    shelf = arrivals_in(found, days, kept, today)
    new = {}
    for chip in (ALL, YOURS, *CHIP_KINDS):
        shown = on_chip(shelf, chip)
        new[chip] = {"count": len(shown), "releases": shown[:SHELF_SHOWN]}
    filed = {kind: listing for listing, kind in MEDIA_OF.items()}
    sourced = {}
    for kind, offered in (media or {}).items():
        if games := lacking_media(found, offered):
            sourced[filed.get(kind, kind)] = games
    missing = {listing: gaps(lacking(found, listing, holders), sourced.pop(listing, []))
               for listing in GAP_KINDS if listing in kept}
    for tab, games in sourced.items():
        missing[tab] = gaps([], games)
    return {"counted": found.get("counted") or "", "days": days, "since": since(days, today),
            "new": new, "authors": authors_collected(found, shelf), "missing": missing}
