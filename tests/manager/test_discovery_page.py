"""The Discovery page: what a catalog entry becomes as a row, and what can be done to one."""

from __future__ import annotations

import unittest
from typing import Any
from unittest import mock

from nicegui import ui

from common.online import vps_kinds
from manager import page
from manager.kit import deeplink
from manager.kit.data import Library
from manager.library import discovery, discovery_ask, discovery_get

# Made at import, outside any task, where NiceGUI still hands out the script's own page.
_PAGE = ui.element()


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


class Cell(unittest.TestCase):
    def test_the_game_cell_says_who_made_it_and_when(self) -> None:
        row = discovery.rows(_found(_entry(img_url="https://vps/a.webp")))[0]

        self.assertEqual(("Bally 1995", "https://vps/a.webp"), (row["said"], row["art"]))

    def test_a_game_with_no_year_says_only_who_made_it(self) -> None:
        row = discovery.rows(_found(_entry(year=None)))[0]

        self.assertEqual("Bally", row["said"])


class KeptKinds(unittest.TestCase):
    def test_a_kind_the_library_does_not_keep_is_blank_and_no_gap(self) -> None:
        row = discovery.rows(_found(_entry()), kept={"tableFiles", "b2sFiles"})[0]

        self.assertEqual("", row["kind_rom"])
        self.assertEqual("", row["gap"])

    def test_every_kind_counts_where_none_is_named(self) -> None:
        self.assertEqual("missing", discovery.rows(_found(_entry()))[0]["gap"])


class Views(unittest.TestCase):
    def test_no_built_in_view_turns_on_what_the_game_cell_already_says(self) -> None:
        for name, preset in discovery.VIEWS.items():
            with self.subTest(name):
                assert not isinstance(preset, list)
                self.assertFalse(set(preset.columns) & {"manufacturer", "year", "game_type",
                                                        "themes"})

    def test_the_picker_still_offers_them(self) -> None:
        fields = {one["field"] for one in discovery.COLUMNS}

        self.assertLessEqual({"manufacturer", "year", "game_type", "themes"}, fields)


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


    def test_add_waits_for_a_comparison_and_says_so(self) -> None:
        row = discovery.rows(_found(_entry(in_library=None, held=[]), counted=""))[0]

        (add,) = discovery.acts(mock.Mock(spec=Library), [row], mock.AsyncMock())

        self.assertIsNone(add.run)
        self.assertEqual("Compare with VPS first", add.hint)


class PaneActs(unittest.TestCase):
    def _verbs(self, row: dict, game_id: str = "") -> dict:
        return {one.label: one for one in discovery.pane_acts(
            mock.Mock(spec=Library), row, game_id, mock.AsyncMock())}

    def test_a_game_in_the_library_opens_in_games_and_cannot_be_added(self) -> None:
        row = discovery.rows(_found(_entry()))[0]

        verbs = self._verbs(row, "g1")

        self.assertEqual("/manager?" + deeplink.query({"view": "games", "game": "g1"}),
                         verbs["Open in Games"].to)
        self.assertIsNone(verbs["Add to Library"].run)
        self.assertEqual("https://vps/v1", verbs["View on VPS"].to)

    def test_a_game_not_in_the_library_says_why_it_cannot_be_opened(self) -> None:
        row = discovery.rows(_found(_entry(in_library=False, held=[])))[0]

        verbs = self._verbs(row)

        self.assertIsNone(verbs["Open in Games"].run)
        self.assertFalse(verbs["Open in Games"].to)
        self.assertEqual("Not in your library", verbs["Open in Games"].hint)
        self.assertIsNotNone(verbs["Add to Library"].run)

    def test_a_game_in_the_library_with_no_game_found_does_not_say_it_is_absent(self) -> None:
        row = discovery.rows(_found(_entry()))[0]

        verbs = self._verbs(row)

        self.assertIsNone(verbs["Open in Games"].run)
        self.assertNotEqual("Not in your library", verbs["Open in Games"].hint)

    def test_before_a_comparison_opening_asks_for_one(self) -> None:
        row = discovery.rows(_found(_entry(in_library=None, held=[]), counted=""))[0]

        self.assertEqual("Compare with VPS first", self._verbs(row)["Open in Games"].hint)

    def test_an_entry_with_no_page_has_no_view_on_vps(self) -> None:
        row = discovery.rows(_found(_entry(url="")))[0]

        self.assertNotIn("View on VPS", self._verbs(row, "g1"))


def _library(*, hidden_assets: tuple[str, ...] = (), hidden_media: tuple[str, ...] = ()) -> Library:
    client = mock.Mock()
    client.library_policy.return_value = {"hidden_asset_kinds": list(hidden_assets),
                                          "hidden_media_kinds": list(hidden_media)}
    library = Library(client)
    library.load_kept_kinds()
    return library


def _held(**files: list[dict]) -> dict:
    kinds = [{"kind": listed_as, "held": bool(files.get(listed_as)),
              "files": files.get(listed_as, [])}
             for listed_as in ("b2sFiles", "romFiles", "wheelArtFiles")]
    return {"kinds": kinds, "tables": files.get("tableFiles", [])}


class Standing(unittest.TestCase):
    def test_the_live_state_decides_which_kinds_are_held(self) -> None:
        row = discovery.rows(_found(_entry(held=[])))[0]
        held = _held(tableFiles=[{"name": "a.vpx", "vps_file_id": ""}],
                     romFiles=[{"name": "rom", "vps_file_id": ""}])

        said = discovery.standing(_library(), row, held)

        self.assertEqual({"tableFiles": "have", "b2sFiles": "missing", "romFiles": "have"}, said)

    def test_the_row_answers_where_the_state_cannot_be_read(self) -> None:
        row = discovery.rows(_found(_entry()))[0]

        said = discovery.standing(_library(), row, None)

        self.assertEqual({"tableFiles": "have", "b2sFiles": "have", "romFiles": "missing"}, said)

    def test_a_game_not_in_the_library_has_no_state_on_any_kind(self) -> None:
        row = discovery.rows(_found(_entry(in_library=False, held=[])))[0]

        self.assertEqual({}, discovery.standing(_library(), row, None))

    def test_a_library_never_counted_has_no_state_on_any_kind(self) -> None:
        row = discovery.rows(_found(_entry(in_library=None, held=[]), counted=""))[0]

        self.assertEqual({}, discovery.standing(_library(), row, None))

    def test_a_kind_the_library_does_not_keep_is_not_counted(self) -> None:
        row = discovery.rows(_found(_entry()))[0]

        said = discovery.standing(_library(hidden_assets=("rom",)), row, None)

        self.assertNotIn("romFiles", said)


class Kept(unittest.TestCase):
    def test_the_table_is_always_kept(self) -> None:
        self.assertTrue(discovery.kept(_library(hidden_assets=("rom",)), "tableFiles"))

    def test_a_kind_switched_off_in_the_library_is_not(self) -> None:
        library = _library(hidden_assets=("rom",), hidden_media=("wheel",))

        self.assertFalse(discovery.kept(library, "romFiles"))
        self.assertFalse(discovery.kept(library, "wheelArtFiles"))
        self.assertTrue(discovery.kept(library, "b2sFiles"))

    def test_a_kind_that_is_two_of_ours_is_kept_while_either_is(self) -> None:
        self.assertTrue(discovery.kept(_library(hidden_assets=("altcolor_serum",)),
                                       "altColorFiles"))
        self.assertFalse(discovery.kept(
            _library(hidden_assets=("altcolor_serum", "altcolor_vni")), "altColorFiles"))


class Records(unittest.TestCase):
    def _records(self, count: int) -> list[dict]:
        return [{"vps_file_id": f"r{index}", "updated_at": f"2024-01-{index + 1:02d}T00:00:00Z"}
                for index in range(count)]

    def test_the_newest_come_first(self) -> None:
        ordered = discovery.newest_first(self._records(3))

        self.assertEqual(["r2", "r1", "r0"], [one["vps_file_id"] for one in ordered])

    def test_five_show_and_the_rest_wait(self) -> None:
        shown, rest = discovery.split_records(discovery.newest_first(self._records(8)), set())

        self.assertEqual((5, 3), (len(shown), len(rest)))

    def test_a_record_you_hold_is_never_behind_the_row(self) -> None:
        shown, rest = discovery.split_records(discovery.newest_first(self._records(8)), {"r0"})

        self.assertIn("r0", [one["vps_file_id"] for one in shown])
        self.assertNotIn("r0", [one["vps_file_id"] for one in rest])


class ChoosingBy(unittest.TestCase):
    def test_the_comment_leads_with_its_first_line_that_says_anything(self) -> None:
        self.assertEqual("Retheme of Count-Down",
                         discovery.first_line("\n  \nRetheme of Count-Down\nplus a long tail"))

    def test_no_comment_has_no_first_line(self) -> None:
        self.assertEqual("", discovery.first_line(None))
        self.assertEqual("", discovery.first_line("  \n "))

    def test_a_mod_and_its_features_share_a_line_without_saying_mod_twice(self) -> None:
        record = {"features": ["MOD", "VR"], "mod_of": {"vps_file_id": "b", "version": "1.0",
                                                          "authors": ["Larouillas"]}}

        self.assertEqual("Mod of 1.0 · Larouillas · VR",
                         discovery.what_it_is(record, features=True))

    def test_a_list_that_hides_features_still_says_a_file_is_a_mod(self) -> None:
        record = {"features": ["MOD", "VR"]}

        self.assertEqual("Mod", discovery.what_it_is(record, features=False))

    def test_a_vpx_file_does_not_name_its_format_and_another_does(self) -> None:
        self.assertEqual("", discovery.what_it_is({"format": "VPX"}, features=True))
        self.assertEqual("Future Pinball",
                         discovery.what_it_is({"format": "FP"}, features=True))

    def test_a_file_is_linked_by_the_site_it_is_on(self) -> None:
        record = {"url": "https://www.vpforums.org/file"}

        self.assertEqual(("VPForums", "https://www.vpforums.org/file"), discovery.site_of(record))

    def test_a_page_is_broken_only_where_vps_marks_that_address(self) -> None:
        links = [{"url": "https://a.example/1", "broken": True}, {"url": "https://b.example/2"}]

        self.assertFalse(discovery.page_is_broken({"url": "https://b.example/2", "urls": links}))
        self.assertTrue(discovery.page_is_broken({"url": "https://a.example/1", "urls": links}))
        self.assertFalse(discovery.page_is_broken({"url": "", "urls": []}))

    def test_a_file_with_no_link_names_no_site(self) -> None:
        self.assertEqual(("", ""), discovery.site_of({"url": ""}))

    def test_the_other_links_are_every_one_but_the_one_it_leads_with(self) -> None:
        record = {"url": "https://vpuniverse.com/a",
                  "urls": [{"url": "https://vpuniverse.com/a", "broken": False},
                           {"url": "https://mega.nz/file/b", "broken": True}]}

        self.assertEqual([("Mega", "https://mega.nz/file/b", True)],
                         discovery.other_links(record))


class TypeWords(unittest.TestCase):
    def test_the_letters_are_spelled_out(self) -> None:
        self.assertEqual(["Solid State", "Electro-Mechanical", "Pure Mechanical"],
                         [discovery.type_word(code) for code in ("SS", "EM", "PM")])

    def test_a_code_it_does_not_know_is_shown_as_it_is(self) -> None:
        self.assertEqual("XY", discovery.type_word("XY"))


class Address(unittest.TestCase):
    def test_the_entry_is_named_in_the_address_on_this_page_only(self) -> None:
        on_page = deeplink.query({"view": "discovery", "entry": "v1"})
        elsewhere = deeplink.query({"view": "games", "entry": "v1"})

        self.assertIn("entry=v1", on_page)
        self.assertNotIn("entry", elsewhere)

    def test_a_subject_is_named_in_the_address_by_its_kind(self) -> None:
        for kind in deeplink.SUBJECTS:
            with self.subTest(kind=kind):
                state = {"view": "discovery", "subject": {"type": kind, "name": "Bally"}}
                self.assertEqual(f"view=discovery&{kind}=Bally", deeplink.query(state))

    def test_a_subject_is_named_on_this_page_only(self) -> None:
        state = {"view": "games", "subject": {"type": "author", "name": "VPW"}}
        self.assertNotIn("author", deeplink.query(state))

    def test_an_address_opens_the_page_for_the_subject_it_names(self) -> None:
        state: dict = {"view": "discovery"}
        deeplink.apply(state, {"view": "discovery", "maker": " Bally "},
                       views=["discovery"], sections=[])
        self.assertEqual(state["subject"], {"type": "maker", "name": "Bally"})


class AskWords(unittest.TestCase):
    def test_taking_a_value_out_of_a_list_leaves_the_rest(self) -> None:
        asked = {"by": ["A", "B"], "mod": "mods"}
        self.assertEqual(discovery_ask.without(asked, "by", "A"), {"by": ["B"], "mod": "mods"})
        self.assertEqual(discovery_ask.without(asked, "mod", "mods"), {"by": ["A", "B"]})

    def test_a_list_key_gains_the_value_and_any_other_key_takes_it_in_place(self) -> None:
        self.assertEqual(discovery_ask.with_value({"by": ["A"]}, "by", "B"), {"by": ["A", "B"]})
        self.assertEqual(discovery_ask.with_value({"mod": "mods"}, "mod", "originals"),
                         {"mod": "originals"})

    def test_asking_for_tables_brings_the_default_format_unless_one_is_named(self) -> None:
        self.assertEqual(discovery_ask.with_value({}, "kind", "tableFiles"),
                         {"kind": "tableFiles", "format": [discovery_ask.FORMAT_DEFAULT]})
        self.assertEqual(
            discovery_ask.with_value({"format": ["FP"]}, "kind", "tableFiles")["format"], ["FP"])
        self.assertNotIn("format", discovery_ask.with_value({}, "kind", "b2sFiles"))

    def test_moving_off_tables_takes_the_default_format_with_it(self) -> None:
        tables = discovery_ask.with_value({}, "kind", "tableFiles")
        self.assertEqual(discovery_ask.with_value(tables, "kind", "b2sFiles"),
                         {"kind": "b2sFiles"})
        chosen = {"kind": "tableFiles", "format": ["FP"]}
        self.assertEqual(discovery_ask.with_value(chosen, "kind", "b2sFiles")["format"], ["FP"])

    def test_the_releases_a_library_does_not_collect_are_left_out(self) -> None:
        found = {"rows": [{"vps_id": "a", "releases": {"tableFiles": [1], "romFiles": [2]}},
                          {"vps_id": "b", "releases": {"romFiles": [3]}}]}
        self.assertEqual(discovery.releases_of(found, ["tableFiles"]), {"a": {"tableFiles": [1]}})

    def test_every_thing_asked_is_one_chip(self) -> None:
        asked = {"kind": "b2sFiles", "by": ["A", "B"], "mod": "mods", "held": "missing"}
        said = discovery_ask.parts(asked, {"b2sFiles": "word.kind"})
        self.assertEqual([key for key, _value, _words in said],
                         ["kind", "by", "by", "mod", "held"])

    def test_an_added_window_is_said_as_the_window_and_not_as_a_date(self) -> None:
        for days, words in (("7", "Past Week"), ("14", "Past 2 Weeks"), ("30", "Past Month"),
                            ("10", "Past 10 Days")):
            self.assertEqual([("since", days, words)],
                             discovery_ask.parts({"since": days}, {}))

    def test_choosing_a_window_replaces_the_one_before(self) -> None:
        week = discovery_ask.with_value({}, "since", "7")

        self.assertEqual({"since": "30"}, discovery_ask.with_value(week, "since", "30"))


class MediaBands(unittest.TestCase):
    def test_the_wheel_and_the_topper_come_first_whatever_order_they_are_given_in(self) -> None:
        bands = discovery.media_bands(list(discovery.KINDS), ["playfield", "topper", "wheel"])

        self.assertEqual(["wheel", "topper", "playfield"], [kind for kind, _one in bands])

    def test_a_kind_vps_lists_keeps_its_vps_row_and_one_only_a_source_has_gets_a_word(
            self) -> None:
        bands = dict(discovery.media_bands(list(discovery.KINDS), ["playfield"]))

        self.assertEqual("wheelArtFiles", bands["wheel"][0])
        self.assertEqual("", bands["playfield"][0])
        self.assertEqual("media.kind.playfield.label", bands["playfield"][2])

    def test_a_kind_neither_vps_nor_a_source_has_is_not_a_band(self) -> None:
        bands = discovery.media_bands([("tableFiles", "kind_table", "word.table")], [])

        self.assertEqual([], bands)


class Picks(unittest.TestCase):
    def _offer(self, **over) -> dict:
        return {"source": "vpinmediadb", "kind": "wheel", "size": "4K", "name": "wheel.png",
                "url": "https://example.test/wheel.png", **over}

    def test_a_pick_is_named_by_where_it_is_from_what_it_is_and_which_size(self) -> None:
        pick = discovery_get.pick_of(self._offer())

        self.assertEqual(("vpinmediadb", "wheel", "4K"), (pick.source, pick.kind, pick.size))
        self.assertEqual(discovery_get.key_of("vpinmediadb", "wheel", "4K"), pick.key)

    def test_an_offer_with_no_size_is_a_pick_with_none(self) -> None:
        self.assertEqual("", discovery_get.pick_of(self._offer(size=None)).size)

    def test_a_tray_belongs_to_the_entry_and_outlives_a_redraw(self) -> None:
        state: dict = {}

        mine = discovery_get.tray_of(state, "v1")

        self.assertIs(mine, discovery_get.tray_of(state, "v1"))
        self.assertIsNot(mine, discovery_get.tray_of(state, "v2"))

    def test_the_wheel_and_the_topper_are_drawn_before_the_rest(self) -> None:
        order = sorted(["playfield", "topper", "wheel", "backglass", "nothing_we_know"],
                       key=discovery_get.media_order)

        self.assertEqual(["wheel", "topper", "backglass", "playfield", "nothing_we_know"], order)


class Ticking(unittest.TestCase):
    def _pick(self, size: str, kind: str = "wheel") -> discovery_get.Pick:
        return discovery_get.pick_of({"source": "vpinmediadb", "kind": kind, "size": size})

    def test_ticking_a_second_file_of_a_kind_unticks_the_first(self) -> None:
        tray, small, big = discovery_get.Tray(), self._pick("1K"), self._pick("4K")

        tray.set(small, True)
        tray.set(big, True)

        self.assertEqual([big], tray.waiting())

    def test_two_kinds_are_both_kept(self) -> None:
        tray = discovery_get.Tray()

        tray.set(self._pick("4K"), True)
        tray.set(self._pick("4K", "topper"), True)

        self.assertEqual({"wheel", "topper"}, {one.kind for one in tray.waiting()})

    def test_unticking_takes_it_off(self) -> None:
        tray, pick = discovery_get.Tray(), self._pick("4K")
        tray.set(pick, True)

        tray.set(pick, False)

        self.assertEqual([], tray.waiting())

    def test_a_file_already_in_is_not_waiting_and_one_that_failed_is(self) -> None:
        tray, done, failed = discovery_get.Tray(), self._pick("4K"), self._pick("4K", "topper")
        tray.set(done, True)
        tray.set(failed, True)

        tray.move(done.key, discovery_get.IN)
        tray.move(failed.key, discovery_get.FAILED, "no connection")

        self.assertEqual([failed], tray.waiting())

    def test_a_file_in_is_not_unticked_by_a_rival(self) -> None:
        tray, done, rival = discovery_get.Tray(), self._pick("1K"), self._pick("4K")
        tray.set(done, True)
        tray.move(done.key, discovery_get.IN)

        tray.set(rival, True)

        self.assertEqual([rival], tray.waiting())
        self.assertIn(done.key, tray.picks)

    def test_a_rival_that_failed_is_replaced_and_its_failure_goes_with_it(self) -> None:
        tray, failed, rival = discovery_get.Tray(), self._pick("1K"), self._pick("4K")
        tray.set(failed, True)
        tray.move(failed.key, discovery_get.FAILED, "no connection")

        tray.set(rival, True)

        self.assertEqual([rival], tray.waiting())
        self.assertNotIn(failed.key, tray.moves)

    def test_releasing_a_kind_lets_go_of_what_is_in_and_nothing_else(self) -> None:
        tray = discovery_get.Tray()
        gone, kept, waiting = self._pick("4K"), self._pick("4K", "topper"), self._pick(
            "4K", "playfield")
        for pick in (gone, kept, waiting):
            tray.set(pick, True)
        tray.move(gone.key, discovery_get.IN)
        tray.move(kept.key, discovery_get.IN)

        tray.release({"wheel", "playfield"})

        self.assertEqual({kept.key, waiting.key}, set(tray.picks))
        self.assertEqual({kept.key}, set(tray.moves))

    def test_repainting_all_redraws_every_key_and_forgets_a_holder_that_was_deleted(self) -> None:
        tray, drawn = discovery_get.Tray(), []
        live, dead = mock.MagicMock(is_deleted=False), mock.MagicMock(is_deleted=True)
        tray._painters = {"a": [(live, lambda: drawn.append("a"))],
                          "b": [(dead, lambda: drawn.append("b"))]}

        tray.repaint_all()

        self.assertEqual(["a"], drawn)
        self.assertEqual([], tray._painters["b"])

    def test_forgetting_a_move_puts_the_tick_back_in_the_waiting(self) -> None:
        tray, pick = discovery_get.Tray(), self._pick("4K")
        tray.set(pick, True)
        tray.move(pick.key, discovery_get.QUEUED)

        tray.forget(pick.key)

        self.assertEqual([pick], tray.waiting())


class Saying(unittest.TestCase):
    def test_a_batch_says_how_many_and_where_each_has_got_to(self) -> None:
        tray = discovery_get.Tray(batch=4)
        for number, state in enumerate((discovery_get.IN, discovery_get.IN,
                                        discovery_get.DOWNLOADING, discovery_get.FAILED)):
            tray.move(f"k{number}", state)

        self.assertEqual("Downloading 4 files: 2 in, 1 downloading, 1 needs you",
                         discovery_get._said(tray))

    def test_one_file_is_not_files(self) -> None:
        tray = discovery_get.Tray(batch=1)
        tray.move("k", discovery_get.DOWNLOADING)

        self.assertEqual("Downloading 1 file: 1 downloading", discovery_get._said(tray))


class Listings(unittest.TestCase):
    def test_a_vps_kind_is_ours_by_the_kinds_behind_it(self) -> None:
        ours, held_in = discovery_get.of_listing("b2sFiles")

        self.assertEqual(("backglass",), ours)
        self.assertEqual(vps_kinds.ASSET, held_in)

    def test_a_kind_that_is_two_of_ours_names_both(self) -> None:
        ours, held_in = discovery_get.of_listing("topperFiles")

        self.assertEqual(("topper", "topper_video"), ours)
        self.assertEqual(vps_kinds.MEDIA, held_in)

    def test_the_table_is_an_asset_kind_of_its_own(self) -> None:
        self.assertEqual((("table",), vps_kinds.ASSET), discovery_get.of_listing("tableFiles"))


class Getting(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.asked: list[str] = []
        self.refused: set[str] = set()
        self.on_asked = lambda kind: None

        async def inline(callback, *args):
            return callback(*args)

        self.enterContext(mock.patch.object(discovery_get.offload, "io", inline))
        self.library = mock.Mock()
        self.library.fetch_media = self._fetch
        self.discovery: dict[str, Any] = {"id": "v1", "name": "Attack from Mars",
                                          "is_in_library": True}
        self.context = {"library": self.library, "state": {}, "discovery": self.discovery}
        self.tray = discovery_get.Tray()

    def _fetch(self, _game, _table, kind, _source, _vps, _size):
        self.asked.append(kind)
        self.on_asked(kind)
        if kind in self.refused:
            raise RuntimeError("the source has no file")
        return {"kind": kind}

    def _tick(self, *kinds: str) -> list[discovery_get.Pick]:
        picks = [discovery_get.pick_of({"source": "vpinmediadb", "kind": kind, "size": "4K"})
                 for kind in kinds]
        for pick in picks:
            self.tray.set(pick, True)
        return picks

    async def _get(self, game_id: str = "g1", **more) -> None:
        with _PAGE:
            await discovery_get.get(self.context, self.tray, game_id, **more)

    async def test_a_file_the_source_refuses_fails_alone_and_the_rest_arrive(self) -> None:
        wheel, topper, playfield = self._tick("wheel", "topper", "playfield")
        self.refused = {"topper"}

        await self._get()

        self.assertEqual({wheel.key: discovery_get.IN, topper.key: discovery_get.FAILED,
                          playfield.key: discovery_get.IN},
                         {key: move.state for key, move in self.tray.moves.items()})
        self.assertEqual("the source has no file", self.tray.moves[topper.key].reason)
        self.assertEqual([topper], self.tray.waiting())
        self.assertFalse(self.tray.running)

    async def test_trying_again_asks_for_that_file_alone(self) -> None:
        wheel, topper = self._tick("wheel", "topper")
        self.refused = {"topper"}
        await self._get()
        self.asked.clear()
        self.refused = set()

        with _PAGE:
            await discovery_get.try_again(self.context, self.tray, "g1", topper)()

        self.assertEqual(["topper"], self.asked)
        self.assertEqual(discovery_get.IN, self.tray.moves[topper.key].state)
        self.assertEqual(discovery_get.IN, self.tray.moves[wheel.key].state)
        self.assertEqual([], self.tray.waiting())

    async def test_stop_ends_the_batch_after_the_file_in_hand(self) -> None:
        wheel, topper, playfield = self._tick("wheel", "topper", "playfield")

        def pressed(kind: str) -> None:
            self.tray.stopping = kind == "wheel"

        self.on_asked = pressed

        await self._get()

        self.assertEqual(["wheel"], self.asked)
        self.assertEqual({wheel.key: discovery_get.IN},
                         {key: move.state for key, move in self.tray.moves.items()})
        self.assertEqual([topper, playfield], self.tray.waiting())
        self.assertFalse(self.tray.running)

    async def test_a_second_press_while_one_batch_runs_starts_nothing(self) -> None:
        self._tick("wheel")
        self.tray.running = True

        await self._get()

        self.assertEqual([], self.asked)

    async def test_trying_again_while_a_batch_runs_starts_nothing(self) -> None:
        (topper,) = self._tick("topper")
        self.tray.move(topper.key, discovery_get.FAILED, "no connection")
        self.tray.running = True

        with _PAGE:
            await discovery_get.try_again(self.context, self.tray, "g1", topper)()

        self.assertEqual([], self.asked)
        self.assertEqual(discovery_get.FAILED, self.tray.moves[topper.key].state)

    async def test_a_game_in_the_library_that_cannot_be_read_gets_nothing_and_says_so(
            self) -> None:
        self._tick("wheel")

        with _PAGE, mock.patch.object(discovery_get.ui, "notify") as said:
            await discovery_get.get(self.context, self.tray, "")

        self.assertEqual([], self.asked)
        self.assertFalse(self.tray.running)
        self.assertEqual("negative", said.call_args.kwargs["type"])

    async def test_a_game_not_in_the_library_is_made_first_and_declining_the_place_ends_it(
            self) -> None:
        self.discovery["is_in_library"] = False
        self._tick("wheel")

        with mock.patch.object(discovery_get.import_dialog, "ask_where",
                               mock.AsyncMock(return_value=None)):
            await self._get("")

        self.assertEqual([], self.asked)
        self.assertEqual({}, self.tray.moves)
        self.assertFalse(self.tray.running)

    async def test_a_game_not_in_the_library_is_made_and_then_gets_what_was_ticked(self) -> None:
        self.discovery["is_in_library"] = False
        self.library.add_game_from_vps = lambda _vps, _where: {"id": "g9"}
        (wheel,) = self._tick("wheel")

        with mock.patch.object(discovery_get.import_dialog, "ask_where",
                               mock.AsyncMock(return_value="place")):
            await self._get("")

        self.assertEqual(["wheel"], self.asked)
        self.assertEqual(discovery_get.IN, self.tray.moves[wheel.key].state)

    async def test_what_the_batch_leaves_ticked_is_drawn_again_when_it_ends(self) -> None:
        wheel, topper = self._tick("wheel", "topper")
        self.refused = {"wheel"}
        redrawn: list[str] = []
        holder = mock.MagicMock(is_deleted=False)
        self.tray._painters = {topper.key: [(holder, lambda: redrawn.append(topper.key))]}

        await self._get(only=wheel)

        self.assertIn(topper.key, redrawn)


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
