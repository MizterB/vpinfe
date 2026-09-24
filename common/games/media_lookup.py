"""Find the media file behind /media/<table_id>/<kind>.

Addressed by table because tier 1 of the chain keys off the table, and resolved that way
too: the scan records one resolution per .vpx, so two builds in a folder can differ.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from common.games import game_identity
from common.games.game import GameRecord
from common.games.game_metadata import normalize_meta
from common.games.tables import entry_filename, table_entries
from common.media_specs import MEDIA_SPECS, canonical_kind

_ATTR_BY_KIND = {spec.kind: spec.attr for spec in MEDIA_SPECS}


def _resolved(game: GameRecord, table_id: str, kind: str) -> str:
    """What the scan resolved for one kind of one table, or "" for nothing."""
    by_table = getattr(game, "media_by_table", None)
    filename = table_filename(game, table_id).lower()
    if by_table is not None and filename in by_table:
        # No fallback: dropping through would hand this table whatever the *default*
        # table resolved.
        return str(by_table[filename].get(kind, "") or "").strip()
    # Nothing per-table to consult, so the default table's answer is the honest one.
    return str(getattr(game, _ATTR_BY_KIND[kind], "") or "").strip()


def resolved_kinds(game: GameRecord, table_id: str = "") -> list[str]:
    """The kinds a table has a file for, in spec order. Names, never paths."""
    return [kind for kind in _ATTR_BY_KIND if _resolved(game, table_id, kind)]


def game_for_table(games: Sequence[Any], table_id: str) -> Any | None:
    """The game that owns a table id, or the game with that id.

    A folder no build has touched has no table ids yet but still has art, so its entry
    addresses media by the game's id.
    """
    wanted = str(table_id or "").strip()
    if not wanted:
        return None
    for game in games:
        if wanted in table_entries(normalize_meta(getattr(game, "meta_config", {}))):
            return game
    return game_identity.find_by_id(games, wanted)


def table_filename(game: GameRecord, table_id: str) -> str:
    """The .vpx the id names, or "" when the id named the game rather than a table."""
    entries = table_entries(normalize_meta(getattr(game, "meta_config", {})))
    return entry_filename(entries.get(str(table_id or "").strip()))


def media_path(games: Sequence[Any], table_id: str, kind: str) -> Path | None:
    """The file behind /media/<table_id>/<kind>, or None if there is not one."""
    # A theme built against an older kind name still addresses media by it.
    kind = canonical_kind(kind)
    if kind not in _ATTR_BY_KIND:
        return None
    game = game_for_table(games, table_id)
    if game is None:
        return None

    resolved = _resolved(game, table_id, kind)
    if not resolved:
        return None
    path = Path(resolved)
    return path if path.is_file() else None
