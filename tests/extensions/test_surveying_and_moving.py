"""What an extension may do to a folder it only declared it reads from.

Looking at one is reading. Taking a file out of one is writing, which is its own
capability - declaring `games:write` lets an extension make entries, and says nothing
about deleting a file from somebody's frontend folder.
"""

from __future__ import annotations

import unittest
from unittest import mock

import httpapi
from common.extensions.context import ExtensionFiles
from common.extensions.contract import ContractError
from common.extensions.games import ExtensionGames, offered, withdraw_all
from common.games import library_folder_ops, library_folders
from tests.support.library import TempTree, write_game


class SurveyTests(TempTree):
    def setUp(self) -> None:
        super().setUp()
        self.tables = self.root / "Tables"
        write_game(self.tables, "Harbor Lights")
        (self.tables / "Quarry Run.vpx").write_bytes(b"table")
        self.elsewhere = self.root / "Elsewhere"
        self.elsewhere.mkdir()
        self.files = ExtensionFiles("tester", allowed=True)
        self.files.set_roots([str(self.tables)])
        self.games = ExtensionGames("tester", ("games:read",), self.files)

    def test_a_declared_folder_is_surveyed(self) -> None:
        self.assertEqual(self.games.survey(self.tables),
                         {"game_folders": ["Harbor Lights"], "loose": ["Quarry Run.vpx"]})

    def test_a_folder_it_never_declared_is_refused(self) -> None:
        with self.assertRaises(ContractError):
            self.games.survey(self.elsewhere)

    def test_reading_is_the_scope_it_takes(self) -> None:
        nothing = ExtensionGames("tester", (), self.files)

        with self.assertRaises(ContractError):
            nothing.survey(self.tables)


class MovingTests(TempTree):
    def setUp(self) -> None:
        super().setUp()
        patcher = mock.patch("common.games.library_enrichment.read_one", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)
        withdraw_all()
        self.addCleanup(withdraw_all)
        httpapi.create_api_app()
        self.tables = self.root / "Tables"
        self.tables.mkdir()
        self.table = self.tables / "Harbor Lights.vpx"
        self.table.write_bytes(b"table")
        self.library = self.root / "Library"
        self.library.mkdir()

    def _games(self, *, writes: bool) -> ExtensionGames:
        files = ExtensionFiles("tester", allowed=True, writes=writes)
        files.set_roots([str(self.tables)])
        return ExtensionGames("tester", ("games:read", "games:write"), files)

    def _entry(self) -> str:
        return str(write_game(self.library, "Harbor Lights", vpx=False))

    def test_a_move_without_the_capability_is_refused_and_nothing_moves(self) -> None:
        games = self._games(writes=False)
        folder = self._entry()

        with mock.patch.object(ExtensionGames, "folder", return_value=folder):
            with self.assertRaises(ContractError) as caught:
                games.add_table("g1", self.table, move=True)

        self.assertIn("fs:write", str(caught.exception))
        self.assertTrue(self.table.exists())

    def test_a_move_with_it_takes_the_file(self) -> None:
        games = self._games(writes=True)
        folder = self._entry()

        with mock.patch.object(ExtensionGames, "folder", return_value=folder):
            found = games.add_table("g1", self.table, move=True)

        self.assertFalse(self.table.exists())
        self.assertTrue((self.library / "Harbor Lights" / "Harbor Lights.vpx").exists())
        self.assertTrue(found["table_id"])

    def test_a_copy_needs_nothing_more(self) -> None:
        games = self._games(writes=False)
        folder = self._entry()

        with mock.patch.object(ExtensionGames, "folder", return_value=folder):
            games.add_table("g1", self.table)

        self.assertTrue(self.table.exists())

    def test_a_file_outside_what_it_declared_is_not_moved_either(self) -> None:
        games = self._games(writes=True)
        folder = self._entry()
        stray = self.root / "Stray.vpx"
        stray.write_bytes(b"table")

        with mock.patch.object(ExtensionGames, "folder", return_value=folder):
            with self.assertRaises(ContractError):
                games.add_table("g1", stray, move=True)

        self.assertTrue(stray.exists())


class LibraryFolderTests(TempTree):
    def setUp(self) -> None:
        super().setUp()
        self.store = library_folders.LocationStore(self.root / "config")
        patcher = mock.patch.object(library_folders, "get_location_store", return_value=self.store)
        patcher.start()
        self.addCleanup(patcher.stop)
        withdraw_all()
        self.addCleanup(withdraw_all)
        httpapi.create_api_app()
        self.folder = self.root / "Games"
        self.folder.mkdir()

    def test_a_folder_becomes_a_library_folder(self) -> None:
        made = library_folder_ops.use_library_folder(str(self.folder))

        self.assertTrue(made["location_id"])
        self.assertEqual([one.path for one in self.store.locations()],
                         [str(self.folder)])
        self.assertEqual(made["kind"], library_folders.KIND_ROOT)

    def test_asking_twice_names_one_place_once(self) -> None:
        first = library_folder_ops.use_library_folder(str(self.folder))
        second = library_folder_ops.use_library_folder(str(self.folder))

        self.assertEqual(first["location_id"], second["location_id"])
        self.assertEqual(len(self.store.locations()), 1)

    def test_adding_a_library_folder_and_seeing_where_games_go_take_the_config_scopes(self) -> None:
        """The same scopes the routes under /locations take, so declaring them means what
        it does for an HTTP client."""
        reader = ExtensionGames("tester", ("config:read",), None)
        writer = ExtensionGames("tester", ("config:write",), None)
        nothing = ExtensionGames("tester", ("games:read", "games:write"), None)

        self.assertIn("new_game_destination", offered())
        self.assertEqual(reader.reaches(), ("new_game_destination",))
        self.assertEqual(writer.reaches(), ("use_library_folder",))
        self.assertEqual(nothing.reaches().count("use_library_folder"), 0)
        with self.assertRaises(ContractError):
            nothing.use_library_folder("/anywhere")


if __name__ == "__main__":
    unittest.main()
