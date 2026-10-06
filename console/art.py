"""The address of a picture the Console draws: which file, at what size, which version."""

from __future__ import annotations

from urllib.parse import quote, urlencode

from common.media_specs import media_family

# The longest edge the API sizes to. CELL is anything drawn at thumbnail scale; PANEL is
# a slot or a tile someone is looking at.
CELL = 256
PANEL = 1024


def media(game_id: str, kind: str, table_id: str = "", *,
          version: str | None = None, size: int | None = None) -> str:
    """A game's shared file for `kind`, or one table's. A size on a kind that is not a
    picture is dropped, because the API refuses it."""
    table = f"/tables/{quote(table_id, safe='')}" if table_id else ""
    base = f"/api/v1/games/{quote(game_id, safe='')}{table}/media/{kind}"
    return _with(base, version, size if media_family(kind) == "image" else None)


def picture(game_id: str, name: str, *, version: str | None = None,
            size: int | None = None) -> str:
    """One of a game's Pictures."""
    return _with(f"/api/v1/games/{quote(game_id, safe='')}/pictures/{quote(name, safe='')}",
                 version, size)


def backglass(game_id: str, path: str, *, version: str | None = None,
              size: int | None = None) -> str:
    """The picture a game's backglass file draws, lit at start and cut as the cabinet
    cuts it."""
    query = urlencode({"path": path, "look": "on", "grill": "true"})
    return _with(f"/api/v1/games/{quote(game_id, safe='')}/assets/backglass/picture?{query}",
                 version, size)


def collection(name: str, *, version: str | None = None, size: int | None = None) -> str:
    return _with(f"/api/v1/collections/{quote(name, safe='')}/image", version, size)


def player(player_id: str, *, version: str | None = None, size: int | None = None) -> str:
    return _with(f"/api/v1/players/{quote(player_id, safe='')}/picture", version, size)


def sized(url: str, size: int) -> str:
    """An art address the API handed over, at `size`."""
    return _with(url, None, size)


def _with(url: str, version: str | None, size: int | None) -> str:
    query = {key: value for key, value in (("size", size), ("v", version)) if value}
    if not query:
        return url
    return f"{url}{'&' if '?' in url else '?'}{urlencode(query)}"
