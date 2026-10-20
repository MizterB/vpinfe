"""Discovery's front page, answered in one read: what VPS added lately, whose work the
library holds, and which of its games lack a kind VPS lists.

Drawn from the answer `library_vps_state.discovery` gives, so Home and the grid never
disagree about what is held. The VPS side is stored state; the media gaps a source can fill
come from the sources' index, which the caller reads.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection, Mapping
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
GAPS_SHOWN = 8


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


def lacking(found: dict[str, Any], listing: str) -> list[dict[str, Any]]:
    """The library's games whose entry lists `listing` while none of it is held, the ones
    with the most on VPS first."""
    out = []
    for row in found.get("rows") or []:
        if not row.get("in_library") or not (row.get("name") or "").strip() \
                or listing not in (row.get("listed") or []):
            continue
        if listing in (row.get("held") or []):
            continue
        out.append({"vps_id": row["vps_id"], "name": (row.get("name") or "").strip(),
                    "img_url": row.get("img_url") or "",
                    "available": len((row.get("releases") or {}).get(listing) or [])})
    out.sort(key=lambda one: (-one["available"], one["name"].casefold()))
    return out


def lacking_media(found: dict[str, Any], offered: Mapping[str, int]) -> list[dict[str, Any]]:
    """The library's games whose entry is in `offered`, a source having a file for a slot
    they have none in, the ones with the most offered first."""
    out = []
    for row in found.get("rows") or []:
        if not row.get("in_library") or not (row.get("name") or "").strip() \
                or row.get("vps_id") not in offered:
            continue
        out.append({"vps_id": row["vps_id"], "name": (row.get("name") or "").strip(),
                    "img_url": row.get("img_url") or "",
                    "available": offered[row["vps_id"]]})
    out.sort(key=lambda one: (-one["available"], one["name"].casefold()))
    return out


def home(found: dict[str, Any], kept: Collection[str], days: int,
         today: date | None = None,
         media: Mapping[str, Mapping[str, int]] | None = None) -> dict[str, Any]:
    """Every shelf. `found` is `library_vps_state.discovery`'s answer, `kept` the VPS kinds
    the library collects, and `days` the window of the New shelf. `media` is the gaps a
    source can fill, by media kind and then by VPS entry, as `media_fill.offered_gaps`
    answers; they follow the VPS kinds in the shelf of games that lack something.

    New is cut to what a tile row shows, once for each chip, with the count each chip holds
    so a chip with nothing in it is left out by the page."""
    shelf = arrivals_in(found, days, kept, today)
    new = {}
    for chip in (ALL, YOURS, *CHIP_KINDS):
        shown = on_chip(shelf, chip)
        new[chip] = {"count": len(shown), "releases": shown[:SHELF_SHOWN]}
    missing = {}
    for listing in GAP_KINDS:
        if listing in kept:
            games = lacking(found, listing)
            missing[listing] = {"count": len(games), "games": games[:GAPS_SHOWN]}
    for kind, offered in (media or {}).items():
        games = lacking_media(found, offered)
        if games:
            missing[kind] = {"count": len(games), "games": games[:GAPS_SHOWN]}
    return {"counted": found.get("counted") or "", "days": days, "since": since(days, today),
            "new": new, "authors": authors_collected(found, shelf), "missing": missing}
