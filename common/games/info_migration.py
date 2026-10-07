"""Bring an unversioned 2.x `.info` up to schema 2.

Generations of the file, counting from the first one that shipped:

  1  what 2.x wrote. Implied - 2.x recorded no version, so a file either carries a
     stamp or is this one.
  2  the current shape.

`schema_of` still answers None rather than 1 for an unstamped file, because callers
need to tell "declares nothing" from "declares 1"; the migration treats them alike.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from common.atomic_write import naming_folder, staged_for, write_atomic
from common.games import high_scores
from common.games.tables import TABLES_KEY, parse_authors
from common.timestamps import iso_from_asctime, iso_from_authored_date

logger = logging.getLogger("vpinfe.common.games.info_migration")

SCHEMA_KEY = "schema"
INFO_SCHEMA = 2

# Declared here rather than in `info_file` because that module imports this one.
GUIDES_KEY = "guides"
# Who put a guide on the game. Only the catalog's records say so; any other is a person's.
GUIDE_ORIGIN = "origin"
FROM_CATALOG = "vps"
BACKUP_MARKER = ".vpinfe-"
# The importer's one copy of a merged `.info`, `<name>.info.bak`. Nothing writes it now.
IMPORTER_BAK = ".bak"
# What a copy VPinFE took was for, the word after the stamp. A copy of a 2.x file has none,
# so it keeps the bare `<file>.vpinfe-<UTC>` that 2.x looks for.
REASON_2X = ""
RESTORE = "restore"
IMPORT = "import"
RESET = "reset"
TURN = "turn"
_COPY_TAIL = re.compile(
    re.escape(BACKUP_MARKER) + r"(?P<stamp>\d{8}T\d{6}Z)(?:-(?P<reason>[a-z]+))?$")

# How the match in `Info` was made, kept in the `vpinfe` section. Absent is VPinFE's
# guess from the folder name.
VPS_MATCHED_BY_KEY = "vps_matched_by"
MATCHED_ON_IMPORT = "import"
MATCHED_BY_USER = "user"

# What 2.x called each VPXFile field, against what it is called now. Matched
# case-insensitively: real files carry both `detectnfozzy` and `detectNfozzy`, and a
# case-sensitive lookup silently drops the flag.
_TABLE_KEYS = {
    "filehash": "file_hash",
    "vbshash": "vbs_hash",
    "version": "version",
    "releasedate": "release_date",
    "savedate": "save_date",
    "saverev": "save_rev",
    "manufacturer": "manufacturer",
    "year": "year",
    "type": "type",
    "rom": "rom",
    "detectnfozzy": "detect_nfozzy",
    "detectfleep": "detect_fleep",
    "detectssf": "detect_ssf",
    "detectlut": "detect_lut",
    "detectscorebit": "detect_scorbit",     # the old name was a typo for Scorbit
    "detectfastflips": "detect_fastflips",
    "detectflex": "detect_flex",
    "detectpinmame": "detect_pinmame",
}

_VPINFE_KEYS = {
    "deletednvramonclose": "delete_nvram_on_close",
    "altlauncher": "alt_launcher",
    "pluginprofile": "plugin_profile",
    "alttitle": "alt_title",
    "altvpsid": "alt_vpsid",
}

_DROPPED_SECTIONS = ("VPXFile", "Medias")
_DROPPED_INFO_KEYS = ("Rom",)

# `alt_launcher` and `plugin_profile` are retired, and this is deliberately not where
# they go. They name a launcher for a *table*, and a table has no id until
# `ensure_unique_table_ids` mints one over the migrated library - so dropping them here
# would destroy the values before anything could record which table they belonged to.
# `launcher_migration` consumes them instead, after the ids exist, and writes the file
# without them.



def schema_of(data: object) -> int | None:
    """The schema a loaded .info declares, or None if it predates versioning.

    Only the section we write today counts - the old PascalCase `schema` numbered that
    section's shape, not the file's (5db3f3d).
    """
    if not isinstance(data, dict):
        return None
    section = data.get("vpinfe")
    if not isinstance(section, dict):
        return None
    try:
        return int(section.get(SCHEMA_KEY) or 0) or None
    except (TypeError, ValueError):
        return None


def is_versioned(data: object) -> bool:
    """Whether this file has been through the migration."""
    return schema_of(data) is not None


def needs_migration(data: object) -> bool:
    """An unversioned file carrying anything 2.x wrote, or a migrated one 2.x wrote again.

    We never write VPXFile or Medias, so either in a stamped file is proof 2.x has been
    back since - checked ahead of the stamp, which is the thing not to trust here.
    """
    if not isinstance(data, dict):
        return False
    if any(name in data for name in _DROPPED_SECTIONS):
        return True
    if is_versioned(data):
        return False
    user = data.get("User")
    if isinstance(user, dict) and "FrontendDOFEvent" in user:
        return True
    legacy = data.get("VPinFE")
    return isinstance(legacy, dict) and any(k.lower() in _VPINFE_KEYS for k in legacy)


def _rename(source: dict, mapping: dict) -> dict:
    renamed = {}
    for key, value in source.items():
        new_key = mapping.get(key.lower())
        if new_key:
            renamed[new_key] = value
    return renamed


def _table_entry(vpx_file: dict, authors: object) -> dict:
    entry = _rename(vpx_file, _TABLE_KEYS)
    entry["release_date"] = iso_from_authored_date(entry.get("release_date", ""))
    entry["save_date"] = iso_from_asctime(entry.get("save_date", ""))
    entry["authors"] = parse_authors(authors)
    return entry


def migrate(data: dict) -> dict:
    """The 2.x file as schema 2. Pure: takes a loaded .info, returns a new one."""
    info = dict(data.get("Info") or {})
    user = dict(data.get("User") or {})
    legacy = data.get("VPinFE")
    legacy = dict(legacy) if isinstance(legacy, dict) else {}
    vpx_file = data.get("VPXFile")
    vpx_file = dict(vpx_file) if isinstance(vpx_file, dict) else {}

    # Authors were game-level, which only worked while a folder held one table.
    # With exactly one, they are that file's - a real recorded fact, so it carries.
    authors = info.pop("Authors", None)
    for key in _DROPPED_INFO_KEYS:
        info.pop(key, None)

    vpinfe = _rename(legacy, _VPINFE_KEYS)
    # Anything else in there came from somewhere we don't know about; it stays as it is.
    vpinfe.update({k: v for k, v in legacy.items() if k.lower() not in _VPINFE_KEYS})
    # A file already holding the new section keeps it, and it wins: running this over
    # its own output has to be a no-op, or the second call eats the first.
    already = data.get("vpinfe")
    if isinstance(already, dict):
        vpinfe.update(already)
    vpinfe[SCHEMA_KEY] = INFO_SCHEMA
    if not is_versioned(data) and str(info.get("VPSId", "") or "").strip():
        vpinfe.setdefault(VPS_MATCHED_BY_KEY, MATCHED_BY_USER)

    # The DOF override is configuration, and User is the interop contract for play
    # history. It moves, and the old key goes with it.
    dof_event = user.pop("FrontendDOFEvent", None)
    if dof_event is not None:
        vpinfe["frontend_dof_event"] = dof_event

    high_scores.from_2x(user)

    # 2.x kept one tutorial link in Info. It becomes a guide, and a file already holding
    # guides keeps them - running this over its own output has to be a no-op.
    primer = str(info.pop("PinballPrimerTut", "") or "").strip()
    guides = data.get(GUIDES_KEY)
    guides = list(guides) if isinstance(guides, list) else []
    if primer and not any(isinstance(one, dict) and one.get("url") == primer
                          for one in guides):
        guides.append({"kind": "tutorial", GUIDE_ORIGIN: FROM_CATALOG, "title": "", "authors": [],
                       "url": primer, "youtube_id": ""})

    tables = dict(data.get(TABLES_KEY) or {})
    filename = str(vpx_file.get("filename", "") or "").strip()
    if filename:
        # Refresh what VPXFile covers and leave the rest - hidden, source, play stats.
        # Nothing to keep on a first migration; everything to lose when 2.x wrote the
        # file again and this runs over an entry we already built.
        prior = tables.get(filename)
        prior = prior if isinstance(prior, dict) else {}
        tables[filename] = {**prior, **_table_entry(vpx_file, authors)}
        # No default is recorded. 2.x described one table, so the resolver picks that
        # one anyway - and writing it down would freeze an arbitrary pick as a choice,
        # which is exactly what `recorded_default` says a rebuild must never do. It
        # also made every migrated game report a user-chosen default it never had.

    migrated: dict[str, Any] = {"Info": info, "User": user, "vpinfe": vpinfe,
                                TABLES_KEY: tables}
    if guides:
        migrated[GUIDES_KEY] = guides
    known = {*_DROPPED_SECTIONS, "Info", "User", "VPinFE", "vpinfe", TABLES_KEY,
             GUIDES_KEY}
    migrated.update({k: v for k, v in data.items() if k not in known})
    return migrated


def backup_path(info_path: str | Path, when: datetime | None = None,
                reason: str = REASON_2X) -> str:
    """Where a copy VPinFE takes of this file goes.

    Timestamped rather than .bak, so a restore point is not overwritten by the next one.
    UTC and no colons, because Windows will not have them in a filename. Every name that
    marks a kept copy is built here.
    """
    stamp = (when or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    return f"{info_path}{BACKUP_MARKER}{stamp}" + (f"-{reason}" if reason else "")


def backup_names(names: Iterable[str], info_name: str) -> list[str]:
    """The copies in a folder listing, newest first.

    Takes names so it can ride a scan already in progress; the stamp sorts lexically.
    """
    prefix = info_name + BACKUP_MARKER
    return sorted((n for n in names if n.startswith(prefix)), reverse=True)


def is_copy(name: str | Path) -> bool:
    """Whether a name is one of VPinFE's kept copies, in either spelling."""
    return _COPY_TAIL.search(Path(name).name) is not None


def backup_stamp(backup: str | Path) -> str:
    """When the copy was taken, as written in its name."""
    name = Path(backup).name
    found = _COPY_TAIL.search(name)
    return found.group("stamp") if found else name.rsplit(BACKUP_MARKER, 1)[-1]


def backup_reason(backup: str | Path) -> str:
    """What the copy was taken for, as written in its name. Empty for a copy of a 2.x file."""
    found = _COPY_TAIL.search(Path(backup).name)
    return (found.group("reason") or "") if found else ""


def is_importer_bak(name: str | Path, info_name: str) -> bool:
    """Whether a name is the importer's old single copy of this `.info`."""
    return Path(name).name == info_name + IMPORTER_BAK


def copied_from(backup: str | Path) -> Path:
    """The file this copy was taken of."""
    path = Path(backup)
    if path.name.endswith(IMPORTER_BAK) and BACKUP_MARKER not in path.name:
        return path.with_name(path.name[:-len(IMPORTER_BAK)])
    return path.with_name(path.name.rsplit(BACKUP_MARKER, 1)[0])


def restorable_backup(game_dir: str | Path, max_schema: int = INFO_SCHEMA,
                      names: Iterable[str] | None = None) -> str | None:
    """The backup this build would restore here, or None.

    Newest readable wins; a newer one is stepped over rather than ending the search.
    Pass `names` when the folder is already listed - only folders with a backup pay.
    """
    folder = Path(game_dir)
    if names is None:
        try:
            names = os.listdir(folder)
        except OSError:
            return None
    info_name = f"{folder.name}.info"
    for name in backup_names(names, info_name):
        candidate = folder / name
        try:
            schema = backup_schema(candidate)
        except (OSError, ValueError):
            logger.warning("Unreadable backup, skipping: %s", candidate)
            continue
        if schema is None or schema <= max_schema:
            return str(candidate)
    return None


def backup_schema(path: str | Path) -> int | None:
    """The schema a backup holds, or None when it predates versioning.

    Raises if the file cannot be read at all - the caller decides whether to skip it.
    """
    with open(path, encoding="utf-8") as handle:
        return schema_of(json.load(handle))


def replace_atomic(source: str | Path, path: str | Path) -> None:
    """Put `source` at `path` with no window where `path` is half written.

    A plain copy truncates first, and restore does that once per game across the library.
    """
    with staged_for(path) as staged:
        shutil.copy2(source, staged)


def write_json_atomic(path: str | Path, data: object) -> None:
    """Write a .info atomically."""
    write_atomic(path, lambda handle: json.dump(data, handle, indent=4))


def _free_backup_path(info_path: str | Path, when: datetime | None = None,
                      reason: str = REASON_2X, into: str | Path | None = None) -> str:
    def named(at: datetime | None) -> str:
        path = backup_path(info_path, at, reason)
        return path if into is None else os.path.join(into, os.path.basename(path))

    path = named(when)
    while os.path.exists(path):        # never overwrite a restore point
        # A whole second, not the second field: replace(second=(s + 1) % 60) wraps 59 to
        # 0, and the name that is supposed to be newer then sorts 59 seconds older. These
        # names are the only ordering restore has.
        when = (when or datetime.now(UTC)) + timedelta(seconds=1)
        path = named(when)
    return path


def write_backup(info_path: str | Path, original_text: str,
                 when: datetime | None = None) -> str:
    """Copy the file aside before it is rewritten, and prove the copy is readable.

    A truncated backup is worse than none: it is the one file whose failure is only
    discovered at the moment somebody needs it. The copy of a 2.x file, so no reason in
    its name.
    """
    json.loads(original_text)
    path = _free_backup_path(info_path, when)
    with naming_folder(info_path):
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(original_text)
        with open(path, encoding="utf-8") as handle:
            json.load(handle)
    keep_newest(info_path)
    return path


def copy_aside(info_path: str | Path, reason: str, when: datetime | None = None,
               into: str | Path | None = None, restoring: str | Path | None = None) -> str:
    """Keep the current file before something replaces it, whatever state it is in.

    `reason` is what the copy is for: `REASON_2X` for a file a 2.x build reads, and otherwise the
    word that goes after the stamp. `into` is a folder other than the file's own.
    `restoring` is the copy about to be put back over the file, which the cap must not
    remove out from under the restore.

    No JSON check: a file too broken to parse is one somebody is restoring *because* it
    is broken.
    """
    path = _free_backup_path(info_path, when, reason, into)
    with naming_folder(info_path):
        shutil.copy2(info_path, path)
    keep_newest(info_path, into, spare=restoring)
    return path


def keep_newest(info_path: str | Path, folder: str | Path | None = None,
                spare: str | Path | None = None) -> list[str]:
    """The cap: remove the copies of this file that VPinFE took itself, keeping the newest
    copy of a 2.x file and the newest of any kind. Returns what it removed.

    Runs when a copy is written, never on a clock. A name that does not end in a stamp and
    at most one word is somebody else's and is left where it is.
    """
    path = Path(info_path)
    where = Path(folder) if folder is not None else path.parent
    try:
        names = os.listdir(where)
    except OSError:
        return []
    own = [n for n in backup_names(names, path.name) if _COPY_TAIL.search(n)]
    keep_2x = next((n for n in own if backup_reason(n) == REASON_2X), None)
    keep = set(own[:1]) | ({keep_2x} if keep_2x else set())
    if spare is not None:
        keep.add(Path(spare).name)
    removed = []
    for name in own:
        if name in keep:
            continue
        try:
            (where / name).unlink()
        except OSError:
            logger.warning("Could not remove an older copy: %s", where / name, exc_info=True)
            continue
        removed.append(name)
    return removed
