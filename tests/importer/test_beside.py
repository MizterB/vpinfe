"""What a source keeps beside its tables: name map, scripts, DMD folders, backglass settings."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from common.extensions import host

host.Registry().load(host.BUNDLED_DIR / "library_importer")

from vpinfe_ext_library_importer import adopt, beside  # noqa: E402
from vpinfe_ext_library_importer.source import SourceGame  # noqa: E402

GRILL = "Plugin.B2SLegacy.B2SHideGrill"
DUAL = "Plugin.B2SLegacy.B2SDualMode"

SETTINGS = """<?xml version="1.0"?>
<B2STableSettings>
  <ArchiveGameOver>0</ArchiveGameOver>
  <taxi_l4>
    <HideGrill>1</HideGrill>
    <HideB2SDMD>2</HideB2SDMD>
    <DualMode>2</DualMode>
  </taxi_l4>
  <odd>
    <DualMode>7</DualMode>
    <HideGrill>3</HideGrill>
  </odd>
  <Other>
    <HideDMD>0</HideDMD>
  </Other>
  <Empty/>
</B2STableSettings>
"""


class BesideCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.install = self.root / "Pinball"
        self.tables = self.install / "Tables"
        self.tables.mkdir(parents=True)
        self.roms = self.install / "VPinMAME" / "roms"
        self.roms.mkdir(parents=True)
        self.user = self.install / "User"
        self.user.mkdir()
        self.scripts = self.install / "Scripts"
        self.scripts.mkdir()
        self.ctx = mock.MagicMock()

    def places(self) -> dict[str, str]:
        return {"tables": str(self.tables), "roms": str(self.roms), "user": str(self.user)}

    def read(self) -> beside.Beside:
        return beside.read(self.ctx, self.places())


class ReadTests(BesideCase):
    def test_the_name_map_is_read_case_blind_and_comments_are_skipped(self) -> None:
        (self.install / "VPinMAME" / "VPMAlias.txt").write_text(
            "# a note\nTaxi_L1,taxi_l4\nlonely\n,empty\nnfl_pat,nfl,\nspace_l1 space_l2\n",
            encoding="utf-8")

        here = self.read()

        self.assertEqual(here.real_rom("taxi_l1"), "taxi_l4")
        self.assertEqual(here.real_rom("TAXI_L1"), "taxi_l4")
        self.assertEqual(here.real_rom("nfl_pat"), "nfl")
        self.assertEqual(here.real_rom("space_l1"), "space_l2")
        self.assertEqual(here.real_rom("lonely"), "")
        self.assertEqual(here.real_rom("other"), "")

    def test_only_the_name_map_is_read_for_the_plan(self) -> None:
        (self.install / "VPinMAME" / "VPMAlias.txt").write_text("a,b\n")
        (self.scripts / "Granny.vbs").write_text("x")

        here = beside.name_map(self.ctx, str(self.roms))

        self.assertEqual(here.real_rom("a"), "b")
        self.assertEqual(here.scripts, {})

    def test_no_name_map_is_no_aliases(self) -> None:
        self.assertEqual(self.read().aliases, {})
        self.assertEqual(self.read().lost, [])

    def test_a_name_map_that_cannot_be_read_is_named_as_lost(self) -> None:
        (self.install / "VPinMAME" / "VPMAlias.txt").write_text("a,b\n")

        with mock.patch.object(Path, "read_text", side_effect=PermissionError("no")):
            here = self.read()

        self.assertEqual(here.aliases, {})
        self.ctx.t.assert_any_call("lost.rom_map", file="VPMAlias.txt")
        self.assertEqual(here.lost, [{"what": self.ctx.t.return_value,
                                      "detail": self.ctx.why.return_value}])

    def test_only_a_script_the_program_does_not_ship_is_carried(self) -> None:
        (self.scripts / "Granny.vbs").write_text("x")
        (self.scripts / "WPC.vbs").write_text("x")
        (self.scripts / "notes.txt").write_text("x")

        here = self.read()

        self.assertEqual(here.names, ("Granny.vbs",))
        self.assertEqual([one.name for one in here.scripts_for(("granny.VBS", "wpc.vbs"))],
                         ["Granny.vbs"])

    def test_the_scripts_folder_beside_the_user_folder_is_a_root_to_read_from(self) -> None:
        self.assertEqual(beside.roots(self.places()), [str(self.scripts)])
        self.assertEqual(beside.roots({}), [])

    def test_a_backglass_entry_becomes_vpx_settings_and_an_undecided_flag_is_left_out(self) -> None:
        (self.tables / "B2STableSettings.xml").write_text(SETTINGS, encoding="utf-8")

        here = self.read()

        self.assertEqual(here.settings_for("taxi_l4"), {GRILL: "1", DUAL: "2"})
        self.assertEqual(here.settings_for("nobody", "OTHER"),
                         {"Plugin.B2SLegacy.B2SHideDMD": "0"})
        self.assertEqual(here.settings_for("nobody"), {})
        self.assertEqual(here.settings_for("empty"), {})

    def test_a_value_outside_what_the_setting_takes_is_left_out(self) -> None:
        (self.tables / "B2STableSettings.xml").write_text(SETTINGS, encoding="utf-8")

        self.assertEqual(self.read().settings_for("odd"), {})

    def test_a_settings_file_that_does_not_parse_is_logged_and_ignored(self) -> None:
        (self.tables / "B2STableSettings.xml").write_text("<oops", encoding="utf-8")

        self.assertEqual(self.read().settings, {})
        self.ctx.logger.warning.assert_called_once()

    def test_dmd_folders_are_found_beside_the_table_in_any_case(self) -> None:
        table = self.tables / "Taxi.vpx"
        table.write_bytes(b"x")
        (self.tables / "Taxi.UltraDMD").mkdir()
        (self.tables / "Other.flexdmd").mkdir()
        (self.tables / "Plain").mkdir()

        here = self.read()

        self.assertEqual(here.asked_of(str(table)),
                         ("Other.flexdmd", "Taxi.UltraDMD", ".flexdmd", ".ultradmd"))
        self.assertEqual([one.name for one in here.dmd_for(str(table), ("taxi.ultradmd",))],
                         ["Taxi.UltraDMD"])
        self.assertEqual(here.dmd_for("", ("taxi.ultradmd",)), [])

    def test_a_script_that_builds_the_folders_name_gives_only_its_suffix(self) -> None:
        table = self.tables / "Taxi.vpx"
        table.write_bytes(b"x")
        (self.tables / "Taxi.UltraDMD").mkdir()

        here = self.read()

        self.assertEqual(here.asked_of(str(table)), ("Taxi.UltraDMD", ".ultradmd"))
        self.assertEqual([one.name for one in here.dmd_for(str(table), (".ultradmd",))],
                         ["Taxi.UltraDMD"])

    def test_a_suffix_picks_nothing_when_two_folders_have_it(self) -> None:
        table = self.tables / "Taxi.vpx"
        table.write_bytes(b"x")
        (self.tables / "Taxi.UltraDMD").mkdir()
        (self.tables / "Other.UltraDMD").mkdir()

        self.assertEqual(self.read().dmd_for(str(table), (".ultradmd",)), [])


class BringTests(BesideCase):
    def game(self) -> SourceGame:
        return SourceGame(key="Taxi", display_name="Taxi (Williams 1988)",
                          table_file=str(self.tables / "Taxi.vpx"))

    def setUp(self) -> None:
        super().setUp()
        (self.tables / "Taxi.vpx").write_bytes(b"x")
        (self.install / "VPinMAME" / "VPMAlias.txt").write_text("taxi_l1,taxi_l4\n")
        (self.scripts / "Granny.vbs").write_text("x")
        (self.scripts / "WPC.vbs").write_text("x")
        (self.tables / "Taxi.UltraDMD").mkdir()
        (self.tables / "B2STableSettings.xml").write_text(SETTINGS, encoding="utf-8")
        self.here = self.read()

    def placed(self) -> set[tuple[str, str]]:
        return {(call.args[1], call.args[2].name)
                for call in self.ctx.games.put_asset.call_args_list}

    def test_the_asked_names_line_is_written_and_what_the_script_names_is_placed(self) -> None:
        adopt._bring_beside(self.ctx, "g1", self.game(), "t1", "taxi_l1",
                            ("Granny.vbs", "Taxi.UltraDMD"), self.here)

        self.ctx.games.put_rom_alias.assert_called_once_with("g1", "taxi_l1", "taxi_l4")
        self.assertEqual(self.placed(),
                         {("scripts", "Granny.vbs"), ("dmd_content", "Taxi.UltraDMD")})

    def test_a_script_nothing_named_is_not_carried(self) -> None:
        adopt._bring_beside(self.ctx, "g1", self.game(), "t1", "taxi_l1", (), self.here)

        self.ctx.games.put_asset.assert_not_called()

    def test_a_name_map_line_the_game_already_holds_is_kept(self) -> None:
        self.ctx.games.put_rom_alias.side_effect = FileExistsError

        adopt._bring_beside(self.ctx, "g1", self.game(), "t1", "taxi_l1", (), self.here)

        self.ctx.logger.warning.assert_not_called()

    def test_the_backglass_entry_is_the_tables_own_setting_by_its_id(self) -> None:
        adopt._bring_beside(self.ctx, "g1", self.game(), "t1", "taxi_l4", (), self.here)

        self.ctx.games.write_table_settings.assert_called_once_with(
            "t1", {GRILL: "1", DUAL: "2"})

    def _written_for(self, program: object) -> dict:
        self.ctx.games.table_program.return_value = program
        adopt._bring_beside(self.ctx, "g1", self.game(), "t1", "taxi_l4", (), self.here)
        return self.ctx.games.write_table_settings.call_args.args[1]

    def test_a_program_with_the_legacy_renderer_takes_every_setting(self) -> None:
        program = {"plugins": ["B2S", "B2SLegacy"], "build": 6200, "defaults": {}}

        self.assertEqual(self._written_for(program),
                         {GRILL: "1", DUAL: "2", "Plugin.B2S.DualMode": "2",
                          "Plugin.B2S.ShowGrill": "0"})

    def test_a_program_with_b2s_alone_takes_its_dual_mode_and_the_grill_inverted(self) -> None:
        program = {"plugins": ["B2S", "Nixie"], "build": 6300, "defaults": {}}

        self.assertEqual(self._written_for(program),
                         {"Plugin.B2S.DualMode": "2", "Plugin.B2S.ShowGrill": "0"})

    def test_a_grill_the_old_server_showed_is_shown_by_b2s(self) -> None:
        wanted = beside.for_program({GRILL: "0"}, {"plugins": ["B2S"]})

        self.assertEqual(wanted, {"Plugin.B2S.ShowGrill": "1"})

    def test_a_program_with_no_plugins_takes_nothing(self) -> None:
        self.ctx.games.table_program.return_value = {"plugins": [], "build": 6000,
                                                     "defaults": {}}
        adopt._bring_beside(self.ctx, "g1", self.game(), "t1", "taxi_l4", (), self.here)

        self.ctx.games.write_table_settings.assert_not_called()

    def test_a_program_that_cannot_be_asked_leaves_the_settings_as_they_were(self) -> None:
        unknown: list[dict | None] = [None, {"plugins": None, "build": None, "defaults": {}}]
        for program in unknown:
            with self.subTest(program=program):
                self.ctx.games.write_table_settings.reset_mock()

                self.assertEqual(self._written_for(program), {GRILL: "1", DUAL: "2"})

    def test_a_program_that_raises_leaves_the_settings_as_they_were(self) -> None:
        self.ctx.games.table_program.side_effect = RuntimeError("no launcher")
        adopt._bring_beside(self.ctx, "g1", self.game(), "t1", "taxi_l4", (), self.here)

        self.ctx.games.write_table_settings.assert_called_once_with(
            "t1", {GRILL: "1", DUAL: "2"})

    def test_the_files_name_is_tried_only_for_a_table_that_asks_for_no_rom(self) -> None:
        (self.tables / "B2STableSettings.xml").write_text(
            SETTINGS.replace("<Other>", "<Taxi>").replace("</Other>", "</Taxi>"),
            encoding="utf-8")
        here = self.read()

        adopt._bring_beside(self.ctx, "g1", self.game(), "t1", "other_rom", (), here)
        self.ctx.games.write_table_settings.assert_not_called()

        adopt._bring_beside(self.ctx, "g1", self.game(), "t1", "", (), here)
        self.ctx.games.write_table_settings.assert_called_once_with(
            "t1", {"Plugin.B2SLegacy.B2SHideDMD": "0"})

    def test_a_table_that_was_already_there_keeps_the_settings_it_has(self) -> None:
        adopt._bring_beside(self.ctx, "g1", self.game(), "", "taxi_l4", (), self.here)

        self.ctx.games.write_table_settings.assert_not_called()

    def test_settings_that_would_not_write_are_logged_and_the_rest_goes_on(self) -> None:
        self.ctx.games.write_table_settings.side_effect = OSError("read only")

        adopt._bring_beside(self.ctx, "g1", self.game(), "t1", "taxi_l4",
                            ("Granny.vbs",), self.here)

        self.ctx.logger.warning.assert_called_once()
        self.assertEqual(self.placed(), {("scripts", "Granny.vbs")})

    def test_a_game_with_no_rom_still_gets_its_scripts(self) -> None:
        adopt._bring_beside(self.ctx, "g1", self.game(), "t1", "", ("Granny.vbs",), self.here)

        self.ctx.games.put_rom_alias.assert_not_called()
        self.assertEqual(self.placed(), {("scripts", "Granny.vbs")})


class AliasedRomTests(BesideCase):
    def test_the_real_rom_is_brought_and_its_scores_follow_it(self) -> None:
        (self.install / "VPinMAME" / "VPMAlias.txt").write_text("taxi_l1,taxi_l4\n")
        (self.roms / "taxi_l4.zip").write_bytes(b"x")
        nvram = self.install / "VPinMAME" / "nvram"
        nvram.mkdir()
        (nvram / "taxi_l4.nv").write_bytes(b"x")
        here = self.read()
        game = SourceGame(key="Taxi", display_name="Taxi")
        row = {"music": 0, "pups": 0, "roms": 0, "altdata": 0, "scores": 0, "refused": []}

        adopt._bring_keyed(self.ctx, "g1", game, "Taxi", here.real_rom("taxi_l1") or "taxi_l1",
                           {"roms": str(self.roms)}, row, asked="taxi_l1")

        placed = {(call.args[1], call.args[2].name)
                  for call in self.ctx.games.put_asset.call_args_list}
        self.assertEqual(placed, {("rom", "taxi_l4.zip"), ("nvram", "taxi_l4.nv")})
        self.assertEqual(row["roms"], 1)


if __name__ == "__main__":
    unittest.main()
