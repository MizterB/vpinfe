"""The library, as an extension is allowed to see it.

A curated view over the same services the API's own routes call, so the two cannot
answer differently. An extension in this process cannot use the HTTP API - a synchronous
call into the server it is running inside deadlocks, which the Console already pays for
elsewhere - and it may not import the library either. This is the door.

What it will do is bounded twice. The manifest's scopes decide which of these an
extension may call at all, which is what makes declaring them mean something. And a path
it hands over has to be inside a folder it said it works from, so an extension cannot use
core as a way to read somewhere it never declared.
"""

from __future__ import annotations

import logging
from pathlib import Path

from .contract import ContractError

logger = logging.getLogger("vpinfe.common.extensions.games")

GAMES_READ = "games:read"
GAMES_WRITE = "games:write"

# What core has said an extension may do to the library, by the name an extension calls
# it: `name -> (scope, callable)`.
#
# Core fills this in, because these are core's own functions and the host is not the
# place that knows them. Filled in rather than imported so this module stays underneath
# the API rather than reaching up into it, and rather than reimplemented so the two
# cannot answer differently - they already did, and it showed up as an importer that
# guessed at core's folder-naming rule and got it wrong.
_OFFERED: dict[str, tuple[str, object]] = {}


def offer(name: str, scope: str, run) -> None:
    """Core: let extensions call this, for anything declaring `scope`."""
    _OFFERED[name] = (scope, run)


def offered() -> tuple[str, ...]:
    return tuple(sorted(_OFFERED))


def withdraw_all() -> None:
    """For tests, which build an app per case and must not inherit the last one's."""
    _OFFERED.clear()


class ExtensionGames:
    def __init__(self, name: str, scopes, files) -> None:
        self._name = name
        self._scopes = frozenset(scopes)
        self._files = files

    def __getattr__(self, name: str):
        """Anything core offered that this does not wrap itself.

        The named methods below stay because they are worth having a shape for - they
        take a path and check it, or they answer with something an importer wants. The
        rest an extension calls the way the API names them, gated the same way.
        """
        if name.startswith("_") or name not in _OFFERED:
            raise AttributeError(
                f"core offers nothing called {name!r} to an extension"
                + (f"; it offers {', '.join(offered())}" if _OFFERED else ""))
        scope, run = _OFFERED[name]
        self._needs(scope)

        def call(*args, **kwargs):
            return run(*args, **kwargs)

        call.__name__ = name
        return call

    def reaches(self) -> tuple[str, ...]:
        """What this extension may actually call, which is what core offers narrowed to
        what its manifest declared."""
        return tuple(name for name, (scope, _run) in sorted(_OFFERED.items())
                     if scope in self._scopes)

    # -- the two bounds -------------------------------------------------------

    def _needs(self, scope: str) -> None:
        if scope not in self._scopes:
            raise ContractError(
                f"{self._name} asks core to do something needing {scope}, which its "
                "manifest does not declare")

    def _source(self, path) -> Path:
        """A file the extension is handing over, checked against what it declared.

        Tighter than the same check on the HTTP routes, and it can be: this one knows
        which extension is asking, where a route only knows a path.
        """
        wanted = Path(str(path or "")).expanduser().resolve()
        roots = [Path(one) for one in self._files.roots()]
        if not any(wanted == root or root in wanted.parents for root in roots):
            raise ContractError(
                f"{self._name} offered {wanted}, which is not inside any folder it says "
                "it works from")
        if not wanted.is_file():
            raise FileNotFoundError(f"there is no file at {wanted}")
        return wanted

    def _game(self, game_id: str):
        from common.games import game_identity
        from common.games.game_repository import all_games

        found = game_identity.ensure_unique_ids(all_games()).get(str(game_id or ""))
        if found is None:
            raise LookupError(f"No game with id {game_id}")
        return found

    # -- reading --------------------------------------------------------------

    def kinds(self) -> tuple[str, ...]:
        """Every media kind this build stores. The vocabulary an importer maps onto, and
        the reason it does not have to hard-code a list that would go stale."""
        self._needs(GAMES_READ)
        from common.media_specs import MEDIA_SPECS

        return tuple(spec.kind for spec in MEDIA_SPECS)

    def existing(self) -> list[dict]:
        """Every game already here, in the little an importer needs to recognise one.

        Not the whole library: what a second run is asking is "have I made this one
        before", and folder name, catalog id and title answer it. Anything more would be
        handing over the library to answer a question about names.
        """
        self._needs(GAMES_READ)
        from common.games import game_identity
        from common.games.game_metadata import game_title, normalize_meta, section
        from common.games.game_repository import all_games

        found = []
        for game in all_games():
            meta = normalize_meta(getattr(game, "meta_config", {}))
            info = section(meta, "Info")
            found.append({
                "game_id": game_identity.game_id(game),
                "folder_name": Path(str(game.fullPathGame)).name,
                "name": game_title(game),
                "vps_id": str(info.get("VPSId", "") or ""),
                "ipdb_id": str(info.get("IPDBId", "") or ""),
            })
        return found

    def folder_name_for(self, name: str) -> str:
        """The folder a game of this name would get.

        Asked rather than guessed. An importer needs this before it creates anything -
        to see what it already has, and to notice that two of its own games want the
        same folder - and a second copy of the rule drifts from this one silently. It
        did: `Star Trek: The Next Generation` and `Star Trek The Next Generation` are one
        folder here and were two to the importer, so the second failed on a name that was
        already taken.
        """
        self._needs(GAMES_READ)
        from common.games.game_service import sanitize_dir_name

        return sanitize_dir_name(name)

    def folder(self, game_id: str) -> str:
        self._needs(GAMES_READ)
        return str(self._game(game_id).fullPathGame)

    # -- writing --------------------------------------------------------------

    def create(self, name: str, location: str = "") -> str:
        """Make an entry and answer with its id."""
        self._needs(GAMES_WRITE)
        from common.games import game_identity, game_service

        folder = game_service.create_game(name, location)
        from common.games.game_repository import all_games

        made = next((game for game in all_games()
                     if Path(str(game.fullPathGame)).resolve() == folder.resolve()), None)
        if made is None:
            raise LookupError(f"Created {folder} but this install does not read it")
        return game_identity.ensure_id(made)

    def add_table(self, game_id: str, path) -> str:
        """Copy a game file into an entry and answer with the table's id."""
        self._needs(GAMES_WRITE)
        from common.games import game_service
        from common.games.ids import new_id

        source = self._source(path)
        table_id = new_id()
        game_service.add_table_file(Path(self.folder(game_id)), source, table_id)
        return table_id

    def put_media(self, game_id: str, kind: str, path, table_stem: str = "") -> str:
        """Put a file in one of an entry's media slots. Answers with what it landed as."""
        self._needs(GAMES_WRITE)
        from common.games import media_placement

        if kind not in self.kinds():
            raise ValueError(f"No media kind called {kind!r}")
        source = self._source(path)
        game_dir = Path(self.folder(game_id))
        written = media_placement.place(game_dir, kind, table_stem or game_dir.name,
                                        source)
        # Recorded as the user's, because it is: somebody's own library came across, and
        # a later media refresh must leave it alone rather than treat it as ours to
        # replace.
        media_placement.record_origin(game_dir, written, "user", "")
        return written.name
