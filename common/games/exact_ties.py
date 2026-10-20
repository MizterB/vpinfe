"""Ties VPinFE makes without being asked, for the files where there is only one answer.

A table whose authors and version are found together on exactly one release of its game's
VPS entry is that release. Anything short of that - no authors, a version that does not
read as one, two releases that fit - is left for a person to pick, and shows up as a table
with no release picked.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from common.games import identity_claims, library_folders, ties
from common.games.game_metadata import (
    SOURCE_KEY,
    effective_vps_id,
    keep_game_meta,
    load_game_meta,
    normalize_meta,
)
from common.games.game_repository import all_games
from common.games.game_service import load_vpsdb, release_fits
from common.games.tables import TABLES_KEY, table_entries
from common.i18n import t
from common.online import vps_releases
from common.runtime import jobs as job_registry
from common.values import parse_version

logger = logging.getLogger("vpinfe.common.games.exact_ties")


def _spelled(version: object) -> str:
    """A version as written, less case, spacing and a leading v, and "" for one that does
    not read as a version. Numeric equality is not enough here: 1.2.1a and 1.2.1b are one
    number, and 1.0 and 1.0.0 are two releases."""
    text = "".join(str(version or "").split()).casefold().removeprefix("v")
    return text if parse_version(text) else ""


def exact_release(table: Mapping[str, Any], vps_entry: Mapping[str, Any]) -> dict:
    """The one release of `vps_entry` that credits every author the table names and lists
    its version, or {}. A table file names the lead and VPS credits the whole team, so the
    release may credit more people than the file does."""
    authors = vps_releases.credit_keys(table.get("authors"))
    version = _spelled(table.get("version"))
    if not authors or not version:
        return {}
    found = [release for release in vps_entry.get(vps_releases.TABLES) or []
             if release.get("id")
             and authors <= vps_releases.credit_keys(release.get("authors"))
             and _spelled(release.get("version")) == version
             and release_fits(release, dict(table))]
    return found[0] if len(found) == 1 else {}


def _untied(table: Mapping[str, Any]) -> bool:
    """Whether nothing has said which release this is, a person has not said it is none,
    and it is not a file we made: a patched table is bytes VPS never listed, so no
    release is its release."""
    held = table.get(SOURCE_KEY)
    source = held if isinstance(held, dict) else {}
    return not (source.get(ties.FILE_KEY) or source.get("base") or source.get("patch")
                or ties.declined(source))


def _sure(config: Mapping[str, Any], catalog: Mapping[str, Mapping[str, Any]]) -> dict:
    """The untied tables of a game's `.info` that have an exact release, by table id."""
    vps_entry = catalog.get(effective_vps_id(normalize_meta(config)))
    if not vps_entry:
        return {}
    found = {}
    for table_id, table in table_entries(dict(config)).items():
        if isinstance(table, dict) and _untied(table) and (
                release := exact_release(table, vps_entry)):
            found[table_id] = release
    return found


def tie_game(game: Any, catalog: Mapping[str, Mapping[str, Any]]) -> int:
    """Tie each of a game's untied tables that has an exact release. How many were tied.

    The cached `.info` says whether there is anything to tie before the disk is read, and
    the file is read again before it is written. The folder must be known writable.
    """
    if getattr(game, "info_pending_upgrade", False):
        return 0
    if not _sure(getattr(game, "meta_config", None) or {}, catalog):
        return 0
    config = load_game_meta(game)
    sure = _sure(config, catalog)
    if not sure:
        return 0
    entries = table_entries(config)
    for table_id, release in sure.items():
        held = entries[table_id].get(SOURCE_KEY)
        entries[table_id][SOURCE_KEY] = ties.tie(
            dict(held) if isinstance(held, dict) else {}, str(release["id"]),
            identity_claims.EXACT, release)
    config[TABLES_KEY] = entries
    keep_game_meta(game, config)
    return len(sure)


def tie_library() -> int | None:
    """Tie what can be tied across the library, and say how many tables were. None where
    another pass over the `.info` files is running, so nothing was looked at.

    A game whose folder cannot be written to is left alone.
    """
    try:
        with job_registry.track(job_registry.KIND_LIBRARY_SCAN,
                                title=t("said.title_tie")) as job:
            catalog = {str(entry.get("id") or ""): entry for entry in load_vpsdb()}
            games = [game for game in (all_games() if catalog else ())
                     if _sure(getattr(game, "meta_config", None) or {}, catalog)]
            blocked = {id(game) for game, _ in library_folders.blocked_games(games)}
            tied = 0
            for game in games:
                if id(game) in blocked:
                    continue
                try:
                    tied += tie_game(game, catalog)
                except Exception:
                    logger.warning("Could not tie the tables of %s",
                                   getattr(game, "game_dir_name", "?"), exc_info=True)
            job.detail = t("said.job_tied", count=tied)
            return tied
    except job_registry.JobBusyError:
        return None
