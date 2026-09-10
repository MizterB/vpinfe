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


class ExtensionGames:
    def __init__(self, name: str, scopes, files) -> None:
        self._name = name
        self._scopes = frozenset(scopes)
        self._files = files

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
            raise FileNotFoundError(str(wanted))
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

    def set_details(self, game_id: str, **fields) -> None:
        self._needs(GAMES_WRITE)
        from common.games import game_service

        game_service.set_details(Path(self.folder(game_id)), fields)

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
