"""A folder read as folders, when no frontend claims it.

Nothing here is a database: the layout is the source. A game folder in the root is a game
as it stands, a table file lying in it is a game that has no folder yet, and what sits
beside a Visual Pinball install says where its ROMs are.

What counts as a game folder or a table is core's rule and depends on what this install
plays, so it is asked through `survey` - the importer's `ctx.games.survey` - rather than
worked out here, the way `folder_name_for` is.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import pinballx
from .source import SourceGame, SourceLibrary, SourceSystem

# The word on screen is the catalog's `source.folders`, so there is no name here.
SOURCE_ID = "folders"

_NOTHING: dict[str, list[str]] = {"game_folders": [], "loose": []}


def _looked_at(root: Path | str, survey: Callable[..., dict] | None) -> dict[str, Any]:
    """Without a survey nothing is a game: this module cannot tell one from a folder."""
    if survey is None:
        return _NOTHING
    try:
        return survey(root)
    except OSError:
        return _NOTHING


def detect(root: Path | str, survey: Callable[..., dict] | None = None) -> bool:
    """Any game folder, or any table, in the root itself.

    Asked last of the readers: a frontend's install folder holds game folders too, and the
    reader that knows its database should be the one that claims it.
    """
    found = _looked_at(root, survey)
    return bool(found["game_folders"] or found["loose"])


def _install_beside(root: Path) -> str:
    """The folder holding VPinMAME, when it is the tables folder's parent or the folder
    itself. Empty when neither is: a ROM folder is not guessed at."""
    for candidate in (root.parent, root):
        try:
            if any(one.is_dir() and one.name.lower() == "vpinmame"
                   for one in candidate.iterdir()):
                return str(candidate)
        except OSError:
            continue
    return ""


def read(root: Path | str, plays: Callable[[str], bool] | None = None,
         known_apps: tuple[str, ...] = (), *, survey: Callable[..., dict] | None = None,
         chosen: dict | None = None) -> SourceLibrary:
    """The loose tables as games, and the game folders by name.

    One system, named for the folder: a root is the folder somebody pointed at. A table is
    keyed on its filename without the suffix, which is also what artwork is filed under.

    `chosen["media"]` is an artwork folder somebody pointed at, read the way PinballX lays
    one out - a folder per kind, a file named for the table.
    """
    root = Path(root)
    found = _looked_at(root, survey)
    games = [SourceGame(key=Path(name).stem, table_file=str(root / name))
             for name in found["loose"]]
    artwork = str((chosen or {}).get("media") or "").strip()
    if artwork and games:
        games = pinballx.read_media(artwork, games)
    return SourceLibrary(
        source_id=SOURCE_ID, root=str(root),
        systems=(SourceSystem(name=root.name or str(root), games=tuple(games),
                              tables_dir=str(root), working_path=_install_beside(root)),),
        in_place=tuple(found["game_folders"]))
