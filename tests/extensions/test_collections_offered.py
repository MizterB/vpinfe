"""An extension's collection calls change the file an HTTP client's would, and are gated.

Against a real `collections.json` on disk, not a stand-in store.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

import httpapi
from common.extensions.contract import ContractError
from common.extensions.games import withdraw_all
from common.extensions.library_collections import ExtensionCollections
from common.games.collection_store import CollectionStore
from tests.support.library import TempTree, fake_game, write_game

IDS = ("Col000000001", "Col000000002", "Col000000003")


class OfferedCollectionTests(TempTree):
    def setUp(self) -> None:
        super().setUp()
        withdraw_all()
        self.addCleanup(withdraw_all)
        self.store = CollectionStore(str(self.root / "collections.json"))
        games = {}
        for index, game_id in enumerate(IDS):
            folder = write_game(self.root, f"Table {index}",
                                info={"Info": {"Name": f"Table {index}"},
                                      "VPinFE": {"game_id": game_id}})
            games[game_id] = fake_game(folder, f"Table {index}")
        for target, value in (
            ("common.games.game_repository.catalog", lambda: games),
            ("common.games.collection_ops.get_collections_manager", lambda: self.store),
            ("common.games.collections_service.get_collections_manager",
             lambda: self.store),
        ):
            held = patch(target, value)
            held.start()
            self.addCleanup(held.stop)
        httpapi.create_api_app()
        self.ext = ExtensionCollections(
            "tester", ("collections:read", "collections:write"))

    def _members(self, name: str) -> list[str]:
        self.store.reload()
        return list(self.store.get_members(name))

    def test_a_collection_made_by_an_extension_is_in_the_file_with_its_games(self) -> None:
        self.ext.create_collection("Williams", games=IDS[:2], description="Two of them")

        self.assertEqual(self._members("Williams"), list(IDS[:2]))

    def test_adding_and_removing_a_game_changes_the_members(self) -> None:
        self.ext.create_collection("Williams", games=IDS[:1])
        self.ext.add_to_collection("Williams", IDS[1])
        self.assertEqual(self._members("Williams"), list(IDS[:2]))

        self.ext.remove_from_collection("Williams", IDS[0])
        self.assertEqual(self._members("Williams"), [IDS[1]])

    def test_adding_a_game_already_in_it_succeeds_and_changes_nothing(self) -> None:
        self.ext.create_collection("Williams", games=IDS[:1])
        self.ext.add_to_collection("Williams", IDS[0])

        self.assertEqual(self._members("Williams"), [IDS[0]])

    def test_an_order_is_kept_as_given(self) -> None:
        self.ext.create_collection("Williams", games=IDS)
        self.ext.set_collection_order("Williams", [IDS[2], IDS[0], IDS[1]])

        self.assertEqual(self._members("Williams"), [IDS[2], IDS[0], IDS[1]])

    def test_a_rename_and_a_description_are_written(self) -> None:
        self.ext.create_collection("Williams", games=IDS[:1])
        self.ext.rename_collection("Williams", "Bally")
        self.ext.describe_collection("Bally", "Pinball 2000 and friends")
        self.store.reload()

        self.assertIn("Bally", self.store.get_collections_name())
        self.assertNotIn("Williams", self.store.get_collections_name())
        self.assertEqual(self.store.get_description("Bally"),
                         "Pinball 2000 and friends")

    def test_a_delete_removes_it(self) -> None:
        self.ext.create_collection("Williams", games=IDS[:1])
        self.ext.delete_collection("Williams")
        self.store.reload()

        self.assertNotIn("Williams", self.store.get_collections_name())

    def test_reading_lists_what_was_made(self) -> None:
        self.ext.create_collection("Williams", games=IDS[:2])

        names = [one["name"] for one in self.ext.list_collections()["collections"]]
        self.assertIn("Williams", names)
        self.assertEqual(len(self.ext.collection_members("Williams")["members"]), 2)

    def test_reading_alone_cannot_write(self) -> None:
        reader = ExtensionCollections("reader", ("collections:read",))

        with self.assertRaises(ContractError):
            reader.create_collection("Nope")
        self.assertEqual(reader.reaches(), (
            "collection_games", "collection_members", "get_collection", "list_collections"))

    def test_without_either_scope_nothing_is_reachable(self) -> None:
        bare = ExtensionCollections("bare", ())

        self.assertEqual(bare.reaches(), ())
        with self.assertRaises(ContractError):
            bare.list_collections()

    def test_only_the_listed_calls_are_offered(self) -> None:
        """Rules, exclusions and pictures stay out: a name added to the offers has to be
        added here too."""
        self.assertEqual(self.ext.reaches(), (
            "add_to_collection", "collection_games", "collection_members",
            "create_collection", "delete_collection", "describe_collection",
            "get_collection", "list_collections", "remove_from_collection",
            "rename_collection", "set_collection_order"))


if __name__ == "__main__":
    unittest.main()
