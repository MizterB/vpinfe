"""Copies of the files an app keeps its settings in.

Only the app knows which file its settings are in; moving a file is core's, which does
it for every kind already. So the app names them and this copies them.

A copy of what is there now is taken before a restore - restoring the wrong one is a
mistake somebody makes once, and without that copy it is the last one they get to make.
"""

from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path

from common.games.info_migration import RESTORE, copied_from, copy_aside
from common.i18n import t

logger = logging.getLogger("vpinfe.common.games.config_backups")

# A launcher id as it is spelt in a folder name.
_LABEL = re.compile(r"[^A-Za-z0-9._-]+")


def safe(label: str) -> str:
    return _LABEL.sub("-", str(label or "").strip()).strip("-.")[:64]


def restore(name: str, files: dict[str, str], *, home: Path) -> Path | None:
    """Put a copy back, over a copy of what is there now. `home` is the folder the copy is
    in.

    Returns the safety copy it took first, so a caller can say what it did rather than
    only that it did it.
    """
    source = home / Path(str(name or "")).name
    if not source.is_file() or source.parent != home:
        raise FileNotFoundError(t("error.launchers.copy_gone"))

    target = target_for(source, files)
    if target is None:
        raise ValueError(t("error.launchers.copy_unmatched"))

    safety = None
    if target.is_file():
        home.mkdir(parents=True, exist_ok=True)
        safety = Path(copy_aside(target, RESTORE, into=home, restoring=source))
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    logger.info("Restored %s over %s", source.name, target)
    return safety


def target_for(source: Path, files: dict[str, str]) -> Path | None:
    """Which of the app's files this copy came from, by the name it was taken under."""
    name = copied_from(source).name
    return next((Path(path).expanduser() for path in files.values()
                 if Path(path).expanduser().name == name), None)
