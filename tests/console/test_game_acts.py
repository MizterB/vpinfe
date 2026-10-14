"""A game's and a table's verbs: one list, drawn in the grid's row menu, the panel's header
menu and the grid's selection menu, so the three cannot offer different things."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import MagicMock, patch

from nicegui import ui

from console import game_acts, panel

_PAGE = ui.element()


def _table(table_id: str, game_id: str = "afm", **fields: Any) -> dict[str, Any]:
    return {"id": table_id, "game_id": game_id, "available": True, "filename": f"{table_id}.vpx",
            **fields}


async def _after(_games: list[str], _gone: bool) -> None:
    return None


async def _refresh(_ids: list[str]) -> None:
    return None


def _game(game_id: str = "afm", **fields: Any) -> dict[str, Any]:
    return {"id": game_id, "name": "Attack from Mars", **fields}


def _library(*games: dict[str, Any]) -> MagicMock:
    library = MagicMock()
    library.games = list(games)
    return library


def _labels(verbs: list[panel.Verb]) -> list[str]:
    return [one.label for one in verbs]


def _acts(table: dict[str, Any], *tables: dict[str, Any], collections: Any = None,
          library: Any = None) -> list[panel.Verb]:
    return game_acts.table_acts(
        library or MagicMock(),
        [game_acts.Target(table["game_id"], "Attack from Mars", table, list(tables) or [table])],
        _after, {}, collections)


def _several(*tables: dict[str, Any], library: Any = None) -> list[panel.Verb]:
    return game_acts.table_acts(
        library or MagicMock(),
        [game_acts.Target(one["game_id"], "Attack from Mars", one, list(tables))
         for one in tables], _after, {}, None)


class ForAGame(unittest.TestCase):
    def test_it_can_be_played_and_filed(self) -> None:
        verbs = game_acts.game_acts(_library(), [_game()], {}, _refresh,
                                    collections=lambda _: None)

        self.assertEqual(["Launch", "Mark Private", "Match to VPS...", "Auto-Match",
                          "Get Missing Media...", "Send to Device...", "Back Up Now",
                          "Add to Collection", "Delete from Disk"], _labels(verbs))

    def test_it_is_filed_only_once_the_collections_are_read(self) -> None:
        verbs = game_acts.game_acts(_library(), [_game()], {}, _refresh)

        self.assertNotIn("Add to Collection", _labels(verbs))

    def test_launching_is_for_one_game(self) -> None:
        verbs = game_acts.game_acts(_library(), [_game(), _game("medusa")], {}, _refresh)

        self.assertTrue(next(one for one in verbs if one.label == "Launch").one)

    def test_rating_is_offered_where_the_caller_can_write_one(self) -> None:
        async def rate(_ids: list[str], _value: int) -> bool:
            return True

        rated = game_acts.game_acts(_library(), [_game()], {}, _refresh, rate=rate)
        unrated = game_acts.game_acts(_library(), [_game()], {}, _refresh)

        self.assertEqual("Rate...", _labels(rated)[1])
        self.assertNotIn("Rate...", _labels(unrated))

    def test_private_is_offered_for_the_games_it_applies_to(self) -> None:
        plain = game_acts.game_acts(_library(), [_game()], {}, _refresh)
        marked = game_acts.game_acts(_library(), [_game(private=True)], {}, _refresh)
        mixed = game_acts.game_acts(_library(), [_game(private=True), _game("medusa")], {},
                                    _refresh)

        self.assertIn("Mark Private", _labels(plain))
        self.assertNotIn("Mark Not Private", _labels(plain))
        self.assertIn("Mark Not Private", _labels(marked))
        self.assertNotIn("Mark Private", _labels(marked))
        self.assertIn("Mark Private", _labels(mixed))
        self.assertIn("Mark Not Private", _labels(mixed))

    def test_sending_asks_where_for_these_games_with_the_pages_state(self) -> None:
        state: dict[str, Any] = {"watch_jobs": lambda: None}
        games = [_game()]
        verbs = game_acts.game_acts(_library(), games, state, _refresh)
        send = next(one for one in verbs if one.label == "Send to Device...")

        with patch.object(game_acts.send_to_device, "ask_where") as ask:
            send.run()

        ask.assert_called_once_with(games, state)

    def test_the_play_record_can_be_reset_only_where_there_is_one(self) -> None:
        played = _library({"id": "afm", "user": {"play_count": 3}})
        unplayed = _library({"id": "afm", "user": {"play_count": 0, "last_played": None}})

        offered = game_acts.game_acts(played, [_game()], {}, _refresh)
        quiet = game_acts.game_acts(unplayed, [_game()], {}, _refresh)

        self.assertTrue(next(one for one in offered if one.label == "Reset Play Record").danger)
        self.assertNotIn("Reset Play Record", _labels(quiet))

    def test_deleting_from_disk_is_a_danger_offered_for_any_games(self) -> None:
        for chosen in ([_game()], [_game(), _game("medusa")]):
            with self.subTest(count=len(chosen)):
                verbs = game_acts.game_acts(_library(), chosen, {}, _refresh)

                self.assertTrue(next(one for one in verbs
                                     if one.label == "Delete from Disk").danger)

    def test_a_single_game_is_named_in_the_match_walk_and_several_are_not(self) -> None:
        self.assertEqual("Attack from Mars", game_acts._only_name([_game()]))
        self.assertEqual("", game_acts._only_name([_game(), _game("medusa")]))


class ForATable(unittest.TestCase):
    def test_the_games_own_record_is_cleared_apart_from_the_tables(self) -> None:
        played = _library({"id": "afm", "user": {"play_count": 3}})

        verb = game_acts.reset_games(played, ["afm"], _refresh, "Reset game's play record")

        self.assertEqual("Reset game's play record", verb.label if verb else "")
        self.assertIsNone(game_acts.reset_games(_library({"id": "afm"}), ["afm"], _refresh))

    def test_a_table_that_is_not_the_default_can_be_made_it(self) -> None:
        verbs = _acts(_table("a"), _table("a"), _table("b", default=True))

        self.assertEqual(["Make Default", "Hide", "Extract Script"], _labels(verbs))

    def test_the_default_of_several_can_be_locked_and_not_made_the_default(self) -> None:
        one = _table("a", default=True)
        verbs = _acts(one, one, _table("b"))

        self.assertNotIn("Make Default", _labels(verbs))
        self.assertEqual(["Hide", "Extract Script"], _labels(verbs)[1:])
        self.assertEqual(3, len(verbs))

    def test_a_hidden_table_offers_to_unhide_and_cannot_be_made_the_default(self) -> None:
        verbs = _acts(_table("a", hidden=True))

        self.assertEqual(["Unhide", "Extract Script"], _labels(verbs))

    def test_a_missing_table_can_be_forgotten_as_a_danger(self) -> None:
        verbs = _acts(_table("a", available=False, absent_since="2026-10-01"),
                      collections=lambda _: None)

        self.assertEqual("Forget", verbs[-1].label)
        self.assertTrue(verbs[-1].danger)
        self.assertEqual("Add to Collection", verbs[-2].label)

    def test_the_play_record_can_be_reset_only_where_there_is_one(self) -> None:
        played = _acts(_table("a", user={"last_played": "2026-10-01T20:00:00Z"}))
        unplayed = _acts(_table("a", user={"play_count": 0}))

        self.assertIn("Reset Play Record", _labels(played))
        self.assertTrue(next(one for one in played
                             if one.label == "Reset Play Record").danger)
        self.assertNotIn("Reset Play Record", _labels(unplayed))

    def test_the_games_record_is_reset_beside_the_tables(self) -> None:
        verbs = _acts(_table("a"), library=_library({"id": "afm", "user": {"play_count": 2}}))

        self.assertEqual("Reset game's play record", verbs[-1].label)
        self.assertTrue(verbs[-1].danger)

    def test_a_table_on_disk_cannot_be_forgotten(self) -> None:
        self.assertFalse([one for one in _acts(_table("a")) if one.danger])

    def test_a_table_running_its_own_script_can_delete_it(self) -> None:
        own = _table("a", assets={"script": {"file": "a.vbs", "resolution": "sidecar"}})
        verbs = _acts(own)

        self.assertIn("Delete Script", _labels(verbs))
        self.assertNotIn("Extract Script", _labels(verbs))
        self.assertTrue(next(one for one in verbs if one.label == "Delete Script").danger)


class HidingSeveralTables(unittest.IsolatedAsyncioTestCase):
    async def test_hiding_offers_undo_that_unhides_each_table_it_hid(self) -> None:
        library = MagicMock()
        offers: list[Any] = []

        async def inline(call, *args):
            return call(*args)

        shown = _table("a")
        already = _table("b", hidden=True)
        with patch.object(game_acts.run, "io_bound", inline), \
                patch.object(game_acts.undo, "offer", lambda *args, **_kw: offers.append(args)), \
                patch.object(game_acts.ui, "notify"):
            verbs = _several(shown, already, library=library)
            hide = next(one for one in verbs if one.label == "Hide")
            with _PAGE:
                await hide.run()
                library.set_table_hidden.assert_called_once_with("afm", "a", True)
                await offers[0][1]()

        self.assertEqual([("afm", "a", True), ("afm", "a", False)],
                         [call.args for call in library.set_table_hidden.call_args_list])


class DeletingGamesFromDisk(unittest.IsolatedAsyncioTestCase):
    async def run_it(self, answer: bool, library: Any, games: list[dict[str, Any]],
                     refreshed: list[list[str]]) -> list[Any]:
        asked: list[Any] = []

        async def inline(call, *args):
            return call(*args)

        async def said(*args, **kwargs):
            asked.append(kwargs)
            return answer

        async def refresh(ids: list[str]) -> None:
            refreshed.append(ids)

        with patch.object(game_acts.run, "io_bound", inline), \
                patch.object(game_acts.confirm, "ask", said), \
                patch.object(game_acts.ui, "notify"):
            verb = game_acts.delete_games(library, games, refresh)
            with _PAGE:
                await verb.run()
        return asked

    async def test_a_no_deletes_nothing(self) -> None:
        library, refreshed = MagicMock(), []

        await self.run_it(False, library, [_game()], refreshed)

        library.delete_game_folder.assert_not_called()
        self.assertEqual([], refreshed)

    async def test_the_question_names_each_folder(self) -> None:
        games = [_game(folder="/tables/Attack"), _game("medusa", folder="/tables/Medusa")]

        asked = await self.run_it(False, MagicMock(), games, [])

        self.assertEqual(["/tables/Attack", "/tables/Medusa"], list(asked[0]["lines"]))

    async def test_a_yes_deletes_each_and_puts_the_page_right(self) -> None:
        library, refreshed = MagicMock(), []

        await self.run_it(True, library, [_game(), _game("medusa")], refreshed)

        self.assertEqual([("afm",), ("medusa",)],
                         [call.args for call in library.delete_game_folder.call_args_list])
        self.assertEqual([["afm", "medusa"]], refreshed)

    async def test_a_failure_part_way_puts_right_what_was_deleted(self) -> None:
        library, refreshed = MagicMock(), []
        library.delete_game_folder.side_effect = [None, RuntimeError("busy")]

        await self.run_it(True, library, [_game(), _game("medusa")], refreshed)

        self.assertEqual([["afm"]], refreshed)


class ForSeveralTables(unittest.TestCase):
    def test_nothing_chosen_offers_nothing(self) -> None:
        self.assertEqual([], game_acts.table_acts(MagicMock(), [], _after, {}, None))

    def test_a_verb_shows_when_it_applies_to_any_of_them(self) -> None:
        verbs = _several(_table("a", hidden=True), _table("b", "medusa"))

        self.assertIn("Hide", _labels(verbs))
        self.assertIn("Unhide", _labels(verbs))

    def test_making_a_default_is_for_one_table_and_says_so(self) -> None:
        verbs = panel.for_selection(_several(_table("a"), _table("b", "medusa")), 2)

        make = next(one for one in verbs if one.label == "Make Default")
        self.assertIsNone(make.run)
        self.assertEqual("One at a time", make.hint)

    def test_forgetting_is_one_verb_for_one_table_or_many(self) -> None:
        gone = {"available": False, "absent_since": "2026-10-01"}
        one = _acts(_table("a", **gone))
        many = _several(_table("a", **gone), _table("b", "medusa", **gone))

        self.assertEqual(["Forget"], [v.label for v in one if v.danger])
        self.assertEqual(["Forget"], [v.label for v in many if v.danger])


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
