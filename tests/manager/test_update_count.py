"""The number on Discovery's entry in the menu: how many games have an update, and the
setting that turns it off."""

from __future__ import annotations

import unittest
from unittest import mock

from common.settings import config_service
from manager import rail_marks, update_count
from manager.kit.data import Library
from manager.library import discovery_list, discovery_marks


class ShownTests(unittest.TestCase):
    def test_it_is_on_unless_the_setting_says_otherwise(self) -> None:
        self.assertTrue(update_count.shown({}))
        self.assertTrue(update_count.shown({"updates": {}}))
        self.assertTrue(update_count.shown({"updates": {"show_update_count": True}}))
        self.assertTrue(update_count.shown({"updates": {"show_update_count": "true"}}))

    def test_the_setting_is_a_switch_on_by_default_and_on_the_discovery_page(self) -> None:
        [section] = [one for one in config_service.schema()["sections"]
                     if one["name"] == "updates"]
        [option] = [one for one in section["options"] if one["key"] == "show_update_count"]

        self.assertEqual(("bool", "true", "library.discovery"),
                         (option["type"], option["default"], option["home"]))

    def test_a_false_turns_it_off_however_it_was_written(self) -> None:
        for off in (False, "false", "False", "0", "off"):
            with self.subTest(off=off):
                self.assertFalse(update_count.shown({"updates": {"show_update_count": off}}))


class WaitingTests(unittest.TestCase):
    def client(self, shown: object, count: int) -> mock.Mock:
        client = mock.Mock()
        client.config_values.return_value = {"updates": {"show_update_count": shown}}
        client.discovery_updates.return_value = {"count": count, "game_ids": [], "games": []}
        return client

    def test_it_is_the_number_of_games_with_an_update(self) -> None:
        self.assertEqual((True, 3), update_count.waiting(self.client(True, 3)))

    def test_it_asks_nothing_of_the_library_while_the_count_is_off(self) -> None:
        client = self.client(False, 3)

        self.assertEqual((False, 0), update_count.waiting(client))
        client.discovery_updates.assert_not_called()


class CountTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.warm: dict[str, rail_marks.Mark] = {}
        self.painted = mock.Mock()
        self.read = mock.Mock(return_value=(True, 3))
        self.count = update_count.Count(self.warm, self.painted, self.read)

    async def test_the_games_with_an_update_are_the_number_on_the_entry(self) -> None:
        await self.count.recount()

        self.assertEqual(3, self.warm[update_count.KEY].count)
        self.painted.assert_called_once()

    async def test_turning_the_setting_off_takes_the_number_off(self) -> None:
        await self.count.recount()
        self.read.return_value = (False, 0)

        await self.count.recount()

        self.assertEqual({}, self.warm)

    async def test_nothing_is_counted_while_the_setting_is_off(self) -> None:
        self.read.return_value = (False, 0)
        await self.count.recount()

        self.count.from_home(5)

        self.assertEqual({}, self.warm)

    async def test_home_sets_the_number_while_the_setting_is_on(self) -> None:
        self.count.from_home(5)

        self.assertEqual(5, self.warm[update_count.KEY].count)
        self.read.assert_not_called()

    async def test_none_left_takes_the_number_off(self) -> None:
        self.count.from_home(2)

        self.count.from_home(0)

        self.assertEqual({}, self.warm)

    async def test_the_entry_is_drawn_again_only_when_the_number_changed(self) -> None:
        self.count.from_home(2)
        self.count.from_home(2)

        self.painted.assert_called_once()

    async def test_a_count_that_cannot_be_read_leaves_the_entry_as_it_was(self) -> None:
        self.count.from_home(2)
        self.read.side_effect = RuntimeError("down")

        await self.count.recount()

        self.assertEqual(2, self.warm[update_count.KEY].count)


class RedrawCountsTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_redraw_by_a_mark_reads_the_count_after_it(self) -> None:
        order: list[str] = []
        counting = mock.Mock(recount=mock.AsyncMock(side_effect=lambda: order.append("count")))

        async def redraw() -> None:
            order.append("redraw")

        await discovery_marks.recounting({"update_count": counting}, redraw)()

        self.assertEqual(["redraw", "count"], order)

    async def test_a_page_with_no_count_redraws_alone(self) -> None:
        redraw = mock.AsyncMock()

        await discovery_marks.recounting({}, redraw)()

        redraw.assert_awaited_once()


class TieCountsTests(unittest.TestCase):
    def library(self) -> tuple[Library, mock.Mock]:
        client = mock.Mock()
        library = Library(client)
        library.after_tie = told = mock.Mock()
        return library, told

    def test_tying_a_table_again_says_so(self) -> None:
        library, told = self.library()

        library.set_table_source("g", "t", "f1")

        told.assert_called_once_with()

    def test_tying_a_file_again_says_so(self) -> None:
        library, told = self.library()

        library.set_asset_source("g", "a.directb2s", "f1")

        told.assert_called_once_with()

    def test_a_library_nobody_watches_ties_alone(self) -> None:
        Library(mock.Mock()).set_table_source("g", "t", "f1")

    def test_one_game_asked_about_is_read_for_that_game_and_kept_by_it(self) -> None:
        client = mock.Mock()
        client.discovery_updates.return_value = {"count": 1, "game_ids": ["g"], "games": [
            {"game_id": "g", "moves": [{"release_id": "f1", "now": "1.2"}]}]}
        library = Library(client)

        moves = library.load_updates("g")

        client.discovery_updates.assert_called_once_with("g")
        self.assertEqual(moves, library.update_moves("g"))
        self.assertEqual([], library.update_moves("other"))


class PaneRowTests(unittest.TestCase):
    MOVES = [{"release_id": "f1", "now": "1.2"}]

    def newer(self, held: dict[str, str], game_id: str = "game-1") -> str:
        library = mock.Mock()
        library.update_moves.return_value = self.MOVES
        return discovery_list._newer({"library": library}, mock.Mock(game_id=game_id), held)

    def test_a_held_file_tied_to_a_release_that_moved_says_the_version(self) -> None:
        self.assertEqual("1.2", self.newer({"vps_file_id": "f1"}))

    def test_a_file_tied_to_another_release_says_nothing(self) -> None:
        self.assertEqual("", self.newer({"vps_file_id": "f2"}))

    def test_a_file_tied_to_nothing_says_nothing(self) -> None:
        self.assertEqual("", self.newer({"name": "x.vpx"}))

    def test_a_pane_for_an_entry_no_game_holds_says_nothing(self) -> None:
        self.assertEqual("", self.newer({"vps_file_id": "f1"}, game_id=""))


if __name__ == "__main__":
    unittest.main()
