"""What core lets an extension do to the library.

One table, kept beside the routes rather than inside the extension host, because these
are core's functions and adding a route is the moment somebody should be deciding whether
extensions get it too.

**The route handlers are called directly, not over HTTP.** They are plain functions; the
scope gate lives in each route's `dependencies=[...]`, which only applies to a request
arriving over the wire. So an extension reaches exactly the code an HTTP client reaches,
and the two cannot drift - which they had, silently, while the host kept its own smaller
copy of the library.

The names are what an extension calls them, not what the handler is called. A handler is
named for its route; an extension author is reading a list of things they can do.
"""

from __future__ import annotations

from common.extensions.games import GAMES_READ, GAMES_WRITE, offer

from . import games, models


def _details(game_id: str, **fields):
    return games.put_game_details(game_id, models.GameDetails(**fields))


def _rate_game(game_id: str, rating):
    return games.put_game_rating(game_id, models.RatingRequest(rating=rating))


def _rate_table(game_id: str, table_id: str, rating):
    return games.put_table_rating(game_id, table_id, models.RatingRequest(rating=rating))


def _tag(game_id: str, tags):
    return games.put_game_tags(game_id, models.TagsRequest(tags=list(tags)))


def _favorite(game_id: str, favorite: bool):
    return games.put_game_favorite(game_id, models.FavoriteRequest(favorite=favorite))


def _default_table(game_id: str, table_id: str):
    return games.put_default_table(game_id, models.TableDefault(table_id=table_id))


# Reading is one scope and writing another, and a few of these are neither obvious:
# launching a game is a write because it changes what the play record says, and taking
# an entry's details from a catalog is a write for the same reason.
READS = {
    "list_games": games.list_games,
    "get_game": games.get_game,
    "game_tables": games.get_games,
    "game_media": games.get_game_media,
    "table_media": games.get_table_media,
    "media_detail": games.get_game_media_detail,
    "vps_state": games.get_vps_state,
    "vps_details": games.get_vps_details,
}

WRITES = {
    "set_details": _details,
    "rate_game": _rate_game,
    "rate_table": _rate_table,
    "set_tags": _tag,
    "set_favorite": _favorite,
    "set_default_table": _default_table,
    "reset_play_record": games.reset_play_record,
    "take_vps_details": games.put_vps_details,
    "remove_media": games.delete_game_media,
    "forget_table": games.delete_table,
    "add_keyed_table": games.add_keyed_table,
}


def offer_all() -> None:
    """Hand the whole table to the extension host. Once, before anything loads."""
    for name, run in READS.items():
        offer(name, GAMES_READ, run)
    for name, run in WRITES.items():
        offer(name, GAMES_WRITE, run)
