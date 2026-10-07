"""The folder VPinFE keeps its own backups in, and every folder it has kept them in.

Changing the setting moves nothing: a backup stays in the folder it was taken in, so the
listing reads each folder a backup was ever written to. A folder is remembered when a
backup is written to it, never when the setting is changed - the setting can name a folder
nothing has been written to.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from urllib.parse import quote, unquote

from common import path_state
from common.config_access import cfg_get, cfg_list, cfg_set
from common.i18n import t
from common.paths import CONFIG_DIR, get_ini_config

logger = logging.getLogger("vpinfe.common.backups.folder")

SECTION = "backups"
FOLDER = "folder"
EARLIER = "earlier"

# Where backups go until a folder is chosen.
DEFAULT_DIR = CONFIG_DIR / "backups"

# A list setting is held joined with commas, and a folder's name may have one.
_SAFE = "/ :\\"


def chosen() -> str:
    """The folder the setting names, as typed. Blank when none is chosen."""
    return cfg_get(get_ini_config(), SECTION, FOLDER).strip()


def current() -> Path:
    """Where a backup taken now is written."""
    named = chosen()
    return _spelled(named) if named else DEFAULT_DIR


def _spelled(named: str) -> Path:
    """Absolute and normalized, the one form a backup's id accepts. Symlinks are not
    resolved: that touches every component, and on a share that has dropped it never returns."""
    return Path(os.path.abspath(os.path.expanduser(named)))


def _earlier() -> list[Path]:
    return [_spelled(unquote(one)) for one in cfg_list(get_ini_config(), SECTION, EARLIER)]


def known() -> list[Path]:
    """Every folder a backup may be in: the current one, the default, and each earlier one.
    Nothing on disk is touched, so a folder on a share that is not answering costs nothing."""
    seen: dict[str, Path] = {}
    for folder in (current(), DEFAULT_DIR, *_earlier()):
        seen.setdefault(str(folder), folder)
    return list(seen.values())


def listable() -> list[Path]:
    """The known folders that answer now. A share that is not connected is left out, not
    waited on - a listing of a dead mount does not return."""
    folders = known()
    found = path_state.look_all([path_state.Ask(str(one), path_state.DIR) for one in folders])
    return [folder for folder, state in zip(folders, found, strict=True)
            if state.state in (path_state.OK, path_state.READ_ONLY)]


def holds(folder: Path) -> bool:
    """Whether a folder is one of the known ones, so a path believed from outside is only
    taken to be a backup when it sits in a place backups are kept."""
    return folder in known()


def status() -> dict[str, str]:
    """The folder a backup would go to now, and what is wrong with it, if anything. The
    default counts as fine before it exists: the first backup makes it."""
    folder = current()
    if folder == DEFAULT_DIR and not folder.exists():
        return {"path": str(folder), "problem": ""}
    found = path_state.look(str(folder), path_state.DIR, writable=True)
    return {"path": str(folder),
            "problem": path_state.refusal(t("backups.folder_name"), found)}


def for_writing() -> Path:
    """The folder a backup is about to be written to, made if it is the default, and
    remembered. Raises `BlockedError` for a chosen folder that cannot be written to."""
    folder = current()
    if folder == DEFAULT_DIR:
        folder.mkdir(parents=True, exist_ok=True)
    path_state.require(str(folder), writable=True, name=t("backups.folder_name"))
    _remember(folder)
    return folder


def _remember(folder: Path) -> None:
    if folder == DEFAULT_DIR:
        return
    if folder in _earlier():
        return
    store = get_ini_config()
    names = [quote(str(one), safe=_SAFE) for one in (*_earlier(), folder)]
    cfg_set(store, SECTION, EARLIER, ",".join(names))
    store.save()
    logger.info("Backups are now also kept in %s", folder)
