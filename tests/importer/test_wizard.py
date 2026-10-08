"""The guided task the importer offers, as core sees it.

Core draws the wizard from what the extension declares, so what is pinned here is the
declaration and the three calls behind it - not the drawing, which is core's and is the
same for every task.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from fastapi.testclient import TestClient
from nicegui import ui

import httpapi
from common import extensions
from common.extensions import host, store
from common.extensions.contract import ContractError
from console import wizard

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests" / "fixtures" / "pinballx"
BASE = "/ext/library_importer"


class WizardCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.store = store.ExtensionStore(self.root)
        self.registry = host.Registry(self.store)
        extensions.set_registry(self.registry)
        self.addCleanup(extensions.set_registry, host.Registry())
        self.addCleanup(self.registry.clear)
        self.record = self.registry.load(host.BUNDLED_DIR / "library_importer")
        self.assertEqual(self.record.state, host.LOADED, self.record.reason)
        self.client = TestClient(httpapi.create_api_app(), raise_server_exceptions=False)

    def _step(self, path, leaving="source", **values) -> dict:
        """The one step after the one named, with whatever has been answered so far."""
        return self.client.post(
            f"{BASE}/wizard/check",
            json={"values": {"path": str(path), **values}, "step": leaving}).json()

    def _check(self, path, **values) -> dict:
        """Walk to the summary the way somebody pressing Next does.

        Walked rather than asked for, because the summary is what the earlier steps add
        up to: a test that jumped to it would pass over the thing being described.
        """
        found = self._step(path, **values)
        seen = {}
        while "summary" not in found and found.get("step"):
            for field in found.get("fields") or []:
                seen.setdefault(field["key"], field.get("value"))
            seen.pop("path", None)
            found = self._step(path, leaving=found["step"], **{**seen, **values})
        return found


class LookTests(WizardCase):
    """What is asked of the catalog, and which library an answer belongs to."""

    def test_a_game_known_only_by_its_file_name_is_asked_by_that_name(self) -> None:
        from vpinfe_ext_library_importer import api
        from vpinfe_ext_library_importer.source import SourceGame

        asked = api._asked(SourceGame(key="Taxi (Williams 1988)"))

        self.assertEqual(asked["folder"], "Taxi (Williams 1988)")

    def test_a_look_is_kept_only_for_the_library_it_was_made_for(self) -> None:
        from vpinfe_ext_library_importer.held import Held
        from vpinfe_ext_library_importer.source import SourceLibrary

        held, first, second = Held(), SourceLibrary("x", "/a"), SourceLibrary("x", "/a")
        key = ("a", "b", "c")
        held.keep(key, first)
        held.keep(key, second)

        held.remember_look(first, {"ready": True}, {1: {}})
        self.assertIsNone(held.look_of(first))
        self.assertIsNone(held.look_of(second))

        held.remember_look(second, {"ready": True}, {2: {}})
        self.assertEqual(held.look_of(second), ({"ready": True}, {2: {}}))
        held.keep(key, first)
        self.assertIsNone(held.look_of(second))


class DeclarationTests(WizardCase):
    def test_the_action_is_listed_with_the_extension(self) -> None:
        found = self.client.get("/extensions").json()["extensions"][0]

        action = found["actions"][0]
        self.assertEqual(action["key"], "import")
        self.assertEqual(action["base"], "/wizard")
        self.assertTrue(action["label"])

    def test_an_action_declares_no_mode(self) -> None:
        """How many steps it has is read off what it answers - the fields it asks
        for and the confirm it names. A declared mode would be a second statement
        of the same thing, and the two come apart."""
        found = self.client.get("/extensions").json()["extensions"][0]
        action = found["actions"][0]

        self.assertEqual(sorted(action), ["base", "description", "key", "label", "label_key"])

    def test_an_extension_that_is_not_running_offers_nothing(self) -> None:
        """A button that refuses is worse than no button."""
        with self.assertLogs("vpinfe.common.extensions", "ERROR"):
            self.registry.disable("library_importer", "asked to")

        found = self.client.get("/extensions").json()["extensions"][0]

        self.assertEqual(found["actions"], [])

    def test_offering_one_without_the_capability_is_refused(self) -> None:
        from common.extensions.context import ExtensionUI

        with self.assertRaises(ContractError):
            ExtensionUI("quiet", allowed=False).action("go", "/x")


class FormTests(WizardCase):
    def test_the_first_step_asks_where_the_library_is(self) -> None:
        found = self.client.get(f"{BASE}/wizard").json()

        self.assertTrue(found["title"])
        self.assertEqual([one["key"] for one in found["fields"]],
                         ["source_type", "path"])
        self.assertEqual(
            next(one["type"] for one in found["fields"] if one["key"] == "path"),
            "path")


class CheckTests(WizardCase):
    def test_it_says_what_would_come_across(self) -> None:
        """Counted before it runs, so the report afterwards has something to be
        measured against."""
        found = self._check(FIXTURE)

        self.assertTrue(found["ready"])
        summary = dict(one for one in found["summary"] if len(one) == 2)
        self.assertEqual(summary["Games"], "4")
        self.assertEqual(summary["Reads as"], "PinballX / PinballY")

    def test_the_play_history_is_a_file_and_the_rest_are_folders(self) -> None:
        """A folder check marks a file missing, and the history is one file."""
        found = self._step(FIXTURE)
        wants = {one["key"]: one.get("wants") for one in found["fields"]
                 if one["type"] == "path"}

        self.assertEqual(wants["history"], "file")
        self.assertIsNone(wants["tables"])

    def test_a_kind_with_no_source_says_it_is_not_coming(self) -> None:
        """"No media" should be a choice somebody can see they made, not a silence
        they notice afterwards."""
        found = self._check(FIXTURE, media="")
        summary = dict(one for one in found["summary"] if len(one) == 2)

        self.assertEqual(summary["No media"], "not being imported")

    def test_every_kind_of_source_is_offered_and_can_be_cleared(self) -> None:
        """Derived where it can be, overridable always, and empty means not imported."""
        found = self._step(FIXTURE)
        fields = {one["key"]: one for one in found["fields"]}

        for key in ("tables", "media"):
            self.assertIn(key, fields)
            self.assertEqual(fields[key]["type"], "path")

    def test_the_notes_travel_with_the_counts(self) -> None:
        """A summary that said four games and stayed quiet about their tables being on a
        machine that is not here would describe an import that will not happen."""
        found = self._check(FIXTURE)

        self.assertTrue(any("not reachable from here" in note
                            for note in found["notes"]))

    def test_the_confirm_says_what_it_will_do(self) -> None:
        self.assertEqual(self._check(FIXTURE)["confirm"], "Import 4 games")

    def test_several_systems_are_a_choice_and_one_is_not(self) -> None:
        found = self._step(FIXTURE)
        fields = {one["key"]: one for one in found["fields"]}

        self.assertIn("systems", fields)
        self.assertEqual(len(fields["systems"]["choices"]), 2)

    def test_a_folder_holding_nothing_readable_is_asked_again(self) -> None:
        """Asked again rather than carried forward. Somebody who typed the wrong folder
        wants that question back, not a summary of nothing four steps later."""
        empty = self.root / "empty"
        empty.mkdir()

        found = self._step(empty)

        self.assertEqual(found["step"], "source")
        self.assertTrue(found["errors"]["path"])

    def test_choosing_the_folder_here_is_what_lets_core_read_it(self) -> None:
        """It is set at the check rather than at the end, because there is nothing to
        summarize until core may read the folder at all."""
        from common.games import media_browse as filesystem

        self._check(FIXTURE)

        self.assertEqual(filesystem.within_roots(str(FIXTURE / "Config")).name, "Config")


class StepOrderTests(WizardCase):
    """Which question comes next, and why it does not depend on how somebody got here."""

    def test_the_source_step_is_followed_by_the_source_map(self) -> None:
        self.assertEqual(self._step(FIXTURE)["step"], "sources")

    def test_going_back_and_forward_asks_the_same_thing_again(self) -> None:
        """The step being left decides what comes next, not what has been answered.

        Answered values decide the *content* of a step; if they decided the order too,
        pressing Back and then Next would skip the step just returned to - which is the
        one thing somebody pressing Back is trying to reach.
        """
        first = self._step(FIXTURE)
        again = self._step(FIXTURE, leaving="source",
                           **{one["key"]: one.get("value")
                              for one in first["fields"] if one["key"] != "path"})

        self.assertEqual(again["step"], first["step"])

    def test_existing_games_are_only_asked_about_when_there_are_some(self) -> None:
        """A library with nothing matching gets one step fewer, not a step saying zero."""
        found = self._step(FIXTURE, leaving="sources", tables="", media="")

        self.assertEqual(found["step"], "summary")

    def test_the_summary_is_the_last_step(self) -> None:
        found = self._check(FIXTURE)

        self.assertEqual(found["step"], "summary")
        self.assertIn("summary", found)
        self.assertNotIn("fields", found)


class SummaryShapeTests(WizardCase):
    def test_a_row_of_one_is_a_heading(self) -> None:
        """Which is how the counts get separated from the settings above them without
        the extension deciding anything about how either is drawn."""
        found = self._check(FIXTURE)

        headings = [one[0] for one in found["summary"] if len(one) == 1]
        self.assertEqual(headings, ["What comes across"])

    def test_the_counts_come_after_the_heading(self) -> None:
        found = self._check(FIXTURE)
        at = next(i for i, one in enumerate(found["summary"]) if len(one) == 1)

        after = [one[0] for one in found["summary"][at + 1:]]
        self.assertEqual(after, ["Games", "Game files", "Media files",
                                 "Backglasses and settings", "Games with play history",
                                 "Matched to VPS", "Left behind"])

    def test_with_no_catalog_the_summary_says_no_game_is_matched(self) -> None:
        found = self._check(FIXTURE)

        self.assertIn(["VPS matching", "The VPS catalog is not available, so no game is "
                                       "matched"], found["summary"])
        self.assertIn(["Matched to VPS", "0"], found["summary"])

    def test_with_a_catalog_the_summary_counts_the_matches_and_names_the_rest(self) -> None:
        catalog = [{"id": "vps-taxi", "name": "Taxi", "manufacturer": "Williams",
                    "year": 1988}]

        with unittest.mock.patch("common.games.game_service.load_vpsdb",
                                 return_value=catalog), \
                unittest.mock.patch("common.online.vpsdb_sync.ensure_catalog",
                                    return_value=True):
            found = self._check(FIXTURE)

        rows = dict(one for one in found["summary"] if len(one) == 2)
        self.assertEqual(rows["Matched to VPS"], "1")
        self.assertEqual(rows["Not matched to VPS"], "3 not found")
        self.assertNotIn("VPS matching", rows)

    def test_with_matching_switched_off_the_summary_says_so(self) -> None:
        with unittest.mock.patch("common.games.auto_match.enabled", return_value=False):
            found = self._check(FIXTURE)

        rows = dict(one for one in found["summary"] if len(one) == 2)
        self.assertEqual(rows["VPS matching"], "Switched off, so no game is matched")

    def test_the_folders_with_no_slot_are_named_with_their_file_counts(self) -> None:
        """Said before the copy starts, so nobody finds out from the report that a folder
        of theirs was not carried."""
        found = self._check(FIXTURE)

        left = dict(one for one in found["summary"] if len(one) == 2)["Left behind"]
        self.assertEqual(left, "Flyer Images/Inside1 (1), Real DMD Videos (1)")

    def test_the_summary_counts_the_games_whose_play_history_comes_across(self) -> None:
        source = self.root / "pinballx"
        shutil.copytree(FIXTURE, source)
        (source / "GameStats.csv").write_text(
            "Game,Play Count\nTaxi (Williams 1988).Visual Pinball X,33\n", encoding="utf-8")

        found = self._check(source)

        self.assertIn(["Games with play history", "1"], found["summary"])

    def test_a_database_it_could_not_read_hovers_why_in_the_console(self) -> None:
        source = self.root / "pinballx"
        shutil.copytree(FIXTURE, source)
        (source / "Databases" / "Visual Pinball X" / "Visual Pinball X.xml").write_text(
            '<menu>\n<game name="A & B"/></menu>')

        found = self._check(source)
        with ui.column() as body:
            wizard._lines(found["notes"], "")
        tips = {one.props["target"]: one.text
                for one in body.descendants() if isinstance(one, ui.tooltip)}
        hovers = {one.text: tips.get(f"#{one.html_id}", "")
                  for one in body.descendants() if isinstance(one, ui.label)}

        self.assertEqual("Line 2 is not written as it should be",
                         hovers["Visual Pinball X.xml could not be read"])

    def test_what_reading_the_play_history_said_is_on_the_summary(self) -> None:
        source = self.root / "pinballx"
        shutil.copytree(FIXTURE, source)
        (source / "GameStats.csv").write_bytes(
            b"Game,Play Count\nCaf\xe9.Visual Pinball X,33\n")

        found = self._check(source)

        self.assertIn("GameStats.csv is in no encoding this reads cleanly, so some "
                      "characters may be wrong", found["notes"])


class RomSummaryTests(WizardCase):
    CATALOG = [{"id": "vps-taxi", "name": "Taxi", "manufacturer": "Williams", "year": 1988,
                "type": "SS"}]

    def summary(self, source=FIXTURE, **values) -> dict[str, str]:
        with unittest.mock.patch("common.games.game_service.load_vpsdb",
                                 return_value=self.CATALOG), \
                unittest.mock.patch("common.online.vpsdb_sync.ensure_catalog",
                                    return_value=True), \
                unittest.mock.patch(
                    "common.extensions.games.ExtensionGames.roms_of",
                    side_effect=lambda paths: {str(one): "taxi_l4" for one in paths}):
            found = self._check(source, **{"into": str(self.root / "library"), **values})
        return {row[0]: row[1] for row in found["summary"] if len(row) == 2}

    def installed(self) -> Path:
        """A copy of the fixture whose game files are on disk, Taxi's among them."""
        source = self.root / "frontend"
        shutil.copytree(FIXTURE, source)
        tables = source / "tables"
        tables.mkdir()
        (tables / "Taxi.vpx").write_bytes(b"table")
        (self.root / "library").mkdir()
        ini = source / "Config" / "PinballX.ini"
        ini.write_bytes(ini.read_text(encoding="utf-16")
                        .replace(r"C:\Visual Pinball\tables", str(tables))
                        .encode("utf-16"))
        return source

    def test_a_folder_that_was_looked_for_and_not_found_says_that(self) -> None:
        rows = self.summary()

        self.assertEqual(rows["No ROMs"], "No ROM folder was found")
        self.assertEqual(rows["No music"], "No music folder was found")

    def test_a_folder_left_empty_on_purpose_says_it_is_not_being_imported(self) -> None:
        source = self.installed()
        (source / "Music").mkdir()

        rows = self.summary(source, music="")

        self.assertEqual(rows["No music"], "not being imported")

    def test_the_games_that_need_a_rom_the_folder_lacks_are_counted(self) -> None:
        roms = self.root / "roms"
        roms.mkdir()

        rows = self.summary(self.installed(), roms=str(roms))

        self.assertEqual(rows["Missing ROMs"], "1 table needs a ROM that is not there")

    def test_a_rom_the_folder_holds_in_another_case_is_not_missing(self) -> None:
        roms = self.root / "roms"
        roms.mkdir()
        (roms / "TAXI_L4.ZIP").write_bytes(b"r")

        rows = self.summary(self.installed(), roms=str(roms))

        self.assertNotIn("Missing ROMs", rows)

    def test_nothing_is_said_of_missing_roms_where_none_are_imported(self) -> None:
        rows = self.summary(self.installed(), roms="")

        self.assertNotIn("Missing ROMs", rows)


if __name__ == "__main__":
    unittest.main()
