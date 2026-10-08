"""Converting a source into entries, through the context and nothing else.

The importer holds no path of ours and opens no file of ours. Everything it does to the
library goes through what it was handed, which is the guarantee the whole model rests on
- so a wall it hits here is a gap in the contract rather than a special case to carve.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from fastapi.testclient import TestClient

import httpapi
from common import extensions
from common.extensions import host, store
from common.extensions.contract import ContractError
from common.games import game_repository
from tests.support.library import own_locations

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests" / "fixtures" / "pinballx"
BASE = "/ext/library_importer"
VPX = "Visual Pinball X"


class AdoptCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.library = self.root / "library"
        self.library.mkdir()

        self.locations = own_locations(self, self.root / "config")

        self.store = store.ExtensionStore(self.root)
        self.registry = host.Registry(self.store)
        extensions.set_registry(self.registry)
        self.addCleanup(extensions.set_registry, host.Registry())
        self.addCleanup(self.registry.clear)
        self.record = self.registry.load(host.BUNDLED_DIR / "library_importer")
        self.assertEqual(self.record.state, host.LOADED, self.record.reason)

        self.client = TestClient(httpapi.create_api_app(), raise_server_exceptions=False)
        self.client.put("/config/locations/one", json={"path": str(self.library)})
        self.client.put("/config", json={
            "settings": {"updates": {"new_games_location": "one"}}})
        game_repository.all_games(reload=True)
        self.addCleanup(game_repository.all_games, True)

        self.client.put(f"{BASE}/source", json={"path": str(FIXTURE)})

    def imported(self) -> dict:
        """Run the conversion on this thread, so the assertions are about a finished
        import rather than a race with one."""
        from vpinfe_ext_library_importer import adopt, pinballx

        library = pinballx.read(FIXTURE)
        return adopt.run(self.ctx(), library, [VPX])

    def ctx(self):
        """The context the host handed the extension, which is the only thing under
        test here - reaching past it is what the whole design forbids."""
        return self._ctx


class ImportTests(AdoptCase):
    def setUp(self) -> None:
        super().setUp()
        # The same context register() was given, so what the test drives is what runs.
        from common.extensions.context import ExtensionContext
        self._ctx = ExtensionContext(self.record.manifest, self.store,
                                     on_failure=lambda why: None)
        self._ctx.files.set_roots([str(FIXTURE)])

    def test_every_game_in_the_system_becomes_an_entry(self) -> None:
        report = self.imported()

        self.assertEqual(report["games"], 3)
        self.assertEqual(report["failed"], 0)

    def test_a_folder_is_named_the_way_our_own_are(self) -> None:
        """The source's description is already Title (Manufacturer Year), which is the
        convention we arrived at separately."""
        self.imported()

        self.assertTrue((self.library / "Attack from Mars (Bally 1995)").is_dir())
        self.assertTrue((self.library / "Taxi (Williams 1988)").is_dir())

    def test_what_the_source_knew_about_the_machine_comes_across(self) -> None:
        """The name is the machine, not the folder. PinballX has no title of its own, so
        without lifting one out of the description every imported game would repeat its
        manufacturer and year in the column beside the ones that hold them."""
        self.imported()
        game_repository.all_games(reload=True)

        rows = {row["name"]: row for row in self.client.get("/games").json()["games"]}
        afm = rows["Attack from Mars"]
        self.assertEqual(afm["manufacturer"], "Bally")
        self.assertEqual(afm["year"], "1995")
        self.assertEqual(afm["themes"], ["Aliens", "Outer Space"])

    def test_artwork_lands_in_our_slots(self) -> None:
        self.imported()

        folder = self.library / "Attack from Mars (Bally 1995)"
        landed = sorted(one.name for one in (folder / "medias").iterdir())
        self.assertTrue(any("Wheel" in one for one in landed), landed)
        self.assertTrue(any("Playfield" in one for one in landed), landed)

    def _planned(self, cleared: str, fill: bool = False, other_taxi: bool = False):
        """The fixture library with a game file and a backglass behind every game.

        `fill` plans against what the library holds, the way a second run does, with
        *Add what they are missing*. `other_taxi` gives Taxi a game file of another name.
        """
        import dataclasses

        from vpinfe_ext_library_importer import pinballx, plan

        read = pinballx.read(FIXTURE)
        files = self.root / "game files"
        files.mkdir(exist_ok=True)
        self._ctx.files.set_roots([str(FIXTURE), str(files)])

        def with_file(game):
            stem = game.display_name or game.key
            (files / f"{stem}.vpx").write_bytes(b"table")
            (files / f"{stem}.directb2s").write_bytes(b"beside it")
            if other_taxi and game.key == "Taxi":
                stem = "Taxi, the other build"
                (files / f"{stem}.vpx").write_bytes(b"another table")
            return dataclasses.replace(game, table_file=str(files / f"{stem}.vpx"))

        library = dataclasses.replace(read, systems=tuple(
            dataclasses.replace(one, games=tuple(with_file(game) for game in one.games))
            for one in read.systems))
        made = plan.build(library, self._ctx.games.existing() if fill else [],
                          systems=[VPX],
                          on_existing="fill" if fill else plan.DEFAULT_ON_EXISTING,
                          folder_name_for=self._ctx.games.folder_name_for,
                          source_id=library.source_id, kinds=self._ctx.games.kinds(),
                          companions_of=self._ctx.games.companions_of)
        made.sources = plan.derive_sources(library, {cleared: ""} if cleared else {})
        return library, made

    def _counts_with(self, cleared: str) -> dict[str, tuple[int, int, int]]:
        from vpinfe_ext_library_importer import adopt, plan

        library, made = self._planned(cleared)
        report = adopt.run(self._ctx, library, [VPX], "", made)
        return {row["key"]: (row["expected"], row["actual"], row["short"])
                for row in plan.against(plan.expected(made), report)}

    def test_a_cleared_media_source_brings_no_artwork_and_the_report_agrees(self) -> None:
        from vpinfe_ext_library_importer import plan

        self.assertGreater(plan.expected(self._planned("")[1])["media"], 0)

        self.assertEqual((0, 0, 0), self._counts_with("media")["media"])
        folder = self.library / "Attack from Mars (Bally 1995)"
        self.assertFalse((folder / "medias").exists() and any((folder / "medias").iterdir()))

    def test_a_cleared_tables_source_brings_no_game_files_and_the_report_agrees(self) -> None:
        from vpinfe_ext_library_importer import plan

        wanted = plan.expected(self._planned("")[1])
        self.assertGreater(wanted["tables"], 0)
        self.assertGreater(wanted["companions"], 0)

        counts = self._counts_with("tables")

        self.assertEqual((0, 0, 0), counts["tables"])
        self.assertEqual((0, 0, 0), counts["companions"])

    def test_a_kind_we_have_no_slot_for_is_reported_not_guessed_at(self) -> None:
        report = self.imported()
        rows = {row["key"]: row for row in report["rows"]}

        self.assertEqual(rows["Taxi"]["skipped_media"], [])

    def test_a_source_whose_tables_are_elsewhere_still_imports(self) -> None:
        """Entries with artwork and no game file, which the library has a word for."""
        report = self.imported()

        self.assertEqual(report["tables"], 0)
        self.assertEqual(report["games"], 3)

    def test_one_game_failing_does_not_stop_the_rest(self) -> None:
        """An import of six hundred stopping on the one folder somebody already had
        would be worse than useless."""
        (self.library / "Taxi (Williams 1988)").mkdir()

        report = self.imported()

        self.assertEqual(report["games"], 2)
        self.assertEqual(report["failed"], 1)
        failed = next(row for row in report["rows"] if row["key"] == "Taxi")
        self.assertEqual(failed["error"]["text"], "no folder could be made for it")
        self.assertEqual(f"Something is already at {self.library / 'Taxi (Williams 1988)'}",
                         failed["error"]["detail"])

    def _with_history(self, *rows: str):
        """The fixture with a GameStats.csv beside it, planned the way the extension
        plans an import."""
        from vpinfe_ext_library_importer import pinballx, plan

        source = self.root / "source"
        shutil.copytree(FIXTURE, source)
        (source / "GameStats.csv").write_bytes(
            "".join(f"{row}\n" for row in ("Game,Play Count,Is Favorite", *rows))
            .encode("utf-16"))
        self._ctx.files.set_roots([str(source)])
        library = pinballx.read(source)
        made = plan.build(library, [], systems=[VPX],
                          folder_name_for=self._ctx.games.folder_name_for,
                          source_id=library.source_id, kinds=self._ctx.games.kinds())
        return library, made

    def test_what_the_source_remembers_about_playing_comes_across(self) -> None:
        from vpinfe_ext_library_importer import adopt

        library, made = self._with_history("Taxi (Williams 1988).Visual Pinball X,33,")

        report = adopt.run(self._ctx, library, [VPX], "", made)

        taxi = next(row for row in report["rows"] if row["key"] == "Taxi")
        self.assertEqual(taxi["history"], 1)
        game = self.client.get(f"/games/{taxi['game_id']}").json()
        self.assertEqual(game["user"]["play_count"], 33)

    PLAYED = ("Taxi (Williams 1988).Visual Pinball X,33,",
              "Attack from Mars (Bally 1995).Visual Pinball X,5,",
              "Taxi 2 (Homebrew 2020).Visual Pinball X,,1",
              "Medieval Madness (Williams 1997).Visual Pinball X,12,")

    def _history_row(self, library, made) -> dict:
        from vpinfe_ext_library_importer import adopt, plan

        want = plan.expected(made)
        report = adopt.run(self._ctx, library, [VPX], "", made)
        return next(row for row in plan.against(want, report) if row["key"] == "history")

    def test_the_report_counts_the_games_whose_play_history_came_across(self) -> None:
        """Taxi 2 holds only a favorite, and the source has no Medieval Madness."""
        row = self._history_row(*self._with_history(*self.PLAYED))

        self.assertEqual((2, 2, 0), (row["expected"], row["actual"], row["short"]))
        self.assertEqual("Games with play history", row["label"])

    def test_a_game_that_does_not_come_across_leaves_its_play_history_short(self) -> None:
        (self.library / "Taxi (Williams 1988)").mkdir()

        row = self._history_row(*self._with_history(*self.PLAYED))

        self.assertEqual((2, 1, 1), (row["expected"], row["actual"], row["short"]))

    def test_running_it_twice_creates_nothing_the_second_time(self) -> None:
        """It only ever creates, so the second run has nowhere to put anything rather
        than quietly writing over the first."""
        self.imported()

        again = self.imported()

        self.assertEqual(again["games"], 0)
        self.assertEqual(again["failed"], 3)

    def test_adding_what_a_copy_is_missing_fills_it_and_replaces_nothing(self) -> None:
        """A matched game is filled at its own id: an empty slot is filled, a held one
        is left, and a game file joins only where none of that name is there."""
        from vpinfe_ext_library_importer import adopt

        library, made = self._planned("")
        self.assertEqual(0, adopt.run(self._ctx, library, [VPX], "", made)["failed"])
        afm = self.library / "Attack from Mars (Bally 1995)"
        taxi = self.library / "Taxi (Williams 1988)"
        kept = next((taxi / "medias").iterdir())
        kept.write_bytes(b"what somebody chose")
        shutil.rmtree(afm / "medias")
        (taxi / "Taxi.vpx").write_bytes(b"edited since")

        library, made = self._planned("", fill=True, other_taxi=True)
        report = adopt.run(self._ctx, library, [VPX], "", made)

        self.assertEqual(0, report["failed"], [row["error"] for row in report["rows"]])
        self.assertTrue(all(row["game_id"] for row in report["rows"]))
        self.assertTrue(any("Playfield" in one.name for one in (afm / "medias").iterdir()))
        self.assertEqual(b"what somebody chose", kept.read_bytes())
        self.assertEqual(b"edited since", (taxi / "Taxi.vpx").read_bytes())
        self.assertEqual(b"another table", (taxi / "Taxi, the other build.vpx").read_bytes())
        rows = {row["key"]: row for row in report["rows"]}
        self.assertFalse(rows["Attack from Mars (Bally 1995)"]["table"])
        self.assertTrue(rows["Taxi"]["table"])

    def test_a_second_run_fills_nothing_that_is_already_there(self) -> None:
        from vpinfe_ext_library_importer import adopt

        library, made = self._planned("")
        adopt.run(self._ctx, library, [VPX], "", made)

        library, made = self._planned("", fill=True)
        again = adopt.run(self._ctx, library, [VPX], "", made)

        self.assertEqual(0, again["failed"])
        self.assertEqual((0, 0, 0), (again["tables"], again["media"], again["companions"]))

    def _filled_with(self, *rows: str):
        """The fixture and a GameStats.csv, planned against what the library holds."""
        from vpinfe_ext_library_importer import pinballx, plan

        source = self.root / "source"
        shutil.rmtree(source, ignore_errors=True)
        shutil.copytree(FIXTURE, source)
        (source / "GameStats.csv").write_bytes(
            "".join(f"{row}\n" for row in ("Game,Play Count,Is Favorite", *rows))
            .encode("utf-16"))
        self._ctx.files.set_roots([str(source)])
        library = pinballx.read(source)
        made = plan.build(library, self._ctx.games.existing(), systems=[VPX],
                          on_existing="fill",
                          folder_name_for=self._ctx.games.folder_name_for,
                          source_id=library.source_id, kinds=self._ctx.games.kinds(),
                          companions_of=self._ctx.games.companions_of)
        return library, made

    def test_filling_adds_the_history_a_game_lacks_and_keeps_what_it_has(self) -> None:
        from vpinfe_ext_library_importer import adopt

        library, made = self._with_history("Taxi (Williams 1988).Visual Pinball X,33,")
        report = adopt.run(self._ctx, library, [VPX], "", made)
        taxi_id = next(row["game_id"] for row in report["rows"] if row["key"] == "Taxi")
        afm_id = next(row["game_id"] for row in report["rows"]
                      if row["key"].startswith("Attack"))
        self._ctx.games.set_play_record(taxi_id, play_count=40)

        library, made = self._filled_with(
            "Taxi (Williams 1988).Visual Pinball X,99,",
            "Attack from Mars (Bally 1995).Visual Pinball X,5,1")
        again = adopt.run(self._ctx, library, [VPX], "", made)

        self.assertEqual(0, again["failed"])
        users = {one: self.client.get(f"/games/{one}").json()["user"]
                 for one in (taxi_id, afm_id)}
        self.assertEqual(40, users[taxi_id]["play_count"])
        self.assertEqual(5, users[afm_id]["play_count"])
        self.assertTrue(users[afm_id]["favorite"])

    def test_a_fill_over_a_complete_library_fills_nothing(self) -> None:
        from vpinfe_ext_library_importer import adopt

        library, made = self._with_history("Taxi (Williams 1988).Visual Pinball X,33,")
        adopt.run(self._ctx, library, [VPX], "", made)

        library, made = self._filled_with("Taxi (Williams 1988).Visual Pinball X,33,")
        again = adopt.run(self._ctx, library, [VPX], "", made)

        self.assertEqual((0, 0), (again["filled"], again["failed"]))

    def test_a_refused_tag_does_not_keep_the_rest_of_the_history_back(self) -> None:
        from vpinfe_ext_library_importer import adopt, plan

        library, made = self._planned("")
        report = adopt.run(self._ctx, library, [VPX], "", made)
        game_id = report["rows"][0]["game_id"]
        adds = plan.Missing(counters={"play_count": 7}, tags=("Odd",), rating=3)

        with unittest.mock.patch.object(self._ctx.games, "set_tags",
                                        side_effect=ValueError("derived")), \
                self.assertLogs(self._ctx.logger, "WARNING"):
            counted = adopt._add_missing(self._ctx, game_id, adds, plan.Held())

        user = self.client.get(f"/games/{game_id}").json()["user"]
        self.assertEqual((1, 7, 3), (counted, user["play_count"], user["rating"]))

    def test_filling_takes_the_rom_from_the_game_it_fills(self) -> None:
        """The game file is held and does not arrive again, so the ROM comes from the
        game; without it nothing keyed on the ROM is placed."""
        from vpinfe_ext_library_importer import adopt, plan

        library, made = self._planned("")
        adopt.run(self._ctx, library, [VPX], "", made)
        library, made = self._planned("", fill=True)
        for one in made.sources:
            if one.key == "roms":
                one.path = "/roms"

        with unittest.mock.patch.object(
                adopt, "_held", return_value=plan.Held(rom="taxi_l4")), \
                unittest.mock.patch.object(adopt, "_bring_rom", return_value=1) as bring:
            report = adopt.run(self._ctx, library, [VPX], "", made)

        self.assertEqual(0, report["failed"])
        self.assertEqual({"taxi_l4"}, {call.args[2] for call in bring.call_args_list})
        self.assertEqual(3, report["roms"])


class BoundsTests(AdoptCase):
    def setUp(self) -> None:
        super().setUp()
        from common.extensions.context import ExtensionContext
        self._ctx = ExtensionContext(self.record.manifest, self.store,
                                     on_failure=lambda why: None)

    def test_a_file_outside_what_it_declared_is_refused(self) -> None:
        """Tighter than the same check on a route, and it can be: this one knows which
        extension is asking."""
        self._ctx.files.set_roots([str(self.root / "somewhere-else")])
        game_id = self._ctx.games.create("Probe")
        stray = self.root / "stray.png"
        stray.write_bytes(b"art")

        with self.assertRaises(ContractError):
            self._ctx.games.put_media(game_id, "wheel", stray)

    def test_a_scope_the_manifest_never_declared_is_refused(self) -> None:
        """Which is what makes declaring them mean something."""
        from common.extensions.games import ExtensionGames

        modest = ExtensionGames("modest", ("games:read",), self._ctx.files)

        with self.assertRaises(ContractError):
            modest.create("Probe")

    def test_an_unknown_media_kind_is_refused(self) -> None:
        self._ctx.files.set_roots([str(FIXTURE)])
        game_id = self._ctx.games.create("Probe")
        art = (FIXTURE / "Media" / VPX / "Wheel Images"
               / "Attack from Mars (Bally 1995).png")

        with self.assertRaises(ValueError):
            self._ctx.games.put_media(game_id, "hologram", art)


class FolderNameTests(unittest.TestCase):
    """The folder a name becomes is core's rule, and the importer asks rather than
    reproduces it.

    A real library held both `Star Trek: The Next Generation (Williams 1993)` and
    `Star Trek - The Next Generation (Williams 1993)`. Core strips the colon, so the
    first two are one folder; the importer's own copy of the rule did not, so it thought
    they were two and the second failed on a name already taken.
    """

    def test_core_answers_what_a_name_becomes(self) -> None:
        from common.extensions.games import ExtensionGames

        games = ExtensionGames("probe", ("games:read",), None)

        self.assertEqual(
            games.folder_name_for("Star Trek: The Next Generation (Williams 1993)"),
            "Star Trek The Next Generation (Williams 1993)")

    def test_reading_a_name_is_a_read(self) -> None:
        """It tells an extension what core would do, so it is gated like anything else
        that reads."""
        from common.extensions.games import ExtensionGames

        with self.assertRaises(ContractError):
            ExtensionGames("silent", (), None).folder_name_for("Anything")


class CompanionTests(unittest.TestCase):
    """A table's backglass and settings come with it.

    Measured on a real library: 696 of 702 tables had a `.directb2s` beside them and 704
    had an `.ini`. Bringing the `.vpx` alone left every one of those behind, which is a
    game with no backglass - the single largest thing the import was losing.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.source = self.root / "Tables"
        self.source.mkdir()

    def _table(self, stem: str, *companions: str) -> Path:
        table = self.source / f"{stem}.vpx"
        table.write_bytes(b"table")
        for one in companions:
            (self.source / one).write_bytes(b"beside it")
        return table

    def test_what_travels_with_a_table(self) -> None:
        from common.games.game_service import companions_beside

        table = self._table("Taxi (Williams 1988)",
                            "Taxi (Williams 1988).directb2s",
                            "Taxi (Williams 1988).ini",
                            "Taxi (Williams 1988).vbs",
                            "Taxi (Williams 1988).pov")

        found = {one.name for one in companions_beside(table)}

        self.assertEqual(len(found), 4)
        self.assertIn("Taxi (Williams 1988).directb2s", found)

    def test_a_neighbour_is_not_a_companion(self) -> None:
        """Matched on the exact stem, or `Taxi.vpx` collects `Taxi 2`'s backglass."""
        from common.games.game_service import companions_beside

        table = self._table("Taxi", "Taxi.directb2s")
        (self.source / "Taxi 2.directb2s").write_bytes(b"another game")

        found = {one.name for one in companions_beside(table)}

        self.assertEqual(found, {"Taxi.directb2s"})

    def test_something_that_is_not_a_companion_kind_stays(self) -> None:
        """The list is the one the export bundle ships, because these are the same
        question asked in two directions."""
        from common.games.game_service import companions_beside

        table = self._table("Taxi", "Taxi.directb2s", "Taxi.png", "Taxi.txt")

        found = {one.name for one in companions_beside(table)}

        self.assertEqual(found, {"Taxi.directb2s"})


class RowShapeTests(unittest.TestCase):
    """Every row the run produces has the same keys.

    The report sums across all of them, so one row built somewhere else and missing a
    key fails the whole import at the end - after the copying, which is the worst moment
    to find out. It happened: a second build of a machine builds its own row, and only
    the first path had been taught the new counts.
    """

    def test_both_kinds_of_row_carry_the_same_counts(self) -> None:
        import inspect

        from extensions.library_importer import adopt

        source = inspect.getsource(adopt)
        rows = [one for one in source.splitlines() if '"key": game.key, "name": name' in one]
        self.assertEqual(len(rows), 2, "expected one row shape per path")

        counted = ("media", "companions", "roms", "altdata")
        for name in ("_one", "_another_build"):
            body = inspect.getsource(getattr(adopt, name))
            for key in counted:
                with self.subTest(function=name, key=key):
                    self.assertIn(f'"{key}"', body)


if __name__ == "__main__":
    unittest.main()
