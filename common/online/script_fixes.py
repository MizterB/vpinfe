"""The community script fixes as a source: the index checked daily, the answer kept.

The watch reads the index once a day, counts the library's tables it has a fix for and keeps
that answer in the cache. Pages read the kept answer and never the network; fetching the
fixes is a separate act that somebody confirms. The index is kept apart from the answer so
reading the answer for each game stays cheap.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import threading
import time
from collections.abc import Mapping
from datetime import timedelta
from typing import Any

from common import timestamps
from common.atomic_write import write_atomic
from common.config.config_store import ConfigStore
from common.config.paths import CACHE_DIR
from common.games import game_repository, library_folders, standalone_scripts
from common.online import sources
from common.online.sources import Source

logger = logging.getLogger("vpinfe.common.online.script_fixes")

ID = "script_fixes"
# The slot a fix fills: the `.vbs` beside the table.
KIND = "script"

ANSWER_PATH = CACHE_DIR / "script-fixes.json"
INDEX_PATH = CACHE_DIR / "script-fixes-index.json"
SCHEMA = 1
EVERY = timedelta(days=1)

_LOCK = threading.RLock()


def available() -> bool:
    """Whether the fixes mean anything on this device. They are scripts written for the
    VPX Standalone engine, not the one Visual Pinball runs on Windows, so there the source
    is not registered at all."""
    return sys.platform != "win32"


def _read(path: Any) -> Any:
    try:
        found = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return found if isinstance(found, dict) and found.get("schema") == SCHEMA else None


_held: tuple[Any, Any] | None = None


def _kept_answer() -> Any:
    """The answer file as `_read` gives it, parsed again only when the file has changed.
    `upgrades` asks once per game, so the file is not read once per game."""
    global _held
    try:
        seen = ANSWER_PATH.stat()
        stamp = (ANSWER_PATH, seen.st_mtime_ns, seen.st_size)
    except OSError:
        _held = None
        return None
    if _held is None or _held[0] != stamp:
        _held = (stamp, _read(ANSWER_PATH))
    return _held[1]


def _write(path: Any, body: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_atomic(path, lambda out: json.dump({**body, "schema": SCHEMA}, out))
    except OSError:
        logger.warning("Could not write %s", path, exc_info=True)


def checked_at() -> str:
    """When the index was last read, ISO 8601 UTC, or "" if it never has been."""
    return str((_read(ANSWER_PATH) or {}).get("checked_at") or "")


def due(now: float | None = None) -> bool:
    """Whether the index is owed a read: never read, read more than a day ago, or stamped
    in the future, which a clock set back leaves and which would otherwise wait it out."""
    was = timestamps.iso_to_epoch(checked_at())
    if was is None:
        return True
    elapsed = (time.time() if now is None else now) - was
    return not 0 <= elapsed < EVERY.total_seconds()


_fetcher: standalone_scripts.StandaloneScripts | None = None


def _read_index() -> list[dict[str, Any]]:
    """The published index, or nothing when it cannot be had. Built once: its constructor
    says so in the log each time. An entry that is not an object is dropped."""
    global _fetcher
    if _fetcher is None:
        _fetcher = standalone_scripts.StandaloneScripts(games=[], auto_run=False)
    return _entries(_fetcher.download_hashes())


def _entries(index: Any) -> list[dict[str, Any]]:
    return [one for one in index if isinstance(one, dict)] if isinstance(index, list) else []


def _library_answers() -> bool:
    """Whether every place the library is kept answers. A count made while one is away
    would describe a smaller library than there is."""
    try:
        return len(library_folders.answering()) == len(library_folders.configured())
    except Exception:  # noqa: BLE001 - not knowing is not a reason to count
        logger.debug("Could not look at the library locations", exc_info=True)
        return False


def check() -> bool:
    """Read the index and count the library against it. True when the tables a fix is
    offered for are not the ones the last count named.

    Nothing is kept, and the next wake asks again, when the index cannot be read (that is
    not a library with nothing to fix) or when the library was not counted: a place that
    does not answer, or no table whose script has been read. A day is stamped only on a
    count that happened.
    """
    if not _library_answers():
        return False
    index = _read_index()
    if not index:
        return False
    with _LOCK:
        found = standalone_scripts.offered_for(game_repository.all_games(), index)
        if not found["checked"]:
            return False
        before = (_read(ANSWER_PATH) or {}).get("offered")
        _write(INDEX_PATH, {"index": index})
        _write(ANSWER_PATH, {**found, "checked_at": timestamps.utc_now_iso()})
    return found["offered"] != before


def recount() -> None:
    """Count the library against the index already held, asking nothing. After a fetch has
    written the fixes, so the answer stops offering them."""
    with _LOCK:
        held, index = _read(ANSWER_PATH), _read(INDEX_PATH)
        if not held or not index:
            return
        found = standalone_scripts.offered_for(game_repository.all_games(),
                                               _entries(index.get("index")))
        _write(ANSWER_PATH, {**found, "checked_at": held.get("checked_at") or ""})


def refresh(config: ConfigStore) -> bool:
    """Read the index if it is due, and say whether what is offered changed."""
    return check() if due() else False


def answer() -> dict[str, Any]:
    """What the last check found, as `standalone_scripts.offered_for` answers it, with
    `checked_at` for when. Nothing is asked of the network. Before the first check, and while
    the source is switched off or does not apply here, it is not reachable and offers nothing."""
    held = _kept_answer()
    if not held or not available() or not sources.enabled(SOURCE):
        return {"reachable": False, "offered": [], "already": 0, "checked": 0,
                "checked_at": ""}
    return {"reachable": bool(held.get("reachable")),
            "offered": [str(one) for one in held.get("offered") or ()],
            "already": int(held.get("already") or 0),
            "checked": int(held.get("checked") or 0),
            "checked_at": str(held.get("checked_at") or "")}


def upgrades(who: Mapping[str, Any], kind: str) -> dict[str, Any]:
    """The fix the last check found for the game in the folder `who` names, as `{"folder"}`,
    or nothing. A fix replaces a table's script, so it answers for that slot only. Asked only
    of an enabled source, by `sources.upgrades`, so the setting is not read again for each
    game."""
    held = _kept_answer()
    if kind != KIND or not held or not available():
        return {}
    folder = re.split(r"[\\/]", str(who.get("folder") or "").rstrip("\\/"))[-1]
    return {"folder": folder} if folder and folder in [str(one) for one in
                                                       held.get("offered") or ()] else {}


SOURCE = Source(id=ID, name="VPX Standalone Scripts",
                url="https://github.com/jsm174/vpx-standalone-scripts",
                refresh=refresh, upgrades=upgrades, upgrades_for=frozenset({KIND}))
