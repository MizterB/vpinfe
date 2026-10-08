"""Turning what a source holds into entries of ours.

It creates, and it writes to the source only when told to move. Without that nothing of
the source is written to and nothing already in the library is changed, so an import that
fails partway leaves both exactly as they were apart from the folders it had already made -
and those are new, complete, and named. A move takes the game files out of where they
were, and is the one thing here that does.

Every write goes through the context. Nothing here opens a file of ours or knows where
the library is.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NotRequired, TypedDict

from . import mapping
from .plan import Held, Missing, history_for, missing_history
from .source import Note, SourceGame, SourceLibrary

# Where a ROM set and the folders keyed on it are placed, by the kind the registry knows
# them as. A color set comes in two formats and the file decides which, so both are
# tried against what is actually there.
ALT_KINDS = {".crz": "altcolor_serum", ".cromc": "altcolor_serum",
             ".vni": "altcolor_vni", ".pal": "altcolor_vni"}


class AdoptedRow(TypedDict):
    """One game and what became of it. `joined` is only on a second build
    of a machine the run has already made a game for, `existing` on a game the library
    already held and the run filled in."""

    key: str
    name: str
    game_id: str
    table: bool
    media: int
    companions: int
    roms: int
    altdata: int
    history: int
    skipped_media: list[str]
    error: Note
    joined: NotRequired[bool]
    existing: NotRequired[bool]


@dataclass(frozen=True)
class Standing:
    """How far a run has got, said as it starts each game."""

    games_done: int
    games_total: int
    bytes_done: int
    bytes_total: int
    name: str


def _bring_rom(ctx: Any, game_id: str, rom: str, roms_dir: str) -> int:
    """The ROM set itself, if that folder has one by this name."""
    found = next((one for one in Path(roms_dir).glob(f"{rom}.*")
                  if one.is_file()), None)
    if found is None:
        return 0
    try:
        ctx.games.put_asset(game_id, "rom", found)
        return 1
    except FileExistsError:
        return 0
    except Exception as exc:
        ctx.logger.warning("%s did not come across: %s", found.name, exc)
        return 0


def _bring_alt_data(ctx: Any, game_id: str, rom: str, alt_dir: str) -> int:
    """Sound banks and color sets, which sit in folders named for the ROM.

    The layout is the one PIN2DMD and altsound document: `altcolor/<rom>/` and
    `altsound/<rom>/`, beside each other under one root.
    """
    brought = 0
    root = Path(alt_dir)
    for folder, kind in (("altsound", "altsound"), ("altcolor", ""), ("serum", "")):
        here = root / folder / rom
        if not here.is_dir():
            continue
        if kind:
            brought += _put(ctx, game_id, kind, here, rom)
            continue
        # A color set's format is the file's to declare, not the folder's.
        for one in sorted(here.iterdir()):
            said = ALT_KINDS.get(one.suffix.lower())
            if said:
                brought += _put(ctx, game_id, said, one, rom)
    return brought


def _remember(ctx: Any, game_id: str, played: Any, held: Held | None = None) -> int:
    """What the old frontend remembered about playing this game.

    The counters go through the one call that sets them; rating, favorite and tags are
    opinions with routes of their own and go through those. A value the source never
    wrote is left alone rather than sent as a zero - a game nobody played and a game
    whose count was never recorded are different, and only one of them should overwrite
    what is already here.

    For a game being filled (`held`), only what the library has none of is written: a
    counter at nothing, a game with no rating, tags added to the ones it has, a favorite
    turned on and never off.
    """
    if held is not None:
        return _add_missing(ctx, game_id, missing_history(played, held.user), held)
    try:
        if played.has_play_record:
            ctx.games.set_play_record(
                game_id, play_count=played.play_count,
                play_time_seconds=played.play_time_seconds,
                last_played=played.last_played)
        if played.tags:
            ctx.games.set_tags(game_id, list(played.tags))
        if played.rating:
            ctx.games.rate_game(game_id, played.rating)
        if played.favorite:
            ctx.games.set_favorite(game_id, True)
    except Exception as exc:
        ctx.logger.warning("Could not carry the play history for %s: %s", game_id, exc)
        return 0
    return 1 if played.counts_as_history else 0


def _add_missing(ctx: Any, game_id: str, adds: Missing, held: Held) -> int:
    """Each kind of history is written on its own, so one the library refuses (a tag it
    derives itself) does not keep the others from arriving. Answers 1 where counters or
    tags were written, the two the report counts."""
    writes = (
        (True, adds.counters,
         lambda: ctx.games.set_play_record(game_id, **adds.counters)),
        (True, adds.tags,
         lambda: ctx.games.set_tags(game_id, [*(held.user.get("tags") or []), *adds.tags])),
        (False, adds.rating, lambda: ctx.games.rate_game(game_id, adds.rating)),
        (False, adds.favorite, lambda: ctx.games.set_favorite(game_id, True)),
    )
    counted = 0
    for reported, wanted, write in writes:
        if not wanted:
            continue
        try:
            write()
        except Exception as exc:
            ctx.logger.warning("Could not carry the play history for %s: %s", game_id, exc)
            continue
        counted = counted or int(reported)
    return counted


def _held(ctx: Any, game_id: str) -> Held | None:
    """What the library holds of this game now, or nothing where it cannot be read, in
    which case a fill writes nothing it cannot tell is missing."""
    try:
        one = ctx.games.get_game(game_id)
    except Exception as exc:
        ctx.logger.warning("Could not read %s before filling it: %s", game_id, exc)
        return None
    return Held(rom=str(one.get("rom") or ""), user=dict(one.get("user") or {}))


def _put(ctx: Any, game_id: str, kind: str, path: Path, rom: str) -> int:
    try:
        ctx.games.put_asset(game_id, kind, path, rom)
        return 1
    except FileExistsError:
        return 0
    except Exception as exc:
        ctx.logger.warning("%s did not come across: %s", path.name, exc)
        return 0


def _one(ctx: Any, source_id: str, game: SourceGame, kinds: tuple[str, ...],
         location: str, name: str = "", sources: Any = None,
         history: Any = None, move: bool = False,
         cleared: frozenset[str] = frozenset(), existing: str = "") -> AdoptedRow:
    """One game, and what became of it. Returns a row for the report.

    `existing` is the id of the game the library already holds for this one. It is filled
    in rather than created: media only into a slot that is empty, the game file only if no
    file of that name is there, and its details are not written, since they may be the
    person's own edits.

    `cleared` holds the kinds whose source the person emptied. Those are not brought, which
    is what the summary told them and what the report expects.

    The name is handed in because the caller has already asked core what folder it
    becomes. Working it out again here would give the unsanitized one, and then the same
    game is counted under two names.
    """
    name = name or mapping.folder_name(game)
    row: AdoptedRow = {"key": game.key, "name": name, "game_id": "", "table": False,
                       "media": 0, "companions": 0, "roms": 0, "altdata": 0,
                       "history": 0, "skipped_media": [], "error": ""}
    if existing:
        game_id = existing
        row["existing"] = True
    else:
        try:
            game_id = ctx.games.create(name, location)
        except Exception as exc:
            ctx.logger.warning("No folder for %s: %s", name, exc)
            row["error"] = {"text": ctx.t("error.no_folder"), "detail": ctx.why(exc)}
            return row

    row["game_id"] = game_id
    details = mapping.details_for(game)
    if details and not existing:
        ctx.games.set_details(game_id, **details)

    # The table first, because a media file named for a game file needs that file's name
    # to exist. Its absence is not a failure: a source whose tables are still on the old
    # machine imports as entries with artwork and no game file, which is a state the
    # library has a word for.
    stem, rom = "", ""
    if game.table_file and "tables" not in cleared:
        try:
            landed = ctx.games.add_table(game_id, game.table_file, move=move)
            row["table"] = True
            row["companions"] = len(landed["companions"])
            rom = landed.get("rom", "")
        except Exception as exc:
            # The copy already holding this file is the copy staying as it is, and its
            # ROM was read when it arrived. Not a failure, and nothing to count.
            if not (existing and isinstance(exc, FileExistsError)):
                ctx.logger.warning("%s: the game file did not come across: %s", name, exc)
                row["error"] = {"text": ctx.t("error.game_file"), "detail": ctx.why(exc)}

    if "media" not in cleared:
        for kind, path in mapping.media_for(source_id, game, kinds):
            try:
                ctx.games.put_media(game_id, kind, path, stem, replace=not existing)
                row["media"] += 1
            except FileExistsError:
                continue
            except Exception as exc:
                ctx.logger.warning("%s: %s did not come across: %s", name, kind, exc)
        row["skipped_media"] = mapping.unmapped_kinds(source_id, game, kinds)

    # After the table, because the ROM comes out of the table. A game with no ROM has
    # nothing keyed on it, which is most of a library and not a failure. A filled game's
    # ROM falls back to the one the game holds.
    held = _held(ctx, game_id) if existing else None
    if held and not rom:
        rom = held.rom
    if (row["table"] or existing) and sources:
        if rom:
            if sources.get("roms"):
                row["roms"] = _bring_rom(ctx, game_id, rom, sources["roms"])
            if sources.get("altdata"):
                row["altdata"] = _bring_alt_data(ctx, game_id, rom, sources["altdata"])

    played = history_for(history or {}, game)
    if played is not None and (held or not existing):
        row["history"] = _remember(ctx, game_id, played, held)
    return row


def _another_build(ctx: Any, game: SourceGame, name: str, game_id: str,
                   move: bool = False, cleared: frozenset[str] = frozenset(),
                   existing: bool = False) -> AdoptedRow:
    """A second build of a machine the run has already made a game for.

    Its file joins that game rather than starting another one. The artwork does not:
    what is already there was placed for the same machine, and a second build's playfield
    would replace it with a picture of the same table. In a game the library already
    held, a file of the same name is already there and stays.
    """
    row: AdoptedRow = {"key": game.key, "name": name, "game_id": game_id,
                       "table": False, "media": 0, "companions": 0, "roms": 0,
                       "altdata": 0, "history": 0, "skipped_media": [], "error": "",
                       "joined": True}
    if existing:
        row["existing"] = True
    if not game.table_file or "tables" in cleared:
        return row
    try:
        landed = ctx.games.add_table(game_id, game.table_file, move=move)
        row["table"] = True
        row["companions"] = len(landed["companions"])
    except Exception as exc:
        if not (existing and isinstance(exc, FileExistsError)):
            ctx.logger.warning("%s: the game file did not come across: %s", name, exc)
            row["error"] = {"text": ctx.t("error.game_file"), "detail": ctx.why(exc)}
    return row


def run(ctx: Any, library: SourceLibrary, systems: list[str], location: str = "",
        plan: Any = None, *, move: bool = False,
        places: dict[str, str] | None = None,
        weigh: Callable[[SourceGame], int] | None = None,
        report: Callable[[Standing], None] | None = None,
        halted: Callable[[], bool] | None = None) -> dict:
    """Convert the chosen systems. Answers with a row per game and the counts.

    `move` takes each game file out of where it was; artwork, ROMs and the rest are
    copied either way. `places` names the location a system's games are made in, by the
    system's name, where that is not `location`.

    A game that fails is recorded and the next one is tried. An import of six hundred
    stopping on the one folder somebody already had would be worse than useless: it is
    the case this exists for, and the answer is to say which one and carry on.

    A game the library already holds is left alone unless the plan says to fill in what
    it is missing. Rewriting what somebody has curated since the last run is the worse
    mistake, so it is not the default. Filling goes to the game it matched, adds what is
    absent and never replaces what is there.

    `report` is told where the run has got to before each game, with `weigh` giving what
    a game is worth in bytes. `halted` is asked between games: a run that is stopped ends
    after the game in hand, so every folder it made is whole, and says so in `stopped`.
    """
    kinds = ctx.games.kinds()
    wanted = [system for system in library.systems
              if not systems or system.name in systems]
    held = {one.key: one for one in (plan.matches if plan else [])}
    sources = {one.key: one.path for one in (plan.sources if plan else ()) if one.active}
    cleared = frozenset(one.key for one in (plan.sources if plan else ())
                        if not one.active)
    history = plan.history if plan else {}
    fill = bool(plan and plan.on_existing == "fill")

    rows, skipped = [], []
    # What this run has already made, by folder name. A source holds several builds of
    # the same machine - three of Kiss (Bally 1979), by different authors - and they are
    # one game with three tables here, not three games. Without this the first wins the
    # folder and the rest fail on a name that is already taken.
    made_here: dict[str, str] = {}
    # The games this run fills in rather than makes, by the source's key.
    held_ids: dict[str, str] = {}
    to_do: list[tuple[str, SourceGame]] = []
    for system in wanted:
        where = (places or {}).get(system.name, location)
        for game in system.games:
            match = held.get(game.key)
            if match is not None and match.existing and not fill:
                skipped.append({"key": game.key, "name": match.folder,
                                "game_id": match.game_id,
                                "how": ctx.t(f"match.{match.how}")})
                continue
            if match is not None and match.existing:
                held_ids[game.key] = match.game_id
            to_do.append((where, game))

    weights = [weigh(game) if weigh else 0 for _where, game in to_do]
    total_bytes, bytes_done, stopped = sum(weights), 0, False
    for at, ((where, game), weight) in enumerate(zip(to_do, weights, strict=True)):
        if halted and halted():
            stopped = True
            break
        # Asked of core, not worked out here: the folder a name becomes is core's
        # rule, and a copy of it drifts without saying so.
        name = ctx.games.folder_name_for(mapping.folder_name(game))
        if report:
            report(Standing(at, len(to_do), bytes_done, total_bytes, name))
        bytes_done += weight
        seen = made_here.get(name.lower())
        if seen:
            rows.append(_another_build(ctx, game, name, seen, move, cleared,
                                       seen in held_ids.values()))
            continue
        row = _one(ctx, library.source_id, game, kinds, where, name, sources,
                   history, move, cleared, held_ids.get(game.key, ""))
        if row["game_id"]:
            made_here[name.lower()] = row["game_id"]
        rows.append(row)
    made = [row for row in rows if row["game_id"]]
    filled = {row["name"].lower() for row in made if row.get("existing") and any(
        row[one] for one in ("table", "media", "companions", "roms", "altdata", "history"))}
    return {
        "games": len({row["name"].lower() for row in made}),
        "filled": len(filled),
        "tables": sum(1 for row in made if row["table"]),
        "media": sum(row["media"] for row in made),
        "companions": sum(row["companions"] for row in made),
        "roms": sum(row["roms"] for row in made),
        "altdata": sum(row["altdata"] for row in made),
        "history": sum(row["history"] for row in made),
        "failed": len(rows) - len(made),
        "stopped": stopped,
        "left": len(to_do) - len(rows),
        # Named rather than counted: after a partial run somebody wants to know which
        # ones were left, not how many.
        "already_here": skipped,
        "rows": rows,
    }
