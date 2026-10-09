"""What a source keeps for its cabinet rather than for any table, found so the report can
name it: window positions, the backglass server, DirectOutput, and the freezy DMD's per-ROM
places.

Nothing here is carried over. The numbers are pixels on the old cabinet's screens.
"""

from __future__ import annotations

import configparser
from dataclasses import dataclass, field
from pathlib import Path

from . import finding

# Found by name in the source's folders; the ones with a place to set them here have
# `displays`. `DmdDevice.ini` sits in the emulator's folder, the rest beside the tables.
FILES = (("ScreenRes.txt", True), ("DmdDevice.ini", True), ("B2SServer", True),
         ("DirectOutput", False))
EMULATOR_FOLDER = "VPinMAME"
DMD_FILE = "DmdDevice.ini"

# The freezy DMD's keys that a ROM's own section may override, behind this prefix.
_PREFIX = "virtualdmd "


@dataclass
class Cabinet:
    """`left_behind` is what was found, as `{what, displays, folder}`, and `dmd` the ROMs
    whose section gives the virtual DMD a place of its own, by name in lower case, with
    where."""

    left_behind: list[dict] = field(default_factory=list)
    dmd: dict[str, tuple[str, str]] = field(default_factory=dict)


def read(places: dict[str, str]) -> Cabinet:
    """The cabinet's files around the folders the run read from, by the kind of each:
    `tables`, `roms`, `user` and the source's own `root`. A folder not given adds nothing,
    and one that cannot be listed is as if it were empty."""
    roots: dict[str, None] = {}
    for key in ("tables", "roms", "user", "root"):
        start = str(places.get(key) or "").strip()
        if start:
            for here in (Path(start), Path(start).parent, Path(start).parent.parent):
                roots[str(here)] = None
    cabinet = Cabinet()
    ini: Path | None = None
    for name, displays in FILES:
        found = _first(roots, name)
        if found is not None:
            cabinet.left_behind.append({"what": name, "displays": displays,
                                        "folder": found.is_dir()})
            if name == DMD_FILE:
                ini = found
    if ini is not None:
        cabinet.dmd = _placed(ini)
    return cabinet


def _first(roots: dict[str, None], name: str) -> Path | None:
    for root in roots:
        for beside in (Path(root), finding.child(root, EMULATOR_FOLDER)):
            found = finding.child(beside, name) if beside is not None else None
            if found is not None:
                return found
    return None


def _placed(path: Path) -> dict[str, tuple[str, str]]:
    """The ROMs whose section moves the virtual DMD, by name in lower case, with its left
    and top. A section that turns it off, or that sets nothing of where it is, is not a
    place."""
    parser = configparser.ConfigParser(strict=False, interpolation=None, allow_no_value=True)
    parser.optionxform = str.lower  # type: ignore[assignment,method-assign]
    try:
        parser.read_string(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, configparser.Error):
        return {}
    found: dict[str, tuple[str, str]] = {}
    for section in parser.sections():
        own = {key[len(_PREFIX):].strip(): str(value or "").strip()
               for key, value in parser.items(section) if key.startswith(_PREFIX)}
        if own.get("enabled", "").casefold() in ("false", "0", "no", "off"):
            continue
        if own.get("left") and own.get("top"):
            found[section.casefold()] = (own["left"], own["top"])
    return found
