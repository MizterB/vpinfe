"""Reading a PinUP Popper library.

A SQLite database rather than a parse, which makes it the third shape: PinballX derives
media from a folder convention, EmulationStation stores a path per game, and this one
answers a query.

**Three name columns, and they are not interchangeable** - verified against a real
install rather than inferred, because the inference was wrong. `GameName` is the identity
and the name media is found by; `GameFileName` is the file, with whatever mod or version
suffix it carries; `GameDisplay` is the bare title. `GameName` is already
"Title (Manufacturer Year)", which is our own folder convention arrived at separately. A
reader using one of the three for all of them finds either no artwork or no table.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from common.extensions.contract import words

from . import drivemap
from .gamestats import Played, stars
from .source import Note, SourceGame, SourceLibrary, SourceMedia, SourceSystem, failed

logger = logging.getLogger(__name__)
t = words("library_importer")

SOURCE_ID = "popper"
SOURCE_NAME = "PinUP Popper"

DATABASE = "PUPDatabase.db"
MEDIA_DIR = "POPMedia"

# One folder per kind under the emulator's media directory. Taken from a real install;
# `pthumbs` and `vsthumbs` sit beside them holding generated thumbnails and are not one.
MEDIA_FOLDERS = (
    "PlayField", "BackGlass", "DMD", "Wheel", "Topper", "Loading", "Menu",
    "GameInfo", "GameHelp", "GameSelect", "Audio", "AudioLaunch", "Other1", "Other2",
)
NOT_MEDIA = ("pthumbs", "vsthumbs")

CARRIED = ("TAGS", "Category", "Notes", "DateAdded", "GAMEVER", "ALTEXE", "DOFStuff",
           "WebLinkURL", "WEBGameID", "ROMALT", "DesignedBy")


def database_path(root: Path | str) -> Path:
    return Path(root) / DATABASE


def detect(root: Path | str, survey: Callable[..., dict] | None = None) -> bool:
    return database_path(root).is_file()


def _open(path: Path) -> sqlite3.Connection:
    """Read-only, so a live frontend running against this database is not blocked by an
    importer that only ever converts from it."""
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    return db


def _text(row: sqlite3.Row, column: str) -> str:
    try:
        value = row[column]
    except (IndexError, KeyError):
        return ""
    return str(value).strip() if value is not None else ""


def _hidden(value: Any) -> bool:
    return str(value) in ("0", "False", "None")


def _media_key(row: sqlite3.Row) -> str:
    """What this game's artwork is named after.

    Usually its name, and sometimes whatever the game says instead: a `MediaSearch`
    holding a `*` replaces the key with what is left once the star is removed. Rare -
    every row in the install this was checked against left it empty - and a reader
    assuming the name finds nothing at all for the ones that use it.
    """
    override = _text(row, "MediaSearch")
    if "*" in override:
        return override.replace("*", "").strip()
    return _text(row, "GameName")


def _game_from(row: sqlite3.Row, tables_dir: str) -> SourceGame | None:
    name = _text(row, "GameName")
    if not name:
        return None

    file_name = _text(row, "GameFileName")
    table_file = ""
    if tables_dir and file_name:
        candidate = Path(tables_dir) / file_name
        table_file = str(candidate) if candidate.is_file() else ""

    return SourceGame(
        key=_media_key(row),
        display_name=name,
        title=_text(row, "GameDisplay"),
        manufacturer=_text(row, "Manufact"),
        year=_text(row, "GameYear"),
        game_type=_text(row, "GameType"),
        themes=tuple(part.strip() for part in _text(row, "GameTheme").split(",")
                     if part.strip()),
        ipdb_id=_text(row, "IPDBNum"),
        rom=_text(row, "ROM"),
        rating=_text(row, "GameRating"),
        players=_text(row, "NumPlayers"),
        author=_text(row, "Author"),
        # Popper hides a game rather than deleting it, the same as the other two.
        hidden=_hidden(row["Visible"]),
        table_file=table_file,
        extras={key: _text(row, key) for key in CARRIED if _text(row, key)},
    )


_FILLED = ("play_count", "play_time_seconds", "last_played", "rating")


def read_stats(path: Path | str) -> tuple[list[Played], list[Note]]:
    """What Popper remembers about playing, from the `GamesStats` table in its database.

    Keyed by the game's name, which is how the plan looks a game up. A game with no row,
    or a row with no plays and no date, is left out rather than read as a zero.
    """
    path = Path(path)
    if not path.is_file():
        return [], []
    try:
        db = _open(path)
    except sqlite3.Error as exc:
        logger.warning("Could not open %s: %s", path, exc)
        return [], [failed(t("note.unopened", file=path.name), exc)]
    try:
        # Every game, with its play row where it has one: a rating is kept on the game
        # itself, and a game nobody played can still have been rated. A database missing
        # either table or column still gives up what it does have.
        tables = {one[0] for one in db.execute("select name from sqlite_master")}
        rated = any(one[1] == "GameRating" for one in db.execute("pragma table_info(Games)"))
        played = "GamesStats" in tables
        rows = list(db.execute(
            "select g.GameName, "
            + ("g.GameRating" if rated else "null") + " as GameRating, "
            + ("s.NumberPlays, s.TimePlayedSecs, s.LastPlayed" if played else
               "null as NumberPlays, null as TimePlayedSecs, null as LastPlayed")
            + " from Games g"
            + (" left join GamesStats s on s.GameID = g.GameID" if played else "")))
    except sqlite3.Error as exc:
        logger.warning("Could not read %s to the end: %s", path, exc)
        return [], [failed(t("note.read_stopped", file=path.name), exc)]
    finally:
        db.close()

    # One entry per name, since that is how the plan looks a game up: a later row fills in
    # what an earlier one left out, and never blanks it, so a rated game that was not
    # played cannot replace the same name's play record.
    found: dict[str, Played] = {}
    for row in rows:
        name = _text(row, "GameName")
        one = Played(name=name, system="",
                     play_count=_positive(row["NumberPlays"]),
                     play_time_seconds=_positive(row["TimePlayedSecs"]),
                     last_played=_when(row["LastPlayed"]),
                     # 0 is unrated, which is not a rating to carry across.
                     rating=stars(row["GameRating"]) or None)
        if not name or not one.remembers_anything:
            continue
        before = found.get(name)
        found[name] = one if before is None else replace(
            before, **{field: getattr(one, field) for field in _FILLED
                       if getattr(one, field) is not None})
    return list(found.values()), []


def _positive(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _when(value: Any) -> int | None:
    """`2026-09-20 21:14:05.100` as epoch seconds, read as local time (no zone is written)."""
    said = str(value or "").strip()
    if not said:
        return None
    for shape in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return int(datetime.strptime(said, shape).astimezone(UTC).timestamp())
        except ValueError:
            continue
        except (OverflowError, OSError):
            return None
    return None


def read_media(media_root: Path | str, games: list[SourceGame]) -> list[SourceGame]:
    """Attach each game's artwork.

    The longest key that prefixes a filename wins, decided across the whole database -
    the same rule the other sources need, because Popper keys on a name too and two
    games' names can be prefixes of one another.
    """
    media_root = Path(media_root)
    folded = {game.key.lower(): game.key for game in games if game.key}
    found: dict[str, list[SourceMedia]] = {game.key: [] for game in games}

    for folder in MEDIA_FOLDERS:
        try:
            entries = [item for item in (media_root / folder).iterdir()
                       if item.is_file() and item.name not in NOT_MEDIA]
        except OSError:
            continue
        for item in entries:
            stem = item.stem.lower()
            owner = max((key for key in folded if stem.startswith(key)),
                        key=len, default=None)
            if owner is not None:
                found[folded[owner]].append(
                    SourceMedia(source_kind=folder, path=str(item)))

    return [SourceGame(**{**vars(game), "media": tuple(found.get(game.key, ()))})
            for game in games]


def _playable(said: str, plays: Callable[[str], bool] | None) -> bool:
    """Whether anything installed here plays what this emulator holds.

    An emulator that records no extension is kept: saying nothing is not saying no, and
    refusing it would drop a library over a blank column.
    """
    suffix = str(said or "").strip().lower()
    if not suffix:
        return True
    if not suffix.startswith("."):
        suffix = f".{suffix}"
    return bool(plays(suffix)) if plays else suffix == ".vpx"


def read(root: Path | str, plays: Callable[[str], bool] | None = None,
         known_apps: tuple[str, ...] = (), *, survey: Callable[..., dict] | None = None,
         chosen: dict | None = None) -> SourceLibrary:
    """Every emulator the database declares, and the games under each.

    The media root is derived from where the database actually is rather than read off
    the row: what an install records is the path on the machine it ran on, and a library
    reached over a share is never at that path.

    Every argument after `root` is accepted so every reader is called the same way. This
    one does not filter on `plays` yet: it reads one system, and what to do when that
    system is not playable here is a question about what the source declares, which is
    unfinished.
    """
    root = Path(root)
    path = database_path(root)
    if not path.is_file():
        return SourceLibrary(source_id=SOURCE_ID, root=str(root),
                             notes=(t("note.no_file", file=DATABASE, folder=root.name),))

    notes: list[Note] = []
    mapped: set[str] = set()
    systems: list[SourceSystem] = []
    try:
        db = _open(path)
    except sqlite3.Error as exc:
        logger.warning("Could not open %s: %s", path, exc)
        return SourceLibrary(source_id=SOURCE_ID, root=str(root),
                             notes=(failed(t("note.unopened", file=DATABASE), exc),))

    try:
        emulators = list(db.execute(
            "select EMUID, EmuName, DirGames, DirRoms, Visible, GamesExt "
            "from Emulators order by EMUID"))
        skipped_systems = []
        for emu in emulators:
            name = _text(emu, "EmuName")
            if not name:
                continue
            # Popper records the extension per emulator, always - which is a better
            # signal than either of the others gives, and the reason this filter is one
            # line here and three branches there.
            if not _playable(_text(emu, "GamesExt"), plays):
                skipped_systems.append(name)
                continue
            recorded = _text(emu, "DirGames")
            found = drivemap.resolve(recorded, root) if recorded else drivemap.Found()
            tables_dir = found.path
            if recorded and not tables_dir:
                notes.append(t("note.tables_unreachable", system=name, path=recorded))
            elif found.recorded_prefix and found.recorded_prefix not in mapped:
                # Said once per prefix rather than once per emulator: it is one fact
                # about where the share is, and repeating it per row buries the rest.
                mapped.add(found.recorded_prefix)
                notes.append(t("note.remapped", recorded=found.recorded_prefix,
                               local=found.local_prefix))

            rows = list(db.execute(
                "select * from Games where EMUID = ? order by GameName",
                (emu["EMUID"],)))
            games = [one for one in (_game_from(row, tables_dir) for row in rows)
                     if one is not None]
            skipped = len(rows) - len(games)
            if skipped:
                notes.append(t("note.rows_unnamed", system=name, count=skipped))
            games = read_media(root / MEDIA_DIR / name, games)
            systems.append(SourceSystem(
                name=name, games=tuple(games), tables_dir=tables_dir,
                working_path=drivemap.resolve(_text(emu, "DirRoms"), root).path
                or _text(emu, "DirRoms"),
                enabled=not _hidden(emu["Visible"])))
        if skipped_systems:
            # Named rather than dropped in silence, the same as the other reader:
            # somebody who set Future Pinball up wants to know it was seen and left.
            notes.append(t("note.not_played", systems=", ".join(sorted(skipped_systems))))
    except sqlite3.Error as exc:
        logger.warning("Could not read %s to the end: %s", path, exc)
        notes.append(failed(t("note.read_stopped", file=DATABASE), exc))
    finally:
        db.close()

    return SourceLibrary(source_id=SOURCE_ID, root=str(root),
                         systems=tuple(systems), notes=tuple(notes))
