"""The Discovery page: what a catalog entry becomes as a row, and what can be done to one."""

from __future__ import annotations

import unittest
from unittest import mock

from manager import page
from manager.kit import deeplink
from manager.kit.data import Library
from manager.library import discovery


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
