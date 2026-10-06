"""A game's and a table's verbs: one list, drawn in the grid's row menu and in the panel's
header menu, so the two cannot offer different things."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import MagicMock

from nicegui import ui

from console import game_acts, panel

_PAGE = ui.element()


def _table(table_id: str, **fields: Any) -> dict[str, Any]:
    return {"id": table_id, "game_id": "afm", "available": True, "filename": f"{table_id}.vpx",
            **fields}


async def _after(_gone: bool) -> None:
    return None


async def _after_game() -> None:
    return None


def _library(*games: dict[str, Any]) -> MagicMock:
    library = MagicMock()
    library.games = list(games)
    return library


def _labels(verbs: list[panel.Verb]) -> list[str]:
    return [one.label for one in verbs]


def _acts(table: dict[str, Any], *tables: dict[str, Any], collections: Any = None,
          ) -> list[panel.Verb]:
    return game_acts.table_acts(MagicMock(), "afm", "Attack from Mars", table,
                                list(tables) or [table], _after, collections)


class ForAGame(unittest.TestCase):
    def test_it_can_be_played_and_filed(self) -> None:
        verbs = game_acts.game_acts(_library(), "afm", "Attack from Mars", lambda _: None,
                                    _after_game)

        self.assertEqual(["Launch", "Add to Collection", "Back up now"], _labels(verbs))

    def test_it_is_only_played_before_the_collections_are_read(self) -> None:
        verbs = game_acts.game_acts(_library(), "afm", "Attack from Mars", None, _after_game)

        self.assertEqual(["Launch", "Back up now"], _labels(verbs))

    def test_the_play_record_can_be_reset_only_where_there_is_one(self) -> None:
        played = _library({"id": "afm", "user": {"play_count": 3}})
        unplayed = _library({"id": "afm", "user": {"play_count": 0, "last_played": None}})

        offered = game_acts.game_acts(played, "afm", "Attack from Mars", None, _after_game)
        quiet = game_acts.game_acts(unplayed, "afm", "Attack from Mars", None, _after_game)

        self.assertEqual(["Launch", "Back up now", "Reset play record"], _labels(offered))
        self.assertTrue(offered[-1].danger)
        self.assertEqual(["Launch", "Back up now"], _labels(quiet))


class ForATable(unittest.TestCase):
    def test_the_games_own_record_is_cleared_apart_from_the_tables(self) -> None:
        played = _library({"id": "afm", "user": {"play_count": 3}})

        verb = game_acts.reset_game(played, "afm", _after_game, "Reset game's play record")

        self.assertEqual("Reset game's play record", verb.label if verb else "")
        self.assertIsNone(game_acts.reset_game(_library({"id": "afm"}), "afm", _after_game))

    def test_a_table_that_is_not_the_default_can_be_made_it(self) -> None:
        verbs = _acts(_table("a"), _table("a"), _table("b", default=True))

        self.assertEqual(["Make default", "Hide", "Extract script"], _labels(verbs))

    def test_the_default_of_several_can_be_locked_and_not_made_the_default(self) -> None:
        one = _table("a", default=True)
        verbs = _acts(one, one, _table("b"))

        self.assertNotIn("Make default", _labels(verbs))
        self.assertEqual(["Hide", "Extract script"], _labels(verbs)[1:])
        self.assertEqual(3, len(verbs))

    def test_a_hidden_table_offers_to_unhide_and_cannot_be_made_the_default(self) -> None:
        verbs = _acts(_table("a", hidden=True))

        self.assertEqual(["Unhide", "Extract script"], _labels(verbs))

    def test_a_missing_table_can_be_forgotten_as_a_danger(self) -> None:
        verbs = _acts(_table("a", available=False, absent_since="2026-10-01"),
                      collections=lambda _: None)

        self.assertEqual("Forget this table", verbs[-2].label)
        self.assertTrue(verbs[-2].danger)
        self.assertEqual("Add to Collection", verbs[-1].label)

    def test_the_play_record_can_be_reset_only_where_there_is_one(self) -> None:
        played = _acts(_table("a", user={"last_played": "2026-10-01T20:00:00Z"}))
        unplayed = _acts(_table("a", user={"play_count": 0}))

        self.assertIn("Reset play record", _labels(played))
        self.assertTrue(next(one for one in played
                             if one.label == "Reset play record").danger)
        self.assertNotIn("Reset play record", _labels(unplayed))

    def test_a_table_on_disk_cannot_be_forgotten(self) -> None:
        self.assertFalse([one for one in _acts(_table("a")) if one.danger])

    def test_a_table_running_its_own_script_can_delete_it(self) -> None:
        own = _table("a", assets={"script": {"file": "a.vbs", "resolution": "sidecar"}})
        verbs = _acts(own)

        self.assertIn("Delete script", _labels(verbs))
        self.assertNotIn("Extract script", _labels(verbs))
        self.assertTrue(next(one for one in verbs if one.label == "Delete script").danger)


class DrawnIntoAMenu(unittest.TestCase):
    def test_an_entry_that_draws_its_own_is_given_what_closes_the_menu(self) -> None:
        given: list[Any] = []

        def draw(close: Any) -> None:
            given.append(close)

        def shut() -> None:
            return None

        with _PAGE, ui.menu():
            panel.verb_entries([panel.Verb("Rate", lambda: None),
                                panel.Verb("Collections", draw=draw)], shut)

        self.assertEqual([shut], given)


if __name__ == "__main__":
    unittest.main()
