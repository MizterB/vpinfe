"""Restores that wait for VPinFE to close.

The files in the config folder are held in memory by the running app and written back from
it, so a copy put in place now would be overwritten by the next save. The restore is
written down here and carried out as the app exits, after everything has stopped writing.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from common.atomic_write import write_atomic
from common.games import info_maintenance
from common.games.info_migration import copied_from, is_copy
from common.paths import CONFIG_DIR

logger = logging.getLogger("vpinfe.common.backups.pending")

PENDING_NAME = ".pending-restores.json"


def _file(config_dir: Path | None = None) -> Path:
    return (config_dir or CONFIG_DIR) / PENDING_NAME


def held(config_dir: Path | None = None) -> dict[str, str]:
    """Each file waiting to be replaced, and the copy that replaces it."""
    try:
        data = json.loads(_file(config_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}


def _write(found: dict[str, str], config_dir: Path | None) -> None:
    path = _file(config_dir)
    if not found:
        path.unlink(missing_ok=True)
        return
    write_atomic(path, lambda handle: json.dump(found, handle, indent=2))


def add(target: Path, copy: Path, config_dir: Path | None = None) -> None:
    """A second copy for the same file replaces the first: only one can end up in place."""
    found = held(config_dir)
    found[str(target)] = str(copy)
    _write(found, config_dir)


def drop(copy: Path, config_dir: Path | None = None) -> bool:
    """Forget a restore waiting on this copy. True when there was one."""
    found = held(config_dir)
    kept = {target: held_copy for target, held_copy in found.items() if held_copy != str(copy)}
    if kept == found:
        return False
    _write(kept, config_dir)
    return True


def apply(config_dir: Path | None = None) -> int:
    """Put each waiting copy in place, keeping what it replaces. Returns how many went in.

    A copy that has gone is skipped, and one that cannot be put in place does not stop the
    others. The list is cleared either way, so a failure is not tried again on every exit.
    """
    folder = config_dir or CONFIG_DIR
    done = 0
    for target, copy in held(folder).items():
        try:
            if (Path(target).parent != folder or Path(copy).parent != folder
                    or not is_copy(copy) or copied_from(copy) != Path(target)
                    or not Path(copy).is_file()):
                continue
            info_maintenance.restore_file(Path(target), Path(copy))
            done += 1
        except (OSError, ValueError):
            logger.exception("Could not restore %s from %s", target, copy)
    _file(folder).unlink(missing_ok=True)
    return done
