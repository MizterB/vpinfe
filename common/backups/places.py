"""Where each kind of kept copy is, and how to read one off the disk.

Every walk here is a listing of a folder or two. The game folders are the long one, and are
read on a thread pool: on a share the listing is the expensive part, and there is one per
game.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from common.games import (
    config_backups,
    game_repository,
    info_maintenance,
    launcher_ops,
    launchers,
    locations,
)
from common.games.collection_store import COLLECTIONS_NAME, COLLECTIONS_NAME_INI
from common.games.game_identity import game_id as game_id_of
from common.games.info_migration import (
    IMPORT,
    OF_2X,
    RESET,
    RESTORE,
    backup_names,
    backup_stamp,
    backup_why,
    copied_from,
    is_copy,
    is_importer_bak,
    needs_migration,
)
from common.i18n import t
from common.online.theme_installer import ASIDE_SUFFIX
from common.paths import CONFIG_DIR, get_themes_dir

from . import archive
from .copies import (
    BY_2X,
    BY_3X,
    KIND_ARCHIVE,
    KIND_COLLECTIONS,
    KIND_DEVICES,
    KIND_GAME,
    KIND_LAUNCHER,
    KIND_PLAYERS,
    KIND_RECORDS,
    KIND_SETTINGS,
    KIND_THEME,
    OF_ARCHIVE,
    OF_GAME,
    OF_LAUNCHER,
    OF_THEME,
    OF_VPINFE,
    PLACE_ARCHIVE,
    PLACE_BESIDE,
    PLACE_GAME,
    PLACE_LAUNCHER,
    PLACE_RECORDS,
    PLACE_THEME,
    PLACE_VPX_2X,
    VPINFE_NAME,
    WHY_FIRST_CHANGE,
    WHY_IMPORT,
    WHY_RESET,
    WHY_RESTORE,
    WHY_UPDATE,
    WHY_UPGRADE,
    WHY_YOURS,
    Copy,
    iso_from_stamp,
    make_id,
    make_member_id,
    read_id,
    read_member_id,
)

logger = logging.getLogger("vpinfe.common.backups.places")

# 2.x's Manager UI kept VPX's settings copies here, named by local time.
INI_2X_DIR = CONFIG_DIR / "backups" / "vpx_ini"
INI_2X_NAME = re.compile(r"^(?P<stem>.+?)-(?P<reason>manual|pre-restore)"
                          r"(?:-(?P<label>.+?))?-(?P<when>\d{8}-\d{6})$")

_WALK_THREADS = 16

# What a copy in the config folder is of, by the file it was taken of.
_RECORD_KINDS = {
    "vpinfe.ini": KIND_SETTINGS, "vpinfe.json": KIND_SETTINGS,
    COLLECTIONS_NAME_INI: KIND_COLLECTIONS, COLLECTIONS_NAME: KIND_COLLECTIONS,
    "devices.json": KIND_DEVICES, "players.json": KIND_PLAYERS,
}

_WHY_BY_WORD = {RESTORE: WHY_RESTORE, IMPORT: WHY_IMPORT, RESET: WHY_RESET}


def _why_of_name(name: str) -> str:
    return _WHY_BY_WORD.get(backup_why(name), WHY_UPGRADE)


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _mtime_iso(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    except OSError:
        return ""


def _written_by_info(path: Path) -> str:
    """Who wrote a `.info` copy. A copy of a 2.x file keeps the bare name 2.x looks for, so
    that one is known by its name; every other is read."""
    if is_copy(path) and backup_why(path) == OF_2X:
        return BY_2X
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return BY_2X if needs_migration(data) else BY_3X


# --- Game folders ----------------------------------------------------------------------

def _is_game_folder(folder: Path) -> bool:
    """Whether a folder is one the library reads, so a copy is only ever taken to be a
    game's when it sits in one."""
    wanted = locations.canonical(str(folder))
    for location in locations.configured():
        held = locations.canonical(location.path)
        if location.kind == locations.KIND_GAME and held == wanted:
            return True
        if location.kind != locations.KIND_GAME and held == locations.canonical(
                str(folder.parent)):
            return folder.is_dir() and not folder.name.startswith(".")
    return False


def game_copies(folder: Path) -> list[Copy]:
    """Every copy kept beside this game's `.info`."""
    info_name = f"{folder.name}.info"
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    held = [name for name in backup_names(names, info_name) if is_copy(name)]
    held += [name for name in names if is_importer_bak(name, info_name)]
    if not held:
        return []
    game_id = info_maintenance.game_id_in(folder / info_name)
    gone = info_name not in names
    found = []
    for name in held:
        path = folder / name
        if is_importer_bak(name, info_name):
            taken, why, written_by = _mtime_iso(path), WHY_IMPORT, _written_by_info(path)
        else:
            taken, why = iso_from_stamp(backup_stamp(name)), _why_of_name(name)
            written_by = _written_by_info(path)
        found.append(Copy(
            id=make_id(PLACE_GAME, path), of_kind=OF_GAME, of_id=game_id,
            of_name=folder.name, kind=KIND_GAME, file=name, path=str(path), taken=taken,
            written_by=written_by, why=why, note="", size=_size(path), gone=gone))
    return found


def game_copy(path: Path) -> Copy | None:
    folder = path.parent
    if not _is_game_folder(folder):
        return None
    return next((one for one in game_copies(folder) if Path(one.path) == path), None)


def _all_game_copies() -> list[Copy]:
    folders = info_maintenance.game_dirs()
    if not folders:
        return []
    with ThreadPoolExecutor(max_workers=min(_WALK_THREADS, len(folders))) as pool:
        return [one for found in pool.map(game_copies, folders) for one in found]


# --- The config folder -----------------------------------------------------------------

def _record_copy(path: Path) -> Copy | None:
    if not is_copy(path) or not path.is_file():
        return None
    base = copied_from(path).name
    kind = _RECORD_KINDS.get(base, KIND_RECORDS)
    written_by = BY_2X if base.endswith(".ini") else BY_3X if base.endswith(".json") else ""
    return Copy(
        id=make_id(PLACE_RECORDS, path), of_kind=OF_VPINFE, of_id="", of_name=VPINFE_NAME,
        kind=kind, file=path.name, path=str(path),
        taken=iso_from_stamp(backup_stamp(path)), written_by=written_by,
        why=_why_of_name(path.name), note="", size=_size(path), gone=False)


def _record_copies() -> list[Copy]:
    try:
        names = os.listdir(CONFIG_DIR)
    except OSError:
        return []
    return [one for name in names if (one := _record_copy(CONFIG_DIR / name))]


def record_copy(path: Path) -> Copy | None:
    return _record_copy(path) if path.parent == CONFIG_DIR else None


# --- Launchers -------------------------------------------------------------------------

def _launcher_list() -> list[launchers.Launcher]:
    return launchers.get_launcher_store().launchers()


def _settings_files(launcher: launchers.Launcher) -> dict[str, str]:
    try:
        return launcher_ops.config_files(launcher)
    except Exception:  # noqa: BLE001 - an app that cannot say where its file is has no copies to list
        logger.warning("Could not read where %s keeps its settings", launcher.display_name,
                       exc_info=True)
        return {}


def _launcher_for_folder(folder: Path,
                        held: Iterable[launchers.Launcher]) -> launchers.Launcher | None:
    """The launcher a `backups/app_config/` folder is named for: `<name>--<id>`, or the id."""
    wanted = folder.name.rsplit("--", 1)[-1]
    return next((one for one in held if config_backups.safe(one.launcher_id) == wanted),
                None)


def _app_config_copy(path: Path, held: list[launchers.Launcher]) -> Copy | None:
    if not path.is_file() or not is_copy(path):
        return None
    owner = _launcher_for_folder(path.parent, held)
    name = owner.display_name if owner else path.parent.name.rsplit("--", 1)[0]
    return Copy(
        id=make_id(PLACE_LAUNCHER, path), of_kind=OF_LAUNCHER,
        of_id=owner.launcher_id if owner else path.parent.name.rsplit("--", 1)[-1],
        of_name=name, kind=KIND_LAUNCHER, file=path.name, path=str(path),
        taken=iso_from_stamp(backup_stamp(path)),
        written_by="", why=WHY_RESTORE, note="", size=_size(path), gone=owner is None)


def _beside_copies(launcher: launchers.Launcher) -> list[Copy]:
    """The copies kept beside a settings file: VPX's own first-change one, and what a
    restore replaced."""
    found, seen = [], set()
    for named in dict.fromkeys(_settings_files(launcher).values()):
        source = Path(named).expanduser()
        try:
            names = os.listdir(source.parent)
        except OSError:
            continue
        for name in backup_names(names, source.name):
            path = source.parent / name
            if path in seen or not is_copy(name):
                continue
            seen.add(path)
            found.append(Copy(
                id=make_id(PLACE_BESIDE, path), of_kind=OF_LAUNCHER,
                of_id=launcher.launcher_id, of_name=launcher.display_name,
                kind=KIND_LAUNCHER, file=name, path=str(path),
                taken=iso_from_stamp(backup_stamp(name)), written_by="",
                why=WHY_FIRST_CHANGE if backup_why(name) == OF_2X else _why_of_name(name),
                note="", size=_size(path), gone=False))
    return found


def _x2_copy(path: Path, held: list[launchers.Launcher]) -> Copy | None:
    found = INI_2X_NAME.match(path.stem)
    if not found or path.suffix.lower() != ".ini" or not path.is_file():
        return None
    try:
        local = datetime.strptime(found.group("when"), "%Y%m%d-%H%M%S")
    except ValueError:
        return None
    taken = local.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    owner = launchers.default_for("vpx", held)
    return Copy(
        id=make_id(PLACE_VPX_2X, path), of_kind=OF_LAUNCHER,
        of_id=owner.launcher_id if owner else "",
        of_name=owner.display_name if owner else "", kind=KIND_LAUNCHER, file=path.name,
        path=str(path), taken=taken, written_by="",
        why=WHY_RESTORE if found.group("reason") == "pre-restore" else WHY_YOURS,
        note=found.group("label") or "", size=_size(path), gone=owner is None)


def _launcher_copies() -> list[Copy]:
    held = _launcher_list()
    found: list[Copy] = []
    app_config = config_backups.BACKUPS_DIR
    if app_config.is_dir():
        for folder in sorted(app_config.iterdir()):
            if folder.is_dir():
                found += [one for path in sorted(folder.iterdir())
                          if (one := _app_config_copy(path, held))]
    for each in held:
        found += _beside_copies(each)
    if INI_2X_DIR.is_dir():
        found += [one for path in sorted(INI_2X_DIR.iterdir()) if (one := _x2_copy(path, held))]
    return found


def launcher_copy(place: str, path: Path) -> Copy | None:
    held = _launcher_list()
    if place == PLACE_LAUNCHER:
        return (_app_config_copy(path, held)
                if path.parent.parent == config_backups.BACKUPS_DIR else None)
    if place == PLACE_VPX_2X:
        return _x2_copy(path, held) if path.parent == INI_2X_DIR else None
    for each in held:
        for copy in _beside_copies(each):
            if Path(copy.path) == path:
                return copy
    return None


# --- Themes ----------------------------------------------------------------------------

def _folder_size(folder: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(folder):
        for name in files:
            total += _size(Path(root) / name)
    return total


def theme_copy(path: Path) -> Copy | None:
    if (path.parent != get_themes_dir() or not path.name.endswith(ASIDE_SUFFIX)
            or path.is_symlink() or not path.is_dir()):
        return None
    theme = path.name[:-len(ASIDE_SUFFIX)]
    if not theme or theme.startswith("."):
        return None
    return Copy(
        id=make_id(PLACE_THEME, path), of_kind=OF_THEME, of_id=theme, of_name=theme,
        kind=KIND_THEME, file=path.name, path=str(path), taken=_mtime_iso(path),
        written_by="", why=WHY_UPDATE, note="", size=_folder_size(path),
        gone=not (path.parent / theme).is_dir())


def _theme_copies() -> list[Copy]:
    try:
        names = sorted(os.listdir(get_themes_dir()))
    except OSError:
        return []
    return [one for name in names if (one := theme_copy(get_themes_dir() / name))]


# --- Back up now -----------------------------------------------------------------------

@dataclass(frozen=True)
class _Present:
    """What exists now, to say which parts of a backup have nothing to go back to."""

    game_ids: frozenset[str]
    game_names: frozenset[str]
    launcher_ids: frozenset[str]


def _present() -> _Present:
    games = game_repository.all_games()
    return _Present(
        frozenset(game_id_of(game) for game in games),
        frozenset(str(game.game_dir_name) for game in games),
        frozenset(one.launcher_id for one in _launcher_list()))


def _member_gone(member: archive.Member, present: _Present) -> bool:
    if member.kind == KIND_GAME:
        if member.of_id:
            return member.of_id not in present.game_ids
        return member.of_name not in present.game_names
    if member.kind == KIND_LAUNCHER:
        return member.of_id not in present.launcher_ids
    return False


def _of_label(manifest: archive.Manifest) -> str:
    members = manifest.members
    if manifest.scope == archive.SCOPE_EVERYTHING:
        return t("backups.of.everything")
    if members and all(one.kind == KIND_GAME for one in members):
        return t("backups.of.games", count=len(members))
    if manifest.scope == archive.SCOPE_LAUNCHER and members:
        return members[0].of_name
    return VPINFE_NAME if members else ""


_OF_BY_KIND = {KIND_GAME: OF_GAME, KIND_LAUNCHER: OF_LAUNCHER}


def _member_copy(path: Path, manifest: archive.Manifest, member: archive.Member,
                 present: _Present) -> Copy:
    return Copy(
        id=make_member_id(path, member.name),
        of_kind=_OF_BY_KIND.get(member.kind, OF_VPINFE), of_id=member.of_id,
        of_name=member.of_name, kind=member.kind, file=Path(member.path).name,
        path=str(path), taken=manifest.taken, written_by=member.written_by, why=WHY_YOURS,
        note=manifest.note, size=member.size, gone=_member_gone(member, present),
        within=make_id(PLACE_ARCHIVE, path))


def archive_copies(path: Path, present: _Present | None = None) -> list[Copy]:
    """The backup, then each file in it."""
    manifest = archive.read(path)
    held = present or _present()
    members = ([_member_copy(path, manifest, one, held) for one in manifest.members]
               if manifest else [])
    taken = (manifest.taken if manifest else "") or archive.taken_from_name(path.name)
    whole = Copy(
        id=make_id(PLACE_ARCHIVE, path), of_kind=OF_ARCHIVE, of_id="",
        of_name=_of_label(manifest) if manifest else "", kind=KIND_ARCHIVE, file=path.name,
        path=str(path), taken=taken, written_by=BY_3X, why=WHY_YOURS,
        note=manifest.note if manifest else "", size=_size(path),
        gone=bool(members) and all(one.gone for one in members))
    return [whole, *members]


def _all_archive_copies() -> list[Copy]:
    held = archive.listed()
    present = _present() if held else None
    return [one for path in held for one in archive_copies(path, present)]


def _is_ours(path: Path) -> bool:
    return (path.parent == archive.ARCHIVES_DIR and archive.is_archive_name(path.name)
            and not path.is_symlink() and path.is_file())


def archive_copy(path: Path) -> Copy | None:
    return archive_copies(path)[0] if _is_ours(path) else None


def member_copy(copy_id: str) -> Copy | None:
    held = read_member_id(copy_id)
    if held is None or not _is_ours(held[0]):
        return None
    return next((one for one in archive_copies(held[0]) if one.id == copy_id), None)


# --- All of it -------------------------------------------------------------------------

def _ordered(found: list[Copy]) -> list[Copy]:
    unique = {one.id: one for one in found}
    return sorted(unique.values(), key=lambda one: (one.taken, one.path), reverse=True)


def _of_one(of_kind: str, of_id: str) -> list[Copy]:
    """What one game, launcher or theme has: its own copies and its file in each backup, read
    without walking every other game's folder."""
    members = [one for one in _all_archive_copies() if one.within] \
        if of_kind in (OF_GAME, OF_LAUNCHER) else []
    if of_kind == OF_GAME:
        folder = game_repository.game_folder(of_id)
        own = game_copies(folder) if folder is not None else []
    elif of_kind == OF_LAUNCHER:
        own = _launcher_copies()
    elif of_kind == OF_THEME:
        own = _theme_copies()
    else:
        return []
    return [one for one in [*own, *members] if one.of_kind == of_kind and one.of_id == of_id]


def scan(of_kind: str = "", of_id: str = "") -> list[Copy]:
    """Every copy there is, newest first, or those of one game, launcher or theme."""
    if of_kind:
        return _ordered(_of_one(of_kind, of_id))
    return _ordered([*_all_game_copies(), *_record_copies(), *_launcher_copies(),
                     *_theme_copies(), *_all_archive_copies()])


def find(copy_id: str) -> Copy | None:
    """The copy an id names, or None. The path in an id is only believed in the place the
    id says, and only when that place holds a copy by that name."""
    if (member := member_copy(copy_id)) is not None:
        return member
    held = read_id(copy_id)
    if held is None:
        return None
    place, path = held
    if place == PLACE_ARCHIVE:
        return archive_copy(path)
    if place == PLACE_GAME:
        return game_copy(path)
    if place == PLACE_RECORDS:
        return record_copy(path)
    if place in (PLACE_LAUNCHER, PLACE_VPX_2X, PLACE_BESIDE):
        return launcher_copy(place, path)
    if place == PLACE_THEME:
        return theme_copy(path)
    return None
