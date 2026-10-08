"""A folder of tables, brought in as it is laid out, copied or moved.

Nothing here is a frontend: the layout is the source. Looking comes first - a game folder
is used where it is, a loose table gets a folder - and only then is anything asked, which
is how a table gets carried (copied or moved) and where the copies go.

Two things are pinned that are easy to lose. The wizard's questions follow from what was
found, so the steps are walked the way somebody pressing Next walks them. And a move
writes to the source, which the importer used never to do, so every test of one checks
what is left behind as well as what arrived.
"""

from __future__ import annotations

import os
import shutil
import time
import unittest
from pathlib import Path
from unittest import mock

from common import jobs
from common.games import library_folders, tables
from tests.importer import test_adopt
from tests.support.skips import needs_posix_permissions

REPO = Path(__file__).resolve().parents[2]
EMULATIONSTATION = REPO / "tests" / "fixtures" / "emulationstation"
BASE = test_adopt.BASE


class FolderCase(test_adopt.AdoptCase):
    """A library to import into, and a folder of tables to import from."""

    def setUp(self) -> None:
        super().setUp()
        self.tables = self.root / "Tables"
        self.tables.mkdir()
        # Parsing a stand-in table would only complain that it is not one.
        patcher = mock.patch("common.games.library_enrichment.read_one", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def loose(self, *names: str, size: int = 100, where: Path | None = None) -> None:
        for name in names:
            (where or self.tables).joinpath(f"{name}.vpx").write_bytes(b"t" * size)

    def a_frontend(self) -> tuple[Path, Path]:
        """A PinballX install, and the folder its config names with one real game file in
        it. The fixture alone lists games and holds none."""
        source = self.root / "PX"
        shutil.copytree(test_adopt.FIXTURE, source)
        held = self.root / "held"
        held.mkdir()
        (held / "Taxi.vpx").write_bytes(b"table")
        ini = source / "Config" / "PinballX.ini"
        ini.write_bytes(ini.read_bytes().decode("utf-16")
                        .replace("C:\\Visual Pinball\\tables", str(held)).encode("utf-16"))
        return source, held

    def game_folder(self, name: str) -> Path:
        folder = self.tables / name
        folder.mkdir()
        (folder / f"{name}.vpx").write_bytes(b"table")
        return folder

    def step(self, path: Path | str, leaving: str = "source", **values) -> dict:
        found = self.client.post(f"{BASE}/wizard/check",
                                 json={"values": {"path": str(path), **values},
                                       "step": leaving})
        self.assertEqual(found.status_code, 200, found.text)
        return found.json()

    def summary_of(self, found: dict) -> dict[str, str]:
        return {row[0]: row[1] for row in found["summary"] if len(row) == 2}

    def run_it(self, path: Path | str, **values) -> dict:
        """Start the import and wait for the job, answering with what it reported."""
        started = self.client.post(f"{BASE}/wizard/run",
                                   json={"values": {"path": str(path), **values}})
        self.assertEqual(started.status_code, 202, started.text)
        self.assertTrue(started.json()["started"], started.json())
        job_id = started.json()["job_id"]
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            job = jobs.get(job_id)
            if job is not None and job.finished_at is not None:
                self.assertEqual(job.state, jobs.DONE, job.error)
                assert isinstance(job.result, dict)
                self.job = job
                return job.result
            time.sleep(0.01)
        self.fail("the import did not finish")

    def refused_run(self, **values) -> dict:
        """Ask for an import that must not start, answering with what was said."""
        started = self.client.post(f"{BASE}/wizard/run",
                                   json={"values": {"path": str(self.tables), **values}})
        self.assertEqual(started.status_code, 202, started.text)
        found = started.json()
        self.assertIs(found["started"], False, found)
        self.assertIs(found["ok"], False, found)
        self.assertTrue(found["reason"], found)
        self.assertNotIn("job_id", found)
        return found

    def games_held(self) -> list[str]:
        from common.games import game_repository

        game_repository.all_games(reload=True)
        return sorted(row["name"] for row in self.client.get("/games").json()["games"])

    def locations_held(self) -> list[str]:
        return [str(Path(one["path"]).resolve())
                for one in self.client.get("/locations").json()["locations"]]


class ReaderTests(FolderCase):
    def setUp(self) -> None:
        super().setUp()
        from vpinfe_ext_library_importer import api, folders

        from common.games import tables

        self.survey = tables.survey
        self.folders = folders
        self.api = api

    def test_a_loose_table_is_a_game_keyed_on_its_filename(self) -> None:
        self.loose("Harbor Lights", "Quarry Run")

        found = self.folders.read(self.tables, survey=self.survey)

        self.assertEqual([one.key for one in found.games], ["Harbor Lights", "Quarry Run"])
        self.assertEqual(found.games[0].table_file, str(self.tables / "Harbor Lights.vpx"))
        self.assertEqual(list(found.in_place), [])

    def test_a_game_folder_is_named_and_not_read_as_a_game(self) -> None:
        """It is already a game. Reading it as one would make a folder inside it."""
        self.game_folder("Orchard")

        found = self.folders.read(self.tables, survey=self.survey)

        self.assertEqual(found.in_place, ("Orchard",))
        self.assertEqual(list(found.games), [])

    def test_a_folder_of_both_is_both(self) -> None:
        self.game_folder("Orchard")
        self.loose("Harbor Lights")

        found = self.folders.read(self.tables, survey=self.survey)

        self.assertEqual(found.in_place, ("Orchard",))
        self.assertEqual([one.key for one in found.games], ["Harbor Lights"])

    def test_the_tables_are_read_from_the_folder_itself(self) -> None:
        self.loose("Harbor Lights")

        system = self.folders.read(self.tables, survey=self.survey).systems[0]

        self.assertEqual(system.tables_dir, str(self.tables))
        self.assertEqual(system.name, "Tables")

    def test_without_a_survey_nothing_is_a_game(self) -> None:
        """This module cannot tell a game from a folder; core can."""
        self.loose("Harbor Lights")

        self.assertFalse(self.folders.detect(self.tables))
        self.assertEqual(list(self.folders.read(self.tables).games), [])

    def test_a_folder_with_nothing_in_it_is_not_claimed(self) -> None:
        self.assertFalse(self.folders.detect(self.tables, self.survey))

    def test_either_kind_of_thing_claims_it(self) -> None:
        self.loose("Harbor Lights")
        self.assertTrue(self.folders.detect(self.tables, self.survey))

        other = self.root / "Other"
        other.mkdir()
        (other / "Orchard").mkdir()
        (other / "Orchard" / "Orchard.vpx").write_bytes(b"table")
        self.assertTrue(self.folders.detect(other, self.survey))

    def test_a_frontend_is_not_taken_for_a_folder(self) -> None:
        """Asked last: a frontend's install folder holds folders too."""
        self.assertIs(self.api.reader_for(test_adopt.FIXTURE, self.survey).SOURCE_ID
                      and self.api.reader_for(test_adopt.FIXTURE, self.survey),
                      self.api.pinballx)

    def test_an_emulationstation_folder_is_read_as_a_folder(self) -> None:
        self.assertIs(self.api.reader_for(EMULATIONSTATION, self.survey), self.api.folders)

    def test_a_vpinmame_beside_the_tables_says_where_the_roms_are(self) -> None:
        install = self.root / "Visual Pinball"
        (install / "Tables").mkdir(parents=True)
        (install / "VPinMAME").mkdir()
        (install / "Tables" / "Harbor Lights.vpx").write_bytes(b"table")

        system = self.folders.read(install / "Tables", survey=self.survey).systems[0]

        self.assertEqual(system.working_path, str(install))

    def test_no_vpinmame_leaves_the_roms_unguessed(self) -> None:
        self.loose("Harbor Lights")

        system = self.folders.read(self.tables, survey=self.survey).systems[0]

        self.assertEqual(system.working_path, "")

    def test_artwork_pointed_at_is_read_the_way_pinballx_files_it(self) -> None:
        self.loose("Harbor Lights")
        art = self.root / "Art"
        (art / "Wheel Images").mkdir(parents=True)
        (art / "Wheel Images" / "Harbor Lights.png").write_bytes(b"w")

        found = self.folders.read(self.tables, survey=self.survey, chosen={"media": str(art)})

        self.assertEqual([one.source_kind for one in found.games[0].media], ["Wheel Images"])

    def test_the_source_is_offered_by_name(self) -> None:
        choices = {row[0]: row[1] for row in
                   self.client.get(f"{BASE}/wizard").json()["fields"][0]["choices"]}

        self.assertEqual(choices["folders"], "No frontend")
        self.assertEqual(list(choices)[-1], "folders")


class StepTests(FolderCase):
    """What is asked, in what order, depending on what was found."""

    def test_a_folder_of_tables_is_read_as_folders(self) -> None:
        self.loose("Harbor Lights")

        found = self.step(self.tables, leaving="how", how="move")

        self.assertEqual(self.summary_of(found)["Reads as"], "No frontend")

    def test_the_second_step_works_out_the_game_files_and_leaves_the_rest_blank(self) -> None:
        self.loose("Harbor Lights")

        found = self.step(self.tables)

        self.assertEqual(found["step"], "sources")
        fields = {one["key"]: one for one in found["fields"]}
        self.assertEqual(sorted(fields), ["altdata", "media", "roms", "tables"])
        self.assertEqual(fields["tables"]["value"], str(self.tables))
        for blank in ("media", "roms", "altdata"):
            self.assertEqual(fields[blank]["value"], "", blank)

    def test_no_play_history_is_offered_for_a_folder_of_tables(self) -> None:
        """Only a frontend that records plays has a history to point at, and a stats file
        lying in the folder is not one."""
        self.loose("Harbor Lights")
        (self.tables / "GameStats.csv").write_text("Game,Last Played\n")

        found = self.step(self.tables)

        self.assertNotIn("history", [one["key"] for one in found["fields"]])

    def test_a_frontend_is_still_offered_its_play_history(self) -> None:
        source, _ = self.a_frontend()

        fields = [one["key"] for one in self.step(source)["fields"]]

        self.assertIn("history", fields)

    def test_choosing_no_frontend_goes_straight_to_where_the_files_are(self) -> None:
        found = self.step("", source_type="folders")

        self.assertEqual(found["step"], "sources")
        self.assertEqual(found["title"], "Where your files are")
        self.assertNotIn("errors", found)
        fields = {one["key"]: one for one in found["fields"]}
        self.assertEqual(sorted(fields), ["altdata", "media", "roms", "tables"])
        self.assertEqual({one["value"] for one in fields.values()}, {""})

    def test_the_folders_pointed_at_there_are_what_is_read(self) -> None:
        """The first step named none, so the second step's answer is the root."""
        self.loose("Harbor Lights", "Quarry Run")

        found = self.step("", leaving="sources", source_type="folders",
                          tables=str(self.tables))

        self.assertEqual(found["step"], "how")
        self.assertEqual(found["help"].count("2"), 1, found["help"])

    def test_the_tables_edited_win_over_the_folder_typed_first(self) -> None:
        elsewhere = self.root / "Elsewhere"
        elsewhere.mkdir()
        self.loose("Harbor Lights")
        self.loose("Quarry Run", where=elsewhere)

        found = self.step(self.tables, leaving="how", source_type="folders",
                          tables=str(elsewhere), how="move")

        self.assertEqual(self.summary_of(found)["Folder"], str(elsewhere))
        self.assertEqual(self.summary_of(found)["Games"], "1")

    def test_the_second_step_is_checked_with_no_folder_typed_on_the_first(self) -> None:
        """The folder is declared to core before it is read, wherever the answer came from."""
        self.loose("Harbor Lights")

        found = self.step(self.tables, leaving="sources", source_type="folders")

        self.assertEqual(found["step"], "how")

    def test_going_back_to_the_first_step_and_on_reads_the_tables_edited(self) -> None:
        elsewhere = self.root / "Elsewhere"
        elsewhere.mkdir()
        self.loose("Quarry Run", where=elsewhere)

        found = self.step(self.tables, source_type="folders", tables=str(elsewhere))

        self.assertEqual(found["step"], "sources")
        self.assertNotIn("errors", found)

    def test_a_folder_that_has_gone_from_the_first_step_does_not_stop_no_frontend(self) -> None:
        self.loose("Harbor Lights")

        found = self.step(self.root / "Gone", source_type="folders",
                          tables=str(self.tables))

        self.assertEqual(found["step"], "sources")
        self.assertNotIn("errors", found)

    def test_a_folder_typed_first_is_what_the_second_step_starts_from(self) -> None:
        self.loose("Harbor Lights")

        found = self.step(self.tables, source_type="folders")

        fields = {one["key"]: one for one in found["fields"]}
        self.assertEqual(found["step"], "sources")
        self.assertEqual(fields["tables"]["value"], str(self.tables))

    def test_no_game_files_is_refused_on_the_field_that_names_them(self) -> None:
        found = self.step("", leaving="sources", source_type="folders",
                          tables=str(self.tables))

        self.assertEqual(found["step"], "sources")
        self.assertTrue(found["errors"]["tables"])
        self.assertNotIn("path", found["errors"])

    def test_leaving_the_files_unsaid_is_refused_there_too(self) -> None:
        found = self.step("", leaving="sources", source_type="folders", tables="")

        self.assertEqual(found["step"], "sources")
        self.assertTrue(found["errors"]["tables"])

    def test_a_folder_that_is_not_there_is_refused_on_the_tables_field(self) -> None:
        found = self.step("", leaving="sources", source_type="folders",
                          tables=str(self.root / "Gone"))

        self.assertEqual(found["step"], "sources")
        self.assertTrue(found["errors"]["tables"])

    def test_the_import_reads_from_the_tables_it_was_pointed_at(self) -> None:
        self.loose("Harbor Lights")
        copies = self.root / "Copies"
        copies.mkdir()

        report = self.run_it("", source_type="folders", tables=str(self.tables),
                             how="copy", into=str(copies))

        self.assertEqual(report["games"], 1)

    def test_loose_tables_are_asked_how_after_the_sources(self) -> None:
        self.loose("Harbor Lights", "Quarry Run")

        found = self.step(self.tables, leaving="sources")

        self.assertEqual(found["step"], "how")
        fields = {one["key"]: one for one in found["fields"]}
        self.assertEqual(fields["how"]["type"], "choice")
        self.assertEqual([one[0] for one in fields["how"]["choices"]], ["copy", "move"])
        self.assertEqual(fields["how"]["value"], "copy")
        self.assertEqual(fields["into"]["type"], "path")

    def test_copy_is_the_default_and_says_the_folder_stays(self) -> None:
        self.loose("Harbor Lights")

        choices = self.step(self.tables, leaving="sources")["fields"][0]["choices"]

        self.assertEqual(choices[0][2], "Copying leaves your Tables folder as it is")

    def test_into_starts_where_new_games_already_go(self) -> None:
        self.loose("Harbor Lights")

        found = self.step(self.tables, leaving="sources")

        into = next(one for one in found["fields"] if one["key"] == "into")
        self.assertEqual(into["value"], str(self.library))

    def test_into_opens_beside_the_source(self) -> None:
        self.loose("Harbor Lights")

        found = self.step(self.tables, leaving="sources")

        into = next(one for one in found["fields"] if one["key"] == "into")
        self.assertEqual(into["opens_at"], str(self.root))

    def test_the_size_a_copy_takes_is_said_before_it_is_chosen(self) -> None:
        self.loose("Harbor Lights", size=3000)
        (self.tables / "Harbor Lights.directb2s").write_bytes(b"b" * 500)

        found = self.step(self.tables, leaving="sources")

        into = next(one for one in found["fields"] if one["key"] == "into")
        self.assertTrue(into["help"].startswith("Needs 3.4 KB, with "), into["help"])

    def test_moving_a_frontends_files_says_its_list_will_point_at_nothing(self) -> None:
        source, _ = self.a_frontend()

        found = self.step(source, leaving="sources")

        choices = found["fields"][0]["choices"]
        self.assertIn("find these tables", choices[1][2])
        self.assertIn("PinballX", choices[1][2])

    def test_moving_from_a_folder_names_no_frontend(self) -> None:
        self.loose("Harbor Lights")

        choices = self.step(self.tables, leaving="sources")["fields"][0]["choices"]

        self.assertNotIn("find these tables", choices[1][2])

    def test_copying_with_nowhere_to_copy_to_is_sent_back(self) -> None:
        self.loose("Harbor Lights")

        found = self.step(self.tables, leaving="how", how="copy", into="")

        self.assertEqual(found["step"], "how")
        self.assertEqual(found["errors"], {"into": "Say where the copies go"})

    def test_a_folder_that_is_not_there_is_not_somewhere_to_copy_to(self) -> None:
        self.loose("Harbor Lights")

        found = self.step(self.tables, leaving="how", how="copy",
                          into=str(self.root / "not made"))

        self.assertEqual(found["step"], "how")
        self.assertIn("into", found["errors"])

    def test_moving_needs_no_place_to_go(self) -> None:
        self.loose("Harbor Lights")

        found = self.step(self.tables, leaving="how", how="move", into="")

        self.assertEqual(found["step"], "summary")

    def test_a_copy_summary_names_where_and_what_it_takes(self) -> None:
        self.loose("Harbor Lights", size=3000)

        found = self.step(self.tables, leaving="how", how="copy", into=str(self.library))
        summary = self.summary_of(found)

        self.assertTrue(found["ready"])
        self.assertEqual(summary["How"], "Copied")
        self.assertEqual(summary["Going into"], str(self.library))
        self.assertTrue(summary["Space needed"].startswith("2.9 KB, with "), summary)
        self.assertEqual(found["confirm"], "Copy 1 table")

    def test_a_move_summary_says_it_takes_no_room_for_the_game_files(self) -> None:
        self.loose("Harbor Lights", size=3000)

        found = self.step(self.tables, leaving="how", how="move")
        summary = self.summary_of(found)

        self.assertEqual(summary["How"], "Moved")
        self.assertIn(str(self.tables), summary["Going into"])
        self.assertNotIn("Space needed", summary)
        self.assertEqual(found["confirm"], "Move 1 table")

    def test_a_copy_that_would_not_fit_is_not_ready_and_says_so(self) -> None:
        self.loose("Harbor Lights", size=3000)

        with mock.patch.object(test_adopt_plan(), "room_at", return_value=(1000, "/")):
            found = self.step(self.tables, leaving="how", how="copy", into=str(self.library))

        self.assertFalse(found["ready"])
        self.assertEqual(found["reason"], "Needs 2.9 KB, but only 1000 B is free on /")

    def test_room_that_cannot_be_told_does_not_stop_anything(self) -> None:
        self.loose("Harbor Lights", size=3000)

        with mock.patch.object(test_adopt_plan(), "room_at", return_value=(-1, "")):
            found = self.step(self.tables, leaving="how", how="copy", into=str(self.library))

        self.assertTrue(found["ready"])
        self.assertEqual(self.summary_of(found)["Space needed"], "2.9 KB")

    def test_game_folders_alone_are_used_as_they_are(self) -> None:
        self.game_folder("Orchard")

        found = self.step(self.tables, leaving="sources")
        summary = self.summary_of(found)

        self.assertEqual(found["step"], "summary")
        self.assertTrue(found["ready"])
        self.assertEqual(summary["Used where they are"], "1 game folder")
        self.assertEqual(found["confirm"], "Use this folder")
        self.assertNotIn("How", summary)

    def test_a_folder_of_both_is_not_asked_how(self) -> None:
        """The game folders say it is a library folder already; its loose tables get
        folders where they lie."""
        self.game_folder("Orchard")
        self.loose("Harbor Lights")

        found = self.step(self.tables, leaving="sources")
        summary = self.summary_of(found)

        self.assertEqual(found["step"], "summary")
        self.assertEqual(summary["How"], "Each loose table gets a folder of its own where it lies")
        self.assertEqual(summary["Used where they are"], "1 game folder")
        self.assertEqual(found["confirm"], "Put 1 table in a folder")

    def test_a_folder_with_nothing_in_it_is_refused(self) -> None:
        found = self.step(self.tables)

        self.assertEqual(found["step"], "source")
        self.assertIn("path", found["errors"])

    def test_a_frontend_is_still_read_by_its_own_reader(self) -> None:
        source, _ = self.a_frontend()

        found = self.step(source, leaving="sources")

        self.assertEqual(found["step"], "how")
        self.assertEqual(self.step(source, leaving="how", how="copy",
                                   into=str(self.library))["step"], "summary")

    def test_an_emulationstation_folder_reads_as_the_game_folders_it_holds(self) -> None:
        found = self.step(EMULATIONSTATION, leaving="sources")

        self.assertEqual(found["step"], "summary")
        self.assertTrue(found["ready"], found)
        self.assertEqual(self.summary_of(found)["Reads as"], "No frontend")
        self.assertEqual(self.summary_of(found)["Used where they are"], "1 game folder")


class StartingPastAlreadyHereTests(FolderCase):
    def setUp(self) -> None:
        super().setUp()
        self.loose("Harbor Lights")
        self.copies = self.root / "Copies"
        self.copies.mkdir()
        self.run_it(self.tables, how="copy", into=str(self.copies))

    def test_what_a_first_run_brought_in_is_asked_about_the_second_time(self) -> None:
        found = self.step(self.tables, leaving="sources", how="copy", into=str(self.copies))

        self.assertEqual(found["step"], "existing")
        self.assertEqual(found["notes"], ["Harbor Lights"])

    def test_a_caller_can_start_past_the_question(self) -> None:
        found = self.step(self.tables, leaving="sources", skip_existing=True)

        self.assertEqual(found["step"], "summary")
        self.assertFalse(found["ready"])
        self.assertEqual(found["reason"], "Nothing left to import")

    def test_a_caller_that_starts_past_it_is_not_asked_when_there_is_nothing_to_ask(self) -> None:
        fresh = self.root / "Fresh"
        fresh.mkdir()
        self.loose("Quarry Run", where=fresh)

        asked = self.step(fresh, leaving="source", skip_existing=True)
        past = self.step(fresh, leaving="source")

        self.assertEqual(asked["step"], past["step"])

    def test_the_default_is_still_to_leave_what_is_here_alone(self) -> None:
        found = self.step(self.tables, leaving="sources")

        self.assertEqual(found["fields"][0]["value"], "skip")


class RunTests(FolderCase):
    def test_a_run_keeps_its_report_and_counts_the_games_that_did_not_come_across(self) -> None:
        self.loose("Harbor Lights", "Quarry Run")
        copies = self.root / "Copies"
        copies.mkdir()
        (copies / "Harbor Lights").write_text("in the way", encoding="utf-8")

        report = self.run_it(self.tables, how="copy", into=str(copies))

        self.assertEqual(report["failed"], 1)
        self.assertEqual(self.job.problems, 1)
        wire = self.client.get(f"/jobs/{self.job.id}").json()
        self.assertTrue(wire["report"])
        self.assertEqual(wire["problems"], 1)
        self.assertEqual(wire["result"]["failed"], 1)

    def test_a_clean_run_has_a_report_and_no_problems(self) -> None:
        self.loose("Harbor Lights")
        copies = self.root / "Copies"
        copies.mkdir()

        self.run_it(self.tables, how="copy", into=str(copies))

        wire = self.client.get(f"/jobs/{self.job.id}").json()
        self.assertTrue(wire["report"])
        self.assertEqual(wire["problems"], 0)

    def test_a_copy_makes_a_folder_for_each_table_and_leaves_the_source(self) -> None:
        self.loose("Harbor Lights", "Quarry Run")
        (self.tables / "Harbor Lights.directb2s").write_bytes(b"backglass")
        copies = self.root / "Copies"
        copies.mkdir()

        report = self.run_it(self.tables, how="copy", into=str(copies))

        self.assertEqual((report["games"], report["tables"], report["failed"]), (2, 2, 0))
        self.assertEqual(report["companions"], 1)
        self.assertTrue((copies / "Harbor Lights" / "Harbor Lights.vpx").is_file())
        self.assertTrue((copies / "Harbor Lights" / "Harbor Lights.directb2s").is_file())
        self.assertTrue((copies / "Quarry Run" / "Quarry Run.vpx").is_file())
        self.assertTrue((self.tables / "Harbor Lights.vpx").is_file())
        self.assertTrue((self.tables / "Harbor Lights.directb2s").is_file())
        self.assertEqual(self.games_held(), ["Harbor Lights", "Quarry Run"])

    def test_the_place_copied_into_becomes_a_library_folder(self) -> None:
        self.loose("Harbor Lights")
        copies = self.root / "Copies"
        copies.mkdir()

        self.run_it(self.tables, how="copy", into=str(copies))

        self.assertIn(str(copies.resolve()), self.locations_held())

    def test_a_move_takes_the_tables_into_folders_beside_where_they_were(self) -> None:
        self.loose("Harbor Lights", "Quarry Run")
        (self.tables / "Harbor Lights.directb2s").write_bytes(b"backglass")

        report = self.run_it(self.tables, how="move")

        self.assertEqual((report["games"], report["tables"], report["failed"]), (2, 2, 0))
        self.assertFalse((self.tables / "Harbor Lights.vpx").exists())
        self.assertFalse((self.tables / "Harbor Lights.directb2s").exists())
        self.assertFalse((self.tables / "Quarry Run.vpx").exists())
        self.assertTrue((self.tables / "Harbor Lights" / "Harbor Lights.vpx").is_file())
        self.assertTrue((self.tables / "Harbor Lights" / "Harbor Lights.directb2s").is_file())
        self.assertTrue((self.tables / "Quarry Run" / "Quarry Run.vpx").is_file())
        self.assertIn(str(self.tables.resolve()), self.locations_held())
        self.assertEqual(self.games_held(), ["Harbor Lights", "Quarry Run"])

    def test_a_move_leaves_a_neighbours_files_alone(self) -> None:
        self.loose("Harbor Lights")
        (self.tables / "Notes.txt").write_text("mine")
        (self.tables / "Other.directb2s").write_bytes(b"someone else's")

        self.run_it(self.tables, how="move")

        self.assertEqual((self.tables / "Notes.txt").read_text(), "mine")
        self.assertTrue((self.tables / "Other.directb2s").exists())

    def test_a_folder_of_both_keeps_its_games_and_gives_the_loose_tables_folders(self) -> None:
        orchard = self.game_folder("Orchard")
        self.loose("Harbor Lights")

        report = self.run_it(self.tables)

        self.assertEqual((report["games"], report["failed"]), (1, 0))
        self.assertEqual(orchard.joinpath("Orchard.vpx").read_bytes(), b"table")
        self.assertEqual([one for one in orchard.iterdir() if one.is_dir()], [])
        self.assertFalse((self.tables / "Harbor Lights.vpx").exists())
        self.assertTrue((self.tables / "Harbor Lights" / "Harbor Lights.vpx").is_file())
        self.assertEqual(self.locations_held().count(str(self.tables.resolve())), 1)
        self.assertEqual(self.games_held(), ["Harbor Lights", "Orchard"])

    def test_game_folders_alone_become_a_library_folder_and_nothing_is_touched(self) -> None:
        orchard = self.game_folder("Orchard")

        report = self.run_it(self.tables)

        self.assertEqual((report["games"], report["failed"]), (0, 0))
        self.assertEqual(orchard.joinpath("Orchard.vpx").read_bytes(), b"table")
        self.assertEqual([one for one in orchard.iterdir() if one.is_dir()], [])
        self.assertIn(str(self.tables.resolve()), self.locations_held())
        self.assertEqual(self.games_held(), ["Orchard"])

    def test_a_table_beside_a_folder_of_its_own_name_is_not_brought_in_twice(self) -> None:
        """The duplicate rule: the game is recognized by its folder's name."""
        self.game_folder("Harbor Lights")
        self.loose("Harbor Lights")

        report = self.run_it(self.tables)

        self.assertEqual(report["games"], 0)
        self.assertEqual(self.games_held(), ["Harbor Lights"])
        self.assertTrue((self.tables / "Harbor Lights.vpx").exists())

    def test_running_it_again_imports_nothing_twice(self) -> None:
        self.loose("Harbor Lights", "Quarry Run")
        copies = self.root / "Copies"
        copies.mkdir()
        self.run_it(self.tables, how="copy", into=str(copies))

        again = self.run_it(self.tables, how="copy", into=str(copies))

        self.assertEqual(again["games"], 0)
        self.assertEqual(sorted(one.name for one in copies.iterdir()),
                         ["Harbor Lights", "Quarry Run"])
        self.assertEqual(self.games_held(), ["Harbor Lights", "Quarry Run"])

    def test_a_move_from_a_frontend_moves_the_game_file_it_listed(self) -> None:
        source, held = self.a_frontend()
        before = held / "Taxi.vpx"

        report = self.run_it(source, how="move")

        self.assertFalse(before.exists())
        self.assertEqual(report["tables"], 1)
        # Beside where it was: the config names that folder as the tables folder, and
        # the games are not made anywhere else.
        self.assertEqual(len(list(held.glob("*/Taxi.vpx"))), 1)
        self.assertIn(str(held.resolve()), self.locations_held())

    def test_a_copy_from_a_frontend_leaves_what_it_listed(self) -> None:
        source, held = self.a_frontend()
        copies = self.root / "Copies"
        copies.mkdir()

        report = self.run_it(source, how="copy", into=str(copies))

        self.assertEqual(report["failed"], 0)
        self.assertTrue((held / "Taxi.vpx").is_file())
        self.assertEqual(len(list(copies.glob("*/Taxi.vpx"))), 1)

    def test_a_copy_with_nowhere_to_go_writes_to_the_place_new_games_go(self) -> None:
        """A caller that sent no `into` still lands where a game made by hand would."""
        self.loose("Harbor Lights")

        report = self.run_it(self.tables, how="copy")

        self.assertEqual(report["games"], 1)
        self.assertTrue((self.library / "Harbor Lights" / "Harbor Lights.vpx").is_file())


class RoomTests(FolderCase):
    """The room a copy needs is asked about the place it will be written, not about the
    default every time."""

    def setUp(self) -> None:
        super().setUp()
        self.loose("Harbor Lights", size=3000)
        self.elsewhere = self.root / "Elsewhere"
        self.elsewhere.mkdir()
        self.asked = mock.patch.object(test_adopt_plan(), "room_at",
                                       return_value=(10**12, "/"))

    def asked_of(self, room_at: mock.Mock) -> set[Path]:
        return {Path(call.args[0]).resolve() for call in room_at.call_args_list}

    def test_a_folder_typed_in_is_the_one_asked_about(self) -> None:
        with self.asked as room_at:
            self.step(self.tables, leaving="how", how="copy", into=str(self.elsewhere))

        self.assertEqual(self.asked_of(room_at), {self.elsewhere.resolve()})

    def test_the_default_is_asked_about_when_nothing_was_typed(self) -> None:
        with self.asked as room_at:
            self.step(self.tables, leaving="sources")

        self.assertEqual(self.asked_of(room_at), {self.library.resolve()})

    def test_a_move_is_asked_about_the_folder_the_tables_are_in(self) -> None:
        with self.asked as room_at:
            self.step(self.tables, leaving="how", how="move")

        self.assertEqual(self.asked_of(room_at), {self.tables.resolve()})

    def test_a_run_is_asked_about_the_folder_typed_in(self) -> None:
        with self.asked as room_at:
            self.run_it(self.tables, how="copy", into=str(self.elsewhere))

        self.assertEqual(self.asked_of(room_at), {self.elsewhere.resolve()})

    def test_a_run_is_asked_about_the_location_it_was_sent_to(self) -> None:
        """No `into`, but a location: the games are made there, so that is where the
        room is. The default would be answered for a folder nothing is written to."""
        self.client.put("/config/locations/two", json={"path": str(self.elsewhere)})

        with self.asked as room_at:
            started = self.client.post(
                f"{BASE}/wizard/run",
                json={"values": {"path": str(self.tables), "how": "copy"}, "location": "two"})
            self.assertTrue(started.json()["started"], started.json())
            job_id = started.json()["job_id"]
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline and not (
                    jobs.get(job_id) and jobs.get(job_id).finished_at):
                time.sleep(0.01)

        self.assertEqual(self.asked_of(room_at), {self.elsewhere.resolve()})
        self.assertTrue((self.elsewhere / "Harbor Lights" / "Harbor Lights.vpx").is_file())
        self.assertFalse((self.library / "Harbor Lights").exists())


class RunRefusesTests(FolderCase):
    """A run says no to what the summary would have, and before it has done anything."""

    def setUp(self) -> None:
        super().setUp()
        self.loose("Harbor Lights", size=3000)
        self.before = self.locations_held()

    def assert_nothing_was_done(self, *, made: Path | None = None) -> None:
        self.assertEqual(self.locations_held(), self.before)
        self.assertEqual(self.games_held(), [])
        if made is not None:
            self.assertFalse(made.exists())

    def test_a_folder_that_is_not_there_is_not_registered_as_a_place_to_copy_to(self) -> None:
        nowhere = self.root / "not made"

        found = self.refused_run(how="copy", into=str(nowhere))

        self.assertEqual(found["reason"], "That folder is not reachable from here")
        self.assert_nothing_was_done(made=nowhere)

    def test_a_copy_with_the_place_left_empty_is_refused(self) -> None:
        found = self.refused_run(how="copy", into="")

        self.assertEqual(found["reason"], "Say where the copies go")
        self.assert_nothing_was_done()

    def test_a_copy_that_would_not_fit_is_refused(self) -> None:
        with mock.patch.object(test_adopt_plan(), "room_at", return_value=(1000, "/")):
            found = self.refused_run(how="copy", into=str(self.library))

        self.assertEqual(found["reason"], "Needs 2.9 KB, but only 1000 B is free on /")
        self.assert_nothing_was_done()
        self.assertFalse((self.library / "Harbor Lights").exists())

    def test_a_location_that_is_not_one_games_can_go_to_is_refused(self) -> None:
        started = self.client.post(
            f"{BASE}/wizard/run",
            json={"values": {"path": str(self.tables), "how": "copy"}, "location": "nope"})

        self.assertIs(started.json()["ok"], False, started.json())
        self.assert_nothing_was_done()

    def test_a_source_that_cannot_be_read_says_so_in_the_same_shape(self) -> None:
        empty = self.root / "Empty"
        empty.mkdir()

        started = self.client.post(f"{BASE}/wizard/run",
                                   json={"values": {"path": str(empty)}})

        self.assertEqual(started.json()["started"], False)
        self.assertIs(started.json()["ok"], False)

    def test_a_move_has_no_place_to_check_and_is_not_refused_for_one(self) -> None:
        self.run_it(self.tables, how="move", into=str(self.root / "not made"))

        self.assertTrue((self.tables / "Harbor Lights" / "Harbor Lights.vpx").is_file())


class SystemsRunTests(FolderCase):
    """A source with several systems, of which only some are brought across."""

    def setUp(self) -> None:
        super().setUp()
        from vpinfe_ext_library_importer import folders
        from vpinfe_ext_library_importer.source import SourceLibrary

        self.alpha, self.beta = self.tables / "Alpha", self.tables / "Beta"
        for folder, name in ((self.alpha, "Harbor Lights"), (self.beta, "Quarry Run")):
            folder.mkdir()
            self.loose(name, where=folder)
        real = folders.read

        def two_systems(root, plays=None, known=(), *, survey=None, chosen=None):
            systems = [real(one, survey=survey, chosen=chosen).systems[0]
                       for one in (self.alpha, self.beta)]
            return SourceLibrary(source_id=folders.SOURCE_ID, root=str(root),
                                 systems=tuple(systems))

        patcher = mock.patch.object(folders, "read", two_systems)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_system_left_out_is_not_registered_as_a_library_folder(self) -> None:
        report = self.run_it(self.tables, how="move", systems=["Alpha"])

        self.assertEqual(report["games"], 1)
        held = self.locations_held()
        self.assertIn(str(self.alpha.resolve()), held)
        self.assertNotIn(str(self.beta.resolve()), held)
        self.assertTrue((self.beta / "Quarry Run.vpx").is_file())

    def test_the_summary_names_only_the_folders_that_are_moved_into(self) -> None:
        found = self.step(self.tables, leaving="how", how="move", systems=["Alpha"])
        going = self.summary_of(found)["Going into"]

        self.assertIn(str(self.alpha), going)
        self.assertNotIn(str(self.beta), going)

    def test_every_system_is_brought_across_where_none_was_left_out(self) -> None:
        report = self.run_it(self.tables, how="move")

        self.assertEqual(report["games"], 2)
        held = self.locations_held()
        self.assertIn(str(self.alpha.resolve()), held)
        self.assertIn(str(self.beta.resolve()), held)


class OrderTests(FolderCase):
    """Bringing a folder in that is already held must not change where new games go: the
    order is the priority, and a run asks for its folders on every import."""

    def setUp(self) -> None:
        super().setUp()
        self.loose("Harbor Lights")
        self.other = self.root / "Other"
        self.other.mkdir()

    def hold(self, *folders: Path) -> None:
        self.locations.save([library_folders.Location(location_id=f"id{i}", path=str(one))
                             for i, one in enumerate(folders)], write_to="")

    def order(self) -> list[Path]:
        return [Path(one).resolve() for one in self.locations_held()]

    def test_copying_into_the_first_folder_leaves_it_first(self) -> None:
        self.hold(self.library, self.other)

        self.run_it(self.tables, how="copy", into=str(self.library))

        self.assertEqual(self.order(), [self.library.resolve(), self.other.resolve()])
        self.assertEqual(Path(library_folders.destination().path).resolve(), self.library.resolve())

    def test_moving_in_a_folder_that_is_first_leaves_it_first(self) -> None:
        self.hold(self.tables, self.library)

        self.run_it(self.tables, how="move")

        self.assertEqual(self.order(), [self.tables.resolve(), self.library.resolve()])
        self.assertEqual(Path(library_folders.destination().path).resolve(), self.tables.resolve())

    def test_a_folder_not_held_yet_goes_last(self) -> None:
        self.hold(self.library, self.other)
        fresh = self.root / "Fresh"
        fresh.mkdir()

        self.run_it(self.tables, how="copy", into=str(fresh))

        self.assertEqual(self.order(), [self.library.resolve(), self.other.resolve(),
                                        fresh.resolve()])


class SurveyedOnceTests(FolderCase):
    """Every wizard request lists the source's child folders once, however many readers
    and steps want to know what is in it."""

    def setUp(self) -> None:
        super().setUp()
        self.loose("Harbor Lights")
        patcher = mock.patch("common.games.tables.survey", wraps=tables.survey)
        self.survey = patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_step_surveys_the_folder_once(self) -> None:
        self.step(self.tables)

        self.assertEqual(self.survey.call_count, 1)

    def test_the_step_that_reads_the_most_still_surveys_it_once(self) -> None:
        self.step(self.tables, leaving="how", how="copy", into=str(self.library))

        self.assertEqual(self.survey.call_count, 1)

    def test_a_run_surveys_it_once(self) -> None:
        self.run_it(self.tables, how="copy", into=str(self.library))

        self.assertEqual(self.survey.call_count, 1)

    def test_a_request_from_the_first_step_looks_again(self) -> None:
        """A folder somebody just changed is read as it is now by the step that starts the
        walk."""
        self.step(self.tables)
        self.loose("Quarry Run")
        self.step(self.tables, leaving="source")

        found = self.step(self.tables, leaving="sources")

        self.assertEqual(self.survey.call_count, 3)
        self.assertEqual(found["help"], "2 tables from Tables")

    def test_a_later_step_takes_what_the_first_read(self) -> None:
        self.step(self.tables)
        self.loose("Quarry Run")

        found = self.step(self.tables, leaving="sources")

        self.assertEqual(self.survey.call_count, 2)
        self.assertEqual(found["help"], "1 table from Tables")

    def test_the_preview_surveys_it_once(self) -> None:
        self.client.put(f"{BASE}/source", json={"path": str(self.tables)})
        self.survey.reset_mock()

        self.client.get(f"{BASE}/preview")

        self.assertEqual(self.survey.call_count, 1)


class UnreadableTests(FolderCase):
    @needs_posix_permissions
    def test_a_folder_that_cannot_be_opened_says_so_rather_than_that_it_is_empty(self) -> None:
        if os.geteuid() == 0:
            self.skipTest("root opens any folder")
        shut = self.root / "Shut"
        shut.mkdir()
        shut.chmod(0o000)
        self.addCleanup(shut.chmod, 0o755)

        found = self.step(shut)

        self.assertEqual(found["step"], "source")
        self.assertEqual(found["errors"], {"path": "That folder cannot be read"})

    def test_a_folder_that_is_not_there_is_still_not_reachable(self) -> None:
        found = self.step(self.root / "gone")

        self.assertEqual(found["errors"], {"path": "That folder is not reachable from here"})


def test_adopt_plan():
    """The module the extension's own `plan` is, under the name it loads as."""
    from vpinfe_ext_library_importer import plan

    return plan


if __name__ == "__main__":
    unittest.main()
