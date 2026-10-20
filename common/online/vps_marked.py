"""The marks drawn against the catalog: what the Wanted shelf lists.

`vps_marks` knows ids only. This reads `library_vps_state.discovery`'s answer to say what
each marked id is, and leaves out the ones the catalog no longer lists.
"""

from __future__ import annotations

from typing import Any

from common.online import vps_marks


def _releases_by_id(found: dict[str, Any]) -> dict[str, tuple[dict[str, Any], str, dict[str, Any]]]:
    """Every release of the catalog by its id, with its entry and the kind it is listed under."""
    out = {}
    for row in found.get("rows") or []:
        for listing, releases in (row.get("releases") or {}).items():
            for release in releases:
                out[str(release["id"])] = (row, listing, release)
    return out


def wanted(found: dict[str, Any], marks: vps_marks.Marks) -> list[dict[str, Any]]:
    """The things marked Wanted, the newest mark first: a game by `scope` `game`, a release
    by `release`. `vps_id` is always the entry, `id` the thing itself."""
    entries = {str(row["vps_id"]): row for row in found.get("rows") or []}
    names = [str(one["name"]) for one in found.get("people") or []]
    releases = _releases_by_id(found) if marks.with_state(
        vps_marks.WANTED, (vps_marks.RELEASE,)) else {}
    out = []
    for one in marks.with_state(vps_marks.WANTED, vps_marks.WANTABLE):
        if one["scope"] == vps_marks.GAME:
            row = entries.get(one["id"])
            if row is None or not (row.get("name") or "").strip():
                continue
            out.append({"scope": vps_marks.GAME, "id": one["id"], "vps_id": one["id"],
                        "game": str(row["name"]).strip(), "img_url": row.get("img_url") or "",
                        "in_library": bool(row.get("in_library")), "listing": "",
                        "version": "", "authors": [], "held": False,
                        "since": one["since"]})
            continue
        found_release = releases.get(one["id"])
        if found_release is None:
            continue
        row, listing, release = found_release
        out.append({"scope": vps_marks.RELEASE, "id": one["id"], "vps_id": str(row["vps_id"]),
                    "game": str(row.get("name") or "").strip(),
                    "img_url": row.get("img_url") or "",
                    "in_library": bool(row.get("in_library")), "listing": listing,
                    "version": release.get("version") or "",
                    "authors": [names[at] for at in release.get("by") or [] if at < len(names)],
                    "held": bool(release.get("held")), "since": one["since"]})
    return [one for one in out if one["game"]]
