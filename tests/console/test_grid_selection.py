"""What a grid's checkboxes select, and what a bulk action reads back."""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from typing import Any

from common.i18n import t
from console import grid, stars
from console.games import add_index, row_transaction


class SelectAll(unittest.TestCase):

    def test_the_header_checkbox_takes_only_the_rows_on_screen(self):
        self.assertEqual(grid.ROW_SELECTION["selectAll"], "filtered")

    def test_a_cell_click_leaves_the_checkboxes_alone(self):
        self.assertFalse(grid.ROW_SELECTION["enableClickSelection"])


def _part(turn: int, at: int, of: int, *ids: str) -> dict:
    return {"turn": turn, "at": at, "of": of, "ids": list(ids)}


class _Grid:
    def run_grid_method(self, *_: object) -> None:
        pass


class PartsTests(unittest.TestCase):
    """The ids arrive in parts, each well under the socket's cap."""

    def setUp(self) -> None:
        self.chosen = grid.Selection([{"id": n} for n in "abcde"])

    def test_parts_in_any_order_come_back_in_the_order_picked(self) -> None:
        self.assertFalse(self.chosen.take(_part(1, 1, 2, "c", "a")))
        self.assertTrue(self.chosen.take(_part(1, 0, 2, "e", "b")))

        self.assertEqual([row["id"] for row in self.chosen.rows()], ["e", "b", "c", "a"])

    def test_a_part_of_an_older_turn_is_dropped(self) -> None:
        self.chosen.take(_part(1, 0, 2, "a"))
        self.assertTrue(self.chosen.take(_part(2, 0, 1, "b")))
        self.assertFalse(self.chosen.take(_part(1, 1, 2, "c")))

        self.assertEqual(self.chosen.ids, ["b"])

    def test_clearing_is_one_empty_part(self) -> None:
        self.chosen.take(_part(1, 0, 1, "a", "b"))
        self.assertTrue(self.chosen.take(_part(2, 0, 1)))

        self.assertEqual(self.chosen.rows(), [])

    def test_a_malformed_part_changes_nothing(self) -> None:
        self.chosen.take(_part(1, 0, 1, "a"))
        junks: tuple[object, ...] = (None, [], {"turn": 3},
                                     {"turn": "3", "at": 0, "of": 1, "ids": []},
                                     {"turn": 3, "at": 0, "of": 1, "ids": "a"})
        for junk in junks:
            self.assertFalse(self.chosen.take(junk))

        self.assertEqual(self.chosen.ids, ["a"])

    def test_a_grid_without_a_selection_has_none(self) -> None:
        self.assertEqual(grid.selection(_Grid()), [])


class HiddenTests(unittest.TestCase):
    """A tick a search hides stays selected, and the bar counts it apart."""

    def setUp(self) -> None:
        self.table = _Grid()
        self.chosen = grid._SELECTIONS[self.table] = grid.Selection(
            [{"id": n} for n in "abcde"])

    def test_a_complete_turn_says_how_many_are_hidden(self) -> None:
        self.chosen.take({**_part(1, 0, 2, "a", "b"), "hidden": 1})
        self.assertEqual(grid.hidden_count(self.table), 0)

        self.chosen.take({**_part(1, 1, 2, "c"), "hidden": 1})
        self.assertEqual(grid.hidden_count(self.table), 1)

    def test_hidden_ticks_are_still_acted_on(self) -> None:
        self.chosen.take({**_part(1, 0, 1, "a", "b", "c"), "hidden": 2})

        self.assertEqual([row["id"] for row in grid.selection(self.table)], ["a", "b", "c"])

    def test_a_search_changes_the_count_without_a_new_selection(self) -> None:
        self.chosen.take({**_part(1, 0, 1, "a", "b"), "hidden": 0})

        self.assertTrue(self.chosen.hide({"hidden": 2}))
        self.assertFalse(self.chosen.hide({"hidden": 2}))
        self.assertEqual(self.chosen.ids, ["a", "b"])

    def test_a_malformed_count_changes_nothing(self) -> None:
        self.chosen.hide({"hidden": 1})
        junks: tuple[object, ...] = (None, [], {}, {"hidden": -1}, {"hidden": "2"})
        for junk in junks:
            self.assertFalse(self.chosen.hide(junk))

        self.assertEqual(self.chosen.hidden, 1)

    def test_the_bar_says_plain_while_nothing_is_hidden(self) -> None:
        self.assertEqual(grid.selection_said(self.table, 3, "3 of 9"), "3 of 9")

    def test_the_bar_says_how_many_are_hidden(self) -> None:
        self.chosen.hide({"hidden": 2})

        self.assertEqual(grid.selection_said(self.table, 5, "5 of 3"),
                         t("console.grid.selected_hidden", count=5, hidden=2))

    def test_a_grid_without_a_selection_hides_none(self) -> None:
        self.assertEqual(grid.hidden_count(_Grid()), 0)


class ReadAtActionTimeTests(unittest.TestCase):
    """Every way a grid's rows change, and a ticked row read back after it."""

    def _ticked(self, held: list[dict], *ids: str) -> grid.Selection:
        chosen = grid.Selection(held)
        chosen.take(_part(1, 0, 1, *ids))
        return chosen

    def test_an_edited_row_resolves_to_its_current_values(self) -> None:
        held = [{"id": "g1", "name": "Old"}, {"id": "g2", "name": "Two"}]
        chosen = self._ticked(held, "g1", "g2")

        grid.transact(_Grid(), held, {"update": [{"id": "g1", "name": "New"}]})

        self.assertEqual([row["name"] for row in chosen.rows()], ["New", "Two"])

    def test_a_removed_row_is_not_acted_on(self) -> None:
        held = [{"id": "g1"}, {"id": "g2"}]
        chosen = self._ticked(held, "g1", "g2")

        grid.transact(_Grid(), held, {"remove": [{"id": "g1"}]})

        self.assertEqual(chosen.rows(), [{"id": "g2"}])

    def test_a_table_refreshed_with_its_game_resolves_as_refreshed(self) -> None:
        held: list[dict[str, Any]] = [{"id": "t1", "game_id": "g", "hidden": False},
                                      {"id": "t9", "game_id": "h", "hidden": False}]
        chosen = self._ticked(held, "t1", "t9")
        fresh = [{"id": "t1", "game_id": "g", "hidden": True}]

        transaction = row_transaction({str(row["id"]): row for row in held}, "g", fresh)
        add_index(held, "g", transaction)
        grid.transact(_Grid(), held, transaction)

        self.assertEqual([row["hidden"] for row in chosen.rows()], [True, False])

    def test_a_rated_row_resolves_with_its_rating(self) -> None:
        held = [{"id": "g1", "rating": 0}]
        chosen = self._ticked(held, "g1")

        class _Client:
            def rate(self, game_id: str, value: int) -> None:
                pass

        rate = stars.rating_handler(held, {"g1": held[0]}, _Grid, _Client)
        asyncio.run(rate(SimpleNamespace(args={"game": "g1", "value": 5})))

        self.assertEqual(chosen.rows()[0]["rating"], 5)

    def test_a_game_s_files_replaced_resolve_as_replaced(self) -> None:
        held = [{"id": "a:1", "game_id": "a", "kind": "old"}, {"id": "b:1", "game_id": "b"}]
        chosen = self._ticked(held, "a:1", "b:1")

        grid.replace_rows(_Grid(), held, {}, [{"id": "a:1", "game_id": "a", "kind": "new"}],
                          lambda row: row["game_id"] == "a")

        self.assertEqual([row.get("kind") for row in chosen.rows()], ["new", None])


if __name__ == "__main__":
    unittest.main()
