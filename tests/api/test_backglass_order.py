"""The order a table draws its backglass and score display in follows what its backglass
file places: the file's DMD switch, its undo, and the launcher's own order all settle it."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from starlette.testclient import TestClient

import httpapi
from common import service_errors
from common.games import backglass_ops, launcher_ops
from common.games.formats import directb2s_parser
from common.host import launch_state
from common.media import sized_media
from tests.api.test_backglass_picture import FOLDER, GAME_ID, _directb2s
from tests.support.library import TempTree, fake_game, write_game

PUT = f"/games/{GAME_ID}/assets/backglass/displays"
UNDO = f"{PUT}/undo"
FILE = "t1.directb2s"
SECOND = "t2.directb2s"
SCORE = {"target": "ScoreView", "x": 2, "y": 3, "w": 12, "h": 4}
SWAPPED = {"ScoreView.Priority.B2S": "2", "ScoreView.Priority.Nixie": "1"}


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
        self.asked: list[tuple[str, bool]] = []
        self.refusing = False
        self.running = launch_state.LaunchState()
        game = fake_game(self.folder, FOLDER, meta=info)
        for patcher in (
                patch("common.games.game_repository.catalog", return_value={GAME_ID: game}),
                patch.object(sized_media, "ROOT", self.root / "sized"),
                patch.object(directb2s_parser, "ROOT", self.root / "glass"),
                patch.object(launch_state, "current", side_effect=lambda: self.running),
                patch.object(backglass_ops, "_table_rows", side_effect=lambda *_a: self.rows),
                patch.object(launcher_ops, "backglass_order", side_effect=self._order),
                patch.object(launcher_ops, "write_table_settings", side_effect=self._write)):
            patcher.start()
            self.addCleanup(patcher.stop)
        directb2s_parser._facts.clear()
        self.addCleanup(directb2s_parser._facts.clear)
        self.client = TestClient(httpapi.create_api_app(), raise_server_exceptions=False)

    def _order(self, table_id: str, in_file: bool) -> dict[str, str]:
        self.asked.append((table_id, in_file))
        return dict(SWAPPED) if in_file else {}

    def _write(self, table_id: str, values: dict[str, str]) -> dict[str, Any]:
        if self.refusing:
            raise service_errors.BlockedError("read-only")
        self.written.append((table_id, dict(values)))
        return {"written": sorted(values), "cleared": []}

    def put(self, body: dict | None = None) -> Any:
        return self.client.put(PUT, params={"path": FILE}, json=body or SCORE)


class FollowingTheFile(Settled):
    def test_a_score_view_dmd_gives_each_table_that_reads_the_file_its_order(self) -> None:
        response = self.put()

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(sorted(self.asked), [("t1", True), ("t2", False)])
        self.assertEqual(self.written, [("t1", SWAPPED)])

    def test_a_table_with_no_launcher_of_its_own_is_never_asked(self) -> None:
        self.put()

        self.assertNotIn("t3", {table for table, _ in self.asked})

    def test_a_backglass_window_dmd_is_not_a_score_view_dmd(self) -> None:
        self.put({"target": "Backglass", "x": 1, "y": 1, "w": 9, "h": 3})

        self.assertEqual(self.asked, [("t1", False), ("t2", False)])
        self.assertEqual(self.written, [])

    def test_taking_the_dmd_out_asks_again_with_the_file_as_it_now_is(self) -> None:
        self.put()
        self.asked.clear()

        self.client.put(PUT, params={"path": FILE}, json={"target": "ScoreView"})

        self.assertEqual(sorted(self.asked), [("t1", False), ("t2", False)])

    def test_undo_settles_the_tables_again(self) -> None:
        token = self.put().json()["undo"]
        self.asked.clear()

        response = self.client.post(UNDO, json={"undo": token})

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(sorted(self.asked), [("t1", False), ("t2", False)])

    def test_a_table_that_cannot_be_written_does_not_fail_the_change(self) -> None:
        self.refusing = True

        response = self.put()

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["displays"], [SCORE])

    def test_a_refused_change_settles_nothing(self) -> None:
        with patch("common.games.backglass_displays.file_move.playing", return_value=True):
            response = self.put()

        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.asked, [])


class FollowingTheLauncher(Settled):
    """A write at the launcher's scope of a setting the order depends on settles its tables."""

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

    def test_a_launcher_write_of_a_key_that_decides_the_order_settles_its_tables(self) -> None:
        self.put()
        self.written.clear()
        self.asked.clear()

        launcher_ops.write_config("L1", {"values": {"ScoreView.Priority.Nixie": "5"}})

        self.assertEqual(sorted(self.asked), [("t1", True), ("t2", False)])

    def test_a_launcher_write_of_any_other_key_settles_nothing(self) -> None:
        launcher_ops.write_config("L1", {"values": {"Player.FXAA": "1"}})

        self.assertEqual(self.asked, [])

    def test_a_table_write_settles_nothing(self) -> None:
        launcher_ops.write_config("L1", {"scope": "entry", "table": "t1",
                                         "values": {"ScoreView.Priority.Nixie": "5"}})

        self.assertEqual(self.asked, [])
