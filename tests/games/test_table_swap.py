"""Putting another file in a table's place, and deleting one table.

What is pinned is what is on disk afterwards and what the record still says: the entry keeps
its id and what a person recorded on it, the old file and whatever is not carried are in
Backups, and a refusal leaves the folder as it was found.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from common import service_errors
from common.backups import folder as backup_folder
from common.backups import ops as backup_ops
from common.games import backglass_order, game_repository, table_ops, table_swap
from common.host import launch_state
from tests.support.library import TempTree, fake_game, game_info, write_game

GAME_ID = "Swapped0001"
FOLDER = "Cactus"
OLD = "Cactus 1.1.vpx"
BEING = "Cactus 1.2.vpx"


class SwapCase(TempTree):
    """A game folder named Cactus with two tables: 1.1, which has been played with, and an
    unrelated one beside it."""

    def setUp(self) -> None:
        super().setUp()
        self.backups = self.root / "backups"
        self.backups.mkdir()
        self.running = launch_state.LaunchState()
        self.info = game_info("Cactus", game_id=GAME_ID, tables={
            "t1": {"id": "t1", "filename": OLD, "rating": 4, "hidden": True, "version": "1.1",
                   "tags": ["mine"],
                   "source": {"vps_file_id": "old-file", "confirmed_by": "user"}},
            "t2": {"id": "t2", "filename": "Cactus Other.vpx"},
        })
        self.info["vpinfe"]["default_table"] = OLD
        self.folder = write_game(self.root / "library", FOLDER, info=self.info, vpx=False,
                                 files={OLD: b"old", "Cactus Other.vpx": b"other"})
        self.game = fake_game(self.folder, FOLDER, meta=self.info)
        self.offered = self.root / "offered"
        self.offered.mkdir()
        self.arrives = self.offered / BEING
        self.arrives.write_bytes(b"new")
        for patcher in (
                patch.object(game_repository, "catalog", side_effect=lambda: {GAME_ID: self.game}),
                patch.object(game_repository, "all_games", side_effect=lambda **_: [self.game]),
                patch.object(table_swap, "reread_game", side_effect=lambda game: game),
                patch.object(table_swap, "read_one", return_value={"version": "1.2"}),
                patch.object(table_ops, "row_or_refuse",
                             side_effect=lambda game, table_id: {"id": table_id}),
                patch.object(backglass_order, "settle", return_value=[]),
                patch.object(backup_folder, "current", return_value=self.backups),
                patch.object(launch_state, "current", side_effect=lambda: self.running)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def put(self, name: str, data: bytes = b"x") -> Path:
        path = self.folder / name
        path.write_bytes(data)
        return path

    def names(self) -> list[str]:
        return sorted(path.name for path in self.folder.iterdir() if path.is_file())

    def kept(self) -> list[str]:
        return sorted(path.name.split(".vpinfe-")[0] for path in self.backups.rglob("*")
                      if path.is_file())

    def assert_kept(self, *names: str) -> None:
        self.assertEqual(self.kept(), sorted(names))

    def kept_bytes(self) -> list[bytes]:
        return sorted(path.read_bytes() for path in self.backups.rglob("*") if path.is_file())

    def record(self) -> dict:
        return json.loads((self.folder / f"{FOLDER}.info").read_text())

    def swap(self, **options) -> dict:
        return table_swap.replace(GAME_ID, "t1", str(self.arrives), **options)


class ReplaceTests(SwapCase):
    def test_the_table_keeps_its_id_and_what_a_person_recorded_on_it(self) -> None:
        self.swap()

        entry = self.record()["tables"]["t1"]
        self.assertEqual((entry["id"], entry["filename"]), ("t1", BEING))
        self.assertEqual((entry["rating"], entry["hidden"], entry["tags"]), (4, True, ["mine"]))
        self.assertEqual(entry["version"], "1.2")
        self.assertEqual(self.record()["vpinfe"]["default_table"], "t1")

    def test_the_old_tie_goes_with_the_old_file(self) -> None:
        self.swap()

        self.assertNotIn("source", self.record()["tables"]["t1"])

    def test_the_new_file_is_in_place_and_the_old_one_is_in_backups_only(self) -> None:
        done = self.swap()

        self.assertEqual(self.names(), [BEING, "Cactus Other.vpx", f"{FOLDER}.info"])
        self.assertEqual((self.folder / BEING).read_bytes(), b"new")
        self.assert_kept(OLD)
        self.assertEqual([one["file"] for one in done["kept"]], [OLD])

    def test_the_file_offered_is_copied_not_moved(self) -> None:
        self.swap()

        self.assertTrue(self.arrives.is_file())

    def test_a_file_with_the_same_name_replaces_it_in_place(self) -> None:
        same = self.offered / OLD
        same.write_bytes(b"newer")

        table_swap.replace(GAME_ID, "t1", str(same))

        self.assertEqual((self.folder / OLD).read_bytes(), b"newer")
        self.assert_kept(OLD)
        self.assertEqual(self.kept_bytes(), [b"old"])
        self.assertEqual(self.record()["tables"]["t1"]["filename"], OLD)

    def test_a_same_name_swap_the_entry_refuses_puts_the_old_file_back(self) -> None:
        same = self.offered / OLD
        same.write_bytes(b"newer")

        with patch.object(table_swap.MetaConfig, "swap_table", return_value=False), \
                self.assertRaises(service_errors.RefusedError):
            table_swap.replace(GAME_ID, "t1", str(same))

        self.assertEqual((self.folder / OLD).read_bytes(), b"old")

    def test_a_file_that_cannot_be_read_leaves_the_entry_to_be_read_again(self) -> None:
        entry = self.info["tables"]["t1"]
        entry.update({"file_hash": "stale", "rom": "oldrom", "detect_pinmame": True})
        (self.folder / f"{FOLDER}.info").write_text(json.dumps(self.info))

        with patch.object(table_swap, "read_one", return_value=None):
            self.swap()

        written = self.record()["tables"]["t1"]
        self.assertEqual(written["filename"], BEING)
        for key in ("file_hash", "rom", "detect_pinmame", "version"):
            self.assertNotIn(key, written)

    def test_a_default_stored_as_the_table_id_stays(self) -> None:
        self.info["vpinfe"]["default_table"] = "t1"
        (self.folder / f"{FOLDER}.info").write_text(json.dumps(self.info))

        self.swap()

        self.assertEqual(self.record()["vpinfe"]["default_table"], "t1")

    def test_another_table_is_not_touched(self) -> None:
        self.swap()

        self.assertEqual(self.record()["tables"]["t2"],
                         {"id": "t2", "filename": "Cactus Other.vpx"})
        self.assertEqual((self.folder / "Cactus Other.vpx").read_bytes(), b"other")

    def test_the_release_picked_is_tied_afterwards(self) -> None:
        with (patch.object(table_swap, "find_vps_release", return_value={}),
              patch.object(table_swap, "set_table_source") as tie):
            self.swap(vps_file_id="new-file")

        tie.assert_called_once_with(self.game, BEING, "new-file")


class CarryTests(SwapCase):
    def setUp(self) -> None:
        super().setUp()
        self.put("Cactus 1.1.ini", b"ini")
        self.put("Cactus 1.1.directb2s", b"glass")
        self.put("Cactus 1.1.vbs", b"script")
        self.put("Cactus 1.1.pov", b"pov")
        self.put("Cactus.directb2s", b"shared glass")

    def test_an_update_carries_the_settings_and_the_machine_files_but_not_the_script(
            self) -> None:
        done = self.swap()

        self.assertEqual(self.names(), [
            "Cactus 1.2.directb2s", "Cactus 1.2.ini", "Cactus 1.2.pov", BEING,
            "Cactus Other.vpx", "Cactus.directb2s", f"{FOLDER}.info"])
        self.assertEqual((self.folder / "Cactus 1.2.directb2s").read_bytes(), b"glass")
        self.assert_kept(OLD, "Cactus 1.1.vbs")
        self.assertEqual(len(done["kept"]), 2)

    def test_another_release_carries_only_what_was_made_for_the_machine(self) -> None:
        self.swap(instead=True)

        self.assertEqual(self.names(), [
            "Cactus 1.2.directb2s", BEING, "Cactus Other.vpx", "Cactus.directb2s",
            f"{FOLDER}.info"])
        self.assert_kept(OLD, "Cactus 1.1.ini", "Cactus 1.1.pov", "Cactus 1.1.vbs")

    def test_what_is_ticked_is_what_is_carried(self) -> None:
        self.swap(carry=["script"])

        self.assertIn("Cactus 1.2.vbs", self.names())
        self.assert_kept(OLD, "Cactus 1.1.directb2s", "Cactus 1.1.ini",
                                       "Cactus 1.1.pov")

    def test_a_file_named_for_the_folder_is_shared_and_stays(self) -> None:
        self.swap(carry=[])

        self.assertEqual((self.folder / "Cactus.directb2s").read_bytes(), b"shared glass")
        self.assertNotIn("Cactus.directb2s", self.kept())

    def test_a_carried_file_wins_over_one_the_new_file_brings(self) -> None:
        (self.offered / "Cactus 1.2.ini").write_bytes(b"theirs")
        (self.offered / "Cactus 1.2.pov").write_bytes(b"their pov")

        self.swap(carry=["ini"])

        self.assertEqual((self.folder / "Cactus 1.2.ini").read_bytes(), b"ini")
        self.assertEqual((self.folder / "Cactus 1.2.pov").read_bytes(), b"their pov")

    def test_what_the_new_file_brings_is_not_carried_over_by_default(self) -> None:
        (self.offered / "Cactus 1.2.ini").write_bytes(b"theirs")

        self.swap()

        self.assertEqual((self.folder / "Cactus 1.2.ini").read_bytes(), b"theirs")
        self.assertIn("Cactus 1.1.ini", self.kept())

    def test_a_new_file_named_for_the_folder_leaves_the_shared_names_alone(self) -> None:
        self.arrives = self.offered / "Cactus.vpx"
        self.arrives.write_bytes(b"new")

        self.swap(carry=["ini", "backglass", "pov"])

        self.assertEqual((self.folder / "Cactus.directb2s").read_bytes(), b"shared glass")
        self.assertNotIn("Cactus.ini", self.names())
        self.assertEqual((self.folder / "Cactus.pov").read_bytes(), b"pov")
        self.assert_kept(OLD, "Cactus 1.1.directb2s", "Cactus 1.1.ini", "Cactus 1.1.vbs")

    def test_a_file_the_new_one_brings_is_placed_where_nothing_is(self) -> None:
        (self.offered / "Cactus 1.2.ini").write_bytes(b"theirs")

        self.swap(carry=[])

        self.assertEqual((self.folder / "Cactus 1.2.ini").read_bytes(), b"theirs")

    def test_a_file_already_named_for_the_new_one_is_kept_before_it_is_replaced(self) -> None:
        self.put("Cactus 1.2.ini", b"stale")

        self.swap(carry=["ini"])

        self.assertEqual((self.folder / "Cactus 1.2.ini").read_bytes(), b"ini")
        self.assertIn("Cactus 1.2.ini", self.kept())
        self.assertIn(b"stale", self.kept_bytes())


class PlanTests(SwapCase):
    def setUp(self) -> None:
        super().setUp()
        for name in ("Cactus 1.1.ini", "Cactus 1.1.directb2s", "Cactus 1.1.vbs"):
            self.put(name)

    def ticked(self, **options) -> dict[str, bool]:
        done = table_swap.plan(GAME_ID, "t1", **options)
        return {one["kind"]: one["carry"] for one in done["files"]}

    def test_an_update_ticks_everything_but_the_script(self) -> None:
        self.assertEqual(self.ticked(), {"backglass": True, "ini": True, "script": False})

    def test_another_release_ticks_only_the_machine_files(self) -> None:
        self.assertEqual(self.ticked(instead=True),
                         {"backglass": True, "ini": False, "script": False})

    def test_a_file_the_new_one_brings_starts_unticked(self) -> None:
        (self.offered / "Cactus 1.2.ini").write_bytes(b"theirs")

        done = table_swap.plan(GAME_ID, "t1", str(self.arrives))

        brought = {one["kind"]: (one["carry"], one["brought"]) for one in done["files"]}
        self.assertEqual(brought["ini"], (False, True))
        self.assertEqual(brought["backglass"], (True, False))

    def test_a_new_file_named_for_the_folder_cannot_take_the_shared_kinds(self) -> None:
        (self.offered / "Cactus.vpx").write_bytes(b"new")

        self.assertEqual(self.ticked(source=str(self.offered / "Cactus.vpx")),
                         {"backglass": False, "ini": False, "script": False})

    def test_the_ticks_are_what_a_swap_without_a_choice_carries(self) -> None:
        (self.offered / "Cactus 1.2.ini").write_bytes(b"theirs")
        ticked = {one["kind"] for one in table_swap.plan(GAME_ID, "t1", str(self.arrives))["files"]
                  if one["carry"]}

        self.swap()

        self.assertEqual(ticked, {"backglass"})
        self.assertEqual(sorted(self.kept()), sorted([OLD, "Cactus 1.1.ini", "Cactus 1.1.vbs"]))

    def test_a_table_patched_from_this_one_is_named(self) -> None:
        self.info["tables"]["t2"]["source"] = {"base": {"file": OLD, "hash": "x"}}
        (self.folder / f"{FOLDER}.info").write_text(json.dumps(self.info))

        self.assertEqual(table_swap.plan(GAME_ID, "t1")["patched"], ["Cactus Other.vpx"])


class RefusalTests(SwapCase):
    def refused(self, error: type[Exception] = service_errors.RefusedError, **options) -> None:
        before = self.names()
        with self.assertRaises(error):
            self.swap(**options)
        self.assertEqual(self.names(), before)
        self.assert_kept()
        self.assertEqual(self.record()["tables"]["t1"]["filename"], OLD)

    def test_a_file_that_is_not_there(self) -> None:
        self.arrives.unlink()

        self.refused()

    def test_a_file_no_app_plays(self) -> None:
        self.arrives = self.offered / "Cactus 1.2.txt"
        self.arrives.write_bytes(b"x")

        self.refused()

    def test_the_file_the_table_already_is(self) -> None:
        self.arrives = self.folder / OLD

        self.refused()

    def test_a_name_another_file_in_the_game_already_has(self) -> None:
        (self.folder / BEING).write_bytes(b"in the way")

        self.refused(service_errors.BlockedError)

    def test_a_game_that_is_running(self) -> None:
        self.running = launch_state.LaunchState(launching=True, game_id=GAME_ID)

        self.refused(service_errors.BlockedError)

    def test_a_table_the_game_does_not_hold(self) -> None:
        with self.assertRaises(service_errors.RefusedError):
            table_swap.replace(GAME_ID, "nope", str(self.arrives))

    def test_a_table_kept_outside_the_game_folder(self) -> None:
        self.info["tables"]["t1"]["path"] = "../elsewhere/Cactus.vpx"
        (self.folder / f"{FOLDER}.info").write_text(json.dumps(self.info))

        with self.assertRaises(service_errors.RefusedError):
            table_swap.replace(GAME_ID, "t1", str(self.arrives))
        with self.assertRaises(service_errors.RefusedError):
            table_swap.delete(GAME_ID, "t1")

        self.assertIn(OLD, self.names())

    def test_a_game_running_under_its_folder_name_is_found_too(self) -> None:
        self.running = launch_state.LaunchState(launching=True, game_name=FOLDER)

        self.refused(service_errors.BlockedError)

    def test_a_release_the_tables_app_does_not_play(self) -> None:
        with patch.object(table_swap, "find_vps_release", return_value={"tableFormat": "FP"}):
            self.refused(vps_file_id="other-format")

    def test_a_backups_folder_that_cannot_be_written(self) -> None:
        with patch.object(backup_folder, "for_writing",
                          side_effect=service_errors.BlockedError("read only")):
            self.refused(service_errors.BlockedError)


class RestoreTests(SwapCase):
    def test_the_old_file_comes_back_from_backups(self) -> None:
        copy = self.swap()["kept"][0]

        backup_ops.restore(copy["id"])

        self.assertEqual((self.folder / OLD).read_bytes(), b"old")
        self.assertEqual((self.folder / BEING).read_bytes(), b"new")

    def test_a_game_that_is_running_is_not_restored_over(self) -> None:
        copy = self.swap()["kept"][0]
        self.running = launch_state.LaunchState(launching=True, game_id=GAME_ID)

        with self.assertRaises(service_errors.BlockedError):
            backup_ops.restore(copy["id"])

        self.assertNotIn(OLD, self.names())


class DeleteTests(SwapCase):
    def test_the_table_and_its_files_go_and_are_kept(self) -> None:
        self.put("Cactus 1.1.ini")
        self.put("Cactus.directb2s")

        done = table_swap.delete(GAME_ID, "t1")

        self.assertEqual(self.names(), ["Cactus Other.vpx", "Cactus.directb2s", f"{FOLDER}.info"])
        self.assert_kept(OLD, "Cactus 1.1.ini")
        self.assertEqual(len(done["kept"]), 2)

    def test_the_entry_goes_and_the_default_is_no_longer_this_table(self) -> None:
        table_swap.delete(GAME_ID, "t1")

        record = self.record()
        self.assertNotIn("t1", record["tables"])
        self.assertEqual(record["vpinfe"]["default_table"], "")
        self.assertIn("t2", record["tables"])

    def test_a_default_stored_as_the_table_id_is_cleared(self) -> None:
        self.info["vpinfe"]["default_table"] = "t1"
        (self.folder / f"{FOLDER}.info").write_text(json.dumps(self.info))

        table_swap.delete(GAME_ID, "t1")

        self.assertEqual(self.record()["vpinfe"]["default_table"], "")

    def test_the_kept_copy_is_the_file_as_it_was(self) -> None:
        table_swap.delete(GAME_ID, "t1")

        self.assertEqual(self.kept_bytes(), [b"old"])

    def test_a_record_that_cannot_be_written_is_a_refusal_and_the_game_is_read_again(self) -> None:
        with patch.object(table_swap.MetaConfig, "drop_table", side_effect=OSError("read only")), \
                patch.object(table_swap, "reread_game") as reread, \
                self.assertRaises(service_errors.BlockedError):
            table_swap.delete(GAME_ID, "t1")

        reread.assert_called_once()

    def test_the_last_table_leaves_the_game_with_its_settings(self) -> None:
        table_swap.delete(GAME_ID, "t2")
        table_swap.delete(GAME_ID, "t1")

        self.assertEqual(self.record()["tables"], {})
        self.assertEqual(self.names(), [f"{FOLDER}.info"])

    def test_a_game_that_is_running_keeps_its_table(self) -> None:
        self.running = launch_state.LaunchState(launching=True, game_id=GAME_ID)

        with self.assertRaises(service_errors.BlockedError):
            table_swap.delete(GAME_ID, "t1")

        self.assertIn(OLD, self.names())

    def test_nothing_is_deleted_when_backups_cannot_be_written(self) -> None:
        with patch.object(backup_folder, "for_writing",
                          side_effect=service_errors.BlockedError("read only")), \
                self.assertRaises(service_errors.BlockedError):
            table_swap.delete(GAME_ID, "t1")

        self.assertIn(OLD, self.names())
        self.assertIn("t1", self.record()["tables"])
