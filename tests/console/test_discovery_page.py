"""The Discovery page: what a catalog entry becomes as a row, and what can be done to one."""

from __future__ import annotations

import unittest
from unittest import mock

from console import deeplink, discovery, page
from console.data import Library


def _entry(vps_id: str = "v1", **over) -> dict:
    return {"vps_id": vps_id, "name": "Attack from Mars", "manufacturer": "Bally",
            "year": 1995, "type": "SS", "themes": ["Space"], "url": "https://vps/v1",
            "listed": ["tableFiles", "b2sFiles", "romFiles"], "in_library": True,
            "held": ["tableFiles", "b2sFiles"], **over}


def _found(*entries: dict, counted: str = "2026-10-01T10:00:00Z") -> dict:
    return {"counted": counted, "rows": list(entries)}


def _cells(row: dict) -> dict:
    return {field: row[field] for _listed, field, _word in discovery.KINDS}


class Rows(unittest.TestCase):
    def test_a_kind_held_reads_have_and_a_kind_listed_but_not_held_reads_missing(self) -> None:
        cells = _cells(discovery.rows(_found(_entry()))[0])

        self.assertEqual(("have", "have", "missing"),
                         (cells["kind_table"], cells["kind_backglass"], cells["kind_rom"]))

    def test_a_kind_the_entry_does_not_list_is_blank(self) -> None:
        cells = _cells(discovery.rows(_found(_entry()))[0])

        self.assertEqual("", cells["kind_pov"])
        self.assertEqual("", cells["kind_topper"])

    def test_a_game_not_in_the_library_is_missing_on_every_kind_it_lists(self) -> None:
        row = discovery.rows(_found(_entry(in_library=False, held=[])))[0]

        cells = _cells(row)
        self.assertEqual("no", row["in_library"])
        self.assertEqual({"missing"}, {cells["kind_table"], cells["kind_backglass"],
                                       cells["kind_rom"]})
        self.assertEqual("", cells["kind_pov"])

    def test_nothing_is_said_while_the_library_has_never_been_counted(self) -> None:
        row = discovery.rows(_found(_entry(in_library=None, held=[]), counted=""))[0]

        self.assertEqual("", row["in_library"])
        self.assertEqual({""}, set(_cells(row).values()))
        self.assertEqual("", row["gap"])

    def test_the_gap_column_says_missing_only_where_something_is(self) -> None:
        complete = _entry("a", listed=["tableFiles"], held=["tableFiles"])
        short = _entry("b")

        gaps = {row["id"]: row["gap"] for row in discovery.rows(_found(complete, short))}

        self.assertEqual({"a": "", "b": "missing"}, gaps)

    def test_the_id_is_the_entry_the_row_stands_for(self) -> None:
        self.assertEqual("v9", discovery.rows(_found(_entry("v9")))[0]["id"])


class Unnamed(unittest.TestCase):
    def test_an_entry_with_no_name_is_not_a_row(self) -> None:
        shown = discovery.rows(_found(_entry("a"), _entry("b", name=""), _entry("c", name="  ")))

        self.assertEqual(["a"], [row["id"] for row in shown])


class Summary(unittest.TestCase):
    def test_a_counted_library_says_how_many_of_them_it_holds(self) -> None:
        shown = discovery.rows(_found(_entry("a"), _entry("b", in_library=False, held=[])))

        self.assertEqual("2 games, 1 in your library", discovery.summary(shown, True))

    def test_an_uncounted_one_says_only_how_many_games_there_are(self) -> None:
        shown = discovery.rows(_found(_entry(in_library=None), counted=""))

        self.assertEqual("1 game", discovery.summary(shown, False))


class Acts(unittest.TestCase):
    def test_add_is_offered_for_a_game_not_in_the_library(self) -> None:
        row = discovery.rows(_found(_entry(in_library=False, held=[])))[0]

        (add,) = discovery.acts(mock.Mock(spec=Library), [row], mock.AsyncMock())

        self.assertIsNotNone(add.run)

    def test_add_is_refused_with_a_reason_where_every_game_is_already_in(self) -> None:
        row = discovery.rows(_found(_entry()))[0]

        (add,) = discovery.acts(mock.Mock(spec=Library), [row], mock.AsyncMock())

        self.assertIsNone(add.run)
        self.assertTrue(add.hint)


    def test_add_waits_for_a_count_and_says_so(self) -> None:
        row = discovery.rows(_found(_entry(in_library=None, held=[]), counted=""))[0]

        (add,) = discovery.acts(mock.Mock(spec=Library), [row], mock.AsyncMock())

        self.assertIsNone(add.run)
        self.assertEqual("Count the library first", add.hint)


class Address(unittest.TestCase):
    def test_the_entry_is_named_in_the_address_on_this_page_only(self) -> None:
        on_page = deeplink.query({"view": "discovery", "entry": "v1"})
        elsewhere = deeplink.query({"view": "games", "entry": "v1"})

        self.assertIn("entry=v1", on_page)
        self.assertNotIn("entry", elsewhere)


class Leaving(unittest.TestCase):
    def test_the_entry_panel_section_does_not_follow_the_user_to_another_page(self) -> None:
        state = {"view": "discovery", "section": "discovery_files", "entry": "v1", "game": "",
                 "table": ""}

        with mock.patch.object(page.remembered, "put"):
            page.leave_for(state, "games")

        self.assertNotIn("section", state)
        self.assertIsNone(state["entry"])


if __name__ == "__main__":
    unittest.main()
