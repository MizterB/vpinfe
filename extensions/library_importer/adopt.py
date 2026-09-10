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
         location: str) -> dict:
    """One game, and what became of it. Returns a row for the report."""
    name = mapping.folder_name(game)
    row = {"key": game.key, "name": name, "game_id": "", "table": False,
           "media": 0, "skipped_media": [], "error": ""}
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
            ctx.games.add_table(game_id, game.table_file)
            row["table"] = True
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


def run(ctx, library: SourceLibrary, systems: list[str], location: str = "") -> dict:
    """Convert the chosen systems. Answers with a row per game.

    A game that fails is recorded and the next one is tried. An import of six hundred
    stopping on the one folder somebody already had would be worse than useless: it is
    the case this exists for, and the answer is to say which one and carry on.
    """
    kinds = ctx.games.kinds()
    wanted = [system for system in library.systems
              if not systems or system.name in systems]

    rows = []
    for system in wanted:
        for game in system.games:
            rows.append(_one(ctx, library.source_id, game, kinds, location))
    made = [row for row in rows if row["game_id"]]
    return {
        "created": len(made),
        "failed": len(rows) - len(made),
        "with_a_game_file": sum(1 for row in made if row["table"]),
        "media_files": sum(row["media"] for row in made),
        "games": rows,
    }
