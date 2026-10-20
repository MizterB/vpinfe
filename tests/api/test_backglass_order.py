"""The order a table draws its backglass and score display in follows what its backglass
file places: the file's DMD switch, its undo, and the launcher's own order all settle it."""

from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from starlette.testclient import TestClient

import httpapi
from common import service_errors
from common.apps.contract import TableOrder
from common.games import backglass_ops, launcher_ops, order_record
from common.games.formats import directb2s_parser
from common.host import launch_state
from common.media import sized_media
from common.runtime import jobs
from tests.api.test_backglass_picture import FOLDER, GAME_ID, _directb2s
from tests.support.library import TempTree, fake_game, write_game

PUT = f"/games/{GAME_ID}/assets/backglass/displays"
UNDO = f"{PUT}/undo"
FILE = "t1.directb2s"
SECOND = "t2.directb2s"
TABLE = "t1.vpx"
SCORE = {"target": "ScoreView", "x": 2, "y": 3, "w": 12, "h": 4}
SWAPPED = {"ScoreView.Priority.B2S": "2", "ScoreView.Priority.Nixie": "1"}
MOVED = {"ScoreView.Priority.B2S": "5", "ScoreView.Priority.Nixie": "1"}
CLEARED = {"ScoreView.Priority.B2S": "", "ScoreView.Priority.Nixie": ""}


def _finished(job: jobs.Job | None) -> jobs.Job:
    assert job is not None
    for _ in range(500):
        if job.state != jobs.RUNNING:
            break
        threading.Event().wait(0.01)
    return job


class Settled(TempTree):
    def setUp(self) -> None:
        super().setUp()
        info = {"Info": {"Title": "Example"},
                "vpinfe": {"schema": 2, "id": GAME_ID, "default_table": "t1"},
                "tables": {"t1": {"id": "t1", "filename": "t1.vpx"},
                           "t2": {"id": "t2", "filename": "t2.vpx"},
                           "t3": {"id": "t3", "filename": "t3.vpx"}}}
        glass = _directb2s(size=(40, 30), scoreview=(24, 8))
        self.folder = write_game(
            self.root, FOLDER, info=info, vpx=False,
            files={"t1.vpx": b"vpx", FILE: glass, "t2.vpx": b"vpx", SECOND: glass,
                   "t3.vpx": b"vpx"})
        self.rows = [
            {"id": "t1", "launcher": "L1", "launcher_app_configurable": True,
             "filename": "t1.vpx"},
            {"id": "t2", "launcher": "L1", "launcher_app_configurable": True,
             "filename": "t2.vpx"},
            {"id": "t3", "launcher": "", "launcher_app_configurable": False,
             "filename": "t3.vpx"}]
        self.written: list[tuple[str, dict[str, str]]] = []
        self.asked: list[tuple[str, bool, dict[str, str]]] = []
        self.refusing = False
        self.moved = False
        self.running = launch_state.LaunchState()
        self.catalog_reads = 0
        game = self.game = fake_game(self.folder, FOLDER, meta=info)
        for patcher in (
                patch("common.games.game_repository.catalog", side_effect=self._catalog(game)),
                patch("common.games.game_repository.all_games", return_value=[game]),
                patch.object(sized_media, "ROOT", self.root / "sized"),
                patch.object(directb2s_parser, "ROOT", self.root / "glass"),
                patch.object(order_record, "PATH", self.root / "draw_order.json"),
                patch.object(launch_state, "current", side_effect=lambda: self.running),
                patch.object(backglass_ops, "_table_rows", side_effect=lambda *_a: self.rows),
                patch.object(launcher_ops, "backglass_order", side_effect=self._order),
                patch.object(launcher_ops, "write_table_settings", side_effect=self._write)):
            patcher.start()
            self.addCleanup(patcher.stop)
        jobs.reset_for_tests()
        self.addCleanup(jobs.reset_for_tests)
        directb2s_parser._facts.clear()
        self.addCleanup(directb2s_parser._facts.clear)
        self.client = TestClient(httpapi.create_api_app(), raise_server_exceptions=False)

    def _catalog(self, game: Any) -> Any:
        def read() -> dict[str, Any]:
            self.catalog_reads += 1
            return {GAME_ID: game}
        return read

    def _order(self, launcher_id: str, target: str, in_file: bool,
               written: dict[str, str] | None = None) -> TableOrder:
        name = target.rsplit("/", 1)[-1]
        self.asked.append((name, in_file, dict(written or {})))
        if in_file and written and self.moved:
            return TableOrder(write=dict(MOVED), ours=dict(MOVED))
        if in_file:
            return (TableOrder(ours=SWAPPED) if written == SWAPPED
                    else TableOrder(write=dict(SWAPPED), ours=dict(SWAPPED)))
        return TableOrder(write=dict(CLEARED)) if written else TableOrder()

    def _write(self, table_id: str, values: dict[str, str], settle: bool = True) -> dict[str, Any]:
        if self.refusing:
            raise service_errors.BlockedError("read-only")
        self.written.append((table_id, dict(values)))
        return {"written": sorted(values), "cleared": []}

    def put(self, body: dict | None = None) -> Any:
        return self.client.put(PUT, params={"path": FILE}, json=body or SCORE)


class FollowingTheFile(Settled):
    def test_a_score_view_dmd_gives_the_table_that_reads_the_file_its_order(self) -> None:
        response = self.put()

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.asked, [(TABLE, True, {})])
        self.assertEqual(self.written, [("t1", SWAPPED)])
        self.assertEqual(order_record.held(), {"t1": SWAPPED})

    def test_a_table_whose_file_places_no_dmd_and_has_no_record_is_never_asked(self) -> None:
        self.put()

        self.assertNotIn("t2.vpx", {name for name, _, _ in self.asked})

    def test_a_table_with_no_launcher_of_its_own_is_never_asked(self) -> None:
        self.put()

        self.assertEqual(self.written and {table for table, _ in self.written}, {"t1"})

    def test_a_backglass_window_dmd_is_not_a_score_view_dmd(self) -> None:
        self.put({"target": "Backglass", "x": 1, "y": 1, "w": 9, "h": 3})

        self.assertEqual(self.asked, [])
        self.assertEqual(self.written, [])
        self.assertEqual(order_record.held(), {})

    def test_taking_the_dmd_out_asks_again_with_the_pair_that_was_recorded(self) -> None:
        self.put()
        self.asked.clear()

        self.client.put(PUT, params={"path": FILE}, json={"target": "ScoreView"})

        self.assertEqual(self.asked, [(TABLE, False, SWAPPED)])
        self.assertEqual(self.written[-1], ("t1", CLEARED))
        self.assertEqual(order_record.held(), {})

    def test_undo_settles_the_tables_again(self) -> None:
        token = self.put().json()["undo"]
        self.asked.clear()

        response = self.client.post(UNDO, json={"undo": token})

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.asked, [(TABLE, False, SWAPPED)])

    def test_a_table_that_cannot_be_written_is_named_and_does_not_fail_the_change(self) -> None:
        self.refusing = True

        response = self.put()

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["displays"], [SCORE])
        self.assertEqual(response.json()["order_failed"],
                         [{"table": "t1", "name": TABLE, "reason": "read-only"}])
        self.assertEqual(order_record.held(), {}, "what was not written is not recorded")

    def test_a_change_that_leaves_every_table_written_names_none(self) -> None:
        self.assertEqual(self.put().json()["order_failed"], [])

    def test_a_refused_change_settles_nothing(self) -> None:
        with patch("common.games.backglass_displays.file_move.playing", return_value=True):
            response = self.put()

        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.asked, [])


class ReadingTheFiles(Settled):
    """What `score_dmds` says of each table: from the file it reads, once while it is unchanged."""

    def scored(self, launcher_id: str = "") -> dict[str, bool]:
        return {one.table: one.in_file for one in backglass_ops.score_dmds(self.game, launcher_id)}

    def test_a_table_is_scored_by_whether_its_file_places_a_score_view_dmd(self) -> None:
        self.assertEqual(self.scored(), {"t1": False, "t2": False})
        self.put()

        self.assertEqual(self.scored(), {"t1": True, "t2": False})

    def test_a_table_that_reads_no_backglass_file_is_scored_false_not_left_out(self) -> None:
        (self.folder / SECOND).unlink()

        self.assertEqual(self.scored(), {"t1": False, "t2": False})

    def test_a_damaged_file_leaves_its_table_out(self) -> None:
        (self.folder / SECOND).write_bytes(b"not a backglass")

        self.assertEqual(self.scored(), {"t1": False})

    def test_a_launcher_is_asked_only_for_the_tables_it_plays(self) -> None:
        self.assertEqual(self.scored("L2"), {})

    def test_the_game_file_is_the_table_s_own_so_its_settings_sit_beside_it(self) -> None:
        one = backglass_ops.score_dmds(self.game)[0]

        self.assertEqual((one.table, one.launcher, one.file),
                         ("t1", "L1", str(self.folder / TABLE)))

    def test_a_file_unchanged_is_not_read_again(self) -> None:
        self.scored()

        with patch.object(directb2s_parser, "read") as read:
            self.scored()

        read.assert_not_called()


class FollowingTheLauncher(Settled):
    """A write at the launcher's scope of a setting the order depends on settles its tables
    as a job, and a write at a table's scope settles that table."""

    def setUp(self) -> None:
        super().setUp()
        self.config = SimpleNamespace(
            scopes=lambda: ("launcher", "entry"), write=lambda *_a: frozenset(),
            order_keys=lambda: {"ScoreView.Priority.Nixie"})
        for patcher in (
                patch.object(launcher_ops, "launcher_or_refuse",
                             return_value=SimpleNamespace(app="vpx", launcher_id="L1")),
                patch.object(launcher_ops, "_app_settings_surface", return_value=self.config),
                patch.object(launcher_ops, "_launcher_settings", return_value={}),
                patch.object(launcher_ops, "_game_file", side_effect=lambda table: table),
                patch.object(launcher_ops, "_writable_before_writing")):
            patcher.start()
            self.addCleanup(patcher.stop)

    def write(self, body: dict[str, Any]) -> dict[str, Any]:
        answer = launcher_ops.write_config("L1", body)
        assert isinstance(answer, dict)
        return answer

    def test_a_launcher_write_of_a_key_that_decides_the_order_settles_as_a_job(self) -> None:
        self.put()
        self.written.clear()
        self.asked.clear()
        self.catalog_reads = 0

        answer = self.write({"values": {"ScoreView.Priority.Nixie": "5"}})
        job = _finished(jobs.get(answer["settling"]))

        self.assertEqual(job.state, jobs.DONE)
        self.assertEqual(self.asked, [(TABLE, True, SWAPPED)])
        self.assertEqual(self.catalog_reads, 1, "the library is read once")
        self.assertIsInstance(job.result, dict)

    def test_a_recorded_pair_is_rewritten_and_recorded_when_the_launcher_ranks_change(
            self) -> None:
        self.put()
        self.moved = True

        answer = self.write({"values": {"ScoreView.Priority.Nixie": "5"}})
        _finished(jobs.get(answer["settling"]))

        self.assertEqual(self.written[-1], ("t1", MOVED))
        self.assertEqual(order_record.held(), {"t1": MOVED})

    def test_the_job_names_the_tables_it_could_not_write(self) -> None:
        self.put()
        self.moved = True
        self.refusing = True

        answer = self.write({"values": {"ScoreView.Priority.Nixie": "5"}})
        job = _finished(jobs.get(answer["settling"]))

        assert isinstance(job.result, dict)
        self.assertEqual(job.result["failed"],
                         [{"table": "t1", "name": TABLE, "reason": "read-only"}])
        self.assertEqual(job.problems, 1)
        self.assertEqual(order_record.held(), {"t1": SWAPPED}, "a failed write keeps the record")

    def test_a_launcher_write_of_any_other_key_starts_no_job(self) -> None:
        answer = self.write({"values": {"Player.FXAA": "1"}})

        self.assertNotIn("settling", answer)
        self.assertEqual(self.asked, [])

    def test_a_launcher_write_is_refused_before_it_writes_while_a_pass_runs(self) -> None:
        release = threading.Event()
        jobs.submit(jobs.KIND_BACKGLASS_ORDER, lambda _job: release.wait(5))
        self.addCleanup(release.set)

        with self.assertRaises(jobs.JobBusyError):
            self.write({"values": {"ScoreView.Priority.Nixie": "5"}})

    def test_a_table_write_of_an_order_key_settles_that_table(self) -> None:
        self.put()
        self.asked.clear()

        self.write({"scope": "entry", "table": "t1",
                                         "values": {"ScoreView.Priority.Nixie": "5"}})

        self.assertEqual(self.asked, [(TABLE, True, SWAPPED)])

    def test_a_table_write_of_any_other_key_settles_nothing(self) -> None:
        self.write({"scope": "entry", "table": "t1",
                                         "values": {"Player.FXAA": "1"}})

        self.assertEqual(self.asked, [])
