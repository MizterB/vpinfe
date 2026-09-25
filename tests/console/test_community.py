"""Community: the lists extensions declare, drawn by core."""

from __future__ import annotations

import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

from common import install_identity
from console import community, page, views
from console.api import ApiError
from console.data import read_state

DECLARED = {"key": "tables", "title": "Site", "base": "/community/tables",
            "columns": [{"field": "name", "header": "Table", "kind": "text",
                         "under": ["maker", "year"]},
                        {"field": "plays", "header": "Plays", "kind": "number"},
                        {"field": "last", "header": "Last", "kind": "date"},
                        {"field": "vps_id", "header": "VPS", "kind": "text"}],
            "views": [{"key": "plays", "name": "Most played", "columns": ["name", "plays"],
                       "sort": [{"field": "plays", "desc": True}], "help": ""}],
            "relation": {"field": "vps_id", "keys": "vps_entry"}}
LOADED = {"name": "site", "state": "loaded", "community": [DECLARED]}


class TheNav(unittest.TestCase):
    def test_a_running_extension_s_list_sits_under_community(self) -> None:
        items = community.nav_items([LOADED, {**LOADED, "name": "off", "state": "failed"}],
                                    install_identity.CORE)
        groups = dict(page.nav_for(None, items))

        self.assertEqual(["community:site:tables"],
                         [one[0] for one in groups[page.NAV_COMMUNITY]])

    def test_community_sits_between_frontend_and_system(self) -> None:
        parents = [parent for parent, _items in page.NAV_GROUPS]

        self.assertEqual([page.NAV_FRONTEND, page.NAV_COMMUNITY, page.NAV_SYSTEM],
                         parents[-3:])

    def test_with_no_list_there_is_no_community(self) -> None:
        self.assertNotIn(page.NAV_COMMUNITY, dict(page.nav_for(None)))

    def test_a_view_finds_its_list(self) -> None:
        self.assertEqual((LOADED, DECLARED),
                         community.find("community:site:tables", [LOADED]))


class RankedOrders(unittest.TestCase):
    RANKED = {**DECLARED, "views": [{**DECLARED["views"][0], "ranks": True},
                                    {"key": "all", "name": "All", "columns": ["name"],
                                     "sort": [], "help": ""}]}

    def test_each_ranked_view_is_named_for_its_page_and_itself(self) -> None:
        offered = community.ranked_orders([{**LOADED, "community": [self.RANKED]},
                                           {**LOADED, "name": "off", "state": "failed",
                                            "community": [self.RANKED]}])

        self.assertEqual({"site/tables/plays": "Site: Most played"}, offered)

    def test_a_list_that_relates_to_nothing_offers_no_order(self) -> None:
        loose = {**self.RANKED, "relation": None}

        self.assertEqual({}, community.ranked_orders([{**LOADED, "community": [loose]}]))

    def test_a_stored_order_no_running_extension_offers_names_the_extension(self) -> None:
        self.assertEqual("Site, not running",
                         community.ranked_label({"extension": "site", "display_name": "Site",
                                                 "offered": False}))


class TheGrid(unittest.TestCase):
    def test_the_first_column_is_scanned_by_and_in_library_follows(self) -> None:
        shown = community.columns(DECLARED)

        self.assertEqual(["name", "plays", "last", "vps_id", community.HELD],
                         [one["field"] for one in shown])
        self.assertIn("console-cell-identifier", shown[0]["cellClass"])
        self.assertEqual("numericColumn", shown[1]["type"])

    def test_a_view_keeps_its_sort_and_yours_keeps_only_what_is_held(self) -> None:
        presets = community.presets(DECLARED)

        self.assertEqual(({"colId": "plays", "sort": "desc", "sortIndex": 0},),
                         presets["plays"].sort)
        self.assertEqual({community.HELD: {"values": [True]}},
                         presets["console.community.yours"].filters)

    def test_a_view_is_kept_by_its_key_and_shown_by_the_name_it_was_sent(self) -> None:
        (plays, _yours) = views.builtins(community.presets(DECLARED))

        self.assertEqual((views.builtin_id("plays"), "Most played"), (plays.id, plays.name))

    def test_a_held_row_links_its_name_to_the_game(self) -> None:
        rows = community.rows([{"name": "AFM", "vps_id": "vps-afm", "last": ""},
                               {"name": "TAF", "vps_id": "vps-taf", "last": ""}], DECLARED,
                              {"vps-afm": {"game_id": "afm", "table_id": "",
                                           "name": "Attack from Mars"}})

        self.assertEqual([(True, "/console?view=games&game=afm"), (False, "")],
                         [(one[community.HELD], one["held_href"]) for one in rows])
        self.assertIn("last_ago", rows[0])

    def test_a_held_release_links_to_its_table(self) -> None:
        released = {**DECLARED, "relation": {"field": "vps_id", "keys": "vps_release"}}
        (row,) = community.rows([{"name": "AFM", "vps_id": "rel-1", "last": ""}], released,
                                {"rel-1": {"game_id": "afm", "table_id": "t1", "name": "AFM"}})

        self.assertEqual("/console?view=tables&game=afm&table=t1", row["held_href"])

    def test_another_version_says_which_and_links_to_the_release(self) -> None:
        released = {**DECLARED, "relation": {"field": "vps_id", "keys": "vps_release"}}
        (row,) = community.rows(
            [{"name": "AFM", "maker": "Bally", "vps_id": "rel-2", "last": ""}], released, {},
            {"rel-2": {"game_id": "afm", "table_id": "t1", "name": "AFM", "version": "1.2",
                       "url": "https://example.test/afm"}})

        self.assertEqual((False, "https://example.test/afm"),
                         (row[community.HELD], row["held_href"]))
        self.assertEqual("Bally · Different version - you have 1.2", row[community.UNDER])

    def test_the_fields_under_the_name_make_its_second_line(self) -> None:
        (row,) = community.rows([{"name": "AFM", "maker": "Bally", "year": 1995,
                                  "vps_id": "", "last": ""}], DECLARED, {})

        self.assertEqual("Bally 1995", row[community.UNDER])

    def test_in_library_is_not_a_column_of_any_view(self) -> None:
        for name, preset in community.presets(DECLARED).items():
            with self.subTest(view=name):
                self.assertNotIn(community.HELD, preset.columns)


def _answering(*rows: dict) -> Callable[[], dict]:
    return lambda: {"rows": list(rows)}


def _down() -> dict:
    raise ApiError("https://site.example did not answer")


class TheLastGoodRead(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.kept = Path(folder.name)
        kept = patch("common.paths.COMMUNITY_KEPT_DIR", self.kept)
        kept.start()
        self.addCleanup(kept.stop)

    def test_a_fresh_read_is_kept_and_said_to_be_now(self) -> None:
        said = community.read("site", "tables", _answering({"name": "AFM"}))

        self.assertEqual(([{"name": "AFM"}], False, ""),
                         (said["rows"], said["stale"], said["error"]))
        self.assertEqual(["AFM"], [one["name"] for one in
                                   community.kept("site", "tables")["rows"]])
        self.assertTrue(said["read_at"])

    def test_an_outage_answers_with_the_last_good_list_said_to_be_stale(self) -> None:
        good = community.read("site", "tables", _answering({"name": "AFM"}))

        said = community.read("site", "tables", _down)

        self.assertEqual(([{"name": "AFM"}], True, good["read_at"]),
                         (said["rows"], said["stale"], said["read_at"]))
        self.assertIn("did not answer", said["error"])
        self.assertIn("Last good read", read_state(said))

    def test_an_outage_with_nothing_kept_has_no_list_to_show(self) -> None:
        said = community.read("site", "tables", _down)

        self.assertEqual((None, True), (said["rows"], said["stale"]))
        self.assertIsNone(community.kept("site", "tables")["rows"])

    def test_with_nothing_kept_the_answer_is_still_an_answer(self) -> None:
        """The page reads it through `offload.io`, which takes None for a shutdown."""
        self.assertEqual({"rows": None, "read_at": "", "stale": False, "error": ""},
                         community.kept("site", "tables"))

    def test_a_later_good_read_replaces_the_kept_one(self) -> None:
        community.read("site", "tables", _answering({"name": "AFM"}))
        community.read("site", "tables", _answering({"name": "TAF"}, {"name": "MM"}))

        self.assertEqual(["TAF", "MM"], [one["name"] for one in
                                         community.kept("site", "tables")["rows"]])

    def test_each_list_is_kept_apart_whatever_its_key_holds(self) -> None:
        community.read("site", "tables", _answering({"name": "AFM"}))
        community.read("site", "../tables", _answering({"name": "TAF"}))

        self.assertEqual((["AFM"], ["TAF"]),
                         tuple([one["name"] for one in community.kept("site", key)["rows"]]
                               for key in ("tables", "../tables")))
        self.assertEqual(["site"], [one.name for one in self.kept.iterdir()])


if __name__ == "__main__":
    unittest.main()
