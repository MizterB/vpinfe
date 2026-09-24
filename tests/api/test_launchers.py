"""Launchers over the wire.

The id is the caller's to send, which is the part worth pinning: it is also how a launcher
copied to a cabinet lands without being renumbered, and renumbering would break every
mapping that travelled with it.
"""

import os
import pathlib
import unittest
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

import httpapi
from common.games import launcher_migration, launchers


def _client() -> TestClient:
    return TestClient(httpapi.create_api_app(), raise_server_exceptions=False)


class LauncherApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = launchers.LauncherStore(
            os.path.join(self.tmp.name, "launchers.json"))
        patcher = patch.object(launchers, "get_launcher_store",
                               return_value=self.store)
        patcher.start()
        self.addCleanup(patcher.stop)
        # Marked as already seeded: building the app runs the startup pass, and a
        # shipped launcher appearing under these would make every count here wrong.
        # A real install is in this state from its second start onwards.
        self.store.mark_migration(launcher_migration.SEEDED)
        self.client = _client()

    def _put(self, launcher_id: str, **body):
        return self.client.put(f"/launchers/{launcher_id}",
                               json={"app": "vpx", **body})

    def test_an_install_with_none_answers_an_empty_list(self) -> None:
        body = self.client.get("/launchers").json()

        self.assertEqual(body["launchers"], [])
        self.assertEqual(body["mappings"], {})
        self.assertIsNone(body["defaults"]["vpx"])

    def test_a_launcher_carries_the_shape_of_its_own_settings(self) -> None:
        """So a client can draw an editor without knowing what a Visual Pinball launcher
        happens to hold - which is the point of the app declaring its fields."""
        self._put("one", display_name="VPX")

        found = self.client.get("/launchers").json()["launchers"][0]

        self.assertEqual(found["app_name"], "Visual Pinball X")
        keys = [field["key"] for field in found["fields"]]
        self.assertIn("bin_path", keys)
        self.assertEqual(sorted(found["settings"]), sorted(keys))

    def test_a_launcher_says_whether_its_app_keeps_settings_of_its_own(self) -> None:
        self._put("vpx", display_name="VPX")
        self._put("gen", app="generic", display_name="Generic")

        held = {one["launcher_id"]: one["has_config"]
                for one in self.client.get("/launchers").json()["launchers"]}

        self.assertEqual(held, {"vpx": True, "gen": False})

    def test_the_caller_names_the_id(self) -> None:
        """A launcher copied from another machine is that launcher. Minting a new id here
        would break the mappings that came with it."""
        self._put("kept-id", display_name="VPX")

        self.assertEqual(self.client.get("/launchers").json()["launchers"][0]
                         ["launcher_id"], "kept-id")

    def test_putting_it_again_replaces_it(self) -> None:
        self._put("one", display_name="First")
        self._put("one", display_name="Second")

        held = self.client.get("/launchers").json()["launchers"]

        self.assertEqual([one["display_name"] for one in held], ["Second"])

    def test_a_name_another_launcher_has_is_refused(self) -> None:
        self._put("one", display_name="VPX")

        refused = self._put("two", display_name=" vpx ")

        self.assertEqual(refused.status_code, 400)
        self.assertEqual(refused.json()["error"]["message"],
                         "Another launcher is already called vpx.")
        self.assertEqual(len(self.client.get("/launchers").json()["launchers"]), 1)

    def test_whatever_app_it_runs(self) -> None:
        self._put("one", display_name="Mine")

        self.assertEqual(self._put("two", app="generic", display_name="MINE").status_code,
                         400)

    def test_a_launcher_keeps_its_own_name(self) -> None:
        self._put("one", display_name="VPX")

        self.assertEqual(self._put("one", display_name="VPX", enabled=True).status_code, 200)

    def test_a_blank_name_is_its_app_s_and_that_is_checked_too(self) -> None:
        self._put("one", display_name="Visual Pinball X")

        self.assertEqual(self._put("two").status_code, 400)

    def test_the_default_is_named_rather_than_left_to_be_worked_out(self) -> None:
        """A client re-deriving "first enabled for this app" is a second place for the
        rule to be wrong."""
        self._put("off", display_name="Off", enabled=False)
        self._put("on", display_name="On")

        self.assertEqual(self.client.get("/launchers").json()["defaults"]["vpx"], "on")

    def test_an_app_this_build_does_not_know_is_refused(self) -> None:
        """A typo would make a launcher nothing can ever run, listed as though it could."""
        response = self.client.put("/launchers/one", json={"app": "atari-pinball"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("atari-pinball", response.json()["error"]["message"])

    def test_a_launcher_says_what_the_disk_makes_of_its_paths(self) -> None:
        """Without it, one pointing at a program that has been uninstalled looks exactly
        like one that works, and the list cannot say which of two can run a table."""
        self._put("one", settings={"bin_path": "/nope/VPinballX"})

        checks = self.client.get("/launchers").json()["launchers"][0]["checks"]

        self.assertEqual(checks["bin_path"]["state"], "missing")
        self.assertTrue(checks["bin_path"]["reason"])

    def test_a_path_that_is_there_is_reported_ok(self) -> None:
        import os
        program = os.path.join(self.tmp.name, "VPinballX")
        with open(program, "w", encoding="utf-8"):
            pass
        os.chmod(program, 0o755)
        self._put("one", settings={"bin_path": program})

        checks = self.client.get("/launchers").json()["launchers"][0]["checks"]

        self.assertEqual(checks["bin_path"]["state"], "ok")
        self.assertEqual(checks["bin_path"]["reason"], "")

    def test_only_the_fields_that_name_a_path_are_checked(self) -> None:
        """A state on every field would be a mark on every row, which says nothing."""
        self._put("one", settings={"bin_path": "/nope/VPinballX"})

        checks = self.client.get("/launchers").json()["launchers"][0]["checks"]

        self.assertNotIn("launch_env", checks)
        self.assertNotIn("log_delete_on_start", checks)

    def test_removing_one_takes_its_mappings(self) -> None:
        self._put("one", display_name="VPX")
        self.client.put("/launchers/mappings/t1", json={"launcher_id": "one"})

        self.client.delete("/launchers/one")

        body = self.client.get("/launchers").json()
        self.assertEqual(body["launchers"], [])
        self.assertEqual(body["mappings"], {})

    def test_removing_one_that_is_not_there_is_a_404(self) -> None:
        self.assertEqual(self.client.delete("/launchers/ghost").status_code, 404)

    def test_a_table_can_be_pointed_at_one_and_cleared(self) -> None:
        self._put("one", display_name="VPX")

        self.client.put("/launchers/mappings/t1", json={"launcher_id": "one"})
        self.assertEqual(self.client.get("/launchers").json()["mappings"],
                         {"t1": "one"})

        self.client.put("/launchers/mappings/t1", json={"launcher_id": ""})
        self.assertEqual(self.client.get("/launchers").json()["mappings"], {},
                         "cleared drops the row, because absent already means default")

    def test_pointing_a_table_at_a_launcher_that_is_not_there_is_refused(self) -> None:
        """Storing it would be a table reporting an override it does not have."""
        response = self.client.put("/launchers/mappings/t1",
                                   json={"launcher_id": "ghost"})

        self.assertEqual(response.status_code, 404)


class _TableCase(unittest.TestCase):
    """A launcher, and one table whose folder has a settings file of its own."""

    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = launchers.LauncherStore(
            os.path.join(self.tmp.name, "launchers.json"))
        store_patch = patch.object(launchers, "get_launcher_store",
                                   return_value=self.store)
        store_patch.start()
        self.addCleanup(store_patch.stop)
        self.store.mark_migration(launcher_migration.SEEDED)
        self.client = _client()
        self.client.put("/launchers/l1",
                        json={"app": "vpx", "settings": {"bin_path": "/opt/vpx"}})
        folder = os.path.join(self.tmp.name, "Attack from Mars")
        os.makedirs(folder)
        self.table = os.path.join(folder, "afm.vpx")
        pathlib.Path(self.table).touch()
        pathlib.Path(folder, "Attack from Mars.ini").write_text(
            "[Player]\nBallTrail = 1\nFXAA = 3\n")
        self.beside = os.path.join(folder, "afm.ini")
        patcher = patch("common.games.launcher_ops._game_file", return_value=self.table)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _write(self, **body):
        return self.client.put("/launchers/l1/config",
                               json={"scope": "entry", "table": "t1", **body})


class TableFileSeedingTests(_TableCase):
    """The two settings layers do not stack, so the write that gives a table its own
    file takes the folder's other keys off it. Carrying them across on that first write
    is what keeps the table doing what it did a moment ago."""

    def test_a_folder_says_what_it_is_giving_a_table_with_no_file_of_its_own(self) -> None:
        got = self.client.get("/launchers/l1/config/reaching?table=t1")

        self.assertEqual(got.json()["reaching"],
                         {"Player.BallTrail": "1", "Player.FXAA": "3"})

    def test_the_first_write_carries_them_across_when_it_is_asked_to(self) -> None:
        self._write(values={"Backglass.BackglassWndX": "137"}, seed=True)

        written = pathlib.Path(self.beside).read_text()
        self.assertIn("BallTrail = 1", written)
        self.assertIn("FXAA = 3", written)
        self.assertIn("BackglassWndX = 137", written)

    def test_and_the_value_being_set_wins_over_what_it_carried(self) -> None:
        """The write is the reason any of this is happening."""
        self._write(values={"Player.FXAA": "0"}, seed=True)

        self.assertIn("FXAA = 0", pathlib.Path(self.beside).read_text())

    def test_without_asking_it_writes_only_what_it_was_given(self) -> None:
        """Which is what takes the other two off the table - so nothing does this
        silently."""
        self._write(values={"Backglass.BackglassWndX": "137"})

        written = pathlib.Path(self.beside).read_text()
        self.assertNotIn("BallTrail", written)
        self.assertIn("BackglassWndX = 137", written)

    def test_a_carried_value_the_launcher_already_has_is_left_to_it(self) -> None:
        app_ini = pathlib.Path(self.tmp.name, "VPinballX.ini")
        app_ini.write_text("[Player]\nBallTrail = 1\n")
        self.client.put("/launchers/l1", json={"app": "vpx", "settings": {
            "bin_path": "/opt/vpx", "ini_path": str(app_ini)}})

        got = self._write(values={"Backglass.BackglassWndX": "137"}, seed=True)

        self.assertEqual(got.status_code, 200, got.text)
        self.assertEqual(got.json(), {"written": ["Backglass.BackglassWndX", "Player.FXAA"],
                                      "cleared": ["Player.BallTrail"]})
        self.assertNotIn("BallTrail", pathlib.Path(self.beside).read_text())

    def test_a_table_that_already_has_a_file_has_nothing_left_reaching_it(self) -> None:
        """So the second write cannot re-seed from a folder it no longer reads."""
        self._write(values={"Backglass.BackglassWndX": "137"}, seed=True)

        got = self.client.get("/launchers/l1/config/reaching?table=t1")

        self.assertEqual(got.json()["reaching"], {})


class ClearingTests(_TableCase):
    def test_a_table_s_own_value_says_what_clearing_it_leaves(self) -> None:
        """The launcher's value, not the folder's: the table's own file is the one
        read now."""
        app_ini = pathlib.Path(self.tmp.name, "VPinballX.ini")
        app_ini.write_text("[Player]\nFXAA = 1\n")
        self.client.put("/launchers/l1", json={"app": "vpx", "settings": {
            "bin_path": "/opt/vpx", "ini_path": str(app_ini)}})
        self._write(values={"Player.FXAA": "2"})

        got = self.client.get("/launchers/l1/config?table=t1&scope=entry")

        held = got.json()["values"]["Player.FXAA"]
        self.assertEqual((held["value"], held["fallback"], held["fallback_scope"]),
                         ("2", "1", "launcher"))


class BlankWordsTests(_TableCase):
    def test_a_window_size_left_blank_reads_from_the_screen(self) -> None:
        app_ini = pathlib.Path(self.tmp.name, "VPinballX.ini")
        app_ini.write_text("[Player]\n; Width: Width of the window [Default: 16384]\n"
                           "PlayfieldWidth =\nFXAA = 1\n")
        self.client.put("/launchers/l1", json={"app": "vpx", "settings": {
            "bin_path": "/opt/vpx", "ini_path": str(app_ini)}})

        got = self.client.get("/launchers/l1/config")

        offered = {f["key"]: f for g in got.json()["groups"] for f in g["settings"]}
        size = offered["Player.PlayfieldWidth"]
        self.assertEqual((size["default"], size["blank"]), ("", "From the screen"))
        self.assertEqual(offered["Player.FXAA"]["blank"], "")


class SharedWithGameTests(_TableCase):
    def test_the_table_named_after_its_folder_says_its_file_is_the_game_s(self) -> None:
        named = os.path.join(os.path.dirname(self.table), "Attack from Mars.vpx")
        pathlib.Path(named).touch()

        with patch("common.games.launcher_ops._game_file", return_value=named):
            got = self.client.get("/launchers/l1/config?table=t1&scope=entry")

        self.assertIs(got.json()["shared_with_game"], True)

    def test_another_table_s_file_is_its_own(self) -> None:
        got = self.client.get("/launchers/l1/config?table=t1&scope=entry")

        self.assertIs(got.json()["shared_with_game"], False)


class AllTablesOnlyTests(_TableCase):
    def setUp(self) -> None:
        super().setUp()
        app_ini = pathlib.Path(self.tmp.name, "VPinballX.ini")
        app_ini.write_text("[Input]\nNudgeSensorCount = 2\n\n"
                           "[Player]\nShowFPS = 0\nFXAA = 1\n")
        self.client.put("/launchers/l1", json={"app": "vpx", "settings": {
            "bin_path": "/opt/vpx", "ini_path": str(app_ini)}})

    def _offered(self, scope: str) -> dict:
        got = self.client.get(f"/launchers/l1/config?table=t1&scope={scope}")
        self.assertEqual(got.status_code, 200, got.text)
        return {f["key"]: f for g in got.json()["groups"] for f in g["settings"]}

    def test_the_launcher_offers_it(self) -> None:
        offered = self._offered("launcher")

        self.assertEqual(offered["Player.ShowFPS"]["scopes"], ["launcher"])
        self.assertEqual(offered["Player.FXAA"]["scopes"], ["launcher", "folder", "entry"])

    def test_a_table_and_a_folder_do_not(self) -> None:
        for scope in ("entry", "folder"):
            with self.subTest(scope=scope):
                offered = self._offered(scope)
                self.assertNotIn("Player.ShowFPS", offered)
                self.assertNotIn("Input.NudgeSensorCount", offered)
                self.assertIn("Player.FXAA", offered)

    def test_one_a_table_s_file_already_holds_is_still_listed(self) -> None:
        pathlib.Path(self.beside).write_text("[Player]\nShowFPS = 1\n")

        offered = self._offered("entry")

        self.assertEqual(offered["Player.ShowFPS"]["scopes"], ["launcher"])

    def test_writing_one_at_a_table_is_refused(self) -> None:
        got = self._write(values={"Player.ShowFPS": "1"})

        self.assertEqual(got.status_code, 400, got.text)
        self.assertFalse(os.path.exists(self.beside))

    def test_clearing_one_at_a_table_is_not(self) -> None:
        pathlib.Path(self.beside).write_text("[Player]\nShowFPS = 1\nFXAA = 3\n")

        got = self._write(values={"Player.ShowFPS": ""})

        self.assertEqual(got.status_code, 200, got.text)
        self.assertNotIn("ShowFPS", pathlib.Path(self.beside).read_text())


class SwitchingOffTests(unittest.TestCase):
    """Three tables, all played by the first of two VPX launchers."""

    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = launchers.LauncherStore(
            os.path.join(self.tmp.name, "launchers.json"))
        store_patch = patch.object(launchers, "get_launcher_store",
                                   return_value=self.store)
        store_patch.start()
        self.addCleanup(store_patch.stop)
        self.store.mark_migration(launcher_migration.SEEDED)
        library = [SimpleNamespace(meta_config={"tables": {
            one: {"id": one, "filename": f"{one}.vpx"} for one in ("t1", "t2", "t3")}})]
        games_patch = patch("common.games.game_repository.all_games",
                            return_value=library)
        games_patch.start()
        self.addCleanup(games_patch.stop)
        self.client = _client()
        self._put("wide", display_name="VPX Wide", bin_path="/opt/wide")
        self._put("plain", display_name="VPX Plain", bin_path="/opt/plain")

    def _put(self, launcher_id: str, *, app: str = "vpx", enabled: bool = True,
             display_name: str = "", bin_path: str = ""):
        return self.client.put(f"/launchers/{launcher_id}", json={
            "app": app, "display_name": display_name, "enabled": enabled,
            "settings": {"bin_path": bin_path}})

    def _fallback(self, launcher_id: str) -> dict:
        got = self.client.get(f"/launchers/{launcher_id}/fallback")
        self.assertEqual(got.status_code, 200, got.text)
        return got.json()

    def _enabled(self, launcher_id: str) -> bool:
        return next(one["enabled"] for one in self.client.get("/launchers").json()
                    ["launchers"] if one["launcher_id"] == launcher_id)

    def test_it_counts_the_tables_it_plays_and_names_where_they_go(self) -> None:
        said = self._fallback("wide")

        self.assertEqual(said["tables"], 3)
        self.assertEqual(said["fallbacks"], [{"launcher_id": "plain",
                                              "display_name": "VPX Plain",
                                              "tables": 3, "has_program": True}])
        self.assertEqual(said["refused"], "")

    def test_a_table_pointed_elsewhere_is_not_counted(self) -> None:
        self.store.assign("t1", "plain")

        self.assertEqual(self._fallback("wide")["tables"], 2)

    def test_one_pointed_at_a_launcher_that_is_not_the_default_is(self) -> None:
        self.store.assign("t1", "plain")

        said = self._fallback("plain")

        self.assertEqual(said["tables"], 1)
        self.assertEqual(said["fallbacks"][0]["launcher_id"], "wide")

    def test_switching_off_onto_a_launcher_with_no_program_is_refused(self) -> None:
        self._put("plain", display_name="VPX Plain")

        got = self._put("wide", display_name="VPX Wide", bin_path="/opt/wide",
                        enabled=False)

        self.assertEqual(got.status_code, 400, got.text)
        self.assertIn("VPX Plain", got.json()["error"]["message"])
        self.assertTrue(self._enabled("wide"))

    def test_and_the_fallback_says_so_before_anything_is_tried(self) -> None:
        self._put("plain", display_name="VPX Plain")

        said = self._fallback("wide")

        self.assertFalse(said["fallbacks"][0]["has_program"])
        self.assertIn("VPX Plain", said["refused"])

    def test_switching_off_the_last_launcher_for_its_tables_is_refused(self) -> None:
        self.client.delete("/launchers/plain")
        self._put("gen", app="generic", display_name="Generic", bin_path="/opt/gen")

        got = self._put("wide", display_name="VPX Wide", bin_path="/opt/wide",
                        enabled=False)

        self.assertEqual(got.status_code, 400, got.text)
        self.assertEqual(self._fallback("wide")["fallbacks"][0]["launcher_id"], "")

    def test_one_no_table_uses_switches_off_whatever_the_fallback(self) -> None:
        self._put("spare", display_name="Spare")

        got = self._put("plain", display_name="VPX Plain", bin_path="/opt/plain",
                        enabled=False)

        self.assertEqual(got.status_code, 200, got.text)

    def test_a_working_fallback_lets_it_go(self) -> None:
        got = self._put("wide", display_name="VPX Wide", bin_path="/opt/wide",
                        enabled=False)

        self.assertEqual(got.status_code, 200, got.text)
        self.assertFalse(self._enabled("wide"))


if __name__ == "__main__":
    unittest.main()
