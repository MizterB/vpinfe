"""What the import's report asks to be looked at, and the cabinet files it names."""

from __future__ import annotations

import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from common.extensions import host

host.Registry().load(host.BUNDLED_DIR / "library_importer")

from vpinfe_ext_library_importer import cabinet, report  # noqa: E402

INI = """[virtualdmd]
enabled = true
left = 10
top = 20

[tz_94h]
virtualdmd left = 100
virtualdmd top = 200
virtualdmd width = 512

[taf_l7]
virtualdmd enabled = false
virtualdmd left = 5
virtualdmd top = 6

[only_size]
virtualdmd width = 300

[Gen_One]
virtualdmd left = 7
"""


def made(**over: object) -> dict:
    row: dict = {"key": "k", "name": "Taxi", "game_id": "g1", "table": True, "error": "",
                 "rom": "taxi_l4", "rom_there": True, "matched": True, "wheel": True,
                 "table_id": "t1"}
    row.update(over)
    return row


def says() -> mock.MagicMock:
    ctx = mock.MagicMock()
    ctx.t.side_effect = lambda key, **given: f"{key}:{given}" if given else key
    return ctx


class CabinetTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.install = Path(self._tmp.name) / "Pinball"
        self.tables = self.install / "Tables"
        self.tables.mkdir(parents=True)
        (self.install / "VPinMAME").mkdir()

    def test_the_files_a_cabinet_keeps_are_named_where_they_sit(self) -> None:
        (self.tables / "screenres.txt").write_text("x")
        (self.install / "VPinMAME" / "DmdDevice.ini").write_text("")
        (self.tables / "B2SServer").mkdir()

        found = cabinet.read({"tables": str(self.tables)})

        self.assertEqual(
            sorted((one["what"], one["displays"]) for one in found.left_behind),
            [("B2SServer", True), ("DmdDevice.ini", True), ("ScreenRes.txt", True)])

    def test_a_rom_whose_section_moves_the_dmd_has_a_place_of_its_own(self) -> None:
        (self.install / "VPinMAME" / "DmdDevice.ini").write_text(INI)

        found = cabinet.read({"tables": str(self.tables)})

        self.assertEqual(found.dmd, {"tz_94h": ("100", "200")})

    def test_a_section_that_turns_the_dmd_off_or_sets_no_position_is_no_place(self) -> None:
        (self.install / "VPinMAME" / "DmdDevice.ini").write_text(INI)

        found = cabinet.read({"tables": str(self.tables)})

        for rom in ("taf_l7", "only_size", "gen_one"):
            self.assertNotIn(rom, found.dmd)

    def test_a_file_that_will_not_parse_is_no_places(self) -> None:
        (self.install / "VPinMAME" / "DmdDevice.ini").write_text("not an ini\n[unclosed")

        self.assertEqual(cabinet.read({"tables": str(self.tables)}).dmd, {})

    def test_no_folders_given_finds_nothing(self) -> None:
        found = cabinet.read({})

        self.assertEqual((found.left_behind, found.dmd), ([], {}))


class ItemsTests(unittest.TestCase):
    def groups(self, row: dict, match: object = None, here: cabinet.Cabinet | None = None):
        return [(one["group"], one["reason"]) for one in report.items_for(
            says(), row, match, here or cabinet.Cabinet())]

    def test_a_game_with_everything_is_asked_about_nothing(self) -> None:
        self.assertEqual(self.groups(made()), [])

    def test_a_table_whose_rom_did_not_come_needs_one_and_the_rom_is_the_reason(self) -> None:
        self.assertEqual(self.groups(made(rom_there=False)), [("need_rom", "taxi_l4")])

    def test_a_game_with_no_rom_or_no_table_needs_none(self) -> None:
        self.assertEqual(self.groups(made(rom="", rom_there=False)), [])
        self.assertEqual(self.groups(made(table=False, rom_there=False)), [])

    def test_a_game_the_catalog_did_not_settle_gives_the_reason_the_matches_page_did(self) -> None:
        match = types.SimpleNamespace(reason="two_entries")

        self.assertEqual(self.groups(made(matched=False), match),
                         [("not_matched", "why.two_entries")])
        self.assertEqual(self.groups(made(matched=False), types.SimpleNamespace(reason="")),
                         [("not_matched", "")])

    def test_a_game_with_neither_a_wheel_nor_a_logo_is_listed_for_one(self) -> None:
        self.assertEqual(self.groups(made(wheel=False)), [("no_wheel", "")])

    def test_a_filled_game_is_not_asked_for_a_match_or_a_wheel(self) -> None:
        self.assertEqual(self.groups(made(existing=True, matched=False, wheel=False)), [])

    def test_a_game_that_failed_or_is_another_build_is_in_no_group(self) -> None:
        self.assertEqual(self.groups(made(error="x", rom_there=False)), [])
        self.assertEqual(self.groups(made(joined=True, rom_there=False)), [])
        self.assertEqual(self.groups(made(game_id="", rom_there=False)), [])

    def test_a_dmd_with_a_place_of_its_own_names_the_table_that_has_it(self) -> None:
        here = cabinet.Cabinet(dmd={"taxi_l4": ("100", "200")})

        found = report.items_for(says(), made(), None, here)

        self.assertEqual([(one["group"], one["table_id"]) for one in found],
                         [("dmd_alone", "t1")])
        self.assertIn("'left': '100'", found[0]["reason"])


if __name__ == "__main__":
    unittest.main()
