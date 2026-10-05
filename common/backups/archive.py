"""Back up now: the zip one press writes, and how it is read back.

A zip holds `manifest.json` and one member per file. What is in a member is a copy of the
file; where it goes back is worked out when it is restored, from the manifest's id and name,
never from a path in the zip.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import threading
import zipfile
import zlib
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from common import service_errors
from common.atomic_write import staged_for
from common.games import game_repository, info_maintenance, launcher_ops, launchers
from common.games.collection_store import COLLECTIONS_NAME, COLLECTIONS_NAME_INI
from common.games.info_migration import needs_migration
from common.i18n import t
from common.paths import CONFIG_DIR
from common.vpinfe_version import get_version

from .copies import (
    BY_2X,
    BY_3X,
    KIND_COLLECTIONS,
    KIND_DEVICES,
    KIND_GAME,
    KIND_LAUNCHER,
    KIND_PLAYERS,
    KIND_RECORDS,
    KIND_SETTINGS,
    VPINFE_NAME,
)

logger = logging.getLogger("vpinfe.common.backups.archive")

ARCHIVES_DIR = CONFIG_DIR / "backups"
NAME_PREFIX = "vpinfe-backup-"
NAME_SUFFIX = ".zip"
MANIFEST = "manifest.json"
FORMAT = 1
MAX_MEMBER_BYTES = 64 * 1024 * 1024
STAMP = "%Y%m%dT%H%M%SZ"

SCOPE_GAMES = "games"
SCOPE_ALL_GAMES = "all_games"
SCOPE_RECORDS = "records"
SCOPE_LAUNCHER = "launcher"
SCOPE_EVERYTHING = "everything"
SCOPES = (SCOPE_GAMES, SCOPE_ALL_GAMES, SCOPE_RECORDS, SCOPE_LAUNCHER, SCOPE_EVERYTHING)

# The records VPinFE keeps in its config folder, by name.
RECORD_KINDS = {
    "vpinfe.json": KIND_SETTINGS, "vpinfe.ini": KIND_SETTINGS,
    COLLECTIONS_NAME: KIND_COLLECTIONS, COLLECTIONS_NAME_INI: KIND_COLLECTIONS,
    "devices.json": KIND_DEVICES, "players.json": KIND_PLAYERS,
    "tags.json": KIND_RECORDS, "launchers.json": KIND_RECORDS,
    "locations.json": KIND_RECORDS, "library.json": KIND_RECORDS,
    "extensions.json": KIND_RECORDS, "ui-preferences.json": KIND_RECORDS,
}

# What reading a damaged or unsupported zip can raise besides OSError.
BROKEN = (zipfile.BadZipFile, zlib.error, EOFError, NotImplementedError, RuntimeError)
_TAKING = threading.Lock()

_KINDS = {KIND_GAME, KIND_LAUNCHER, *RECORD_KINDS.values()}
_NAME = re.compile(rf"^{re.escape(NAME_PREFIX)}\d{{8}}T\d{{6}}Z(?:-\d+)?{re.escape(NAME_SUFFIX)}$")


@dataclass(frozen=True)
class Member:
    """One file in a backup. `path` is where it was, relative to its location: the game's
    folder and file, a record's name, or an app's settings file's name."""

    name: str
    kind: str
    of_id: str
    of_name: str
    path: str
    size: int = 0
    written_by: str = ""


@dataclass(frozen=True)
class Manifest:
    note: str
    taken: str
    version: str
    scope: str
    members: tuple[Member, ...] = field(default_factory=tuple)


def is_archive_name(name: str) -> bool:
    return _NAME.match(name) is not None


def _stamp_of(name: str) -> str:
    return name[len(NAME_PREFIX):len(NAME_PREFIX) + 16]


def taken_from_name(name: str) -> str:
    stamp = _stamp_of(name)
    return f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}T{stamp[9:11]}:{stamp[11:13]}:{stamp[13:15]}Z"


def _member_from(item: Any, held: set[str]) -> Member | None:
    if not isinstance(item, dict):
        return None
    name, kind = item.get("name"), item.get("kind")
    if not isinstance(name, str) or name not in held or kind not in _KINDS:
        return None
    size = item.get("size")
    return Member(
        name=name, kind=kind, of_id=str(item.get("of_id") or ""),
        of_name=str(item.get("of_name") or ""), path=str(item.get("path") or ""),
        size=size if isinstance(size, int) and size >= 0 else 0,
        written_by=str(item.get("written_by") or ""))


def read(path: Path) -> Manifest | None:
    """The manifest of a backup, or None for a file that is not a readable one."""
    try:
        with zipfile.ZipFile(path) as bundle:
            info = bundle.getinfo(MANIFEST)
            if info.file_size > MAX_MEMBER_BYTES:
                return None
            raw = json.loads(bundle.read(info))
            held = {item.filename for item in bundle.infolist()}
    except (OSError, ValueError, KeyError, *BROKEN):
        return None
    if not isinstance(raw, dict) or raw.get("format") != FORMAT:
        return None
    listed = raw.get("members")
    found = (_member_from(item, held) for item in listed) if isinstance(listed, list) else ()
    return Manifest(note=str(raw.get("note") or ""), taken=str(raw.get("taken") or ""),
                    version=str(raw.get("version") or ""), scope=str(raw.get("scope") or ""),
                    members=tuple(one for one in found if one is not None))


def game_folder(member: Member) -> Path | None:
    """The folder a game member goes back to. A member with an id goes to the game that has
    it; only a member without one is matched by its folder's name."""
    if member.of_id:
        folder = game_repository.game_folder(member.of_id)
    else:
        game = game_repository.by_folder_name(member.of_name)
        folder = Path(str(game.full_path_game)) if game is not None else None
    return folder if folder is not None and folder.is_dir() else None


def extract(path: Path, member: Member, into: Path) -> Path:
    """The member written as `into/<its file's name>`, or nothing written at all. Refused
    past MAX_MEMBER_BYTES and for a member that cannot be read."""
    target = into / (Path(member.path).name or "member")
    try:
        with zipfile.ZipFile(path) as bundle:
            info = bundle.getinfo(member.name)
            if info.file_size > MAX_MEMBER_BYTES:
                raise service_errors.RefusedError(t("error.backups.too_big"))
            with staged_for(target) as staged, bundle.open(info) as source, \
                    open(staged, "wb") as sink:
                shutil.copyfileobj(source, sink)
    except (KeyError, *BROKEN) as exc:
        raise service_errors.RefusedError(t("error.backups.unreadable")) from exc
    return target


# --- Taking one ------------------------------------------------------------------------

@dataclass(frozen=True)
class _Gathered:
    member: Member
    data: bytes


def _info_writer(data: bytes) -> str:
    try:
        return BY_2X if needs_migration(json.loads(data)) else BY_3X
    except ValueError:
        return ""


def _game_member(index: int, folder: Path) -> _Gathered | None:
    info = folder / f"{folder.name}.info"
    try:
        data = info.read_bytes()
    except OSError:
        return None
    return _Gathered(Member(
        name=f"games/{index:04d}/{info.name}", kind=KIND_GAME,
        of_id=info_maintenance.game_id_in(info), of_name=folder.name,
        path=f"{folder.name}/{info.name}", size=len(data),
        written_by=_info_writer(data)), data)


def _record_members() -> list[_Gathered]:
    found = []
    for name, kind in RECORD_KINDS.items():
        try:
            data = (CONFIG_DIR / name).read_bytes()
        except OSError:
            continue
        found.append(_Gathered(Member(
            name=f"records/{name}", kind=kind, of_id="", of_name=VPINFE_NAME, path=name,
            size=len(data), written_by=BY_2X if name.endswith(".ini") else BY_3X), data))
    return found


def _launcher_members(launcher: launchers.Launcher) -> list[_Gathered]:
    found = []
    for named in dict.fromkeys(launcher_ops.config_files(launcher).values()):
        source = Path(named).expanduser()
        try:
            data = source.read_bytes()
        except OSError:
            continue
        found.append(_Gathered(Member(
            name=f"launchers/{launcher.launcher_id}/{source.name}", kind=KIND_LAUNCHER,
            of_id=launcher.launcher_id, of_name=launcher.display_name, path=source.name,
            size=len(data)), data))
    return found


def _launcher_named(launcher_id: str) -> launchers.Launcher:
    found = launchers.get_launcher_store().get(launcher_id)
    if found is None:
        raise service_errors.NotFoundError(t("error.backups.no_owner", name=launcher_id))
    return found


def _games(folders: Iterable[Path]) -> list[_Gathered]:
    gathered = (_game_member(index, folder) for index, folder in enumerate(folders, 1))
    return [one for one in gathered if one is not None]


def _gather(scope: str, game_ids: list[str], launcher_id: str) -> list[_Gathered]:
    if scope == SCOPE_GAMES:
        folders = []
        for game_id in dict.fromkeys(game_ids):
            folder = game_repository.game_folder(game_id)
            if folder is None:
                raise service_errors.NotFoundError(t("error.backups.no_game", id=game_id))
            folders.append(folder)
        return _games(folders)
    if scope == SCOPE_ALL_GAMES:
        return _games(info_maintenance.game_dirs())
    if scope == SCOPE_RECORDS:
        return _record_members()
    if scope == SCOPE_LAUNCHER:
        return _launcher_members(_launcher_named(launcher_id))
    if scope == SCOPE_EVERYTHING:
        found = _games(info_maintenance.game_dirs()) + _record_members()
        for each in launchers.get_launcher_store().launchers():
            found += _launcher_members(each)
        return found
    raise service_errors.RefusedError(t("error.backups.scope", scope=scope))


def _free_path(now: datetime) -> Path:
    while True:
        stamp = now.strftime(STAMP)
        path = ARCHIVES_DIR / f"{NAME_PREFIX}{stamp}{NAME_SUFFIX}"
        if not path.exists():
            return path
        now += timedelta(seconds=1)


def take(scope: str, *, game_ids: list[str] | None = None, launcher_id: str = "",
         note: str = "") -> Path:
    """Write one backup and return its path. Refused when there is nothing to put in it."""
    gathered = _gather(scope, game_ids or [], launcher_id)
    if not gathered:
        raise service_errors.RefusedError(t("error.backups.nothing"))
    now = datetime.now(UTC)
    manifest: dict[str, Any] = {
        "format": FORMAT, "note": note.strip(), "taken": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "version": get_version(), "scope": scope,
        "members": [asdict(one.member) for one in gathered]}
    ARCHIVES_DIR.mkdir(parents=True, exist_ok=True)
    with _TAKING:
        path = _free_path(now)
        with staged_for(path) as staged, zipfile.ZipFile(
                staged, "w", zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr(MANIFEST, json.dumps(manifest, indent=2))
            for one in gathered:
                bundle.writestr(one.member.name, one.data)
    return path


def listed() -> list[Path]:
    try:
        names = os.listdir(ARCHIVES_DIR)
    except OSError:
        return []
    return [ARCHIVES_DIR / name for name in sorted(names) if is_archive_name(name)]
