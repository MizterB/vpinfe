"""The scores and saved files a game's source kept: what rides with a ROM, what a script names."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from common.extensions import host
from common.games import vpreg
from tests.support.ole import stg_bytes

host.Registry().load(host.BUNDLED_DIR / "library_importer")

from vpinfe_ext_library_importer import (  # noqa: E402
    adopt,
    saved,
)
from vpinfe_ext_library_importer import plan as plan_for  # noqa: E402
from vpinfe_ext_library_importer.source import (  # noqa: E402
    SourceGame,
    SourceLibrary,
    SourceSystem,
)


class ScoresCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.vp = self.root / "VPinMAME"
        self.ctx = mock.MagicMock()
        self.ctx.games.saved_sets.side_effect = lambda path: tuple(vpreg.sets_in(path))
        self.user = self.root / "User"
        self.user.mkdir()

    def made(self, *parts: str) -> Path:
        path = self.vp.joinpath(*parts) if parts[0] != "User" else self.root.joinpath(*parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
        return path

    def placed(self) -> set[tuple[str, str]]:
        return {(call.args[1], call.args[2].name)
                for call in self.ctx.games.put_asset.call_args_list}


class RidesWithTheRomTests(ScoresCase):
    def bring(self, rom: str = "taxi_l4") -> dict:
        row = {"music": 0, "pups": 0, "roms": 0, "altdata": 0, "scores": 0}
        game = SourceGame(key="Taxi", display_name="Taxi (Williams 1988)")
        adopt._bring_keyed(self.ctx, "g1", game, "Taxi (Williams 1988)", rom,
                           {"roms": str(self.vp / "roms")}, row)
        return row

    def test_scores_and_settings_come_with_the_rom_they_are_named_for(self) -> None:
        self.made("roms", "taxi_l4.zip")
        self.made("nvram", "taxi_l4.nv")
        self.made("cfg", "taxi_l4.cfg")
        self.made("nvram", "other.nv")

        row = self.bring()

        self.assertEqual((row["roms"], row["scores"]), (1, 2))
        self.assertEqual(self.placed(), {("rom", "taxi_l4.zip"), ("nvram", "taxi_l4.nv"),
                                         ("cfg", "taxi_l4.cfg")})

    def test_switching_scores_off_brings_the_rom_alone(self) -> None:
        self.made("roms", "taxi_l4.zip")
        self.made("nvram", "taxi_l4.nv")
        self.made("cfg", "taxi_l4.cfg")
        row = {"music": 0, "pups": 0, "roms": 0, "altdata": 0, "scores": 0}
        game = SourceGame(key="Taxi", display_name="Taxi (Williams 1988)")

        adopt._bring_keyed(self.ctx, "g1", game, "Taxi (Williams 1988)", "taxi_l4",
                           {"roms": str(self.vp / "roms")}, row, scores=False)

        self.assertEqual((row["roms"], row["scores"]), (1, 0))
        self.assertEqual(self.placed(), {("rom", "taxi_l4.zip")})

    def test_a_cfg_with_no_rom_stays_behind(self) -> None:
        self.made("roms", "other.zip")
        self.made("nvram", "taxi_l4.nv")
        self.made("cfg", "taxi_l4.cfg")

        row = self.bring()

        self.assertEqual((row["roms"], row["scores"]), (0, 0))
        self.ctx.games.put_asset.assert_not_called()

    def test_a_rom_that_would_not_go_leaves_its_scores_behind(self) -> None:
        self.made("roms", "taxi_l4.zip")
        self.made("nvram", "taxi_l4.nv")

        def refuse(game_id, kind, path, rom=""):
            if kind == "rom":
                raise OSError("disk full")

        self.ctx.games.put_asset.side_effect = refuse

        row = self.bring()

        self.assertEqual(row["scores"], 0)
        self.assertEqual({kind for kind, _ in self.placed()}, {"rom"})

    def test_a_rom_the_game_already_holds_still_takes_its_scores(self) -> None:
        self.made("roms", "taxi_l4.zip")
        self.made("nvram", "taxi_l4.nv")

        def held(game_id, kind, path, rom=""):
            if kind == "rom":
                raise FileExistsError

        self.ctx.games.put_asset.side_effect = held

        row = self.bring()

        self.assertEqual((row["roms"], row["scores"]), (0, 1))

    def test_the_default_cfg_stays_behind(self) -> None:
        self.made("roms", "taxi_l4.zip")
        self.made("cfg", "default.cfg")

        self.bring()

        self.assertEqual({kind for kind, _ in self.placed()}, {"rom"})

    def test_a_game_with_no_rom_gets_nothing(self) -> None:
        self.made("roms", "taxi_l4.zip")
        self.made("nvram", "taxi_l4.nv")

        self.assertEqual(self.bring(rom="")["scores"], 0)

    def test_files_in_another_case_are_found(self) -> None:
        self.made("roms", "TAXI_L4.ZIP")
        self.made("NVRAM", "Taxi_L4.NV")

        self.bring()

        self.assertIn(("nvram", "Taxi_L4.NV"), self.placed())


class SavedByTheScriptTests(ScoresCase):
    def setUp(self) -> None:
        super().setUp()
        (self.user / "Taxi Scores.txt").write_text("1")
        (self.user / "Shared.txt").write_text("2")
        (self.user / "Nobody.txt").write_text("3")
        (self.user / "VPReg.stg").write_bytes(
            stg_bytes({"Taxi": {"Hi": "5"}, "Other": {"Hi": "6"}}))
        self.kept = saved.read(self.ctx, str(self.user))

    def test_what_a_script_might_name_is_each_file_and_each_set(self) -> None:
        self.assertEqual(self.kept.names,
                         ("Nobody", "Other", "Shared", "Taxi", "Taxi Scores"))

    def test_the_stg_is_not_a_saved_file(self) -> None:
        self.assertNotIn("vpreg", self.kept.files)

    def test_a_folder_not_given_or_not_there_holds_nothing(self) -> None:
        self.assertEqual(saved.read(self.ctx, ""), saved.Saved())
        self.assertEqual(saved.read(self.ctx, str(self.root / "gone")), saved.Saved())

    def test_each_file_goes_to_the_game_whose_script_names_it(self) -> None:
        adopt._bring_scores(self.ctx, "g1", "", {}, self.kept, ("taxi scores", "Shared"))

        self.assertEqual(self.placed(), {("user", "Taxi Scores.txt"), ("user", "Shared.txt")})

    def test_a_file_no_script_names_stays_behind(self) -> None:
        adopt._bring_scores(self.ctx, "g1", "", {}, self.kept, ("Taxi Scores",))

        self.assertNotIn(("user", "Nobody.txt"), self.placed())

    def test_only_the_sets_a_script_names_are_written(self) -> None:
        brought = adopt._bring_scores(self.ctx, "g1", "", {}, self.kept, ("Taxi",))

        self.assertEqual(brought, 1)
        self.ctx.games.put_saved_sets.assert_called_once_with(
            "g1", str(self.user / "VPReg.stg"), ["Taxi"])

    def test_the_names_a_game_file_gave_reach_the_scores(self) -> None:
        self.ctx.games.add_table.return_value = {"companions": (), "rom": "",
                                                 "named": ("Shared",)}
        row = adopt._one(self.ctx, "pinballx", SourceGame(key="Taxi", table_file="/t/Taxi.vpx"),
                         (), "loc", sources={"user": str(self.user)}, saved_here=self.kept)

        self.assertEqual(row["scores"], 1)
        self.assertEqual(self.placed(), {("user", "Shared.txt")})
        self.assertEqual(self.ctx.games.add_table.call_args.kwargs["names"], self.kept.names)

    def test_a_folder_that_cannot_be_listed_holds_nothing(self) -> None:
        with mock.patch.object(saved.finding, "files", side_effect=PermissionError("no")):
            self.assertEqual(saved.read(self.ctx, str(self.user)).files, {})

    def test_nothing_named_places_nothing(self) -> None:
        self.assertEqual(adopt._bring_scores(self.ctx, "g1", "", {}, self.kept, ()), 0)
        self.ctx.games.put_asset.assert_not_called()
        self.ctx.games.put_saved_sets.assert_not_called()


class CountedTests(ScoresCase):
    def setUp(self) -> None:
        super().setUp()
        (self.vp / "roms").mkdir(parents=True)
        (self.vp / "roms" / "taxi_l4.zip").write_bytes(b"r" * 700)
        self.made("nvram", "taxi_l4.nv").write_bytes(b"n" * 50)
        self.made("cfg", "taxi_l4.cfg").write_bytes(b"c" * 30)
        (self.user / "Scores.txt").write_bytes(b"s" * 20)
        self.table = str(self.root / "Taxi.vpx")
        Path(self.table).write_bytes(b"t" * 1000)
        self.games = [SourceGame(key="Taxi", table_file=self.table)]

    def bytes_of(self, **more) -> int:
        return plan_for.bytes_to_copy(self.games, "pinballx", (), lambda path: [], **more)

    def test_scores_and_settings_count_with_the_rom(self) -> None:
        got = self.bytes_of(roms={self.table: "taxi_l4"}, roms_dir=str(self.vp / "roms"))

        self.assertEqual(got, 1000 + 700 + 50 + 30)

    def test_scores_without_a_rom_count_for_nothing(self) -> None:
        got = self.bytes_of(roms={self.table: "afm_113b"}, roms_dir=str(self.vp / "roms"))

        self.assertEqual(got, 1000)

    def test_a_saved_file_counts_for_the_game_that_names_it(self) -> None:
        kept = saved.read(self.ctx, str(self.user))

        self.assertEqual(self.bytes_of(named={self.table: ("scores",)}, saved=kept), 1020)
        self.assertEqual(self.bytes_of(named={self.table: ()}, saved=kept), 1000)

    def test_a_user_folder_beside_the_tables_is_found(self) -> None:
        (self.root / "Tables").mkdir()
        library = SourceLibrary(source_id="pinballx", root=str(self.root), systems=(
            SourceSystem(name="Visual Pinball X", games=(SourceGame(key="Taxi"),),
                         tables_dir=str(self.root / "Tables")),))

        found = {one.key: one for one in plan_for.derive_sources(library, {})}

        self.assertEqual(found["user"].path, str(self.user))
