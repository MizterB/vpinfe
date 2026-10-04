"""What an import would do, before it does any of it.

Two things this holds. Every source is an option with a derived default, so "no ROMs came
across" is something somebody chose and can see they chose. And an import can be run more
than once - a first pass fails partway, or the games come now and the ROMs when the old
machine is back - so what is already here is recognized rather than collided with.
"""

from __future__ import annotations

import tempfile
import unittest
import unittest.mock
from pathlib import Path

from common.extensions import host

host.Registry().load(host.BUNDLED_DIR / "library_importer")

from vpinfe_ext_library_importer import plan as plan_for  # noqa: E402
from vpinfe_ext_library_importer.source import (  # noqa: E402
    SourceGame,
    SourceLibrary,
    SourceMedia,
    SourceSystem,
)


def _library(*games, tables_dir="/src/tables", roms="/src/roms"):
    return SourceLibrary(source_id="pinballx", root="/src", systems=(
        SourceSystem(name="Visual Pinball X", games=tuple(games),
                     tables_dir=tables_dir, working_path=roms),))


def _game(key, **fields):
    fields.setdefault("display_name", key)
    return SourceGame(key=key, **fields)


class SourceTests(unittest.TestCase):
    def test_what_can_be_worked_out_is_the_default(self) -> None:
        library = _library(_game("Taxi", media=(
            SourceMedia(source_kind="Wheel Images", path="/src/Media/VPX/Wheel/Taxi.png"),)))

        found = {one.key: one for one in plan_for.derive_sources(library)}

        self.assertEqual(found["tables"].path, "/src/tables")
        self.assertTrue(found["tables"].derived)
        self.assertTrue(found["media"].derived)

    def test_a_kind_with_nowhere_to_go_is_not_offered(self) -> None:
        """A field that carries nothing is a promise the code cannot keep. Registry
        settings have no destination on this platform at all - VPinMAME's per-ROM values
        live in memory and nothing persists them - so they are read and not offered."""
        found = {one.key for one in plan_for.derive_sources(_library())}

        self.assertNotIn("registry", found)
        self.assertIn("roms", found)

    def test_what_the_user_said_wins(self) -> None:
        found = {one.key: one for one in
                 plan_for.derive_sources(_library(_game("Taxi")),
                                         {"tables": "/elsewhere"})}

        self.assertEqual(found["tables"].path, "/elsewhere")
        self.assertFalse(found["tables"].derived)

    def test_clearing_one_is_how_somebody_says_not_that(self) -> None:
        """An empty source means that kind is not imported. It has to be reachable, or
        a derived guess cannot be refused."""
        found = {one.key: one for one in
                 plan_for.derive_sources(_library(_game("Taxi")), {"tables": ""})}

        self.assertFalse(found["tables"].active)


class MatchTests(unittest.TestCase):
    HELD = [{"game_id": "g1", "folder_name": "Taxi (Williams 1988)",
             "name": "Taxi", "vps_id": "vps-taxi"}]

    def test_a_game_a_previous_run_made_is_recognized_by_its_folder(self) -> None:
        library = _library(_game("Taxi", display_name="Taxi (Williams 1988)"))

        found = plan_for.match_existing(library, self.HELD)

        self.assertTrue(found[0].existing)
        self.assertEqual(found[0].how, "folder")

    def test_one_renamed_since_is_still_recognized(self) -> None:
        """A rename should not turn one game into two."""
        library = _library(_game("Taxi", display_name="Taxi, the good one",
                                 vps_id="vps-taxi"))

        found = plan_for.match_existing(library, self.HELD)

        self.assertTrue(found[0].existing)
        self.assertEqual(found[0].how, "vps_id")

    def test_a_game_nothing_here_matches_is_new(self) -> None:
        found = plan_for.match_existing(_library(_game("Funhouse")), self.HELD)

        self.assertFalse(found[0].existing)


class ExpectedTests(unittest.TestCase):
    KINDS = ("playfield", "wheel")

    def _plan(self, library, held=(), **fields):
        """Built the way the extension builds it: the counts a report compares against
        are worked out while each game is in hand, so the plan needs to know what a
        media kind is."""
        fields.setdefault("source_id", "pinballx")
        fields.setdefault("kinds", self.KINDS)
        return plan_for.build(library, list(held), **fields)

    def test_it_counts_what_the_run_will_act_on(self) -> None:
        library = _library(
            _game("Taxi", table_file="/src/tables/Taxi.vpx", rom="taxi_l4",
                  media=(SourceMedia(source_kind="Wheel Images", path="/w/Taxi.png"),)),
            _game("Funhouse", table_file="/src/tables/Funhouse.vpx"))

        counts = plan_for.expected(self._plan(library))

        self.assertEqual(counts["games"], 2)
        self.assertEqual(counts["tables"], 2)
        self.assertEqual(counts["media"], 1)

    def test_several_builds_of_one_machine_are_one_game(self) -> None:
        """A real library held three of Kiss (Bally 1979) by different authors, and 34
        colliding folder names across 656 games. They are one game with three tables
        here, so the count has to say one - a plan promising three reports a shortfall
        for behaving correctly."""
        library = _library(
            _game("Kiss (Bally 1979)", table_file="/src/a.vpx"),
            _game("Kiss (Bally 1979)", table_file="/src/b.vpx"),
            _game("Kiss (Bally 1979)", table_file="/src/c.vpx"))

        counts = plan_for.expected(self._plan(library))

        self.assertEqual(counts["games"], 1)
        self.assertEqual(counts["tables"], 3)

    def test_only_the_first_build_brings_artwork(self) -> None:
        """The rest are the same table photographed twice, and the run does not place
        them - so counting them promises files that never arrive."""
        art = (SourceMedia(source_kind="Wheel Images", path="/w/Kiss.png"),)
        library = _library(
            _game("Kiss (Bally 1979)", table_file="/src/a.vpx", media=art),
            _game("Kiss (Bally 1979)", table_file="/src/b.vpx", media=art))

        counts = plan_for.expected(self._plan(library))

        self.assertEqual(counts["media"], 1)

    def test_two_games_with_the_same_key_are_both_counted(self) -> None:
        """A real source held two entries with byte-identical name attributes. Keyed on
        that, a dict silently keeps one, and the run then does more than the plan said."""
        library = _library(
            _game("Alpha", table_file="/src/a.vpx"),
            _game("Beta", table_file="/src/b.vpx"))
        same = [one for one in library.games]
        self.assertEqual(len({one.key for one in same}), 2)

        counts = plan_for.expected(self._plan(library))

        self.assertEqual(counts["tables"], 2)

    def test_a_quote_a_filesystem_cannot_keep_does_not_make_a_second_game(self) -> None:
        """A real library held `'300' (Gottlieb 1975)` where the source called it
        `"300" (Gottlieb 1975)`. The quote is the only difference, and a filesystem
        substitutes one for the other - matched literally, the machine ends up with the
        game twice."""
        library = _library(_game('"300"', display_name='"300" (Gottlieb 1975)',
                                 table_file="/src/tables/300.vpx"))
        held = [{"game_id": "g1", "folder_name": "'300' (Gottlieb 1975)",
                 "name": "300", "vps_id": ""}]

        made = self._plan(library, held)

        self.assertEqual(len(made.already), 1)
        self.assertEqual(made.new, [])

    def test_two_machines_whose_names_differ_stay_two(self) -> None:
        """The line this stops at: stripping punctuation generally would make Taxi and
        Taxi 2 one game, and merging two machines is worse than holding a duplicate."""
        library = _library(_game("Taxi", display_name="Taxi",
                                 table_file="/src/tables/Taxi.vpx"))
        held = [{"game_id": "g1", "folder_name": "Taxi 2", "name": "Taxi 2",
                 "vps_id": ""}]

        made = self._plan(library, held)

        self.assertEqual(made.already, [])
        self.assertEqual(len(made.new), 1)

    def test_a_source_nobody_set_contributes_nothing(self) -> None:
        """And says zero rather than being left out - an absent row reads as an
        oversight where a zero reads as a decision."""
        library = _library(_game("Taxi", rom="taxi_l4"))

        counts = plan_for.expected(
            self._plan(library, chosen={"media": ""}))

        self.assertEqual(counts["media"], 0)

    def test_a_kind_with_nowhere_to_go_is_not_offered(self) -> None:
        """Registry settings are read and not offered: nothing on this platform reads
        per-ROM VPinMAME values back, so anything written would be consumed by nothing."""
        offered = set(plan_for.SOURCES)

        self.assertNotIn("registry", offered)
        self.assertIn("registry", plan_for.NOT_YET)
        # And what does have somewhere to go is offered.
        self.assertIn("roms", offered)

    def test_games_already_here_are_not_counted_unless_they_are_being_filled(self) -> None:
        library = _library(_game("Taxi", display_name="Taxi (Williams 1988)",
                                 table_file="/src/tables/Taxi.vpx"))
        held = [{"game_id": "g1", "folder_name": "Taxi (Williams 1988)",
                 "name": "Taxi", "vps_id": ""}]

        skipping = plan_for.expected(self._plan(library, held))
        filling = plan_for.expected(self._plan(library, held, on_existing="fill"))

        self.assertEqual(skipping["games"], 0)
        self.assertEqual(filling["games"], 1)

    def _stats(self, *rows: str) -> dict:
        """A GameStats.csv holding these rows, chosen as the play history source."""
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "GameStats.csv"
        path.write_text("".join(f"{row}\n" for row in ("Game,Play Count,Is Favorite",
                                                        *rows)), encoding="utf-8")
        return {"history": str(path)}

    def test_a_game_the_play_history_names_is_counted(self) -> None:
        library = _library(_game("Taxi", display_name="Taxi (Williams 1988)"),
                           _game("Funhouse", display_name="Funhouse (Williams 1990)"))
        chosen = self._stats("Taxi (Williams 1988).Visual Pinball X,33,",
                             "Medieval Madness (Williams 1997).Visual Pinball X,12,")

        counts = plan_for.expected(self._plan(library, chosen=chosen))

        self.assertEqual(counts["history"], 1)

    def test_a_machine_brings_its_play_history_once(self) -> None:
        library = _library(
            _game("Kiss (Bally 1979)", table_file="/src/a.vpx"),
            _game("Kiss (Bally 1979)", table_file="/src/b.vpx"))
        chosen = self._stats("Kiss (Bally 1979).Visual Pinball X,7,")

        counts = plan_for.expected(self._plan(library, chosen=chosen))

        self.assertEqual(counts["history"], 1)

    def test_a_game_left_alone_brings_no_play_history(self) -> None:
        library = _library(_game("Taxi", display_name="Taxi (Williams 1988)"))
        held = [{"game_id": "g1", "folder_name": "Taxi (Williams 1988)",
                 "name": "Taxi", "vps_id": ""}]
        chosen = self._stats("Taxi (Williams 1988).Visual Pinball X,33,")

        skipping = plan_for.expected(self._plan(library, held, chosen=chosen))
        filling = plan_for.expected(self._plan(library, held, chosen=chosen,
                                               on_existing="fill"))

        self.assertEqual(skipping["history"], 0)
        self.assertEqual(filling["history"], 1)

    def test_a_row_holding_only_a_favorite_is_not_counted(self) -> None:
        library = _library(_game("Taxi", display_name="Taxi (Williams 1988)"))
        chosen = self._stats("Taxi (Williams 1988).Visual Pinball X,,1")

        counts = plan_for.expected(self._plan(library, chosen=chosen))

        self.assertEqual(counts["history"], 0)

    def test_leaving_them_alone_is_the_default(self) -> None:
        """Rewriting what somebody has curated since the last run is the worse
        mistake."""
        self.assertEqual(plan_for.build(_library(), []).on_existing, "skip")


class ComparisonTests(unittest.TestCase):
    def test_expected_and_actual_come_back_together(self) -> None:
        rows = {one["key"]: one for one in
                plan_for.against({"games": 8, "media": 20}, {"games": 7, "media": 20})}

        self.assertEqual(rows["games"]["short"], 1)
        self.assertEqual(rows["media"]["short"], 0)

    def test_every_row_is_reported_not_only_the_short_ones(self) -> None:
        """A line that appears only when something went wrong makes a clean import read
        as a report with things missing from it."""
        rows = plan_for.against({"games": 3}, {"games": 3})

        self.assertEqual(len(rows), len(plan_for.COUNTS))


class SpaceTests(unittest.TestCase):
    """What a run writes and whether there is room for it, said before it writes any."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / "Harbor Lights.vpx").write_bytes(b"t" * 1000)
        (self.root / "Harbor Lights.directb2s").write_bytes(b"b" * 500)
        (self.root / "Quarry Run.vpx").write_bytes(b"t" * 2000)
        (self.root / "wheel.png").write_bytes(b"w" * 40)
        self.games = [
            SourceGame(key="Harbor Lights", table_file=str(self.root / "Harbor Lights.vpx"),
                       media=(SourceMedia(source_kind="Wheel Images",
                                          path=str(self.root / "wheel.png")),)),
            SourceGame(key="Quarry Run", table_file=str(self.root / "Quarry Run.vpx"))]

    def _companions(self, table_file: str) -> list[str]:
        stem = Path(table_file).stem
        return sorted(one.name for one in self.root.iterdir()
                      if one.stem == stem and one.suffix != ".vpx")

    def _bytes(self, **more) -> int:
        return plan_for.bytes_to_copy(self.games, "pinballx", ("wheel",),
                                      self._companions, **more)

    def test_a_copy_counts_the_game_file_what_rides_with_it_and_the_artwork(self) -> None:
        self.assertEqual(self._bytes(), 1000 + 500 + 2000 + 40)

    def test_a_move_counts_only_the_artwork(self) -> None:
        """The game files are not written again; they change folders."""
        self.assertEqual(self._bytes(move=True), 40)

    def test_a_file_that_is_gone_counts_for_nothing(self) -> None:
        (self.root / "Quarry Run.vpx").unlink()

        self.assertEqual(self._bytes(), 1000 + 500 + 40)

    def test_a_source_with_no_game_file_counts_its_artwork_alone(self) -> None:
        self.games[0] = SourceGame(key="Harbor Lights", media=self.games[0].media)

        self.assertEqual(self._bytes(), 2000 + 40)

    def test_games_are_made_where_the_game_files_are(self) -> None:
        """A source can name a folder its tables are not in, and moving into that one
        would put the folders somewhere the files never were."""
        library = SourceLibrary(source_id="emulationstation", root=str(self.root), systems=(
            SourceSystem(name="x", games=tuple(self.games), tables_dir="/elsewhere"),))

        self.assertEqual(plan_for.tables_folder(library.systems[0]), str(self.root))

    def test_game_files_in_several_folders_fall_back_to_the_one_the_source_names(self) -> None:
        elsewhere = SourceGame(key="Orchard", table_file="/else/Orchard.vpx")
        system = SourceSystem(name="x", games=(*self.games, elsewhere), tables_dir="/named")

        self.assertEqual(plan_for.tables_folder(system), "/named")

    def test_a_system_with_no_game_files_has_the_folder_it_was_told(self) -> None:
        system = SourceSystem(name="x", games=(SourceGame(key="Orchard"),),
                              tables_dir="/named")

        self.assertEqual(plan_for.tables_folder(system), "/named")

    def test_a_listed_file_that_is_gone_has_nothing_riding_with_it(self) -> None:
        """A frontend's list outlives the files it names."""
        def refusing(path: str) -> list[str]:
            raise FileNotFoundError(path)

        gone = [SourceGame(key="Taxi", table_file=str(self.root / "Taxi.vpx"))]

        self.assertEqual(plan_for.bytes_to_copy(gone, "pinballx", (), refusing), 0)

    def test_sizes_read_in_the_unit_a_person_would_say(self) -> None:
        self.assertEqual(plan_for.size_of(0), "0 B")
        self.assertEqual(plan_for.size_of(1023), "1023 B")
        self.assertEqual(plan_for.size_of(1024), "1.0 KB")
        self.assertEqual(plan_for.size_of(3500), "3.4 KB")
        self.assertEqual(plan_for.size_of(5 * 1024 ** 2), "5.0 MB")
        self.assertEqual(plan_for.size_of(int(2.5 * 1024 ** 3)), "2.5 GB")
        self.assertEqual(plan_for.size_of(3 * 1024 ** 4), "3.0 TB")

    def test_there_is_always_a_unit_to_say_it_in(self) -> None:
        self.assertTrue(plan_for.size_of(5000 * 1024 ** 4).endswith("TB"))

    def test_room_is_asked_of_the_nearest_folder_that_exists(self) -> None:
        free, where = plan_for.room_at(str(self.root / "not" / "made" / "yet"))

        self.assertGreater(free, 0)
        self.assertTrue(where)

    def test_room_that_cannot_be_told_is_minus_one(self) -> None:
        with unittest.mock.patch.object(plan_for.shutil, "disk_usage", side_effect=OSError):
            self.assertEqual(plan_for.room_at(str(self.root)), (-1, ""))


if __name__ == "__main__":
    unittest.main()
