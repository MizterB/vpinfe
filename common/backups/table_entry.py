"""A table's record, kept in Backups beside its file when the table is deleted.

The record is its plays, rating, tags, Hidden and the rest of its entry in the game's
`.info`. It is a copy of its own in the tables area, named `<table file>.entry.json`, taken in
the same delete as the file's, so restoring the file can find it by the stamps.
"""

from __future__ import annotations

import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from common import kept_copies
from common.games import info_migration

from . import folder as backup_folder
from . import media
from .copies import REASON_REPLACE

SUFFIX = ".entry.json"
# The record is copied a moment after the table file, so the two stamps can differ by seconds.
_APART = 10


def is_entry(relative: str) -> bool:
    return relative.endswith(SUFFIX)


def keep(game_id: str, filename: str, entry: dict[str, Any],
         reason: str = REASON_REPLACE) -> Path:
    """Copy `entry`, the record of the table `filename`, into Backups."""
    with tempfile.TemporaryDirectory() as scratch:
        staged = Path(scratch) / f"{filename}{SUFFIX}"
        staged.write_text(json.dumps(entry, indent=2, ensure_ascii=False), encoding="utf-8")
        return media.keep(backup_folder.for_writing(), game_id, staged, staged.name,
                          reason, area=media.TABLES)


def read(copy: Path) -> dict[str, Any] | None:
    """The record a copy holds, or None when it cannot be read."""
    try:
        data = json.loads(copy.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def beside(copy: Path) -> dict[str, Any] | None:
    """The record kept with a table file's copy: the one for the same file taken in the
    same delete, or None when the file went to Backups some other way."""
    name = info_migration.copied_from(copy).name
    taken = _stamp(copy)
    if taken is None:
        return None
    best: tuple[float, Path] | None = None
    for each in copy.parent.glob(f"{name}{SUFFIX}{kept_copies.BACKUP_MARKER}*"):
        at = _stamp(each)
        if at is None or not kept_copies.is_copy(each):
            continue
        apart = abs((at - taken).total_seconds())
        if apart <= _APART and (best is None or apart < best[0]):
            best = (apart, each)
    return None if best is None else read(best[1])


def _stamp(copy: Path) -> datetime | None:
    try:
        return datetime.strptime(kept_copies.backup_stamp(copy), "%Y%m%dT%H%M%SZ").replace(
            tzinfo=UTC)
    except ValueError:
        return None
