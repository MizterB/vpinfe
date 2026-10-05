"""What an update did to a person's files, kept so the review of it can say so.

Written beside the stores each migration changes, never inside them, and by the caller
that knows the count. A migration's own marker says it ran; this says what it did.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from pathlib import Path

from common import paths
from common.atomic_write import write_atomic
from common.release_notes import is_release, newer

logger = logging.getLogger("vpinfe.common.migration_ledger")

FILE_NAME = "migrations.json"

_lock = threading.Lock()


@dataclass(frozen=True)
class Entry:
    name: str
    version: str
    count: int = 0


def _path(path: str | Path | None) -> Path:
    return Path(path) if path is not None else paths.CONFIG_DIR / FILE_NAME


def _load(path: Path) -> list[dict]:
    """What the file holds. A file that is not there holds nothing; one that is there and
    cannot be read raises, so a later write does not replace history with one entry."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except ValueError:
        return []
    found = data.get("migrations") if isinstance(data, dict) else None
    return [one for one in found if isinstance(one, dict) and one.get("name")] \
        if isinstance(found, list) else []


def record(name: str, version: str, count: int = 0, path: str | Path | None = None) -> None:
    """Note that `name` ran under `version` and changed `count` things. A second call for
    the same name and version adds its count, so a job that runs in pieces is one line.
    Never raises: a note that cannot be kept must not fail what it describes."""
    target = _path(path)
    with _lock:
        try:
            kept = _load(target)
            for one in kept:
                if one["name"] == name and one.get("version") == version:
                    one["count"] = int(one.get("count") or 0) + int(count)
                    break
            else:
                kept.append({"name": name, "version": version, "count": int(count)})
            write_atomic(target, lambda handle: json.dump({"migrations": kept}, handle,
                                                          indent=2))
        except OSError:
            logger.exception("Could not record that %s ran", name)


def entries(since: str, path: str | Path | None = None) -> list[Entry]:
    """What ran under a tagged release after `since`, in the order it ran. With nothing
    for `since`, every such entry. A build that is not a release is not one a person ran
    an update to, so what it did is left out."""
    try:
        kept = _load(_path(path))
    except OSError:
        return []
    return [Entry(one["name"], str(one.get("version") or ""), int(one.get("count") or 0))
            for one in kept
            if is_release(str(one.get("version") or ""))
            and (not since or newer(str(one["version"]), since))]
