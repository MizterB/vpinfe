"""One kept copy, and the id a client holds for it."""

from __future__ import annotations

import base64
import binascii
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

# What a copy is of.
OF_GAME = "game"
OF_LAUNCHER = "launcher"
OF_THEME = "theme"
OF_VPINFE = "vpinfe"
OF_ARCHIVE = "archive"

# What the records in the config folder are of.
VPINFE_NAME = "VPinFE"

# What kind of file it is.
KIND_GAME = "game_metadata"
KIND_SETTINGS = "settings"
KIND_COLLECTIONS = "collections"
KIND_DEVICES = "devices"
KIND_PLAYERS = "players"
KIND_RECORDS = "records"
KIND_LAUNCHER = "launcher_settings"
KIND_THEME = "theme"
KIND_ARCHIVE = "backup"

# Why it was taken.
WHY_UPGRADE = "upgrade"
WHY_RESTORE = "restore"
WHY_IMPORT = "import"
WHY_RESET = "reset"
WHY_FIRST_CHANGE = "first_change"
WHY_UPDATE = "update"
WHY_YOURS = "yours"

# Who wrote the file the copy holds. Empty where the file is not VPinFE's own.
BY_2X = "2.x"
BY_3X = "3.0"

# Where it is kept. Part of the id, so a path is only ever read in the place it came from.
PLACE_GAME = "game"
PLACE_RECORDS = "records"
PLACE_LAUNCHER = "launcher"
PLACE_BESIDE = "beside"
PLACE_VPX_2X = "vpx_2x"
PLACE_THEME = "theme"
PLACE_ARCHIVE = "archive"
PLACE_MEMBER = "member"


@dataclass(frozen=True)
class Copy:
    id: str
    of_kind: str
    of_id: str
    of_name: str
    kind: str
    file: str
    path: str
    taken: str
    written_by: str
    why: str
    note: str
    size: int
    gone: bool
    # The id of the backup this is a part of. Empty for a copy that is a file of its own.
    within: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def make_id(place: str, path: str | Path) -> str:
    """Opaque to a client: it holds the id the listing gave and hands it back."""
    raw = json.dumps([place, str(path)], separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _parts(copy_id: str) -> list[str] | None:
    try:
        padded = str(copy_id) + "=" * (-len(str(copy_id)) % 4)
        raw = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except (ValueError, binascii.Error, UnicodeError):
        return None
    if not isinstance(raw, list) or not all(isinstance(part, str) and part for part in raw):
        return None
    return raw


def _is_clean(path: str) -> bool:
    return "\0" not in path and os.path.isabs(path) and os.path.normpath(path) == path


def read_id(copy_id: str) -> tuple[str, Path] | None:
    """The place and the path an id holds, or None for anything that is not one."""
    parts = _parts(copy_id)
    if parts is None or len(parts) != 2 or not _is_clean(parts[1]):
        return None
    return parts[0], Path(parts[1])


def make_member_id(archive: str | Path, member: str) -> str:
    raw = json.dumps([PLACE_MEMBER, str(archive), member], separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def read_member_id(copy_id: str) -> tuple[Path, str] | None:
    """The backup and the part of it an id holds, or None for anything that is not one."""
    parts = _parts(copy_id)
    if parts is None or len(parts) != 3 or parts[0] != PLACE_MEMBER or not _is_clean(parts[1]):
        return None
    return Path(parts[1]), parts[2]


def iso_from_stamp(stamp: str) -> str:
    """`20261004T020630Z` as `2026-10-04T02:06:30Z`."""
    return (f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}T{stamp[9:11]}:"
            f"{stamp[11:13]}:{stamp[13:15]}Z")
