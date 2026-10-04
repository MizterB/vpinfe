"""Copies of the files an app keeps its settings in.

Only the app knows which file its settings are in; moving a file is core's, which does
it for every kind already. So the app names them and this copies them.

Named, timestamped, and a copy of what is there now taken before a restore - restoring
the wrong one is a mistake somebody makes once, and without that copy it is the last one
they get to make.
"""

from __future__ import annotations

import logging
import re
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from common.games.info_migration import (
    RESTORE,
    backup_stamp,
    backup_why,
    copied_from,
    copy_aside,
    is_copy,
)
from common.i18n import t
from common.paths import CONFIG_DIR

logger = logging.getLogger("vpinfe.common.games.config_backups")

BACKUPS_DIR = CONFIG_DIR / "backups" / "app_config"

# What a person may call one. Anything else would end up in a filename.
_LABEL = re.compile(r"[^A-Za-z0-9._-]+")
# `<stem>--<when>--<reason>[--<label>].<ext>`, the name of a copy somebody asked for. Two
# dashes, because a stem may hold one.
_PARTS = re.compile(r"^(?P<stem>.+?)--(?P<when>\d{8}T\d{6}Z)"
                    r"--(?P<reason>[a-z]+(?:-[a-z]+)*)"
                    r"(?:--(?P<label>.*))?$")

BEFORE_RESTORE = "before-restore"
MANUAL = "manual"
# A copy VPinFE took before a restore is named for the file, not parsed into parts: it is
# `<file>.vpinfe-<UTC>-restore` here, as it is beside a game's .info.


@dataclass(frozen=True)
class Backup:
    name: str
    path: str
    taken_at: str
    reason: str
    label: str = ""
    size: int = 0


def _safe(label: str) -> str:
    return _LABEL.sub("-", str(label or "").strip()).strip("-.")[:64]


def _home(launcher_id: str, named: str = "") -> Path:
    """One folder per launcher. Two launchers on one machine each have their own ini,
    and copies of both in one folder would be told apart by a filename alone.

    Named for the launcher and then its id, because somebody who goes looking in Finder
    should not have to work out which of two ten-character ids is theirs - and the id is
    what keeps two launchers with one name apart.
    """
    stem = _safe(launcher_id) or "unknown"
    return BACKUPS_DIR / (f"{_safe(named)}--{stem}" if _safe(named) else stem)


def home_for(launcher_id: str, named: str = "") -> str:
    """Where this launcher's copies are kept, for a surface that has to say so."""
    return str(_home(launcher_id, named))


def take(launcher_id: str, files: dict[str, str], *, label: str = "",
         named: str = "") -> list[Backup]:
    """A copy of every file the app named, or nothing where none of them is there yet."""
    home = _home(launcher_id, named)
    when = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    taken: list[Backup] = []
    for path in dict.fromkeys(files.values()):
        source = Path(path).expanduser()
        if not source.is_file():
            continue
        parts = [source.stem, when, MANUAL]
        if _safe(label):
            parts.append(_safe(label))
        target = home / f"{'--'.join(parts)}{source.suffix}"
        home.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        taken.append(_described(target))
    return taken


def held(launcher_id: str, named: str = "") -> list[Backup]:
    """Every copy this launcher has, newest first."""
    home = _home(launcher_id, named)
    if not home.is_dir():
        return []
    found = [_described(path) for path in home.iterdir() if path.is_file()]
    return sorted(found, key=lambda one: one.taken_at, reverse=True)


def restore(launcher_id: str, name: str, files: dict[str, str],
            named: str = "") -> Backup | None:
    """Put a copy back, over a copy of what is there now.

    Returns the safety copy it took first, so a caller can say what it did rather than
    only that it did it.
    """
    home = _home(launcher_id, named)
    source = home / Path(str(name or "")).name
    if not source.is_file() or source.parent != home:
        raise FileNotFoundError(t("error.launchers.copy_gone"))

    target = _target_for(source, files)
    if target is None:
        raise ValueError(t("error.launchers.copy_unmatched"))

    safety = None
    if target.is_file():
        home.mkdir(parents=True, exist_ok=True)
        safety = _described(Path(copy_aside(target, RESTORE, into=home, restoring=source)))
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    logger.info("Restored %s over %s", source.name, target)
    return safety


def _target_for(source: Path, files: dict[str, str]) -> Path | None:
    """Which of the app's files this copy came from, by the name it was taken under."""
    if is_copy(source):
        name = copied_from(source).name
        return next((Path(path).expanduser() for path in files.values()
                     if Path(path).expanduser().name == name), None)
    found = _PARTS.match(source.stem)
    stem = found.group("stem") if found else source.stem
    for path in files.values():
        candidate = Path(path).expanduser()
        if candidate.stem == stem and candidate.suffix == source.suffix:
            return candidate
    return None


def _described(path: Path) -> Backup:
    if is_copy(path):
        stamp = backup_stamp(path)
        return Backup(
            name=path.name, path=str(path),
            taken_at=f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}T{stamp[9:11]}:"
                     f"{stamp[11:13]}:{stamp[13:15]}Z",
            reason=BEFORE_RESTORE if backup_why(path) == RESTORE else backup_why(path),
            size=path.stat().st_size if path.is_file() else 0)
    found = _PARTS.match(path.stem)
    when = found.group("when") if found else ""
    return Backup(
        name=path.name,
        path=str(path),
        taken_at=(f"{when[:4]}-{when[4:6]}-{when[6:8]}T{when[9:11]}:"
                  f"{when[11:13]}:{when[13:15]}Z" if when else ""),
        reason=(found.group("reason") if found else ""),
        label=(found.group("label") or "" if found else ""),
        size=path.stat().st_size if path.is_file() else 0,
    )
