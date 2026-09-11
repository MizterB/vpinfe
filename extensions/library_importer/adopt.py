"""Turning what a source holds into entries of ours.

It only ever creates. Nothing of the source is written to and nothing already in the
library is changed, so an import that fails partway leaves both exactly as they were
apart from the folders it had already made - and those are new, complete, and named.

Every write goes through the context. Nothing here opens a file of ours or knows where
the library is.
"""

from __future__ import annotations

from . import mapping
from .source import SourceGame, SourceLibrary


def _one(ctx, source_id: str, game: SourceGame, kinds: tuple[str, ...],
         location: str, name: str = "") -> dict:
    """One game, and what became of it. Returns a row for the report.

    The name is handed in because the caller has already asked core what folder it
    becomes. Working it out again here would give the unsanitized one, and then the same
    game is counted under two names.
    """
    name = name or mapping.folder_name(game)
    row = {"key": game.key, "name": name, "game_id": "", "table": False,
           "media": 0, "companions": 0, "skipped_media": [], "error": ""}
    try:
        game_id = ctx.games.create(name, location)
    except Exception as exc:
        row["error"] = str(exc)
        return row

    row["game_id"] = game_id
    details = mapping.details_for(game)
    if details:
        ctx.games.set_details(game_id, **details)

    # The table first, because a media file named for a game file needs that file's name
    # to exist. Its absence is not a failure: a source whose tables are still on the old
    # machine imports as entries with artwork and no game file, which is a state the
    # library has a word for.
    stem = ""
    if game.table_file:
        try:
            landed = ctx.games.add_table(game_id, game.table_file)
            row["table"] = True
            row["companions"] = len(landed["companions"])
        except Exception as exc:
            row["error"] = f"the game file did not come across: {exc}"

    for kind, path in mapping.media_for(source_id, game, kinds):
        try:
            ctx.games.put_media(game_id, kind, path, stem)
            row["media"] += 1
        except Exception as exc:
            ctx.logger.warning("%s: %s did not come across: %s", name, kind, exc)
    row["skipped_media"] = mapping.unmapped_kinds(source_id, game, kinds)
    return row


def _another_build(ctx, game: SourceGame, name: str, game_id: str) -> dict:
    """A second build of a machine the run has already made a game for.

    Its file joins that game rather than starting another one. The artwork does not:
    what is already there was placed for the same machine, and a second build's playfield
    would replace it with a picture of the same table.
    """
    row = {"key": game.key, "name": name, "game_id": game_id, "table": False,
           "media": 0, "companions": 0, "skipped_media": [], "error": "", "joined": True}
    if not game.table_file:
        return row
    try:
        landed = ctx.games.add_table(game_id, game.table_file)
        row["table"] = True
        row["companions"] = len(landed["companions"])
    except Exception as exc:
        row["error"] = f"the game file did not come across: {exc}"
    return row


def run(ctx, library: SourceLibrary, systems: list[str], location: str = "",
        plan=None) -> dict:
    """Convert the chosen systems. Answers with a row per game and the counts.

    A game that fails is recorded and the next one is tried. An import of six hundred
    stopping on the one folder somebody already had would be worse than useless: it is
    the case this exists for, and the answer is to say which one and carry on.

    A game the library already holds is left alone unless the plan says to fill in what
    it is missing. Rewriting what somebody has curated since the last run is the worse
    mistake, so it is not the default.
    """
    kinds = ctx.games.kinds()
    wanted = [system for system in library.systems
              if not systems or system.name in systems]
    held = {one.key: one for one in (plan.matches if plan else [])}
    fill = bool(plan and plan.on_existing == "fill")

    rows, skipped = [], []
    # What this run has already made, by folder name. A source holds several builds of
    # the same machine - three of Kiss (Bally 1979), by different authors - and they are
    # one game with three tables here, not three games. Without this the first wins the
    # folder and the rest fail on a name that is already taken.
    made_here: dict[str, str] = {}
    for system in wanted:
        for game in system.games:
            match = held.get(game.key)
            if match is not None and match.existing and not fill:
                skipped.append({"key": game.key, "name": match.folder,
                                "game_id": match.game_id, "how": match.how})
                continue
            # Asked of core, not worked out here: the folder a name becomes is core's
            # rule, and a copy of it drifts without saying so.
            name = ctx.games.folder_name_for(mapping.folder_name(game))
            seen = made_here.get(name.lower())
            if seen:
                rows.append(_another_build(ctx, game, name, seen))
                continue
            row = _one(ctx, library.source_id, game, kinds, location, name)
            if row["game_id"]:
                made_here[name.lower()] = row["game_id"]
            rows.append(row)
    made = [row for row in rows if row["game_id"]]
    return {
        "games": len({row["name"].lower() for row in made}),
        "tables": sum(1 for row in made if row["table"]),
        "media": sum(row["media"] for row in made),
        "companions": sum(row["companions"] for row in made),
        "failed": len(rows) - len(made),
        # Named rather than counted: after a partial run somebody wants to know which
        # ones were left, not how many.
        "already_here": skipped,
        "rows": rows,
    }
