"""A ranked view of a Community list: the order it puts what it relates to in, and the
read that keeps that order current."""

from __future__ import annotations

import unittest

from common import events
from common.games import community_lists, rankings
from tests.extensions.test_derived_tags import DerivedTagCase

LISTING = {"columns": [{"field": "id", "kind": "text"},
                       {"field": "rating", "kind": "number"},
                       {"field": "ratings", "kind": "number"},
                       {"field": "year", "kind": "number"},
                       {"field": "played", "kind": "date"}],
           "relation": {"field": "id", "keys": "vps_entry"}}
TOP_RATED = {"key": "top", "ranks": True,
             "sort": [{"field": "rating", "desc": True}, {"field": "ratings", "desc": True}]}


def _ranked(rows: list[dict], view: dict = TOP_RATED) -> list[tuple[str, int]]:
    return sorted(rankings.ranks(rows, LISTING, view).items(), key=lambda one: one[1])


class TheOrder(unittest.TestCase):
    def test_each_field_sorts_in_its_own_direction(self) -> None:
        view = {"sort": [{"field": "rating", "desc": True}, {"field": "year"}]}

        self.assertEqual([("b", 1), ("a", 2), ("c", 3)],
                         _ranked([{"id": "a", "rating": 8, "year": 1995},
                                  {"id": "b", "rating": 8, "year": 1992},
                                  {"id": "c", "rating": 7, "year": 1980}], view))

    def test_a_row_with_no_number_ranks_nowhere(self) -> None:
        self.assertEqual([("a", 1)],
                         _ranked([{"id": "a", "rating": 7.5, "ratings": 3},
                                  {"id": "b", "rating": None, "ratings": 9},
                                  {"id": "c", "ratings": 4}]))

    def test_a_missing_later_field_sorts_after_one_that_has_it(self) -> None:
        self.assertEqual([("a", 1), ("b", 2)],
                         _ranked([{"id": "b", "rating": 8}, {"id": "a", "rating": 8,
                                                             "ratings": 1}]))

    def test_rows_that_sort_the_same_share_a_rank(self) -> None:
        self.assertEqual([("a", 1), ("b", 1), ("c", 2)],
                         _ranked([{"id": "a", "rating": 8, "ratings": 2},
                                  {"id": "b", "rating": 8, "ratings": 2},
                                  {"id": "c", "rating": 6, "ratings": 9}]))

    def test_an_id_on_several_rows_takes_its_best(self) -> None:
        """A leaderboard lists a machine once for every score on it."""
        self.assertEqual([("a", 1), ("b", 2)],
                         _ranked([{"id": "b", "rating": 9}, {"id": "a", "rating": 5},
                                  {"id": "a", "rating": 9.5}]))

    def test_dates_rank_newest_first_when_the_view_says_so(self) -> None:
        view = {"sort": [{"field": "played", "desc": True}]}

        self.assertEqual([("new", 1), ("old", 2)],
                         _ranked([{"id": "old", "played": "2026-01-02T10:00:00Z"},
                                  {"id": "new", "played": "2026-09-20T10:00:00Z"},
                                  {"id": "never", "played": ""}], view))

    def test_a_list_that_relates_to_nothing_ranks_nothing(self) -> None:
        self.assertEqual([], rankings.views_of({"views": [TOP_RATED]}))


class TheRead(DerivedTagCase):
    def told(self) -> list[dict]:
        heard: list[dict] = []

        def hear(**payload) -> None:
            heard.append(payload)

        events.subscribe(events.COLLECTIONS_CHANGED, hear)
        self.addCleanup(events.unsubscribe, events.COLLECTIONS_CHANGED, hear)
        return heard

    def test_a_ranked_list_is_kept_by_the_same_read_as_the_tags(self) -> None:
        self.week(ratings="afm-entry=8.1,mm-entry=")
        self.read()

        said = community_lists.kept("challenge", "ratings")
        self.assertEqual(["afm-entry", "mm-entry"], [one["vps_id"] for one in said["rows"]])
        self.assertTrue(said["read_at"])

    def test_a_read_that_moves_the_order_tells_the_cabinet(self) -> None:
        heard = self.told()
        self.week(ratings="afm-entry=8.1,mm-entry=7.9")
        self.read()
        self.week(ratings="afm-entry=8.1,mm-entry=8.4")

        self.assertTrue(self.read())
        self.assertEqual(2, len(heard))

    def test_new_numbers_in_the_same_order_tell_nobody(self) -> None:
        self.week(ratings="afm-entry=8.1,mm-entry=7.9")
        self.read()
        heard = self.told()
        self.week(ratings="afm-entry=8.3,mm-entry=7.2")

        self.assertFalse(self.read())
        self.assertEqual([], heard)

    def test_a_failed_read_keeps_the_last_good_list(self) -> None:
        self.week(ratings="afm-entry=8.1")
        self.read()
        self.week(ratings="mm-entry=9", fail=True)
        self.read()

        self.assertEqual(["afm-entry"], [one["vps_id"] for one in
                                         community_lists.kept("challenge", "ratings")["rows"]])

    def test_a_stopped_extension_s_lists_are_not_read(self) -> None:
        self.registry.disable("challenge", "switched off")

        self.assertEqual([], community_lists.reading())

    def test_the_community_page_s_own_read_moves_the_order_too(self) -> None:
        community_lists.keep("challenge", "ratings",
                             [{"vps_id": "afm-entry", "rating": 8.0}])
        heard = self.told()

        community_lists.keep("challenge", "ratings",
                             [{"vps_id": "afm-entry", "rating": 8.0},
                              {"vps_id": "mm-entry", "rating": 9.0}])

        self.assertEqual(1, len(heard))


if __name__ == "__main__":
    unittest.main()
