"""Telling VPinPlay what this cabinet has and what has been played on it.

Built from what core hands over rather than read off disk. The version of this that
lived in core enumerated the library itself, which is the wrong direction and was named
as such in the architecture notes: the online client reached down into games. An
extension has no such reach, and does not need one - the same records arrive through the
context.

Every key and every bound below is the service's, read from a value that is ours. Their
models reject nothing they do not recognize, so a name that drifts is dropped in silence
rather than refused, and that is why the adapter is one place and not several.
"""

from __future__ import annotations

from typing import Any

# Their bound, and one game outside it fails the whole request rather than that game.
RATING_MIN, RATING_MAX = 0, 5

# What the service calls each thing a script was seen to use. Ours are in `features`
# under shorter names; theirs spell Scorbit's product "Scorebit".
FEATURES = {
    "detectNfozzy": "nfozzy",
    "detectFleep": "fleep",
    "detectSSF": "ssf",
    "detectLUT": "lut",
    "detectScorebit": "scorbit",
    "detectFastflips": "fastflips",
    "detectFlex": "flexdmd",
}


def payload_for(game: dict, table: dict | None) -> dict | None:
    """One game in the shape the service accepts, or None where it has nothing to say.

    A game no catalog has matched is skipped: the service keys on the catalog id, so a
    game without one describes nothing it can file.
    """
    vps_id = str(game.get("vps_id") or "").strip()
    if not vps_id:
        return None

    table = table or {}
    user = game.get("user") or {}
    overrides = game.get("overrides") or {}
    features = table.get("features") or {}

    return {
        "info": {"vpsId": vps_id, "rom": _text(game.get("rom"))},
        "user": {
            "rating": _rating(user.get("rating")),
            "lastRun": _epoch(user.get("last_played")),
            "startCount": _number(user.get("play_count")),
            "runTime": _number(user.get("play_time_seconds")) // 60,
            "score": user.get("score") if user.get("score") not in ("", None) else None,
        },
        "vpxFile": {
            "filename": _text(table.get("filename")),
            "filehash": _text(table.get("file_hash")),
            "version": _text(table.get("version")),
            "releaseDate": _text(table.get("release_date")),
            "saveDate": _text(table.get("save_date")),
            "saveRev": _text(table.get("save_rev")),
            # The file's own words, not the game's resolved answer: this section
            # describes the file, and a catalog match would be a different claim.
            "manufacturer": _text(table.get("manufacturer")),
            "year": _text(table.get("year")),
            "type": _text(table.get("type")),
            "vbsHash": _text(table.get("vbs_hash")),
            "rom": _text(game.get("rom")),
            **{theirs: bool(features.get(ours))
               for theirs, ours in FEATURES.items()},
        },
        "vpinfe": {
            "alttitle": _text(overrides.get("alt_title")),
            "altvpsid": _text(overrides.get("alt_vps_id")),
        },
    }


def envelope(user_id: str, initials: str, machine_id: str,
             games: list[dict], program_version: str, sent_at: str) -> dict:
    """What wraps the games. The program and its version are theirs to record."""
    return {
        "source": {"program": "VPinFE", "programVersion": program_version},
        "client": {"userId": user_id, "initials": initials, "machineId": machine_id},
        "sentAt": sent_at,
        "games": games,
    }


def _epoch(value: Any) -> int | None:
    """When it was last played, in the seconds the service takes.

    Records keep an epoch and the API hands out ISO, because those are the right answers
    for a file and for a reader. This is neither: it is what the service accepts, so the
    conversion belongs here with the rest of their vocabulary.
    """
    if value in ("", None):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    from datetime import datetime

    said = str(value).strip().replace("Z", "+00:00")
    try:
        return int(datetime.fromisoformat(said).timestamp())
    except ValueError:
        return None


def _text(value: Any) -> str:
    return str(value or "")


def _number(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _rating(value: Any) -> int:
    """Clamped rather than sent as it came: one game outside their bound fails the
    whole request, so a rating nobody meant is not worth losing a sync over."""
    return max(RATING_MIN, min(RATING_MAX, _number(value)))
