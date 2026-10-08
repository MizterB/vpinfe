"""Finding what a source keeps for a ROM or a table, by a name that may differ in case.

A source copied from Windows holds `Aladdins_Castle.zip` for a table that names
`aladdins_castle`, and a case-sensitive lookup misses it without a word. A listing is
read once per folder and kept for a minute, because a run asks the same folder for every
game and a share charges for each listing.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

KEPT = 60.0

_lock = threading.Lock()
_listed: dict[str, tuple[float, dict[str, list[Path]]]] = {}


def forget() -> None:
    """Drop every listing, so the next question reads the folder again."""
    with _lock:
        _listed.clear()


def _listing(folder: str | Path) -> dict[str, list[Path]]:
    """The folder's children by the part of their name before the first dot, folded."""
    key = str(folder)
    with _lock:
        held = _listed.get(key)
        if held and time.monotonic() - held[0] < KEPT:
            return held[1]
    found: dict[str, list[Path]] = {}
    try:
        for one in sorted(Path(key).iterdir(), key=lambda path: path.name):
            found.setdefault(one.name.split(".", 1)[0].casefold(), []).append(one)
    except OSError:
        found = {}
    with _lock:
        _listed[key] = (time.monotonic(), found)
    return found


def rom_file(folder: str | Path, rom: str) -> Path | None:
    """The file in `folder` that is the ROM set `rom`: its name, any case, any extension.

    The spelling the table gave wins where two files differ only in case.
    """
    wanted = str(rom or "").strip()
    if not wanted or not folder:
        return None
    candidates = [one for one in _listing(folder).get(wanted.split(".", 1)[0].casefold(), [])
                  if one.name.casefold().startswith(wanted.casefold() + ".")]
    candidates.sort(key=lambda one: not one.name.startswith(wanted + "."))
    return next((one for one in candidates if one.is_file()), None)


def child(folder: str | Path, name: str) -> Path | None:
    """The child of `folder` called `name` in any case, a folder or a file. The exact
    spelling wins where two differ only in case."""
    wanted = str(name or "").strip()
    if not wanted or not folder:
        return None
    candidates = [one for one in _listing(folder).get(wanted.split(".", 1)[0].casefold(), [])
                  if one.name.casefold() == wanted.casefold()]
    candidates.sort(key=lambda one: one.name != wanted)
    return candidates[0] if candidates else None


def files(folder: str | Path) -> list[Path]:
    """The files directly in `folder`, by name. Nothing where it cannot be listed."""
    if not folder:
        return []
    return [one for one in sorted((one for found in _listing(folder).values()
                                   for one in found), key=lambda path: path.name)
            if one.is_file()]
