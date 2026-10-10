"""The rows of Needs You: which draw, in what order, counting what, and opening what.

The rows are decided by `needs.collect`, apart from the page, so this runs without one.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from common import feature_checks
from common.jobs import DONE, FAILED
from console import games, needs


class FakeLibrary:
    def __init__(self, games_=(), tables=(), watched=None, hidden=(), unreadable=(),
                 collected=("playfield", "backglass")):
        self.games = list(games_)
        self.media = {g["id"]: g.get("media", {}) for g in self.games}
        self._tables = list(tables)
        self._watched = watched or {}
        self._hidden = set(hidden)
        self._unreadable = list(unreadable)
        self._collected = set(collected)

    def table_rows(self):
        return self._tables

    def hidden_checks(self):
        return self._hidden

    def kept_kinds(self):
        return {"media": self._collected}

    def watched(self):
        return self._watched

    def metadata_state(self):
        return {"unreadable": self._unreadable}


def game(game_id, **rest):
    return {"id": game_id, "name": game_id, "year": "1992", "vps_id": "v", **rest}


def present(*kinds):
    return {"media": {kind: {"present": True} for kind in kinds}}


def table(game_id, **rest):
    return {"id": f"t-{game_id}", "game_id": game_id, "rom": "afm", **rest}


def keys(rows):
    return [one.key for one in rows]


class DrawsOnlyWhatHasSomethingToSay(unittest.TestCase):
    def test_a_clean_library_has_no_rows(self):
        lib = FakeLibrary([game("g1", **present("playfield", "backglass"))])
        self.assertEqual([], needs.collect(lib, {}))

    def test_a_check_the_library_turned_off_does_not_draw(self):
        lib = FakeLibrary([game("g1", year="", **present("playfield", "backglass"))],
                          hidden=["no_year"])
        self.assertEqual([], needs.collect(lib, {}))

    def test_a_kind_nobody_collects_is_not_a_row(self):
        lib = FakeLibrary([game("g1", **present("playfield"))], collected=("playfield",))
        self.assertEqual([], needs.collect(lib, {}))


class CountsKeepTheirOwnUnit(unittest.TestCase):
    def test_a_missing_rom_counts_tables_and_a_game_without_art_counts_games(self):
        lib = FakeLibrary(
            [game("g1"), game("g2", **present("playfield", "backglass"))],
            [table("g1", rom_installed=False), table("g1", rom_installed=False),
             table("g2", rom_installed=True)])
        rows = {one.key: one for one in needs.collect(lib, {})}

        self.assertEqual(2, rows["rom_missing"].count)
        self.assertEqual("2 tables", rows["rom_missing"].counted())
        self.assertEqual("1 game", rows["no_playfield"].counted())

    def test_the_same_game_is_counted_by_each_row_that_names_it(self):
        lib = FakeLibrary([game("g1", year="")])
        rows = {one.key: one for one in needs.collect(lib, {})}
        self.assertEqual(("g1",), rows["no_year"].ids)
        self.assertEqual(("g1",), rows["no_media"].ids)

    def test_an_unknown_rom_is_not_missing(self):
        lib = FakeLibrary([game("g1", **present("playfield", "backglass"))],
                          [table("g1", rom_installed=None)])
        self.assertEqual([], needs.collect(lib, {}))


class OrderedByCost(unittest.TestCase):
    def test_cannot_play_then_missing_then_ready_then_tidy(self):
        update = {"update_available": True, "latest_version": "9.9.9", "update_supported": True}
        lib = FakeLibrary(
            [game("g1", year="", vps_id="")],
            [table("g1", rom_installed=False, update_available=True)],
            watched={"update": update, "recordings": ["r1"]},
            unreadable=[{"folder": "x"}])
        trouble = [SimpleNamespace(where=feature_checks.WHERE_LAUNCHERS)]

        order = keys(needs.collect(lib, {"trouble": trouble}))

        self.assertEqual(["rom_missing", "launchers", "unreadable", "unmatched",
                          "no_playfield", "no_backglass", "no_media", "update", "newer",
                          "recordings", "no_year"], order)

    def test_the_tones_follow_the_cost(self):
        lib = FakeLibrary([game("g1", year="", vps_id="")], [table("g1", rom_installed=False)])
        tones = {one.key: one.tone for one in needs.collect(lib, {})}
        self.assertEqual(needs.DANGER, tones["rom_missing"])
        self.assertEqual(needs.WARM, tones["unmatched"])
        self.assertEqual(needs.MUTED, tones["no_year"])


class WhereAClickLands(unittest.TestCase):
    def test_each_grid_row_opens_its_grid_on_what_it_counted(self):
        update = {"update_available": False}
        lib = FakeLibrary([game("g1", year="", vps_id="")],
                          [table("g1", rom_installed=False, update_available=True)],
                          watched={"update": update})
        rows = {one.key: one.opens for one in needs.collect(lib, {})}

        self.assertEqual(("tables", games.ROM_MISSING),
                         (rows["rom_missing"].view, rows["rom_missing"].arriving))
        self.assertEqual(("tables", games.NEWER_ON_VPS),
                         (rows["newer"].view, rows["newer"].arriving))
        self.assertEqual(("games", games.UNMATCHED),
                         (rows["unmatched"].view, rows["unmatched"].arriving))
        self.assertEqual({"media_playfield": {"values": [""]}}, rows["no_playfield"].arriving)

    def test_no_media_needs_every_collected_kind_blank(self):
        lib = FakeLibrary([game("g1")])
        rows = {one.key: one.opens for one in needs.collect(lib, {})}
        self.assertEqual({"media_backglass": {"values": [""]},
                          "media_playfield": {"values": [""]}}, rows["no_media"].arriving)

    def test_the_rows_that_are_not_a_grid_say_what_they_do_instead(self):
        lib = FakeLibrary(watched={"recordings": ["r1"]}, unreadable=[{"folder": "x"}])
        rows = {one.key: one.opens for one in needs.collect(lib, {})}
        self.assertEqual(needs.METADATA, rows["unreadable"].then)
        self.assertEqual(needs.REVIEW, rows["recordings"].then)


class WhatVPinFECanDoItself(unittest.TestCase):
    def test_art_that_is_missing_can_be_fetched(self):
        lib = FakeLibrary([game("g1", **present("backglass"))])
        row = next(one for one in needs.collect(lib, {}) if one.key == "no_playfield")
        self.assertEqual((needs.GET_MEDIA, "playfield"), (row.fix.key, row.fix.kind))

    def test_an_update_is_offered_only_where_this_build_can_take_it(self):
        def row(supported):
            update = {"update_available": True, "latest_version": "3.0.2",
                      "update_supported": supported}
            lib = FakeLibrary(watched={"update": update})
            return needs.collect(lib, {})[0]

        self.assertEqual("VPinFE 3.0.2 Is Out", row(True).label)
        self.assertIsNotNone(row(True).fix)
        self.assertIsNone(row(False).fix)

    def test_a_failed_check_for_an_update_is_not_an_update(self):
        lib = FakeLibrary(watched={"update": {"update_available": True, "error": "offline"}})
        self.assertEqual([], needs.collect(lib, {}))


class MediaFill(unittest.TestCase):
    def _fill(self, state, problems=0, stopped=False):
        return {"kind": "library.media_fill", "state": state, "problems": problems,
                "stopped": stopped, "title": "Get media"}

    def test_a_fill_that_ended_with_errors_is_a_row_that_opens_that_run(self):
        lib = FakeLibrary(watched={"fill": self._fill(DONE, problems=2)})
        row = needs.collect(lib, {})[0]
        self.assertEqual("fill_errors", row.key)
        self.assertEqual("jobs", row.opens.view)
        self.assertEqual("Get media", row.opens.keys["jobs_find"])

    def test_a_failed_fill_is_one_too(self):
        lib = FakeLibrary(watched={"fill": self._fill(FAILED)})
        self.assertEqual(["fill_errors"], keys(needs.collect(lib, {})))

    def test_a_clean_fill_is_not(self):
        lib = FakeLibrary(watched={"fill": self._fill(DONE)})
        self.assertEqual([], needs.collect(lib, {}))


if __name__ == "__main__":
    unittest.main()
