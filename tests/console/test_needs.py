"""The rows of Needs You: which draw, in what order, counting what, and opening what.

The rows are decided by `needs.collect`, apart from the page, so this runs without one.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from common import feature_checks
from common.i18n import t
from common.jobs import DONE, FAILED
from console import games, needs
from console.data import Library


class FakeLibrary:
    def __init__(self, games_=(), tables=(), watched=None, hidden=(), unreadable=(),
                 collected=("playfield", "backglass"), patches=None, fixed=()):
        self.games = list(games_)
        self.media = {g["id"]: g.get("media", {}) for g in self.games}
        self._tables = list(tables)
        self._watched = watched or {}
        self._hidden = set(hidden)
        self._unreadable = list(unreadable)
        self._collected = set(collected)
        self._patches = {"reachable": True, "offered": []} if patches is None else patches
        self._fixed = tuple(fixed)

    def script_patches(self):
        return self._patches

    def script_fix_tables(self):
        return self._fixed

    def table_rows(self):
        return self._tables

    def hidden_checks(self):
        return self._hidden

    def stopped(self):
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
            unreadable=[{"folder": "x"}], fixed=("t-g1",))
        trouble = [SimpleNamespace(where=feature_checks.WHERE_LAUNCHERS)]

        order = keys(needs.collect(lib, {"trouble": trouble}))

        self.assertEqual(["rom_missing", "launchers", "unreadable", "unmatched",
                          "no_playfield", "no_backglass", "no_media", "update", "newer",
                          "script_fixes", "recordings", "no_year"], order)

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
        self.assertEqual(("settings", {"settings_page": needs.METADATA_PAGE}),
                         (rows["unreadable"].view, dict(rows["unreadable"].keys)))
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


class AReadThatFailedIsSaid(unittest.TestCase):
    def test_a_page_that_could_not_look_never_says_nothing_needs_you(self):
        lib = FakeLibrary(watched={"unread": ["recordings", "fill"]})
        rows = needs.collect(lib, {})
        self.assertEqual(["unread"], keys(rows))
        self.assertEqual(needs.RETRY, rows[0].opens.then)
        self.assertIn("the recordings waiting", rows[0].tip)
        self.assertIn("the last media fill", rows[0].tip)
        self.assertNotIn("update", rows[0].tip)

    def test_each_read_that_fails_is_named_and_the_others_still_count(self):
        def refuse():
            raise OSError("down")

        client = SimpleNamespace(update_check=lambda: {"error": "offline"},
                                 capture_proposals=lambda: {"proposals": [{"id": "r1"}]},
                                 jobs=lambda limit: refuse(),
                                 extension_needs=lambda: {"needs": []})
        library = Library.__new__(Library)
        library._client = client

        read = library._read_watched()

        self.assertEqual(["update", "fill"], read["unread"])
        self.assertEqual(["r1"], read["recordings"])

    def test_it_comes_last_and_only_when_a_read_failed(self):
        lib = FakeLibrary([game("g1", year="")], watched={"unread": ["update"]})
        self.assertEqual("unread", keys(needs.collect(lib, {}))[-1])
        self.assertNotIn("unread", keys(needs.collect(FakeLibrary([game("g1", year="")]), {})))


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


def bare(key, ids=(), token=()):
    return needs.Need(key, key, "", needs.WARM, "x", needs.Opens(), tuple(ids),
                      "console.games.games", token=tuple(token))


class SettingAsideOverWhatItCounted(unittest.TestCase):
    def test_a_row_stays_away_while_every_id_it_counts_is_in_the_record(self):
        arranged = needs.arrange([bare("unmatched", ["a", "b"])], {"unmatched": ["a", "b"]},
                                 set())
        self.assertEqual([], arranged.rows)
        self.assertEqual(["unmatched"], [one.key for one in arranged.aside])
        self.assertEqual({"unmatched": ["a", "b"]}, arranged.record)

    def test_a_row_with_nothing_recorded_draws_whole(self):
        arranged = needs.arrange([bare("unmatched", ["a"])], {}, set())
        self.assertEqual(["unmatched"], keys(arranged.rows))
        self.assertEqual((), arranged.rows[0].new)

    def test_a_joiner_brings_it_back_with_the_true_total_and_the_new_marked(self):
        arranged = needs.arrange([bare("unmatched", ["a", "b", "c"])],
                                 {"unmatched": ["a", "b"]}, set())
        self.assertEqual(3, arranged.rows[0].count)
        self.assertEqual(("c",), arranged.rows[0].new)
        self.assertEqual([], arranged.aside)

    def test_what_the_row_no_longer_counts_leaves_the_record(self):
        arranged = needs.arrange([bare("unmatched", ["a", "c"])], {"unmatched": ["a", "b"]},
                                 set())
        self.assertEqual({"unmatched": ["a"]}, arranged.record)

    def test_a_row_whose_old_ids_are_all_gone_is_a_different_finding_and_unmarked(self):
        arranged = needs.arrange([bare("unmatched", ["c"])], {"unmatched": ["a"]}, set())
        self.assertEqual((), arranged.rows[0].new)
        self.assertEqual({}, arranged.record)

    def test_a_row_not_checked_keeps_its_record_but_an_absent_one_keeps_nothing(self):
        record = {"unmatched": ["a"], "no_year": ["b"]}
        arranged = needs.arrange([], record, {"no_year"})
        self.assertEqual({"no_year": ["b"]}, arranged.record)

    def test_a_read_that_failed_keeps_its_record(self):
        arranged = needs.arrange([], {"update": ["3.1"], "unmatched": ["a"]}, set(),
                                 ["update"])
        self.assertEqual({"update": ["3.1"]}, arranged.record)

    def test_a_blind_row_keeps_its_record(self):
        arranged = needs.arrange([], {"rom_missing": ["t-a"], "unmatched": ["a"]}, set(), (),
                                 {"rom_missing"})
        self.assertEqual({"rom_missing": ["t-a"]}, arranged.record)

    def test_a_row_with_no_ids_is_dismissed_over_its_token(self):
        row = bare("update", token=["3.1"])
        self.assertEqual([], needs.arrange([row], {"update": ["3.1"]}, set()).rows)
        self.assertEqual(["update"], keys(needs.arrange([row], {"update": ["3.0"]}, set()).rows))

    def test_the_unread_row_is_never_set_aside(self):
        row = needs.Need("unread", "x", "", needs.MUTED, "x", needs.Opens(then=needs.RETRY))
        self.assertEqual(["unread"], keys(needs.arrange([row], {"unread": ["x"]}, set()).rows))

    def test_a_stopped_check_is_set_aside_as_not_checked(self):
        arranged = needs.arrange([], {}, {"no_year", "recordings"})
        self.assertEqual(["recordings", "no_year"], [one.key for one in arranged.aside])
        self.assertTrue(all(one.stopped for one in arranged.aside))

    def test_an_update_dismissal_says_skipped(self):
        arranged = needs.arrange([bare("update", token=["3.1"])], {"update": ["3.1"]}, set())
        self.assertEqual("Skipped", arranged.aside[0].chip)


class WhereAStopIsKept(unittest.TestCase):
    def test_a_device_row_is_this_installs_and_a_library_row_the_librarys(self):
        self.assertTrue(all(needs.is_device(key) for key in
                            ("launchers", "fill_errors", "update", "recordings")))
        self.assertFalse(any(needs.is_device(key) for key in
                             ("rom_missing", "unreadable", "unmatched", "newer", "no_year")))

    def test_the_unread_row_cannot_be_set_aside(self):
        self.assertFalse(needs.can_set_aside("unread"))
        self.assertTrue(all(needs.can_set_aside(key) for key in needs.ORDER))

    def test_no_vpx_and_no_catalog_leave_the_rom_and_newer_rows_blind(self):
        library = FakeLibrary(tables=[table("a", rom_installed=None, update_available=None)])
        self.assertEqual({"rom_missing", "newer"}, needs.blind(library))

    def test_script_fixes_are_blind_until_somebody_has_checked(self):
        library = FakeLibrary(tables=[table("a", rom_installed=True, update_available=False)],
                              patches={})
        self.assertEqual({"script_fixes"}, needs.blind(library))

    def test_script_fixes_are_blind_when_the_index_could_not_be_reached(self):
        library = FakeLibrary(tables=[table("a", rom_installed=True, update_available=False)],
                              patches={"reachable": False, "offered": []})
        self.assertEqual({"script_fixes"}, needs.blind(library))

    def test_a_row_the_library_can_count_is_not_blind(self):
        library = FakeLibrary(tables=[table("a", rom_installed=True, update_available=False)])
        self.assertEqual(set(), needs.blind(library))

    def test_a_kind_the_library_does_not_collect_leaves_its_row_blind(self):
        library = FakeLibrary(tables=[table("a", rom_installed=True, update_available=False)],
                              collected=("backglass",))
        self.assertEqual({"no_playfield"}, needs.blind(library))

    def test_every_row_that_can_be_set_aside_has_a_name_and_a_line_on_when_it_returns(self):
        for key in needs.ORDER:
            self.assertTrue(needs.name_of(key), key)
            self.assertTrue(needs.comes_back(key), key)


class StoppingOneRowKeepsTheOthers(unittest.TestCase):
    def setUp(self) -> None:
        self.client = Mock()
        self.client.library_policy.return_value = {"hidden_checks": ["no_year"]}
        self.client.console_policy.return_value = {"hidden_overview": ["recordings"]}
        self.client.put_library_policy.return_value = {}
        self.library = Library(self.client)

    def test_a_library_row_is_added_to_what_the_server_holds_not_to_what_the_page_held(self):
        self.library.set_checking("unmatched", False, device=False)
        self.client.put_library_policy.assert_called_once_with(
            {"hidden_checks": ["no_year", "unmatched"]})

    def test_a_device_row_is_added_to_what_the_server_holds(self):
        self.library.set_checking("update", False, device=True)
        self.client.put_console_policy.assert_called_once_with(
            {"hidden_overview": ["recordings", "update"]})

    def test_checking_again_takes_only_that_row_out(self):
        self.library.set_checking("recordings", True, device=True)
        self.client.put_console_policy.assert_called_once_with({"hidden_overview": []})

    def test_a_policy_that_cannot_be_read_writes_nothing(self):
        self.client.library_policy.side_effect = OSError("refused")
        with self.assertRaises(OSError):
            self.library.set_checking("unmatched", False, device=False)
        self.client.put_library_policy.assert_not_called()


class TableScriptFixes(unittest.TestCase):
    def test_the_row_counts_tables_and_opens_the_grid_on_them_with_fetch_at_its_end(self):
        lib = FakeLibrary(patches={"reachable": True, "offered": ["Sample Game"]},
                          fixed=("t-g2", "t-g1"))
        [row] = [one for one in needs.collect(lib, {}) if one.key == "script_fixes"]

        self.assertEqual(needs.ACCENT, row.tone)
        self.assertEqual("2 tables", row.counted())
        self.assertEqual("tables", row.opens.view)
        self.assertEqual({games.FIXES_KEY: ("t-g2", "t-g1")}, dict(row.opens.keys))
        self.assertEqual(needs.FETCH_FIXES, row.fix.key)

    def test_no_row_draws_before_anybody_has_checked(self):
        lib = FakeLibrary(patches={})
        self.assertNotIn("script_fixes", keys(needs.collect(lib, {})))

    def test_the_stamp_marks_only_the_tables_with_a_fix(self):
        built = [{"id": "t-a"}, {"id": "t-b"}]
        stamped = games.stamp_fixes(built, {"t-a"})
        self.assertEqual([[games.fixes_label()], []], [r[games.FIXES_COLUMN] for r in stamped])
        self.assertNotIn(games.FIXES_COLUMN, built[0])

    def test_the_column_is_offered_on_any_visit_to_the_tables_grid(self):
        self.assertIn(games.FIXES_COLUMN, [c["field"] for c in games.TABLE_COLUMNS])

    def test_nothing_is_stamped_without_a_fix_list(self):
        built = [{"id": "t-a"}]
        self.assertIs(built, games.stamp_fixes(built, None))


class WhichTablesTheIndexNamed(unittest.TestCase):
    def test_the_default_table_of_each_named_folder_is_the_one_counted(self):
        library = Library.__new__(Library)
        library._script_patches = {"offered": ["Sample Game (Original 2024)"]}
        library.games = [{"id": "g1", "folder": "/lib/Sample Game (Original 2024)"},
                         {"id": "g2", "folder": "/lib/Other"}]
        library._table_rows = [
            {"id": "t1", "game_id": "g1", "default": True},
            {"id": "t2", "game_id": "g1", "default": False},
            {"id": "t3", "game_id": "g2", "default": True}]

        self.assertEqual(("t1",), library.script_fix_tables())

    def test_a_folder_given_with_backslashes_is_still_matched_by_its_name(self):
        library = Library.__new__(Library)
        library._script_patches = {"offered": ["Sample Game"]}
        library.games = [{"id": "g1", "folder": "C:\\vpx\\Sample Game"}]
        library._table_rows = [{"id": "t1", "game_id": "g1", "default": True}]

        self.assertEqual(("t1",), library.script_fix_tables())

    def test_nothing_offered_names_no_table(self):
        library = Library.__new__(Library)
        library._script_patches = {"reachable": True, "offered": []}
        library.games, library._table_rows = [], []
        self.assertEqual((), library.script_fix_tables())


RAISED = {"extension": "site", "display_name": "Site", "kind": "share_down",
          "key": "ext:site:share_down", "label": "3 plays are down", "says": "Not sent",
          "tone": "warm", "opens": "list", "to": "plays", "count": 3,
          "covered": ["a", "b", "c"]}


class WhatExtensionsAskFor(unittest.TestCase):
    def test_a_row_is_drawn_after_core_s_with_the_extension_named(self):
        lib = FakeLibrary([game("g1", year="", **present("playfield", "backglass"))],
                          watched={"extension_needs": [RAISED]})

        rows = needs.collect(lib, {})

        self.assertEqual(["no_year", "ext:site:share_down"], keys(rows))
        one = rows[-1]
        self.assertEqual(("3 plays are down", "Not sent", "Site", 3, "warm"),
                         (one.label, one.tip, one.source, one.count, one.tone))

    def test_each_kind_of_act_opens_its_own_place(self):
        opened = {kind: needs.extension_rows([{**RAISED, "opens": kind, "to": "x"}])[0].opens
                  for kind in ("list", "page", "action")}

        self.assertEqual("community:site:x", opened["list"].view)
        self.assertEqual("page:site:x", opened["page"].view)
        self.assertEqual(("site", "x", ""),
                         (opened["action"].extension, opened["action"].action,
                          opened["action"].view))

    def test_a_row_can_be_dismissed_and_comes_back_for_a_different_token(self):
        row = needs.extension_rows([RAISED])[0]
        record = {row.key: ["a", "b", "c"]}

        self.assertEqual([], needs.arrange([row], record, set()).rows)
        arranged = needs.arrange([needs.extension_rows([{**RAISED, "covered": ["a", "z"]}])[0]],
                                 record, set())
        self.assertEqual(("z",), arranged.rows[0].new)

    def test_a_dismissal_outlasts_an_extension_that_could_not_answer(self):
        record = {"ext:site:share_down": ["a"], "ext:other:old": ["b"]}

        away = needs.arrange([], record, set(), [needs.AWAY + "site"])
        every = needs.arrange([], record, set(), [needs.AWAY_ALL])
        read = needs.arrange([], record, set(), [])

        self.assertEqual({"ext:site:share_down": ["a"]}, away.record)
        self.assertEqual(record, every.record)
        self.assertEqual({}, read.record)

    def test_it_can_be_set_aside_and_stopped_as_a_row_of_this_install(self):
        self.assertTrue(needs.can_set_aside("ext:site:share_down"))
        self.assertTrue(needs.is_extension("ext:site:share_down"))
        self.assertTrue(needs.is_device("ext:site:share_down"))
        self.assertIn("extension", needs.comes_back("ext:site:share_down"))

    def test_a_stopped_row_is_set_aside_as_not_checked_and_the_extension_s_others_stay(self):
        other = {**RAISED, "kind": "other", "key": "ext:site:other", "label": "1 thing"}
        lib = FakeLibrary(watched={"extension_needs": [RAISED, other]},
                          hidden={"ext:site:share_down"})

        arranged = needs.arrange(needs.collect(lib, {}), {}, lib.stopped())

        self.assertEqual(["ext:site:other"], [one.key for one in arranged.rows
                                              if needs.is_extension(one.key)])
        (aside,) = [one for one in arranged.aside if one.key == "ext:site:share_down"]
        self.assertEqual(("3 plays are down", True), (aside.label, aside.stopped))

    def test_a_stopped_row_keeps_what_was_dismissed_over_it(self):
        row = needs.extension_rows([{**RAISED, "covered": ["a"]}])[0]

        arranged = needs.arrange([row], {row.key: ["a"]}, {row.key})

        self.assertEqual({row.key: ["a"]}, arranged.record)

    def test_a_row_with_only_a_count_says_it_waits_for_the_extension_to_stop_asking(self):
        by_ids = needs.extension_rows([RAISED])[0]
        by_kind = needs.extension_rows([{**RAISED, "covered": ["share_down"]}])[0]

        self.assertFalse(by_ids.by_kind)
        self.assertTrue(by_kind.by_kind)
        self.assertEqual(t("console.needs.back.extension"),
                         needs.comes_back(by_ids.key, by_ids))
        self.assertEqual(t("console.needs.back.extension_kind"),
                         needs.comes_back(by_kind.key, by_kind))
        self.assertEqual([], needs.arrange([by_kind], {by_kind.key: ["share_down"]}, set()).rows)

    def test_a_read_that_failed_is_said_and_stays_in_the_row_that_says_so(self):
        lib = FakeLibrary(watched={"unread": ["extensions", needs.AWAY + "site"]})

        rows = needs.collect(lib, {})

        self.assertEqual(["unread"], keys(rows))
        self.assertIn("what extensions ask for", rows[0].tip)

    def test_the_read_collects_what_the_api_gave_and_who_was_away(self):
        client = SimpleNamespace(
            update_check=lambda: {}, capture_proposals=lambda: {"proposals": []},
            jobs=lambda limit: [],
            extension_needs=lambda: {"needs": [RAISED], "away": ["old"], "failed": ["old"]})
        library = Library.__new__(Library)
        library._client = client

        read = library._read_watched()

        self.assertEqual([RAISED], read["extension_needs"])
        self.assertEqual(["away:old", "extensions"], read["unread"])


if __name__ == "__main__":
    unittest.main()
