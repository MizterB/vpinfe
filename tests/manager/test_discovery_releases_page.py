"""Discovery's Releases tab: the rows a question becomes, and which tab a page is on."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import patch

from common.online import vps_question
from manager.kit import views, when
from manager.library import discovery, discovery_releases

PEOPLE = [{"name": "Guet35", "aliases": [], "releases": 2},
          {"name": "VPW", "aliases": [], "releases": 1}]


def _release(release_id: str, **over: Any) -> dict[str, Any]:
    return {"id": release_id, "by": [0], "mod": False, "features": [], "format": "VPX",
            "version": "1.0", "added": "2025-10-13T00:00:00Z", "held": False, **over}


GAMES = {
    "g1": {"id": "g1", "name": "Alpha", "said": "Bally 1990", "manufacturer": "Bally",
           "themes": [], "listed": ["tableFiles", "b2sFiles"], "is_in_library": True,
           "img": "http://x/a.png"},
    "g2": {"id": "g2", "name": "Beta", "said": "Williams 1992", "manufacturer": "Williams",
           "themes": [], "listed": ["tableFiles"], "is_in_library": False},
    "g3": {"id": "g3", "name": "Gamma", "said": "", "manufacturer": "", "themes": [],
           "listed": [], "is_in_library": False},
}
RELEASES = {
    "g1": {"tableFiles": [_release("t1", by=[0, 1], version="2.0", held=True, mod=True,
                                   features=["VR", "MOD"]),
                          _release("t2", version="")],
           "b2sFiles": [_release("b1", format="")]},
    "g2": {"tableFiles": [_release("t3", by=[1])]},
}


def _rows(question: dict[str, Any], *, counted: bool = True) -> list[dict[str, Any]]:
    found = vps_question.games_found(question, PEOPLE, list(GAMES.values()), RELEASES)
    return discovery_releases.rows(found, GAMES, PEOPLE, counted=counted)


class Rows(unittest.TestCase):
    def test_a_release_is_a_row_and_a_game_with_two_is_two_rows(self) -> None:
        rows = _rows({"kind": "tableFiles"})

        self.assertEqual(["g1:t1", "g1:t2", "g2:t3"], [one["id"] for one in rows])

    def test_a_game_with_no_release_has_no_row(self) -> None:
        self.assertNotIn("g3", {one["game_id"] for one in _rows({})})

    def test_the_row_carries_the_games_name_and_line_and_the_releases_own_facts(self) -> None:
        row = _rows({"kind": "tableFiles"})[0]

        self.assertEqual(("Alpha", "Bally 1990", "tableFiles", "2.0", "Guet35, VPW"),
                         (row["name"], row["said"], row["kind"], row["version"],
                          row["authors"]))
        self.assertEqual(("2025-10-13T00:00:00Z", "VPX", "VR, MOD", "mod"),
                         (row["added"], row["format"], row["features"], row["mod"]))

    def test_a_release_with_no_version_or_format_reads_blank(self) -> None:
        rows = {one["id"]: one for one in _rows({})}

        self.assertEqual("", rows["g1:t2"]["version"])
        self.assertEqual("", rows["g1:b1"]["format"])
        self.assertEqual("", rows["g1:t2"]["mod"])

    def test_the_question_leaves_out_the_releases_that_do_not_fit(self) -> None:
        rows = _rows({"kind": "tableFiles", "by": ["VPW"]})

        self.assertEqual(["g1:t1", "g2:t3"], [one["id"] for one in rows])

    def test_a_held_release_reads_have_once_the_library_has_been_counted(self) -> None:
        held = {one["id"]: one["held"] for one in _rows({"kind": "tableFiles"})}
        before = {one["held"] for one in _rows({"kind": "tableFiles"}, counted=False)}

        self.assertEqual({"g1:t1": "have", "g1:t2": "", "g2:t3": ""}, held)
        self.assertEqual({""}, before)

    def test_the_search_text_carries_the_games_type_and_themes(self) -> None:
        games = {"g1": {**GAMES["g1"], "game_type": "Solid State", "themes": ["Space", "Movie"]}}
        found = {"g1": [("tableFiles", _release("t1"))]}

        row = discovery_releases.rows(found, games, PEOPLE, counted=True)[0]

        self.assertEqual("Solid State Space Movie", row["find"])

    def test_old_releases_added_on_one_date_say_it_in_one_call(self) -> None:
        found = {"g1": [("tableFiles", _release("a", added="2020-03-04T01:00:00Z")),
                        ("tableFiles", _release("b", added="2020-03-04T01:00:09Z"))]}

        with patch.object(when, "ago", wraps=when.ago) as ago:
            said = [one["added_said"] for one
                    in discovery_releases.rows(found, GAMES, PEOPLE, counted=True)]

        self.assertEqual(1, ago.call_count)
        self.assertEqual(said[0], said[1])
        self.assertNotEqual("", said[0])

    def test_a_game_the_rows_do_not_know_is_not_a_row(self) -> None:
        found = {"gone": [("tableFiles", _release("x"))]}

        self.assertEqual([], discovery_releases.rows(found, GAMES, PEOPLE, counted=True))


def _everything() -> views.Preset:
    view = discovery_releases.VIEWS["manager.view.everything"]
    assert isinstance(view, views.Preset)
    return view


class Columns(unittest.TestCase):
    def test_every_column_a_view_shows_is_one_the_grid_has(self) -> None:
        fields = {one["field"] for one in discovery_releases.columns({"tableFiles": "word.table"})}

        self.assertTrue(set(_everything().columns) <= fields)

    def test_the_default_order_is_newest_added_first(self) -> None:
        sort = _everything().sort[0]

        self.assertEqual(("added", "desc"), (sort["colId"], sort["sort"]))

    def test_the_kind_column_filters_by_the_kinds_the_library_collects(self) -> None:
        kind = next(one for one in discovery_releases.columns(
            {"tableFiles": "word.table", "b2sFiles": "asset.kind.backglass.label"})
            if one["field"] == "kind")

        self.assertEqual(["tableFiles", "b2sFiles"],
                         [one["value"] for one in kind["filterParams"]["choices"]])


class Tab(unittest.TestCase):
    def test_a_page_opens_on_games_unless_releases_was_chosen(self) -> None:
        self.assertEqual(discovery.BROWSE, discovery.tab_of({}))
        self.assertEqual(discovery.RELEASES,
                         discovery.tab_of({"discovery_tab": discovery.RELEASES}))

    def test_a_subject_page_is_a_games_page_whatever_tab_was_chosen(self) -> None:
        state = {"discovery_tab": discovery.RELEASES,
                 "subject": {"type": "author", "name": "Guet35"}}

        self.assertEqual(discovery.BROWSE, discovery.tab_of(state))


class Summary(unittest.TestCase):
    def test_it_counts_releases(self) -> None:
        self.assertEqual("1 release", discovery_releases.summary(1))
        self.assertEqual("37 releases", discovery_releases.summary(37))


if __name__ == "__main__":
    unittest.main()
