"""The script fixes as a source: asked daily by the watch, answered from the cache."""

from __future__ import annotations

import json
import threading
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from starlette.testclient import TestClient

import httpapi
from common import timestamps
from common.config.config_store import ConfigStore
from common.games import game_service, library_ops, library_policy
from common.i18n import t
from common.online import arrivals, script_fixes, sources, sources_watch, vpsdb_sync
from common.runtime import jobs
from manager.settings import settings
from tests.support.library import TempTree
from tests.support.sources import built_ins_afresh, fixes_apply_here, only

INDEX = [{"sha256": "aaa", "patched": {"url": "https://example.invalid/Alpha.vbs"}}]
ALPHA_HASH = "aaa"
FOUND = {"reachable": True, "offered": ["Alpha"], "already": 1, "checked": 4}


class _Kept(TempTree):
    """The cache in a folder of its own, the library policy fresh, every place the library
    is kept answering, and no request made. The count is stubbed unless `real` is set."""

    real = False

    def setUp(self) -> None:
        super().setUp()
        fixes_apply_here().start()
        built_ins_afresh().start()
        self.policy = library_policy.reset_for_tests(ConfigStore(str(self.root / "vpinfe.ini")))
        self.addCleanup(library_policy.reset_for_tests)
        self.addCleanup(setattr, script_fixes, "_fetcher", None)
        script_fixes._fetcher = None
        for one in (patch.object(script_fixes, "ANSWER_PATH", self.root / "answer.json"),
                    patch.object(script_fixes, "INDEX_PATH", self.root / "index.json"),
                    patch.object(script_fixes.game_repository, "all_games", return_value=[])):
            one.start()
            self.addCleanup(one.stop)
        self.answering = patch.object(script_fixes, "_library_answers", return_value=True).start()
        self.fetched = patch.object(script_fixes.standalone_scripts.StandaloneScripts,
                                    "download_hashes", return_value=INDEX).start()
        if not self.real:
            self.counted = patch.object(script_fixes.standalone_scripts, "offered_for",
                                        return_value=dict(FOUND)).start()
        self.addCleanup(patch.stopall)

    def free_while(self, holder: MagicMock) -> list[bool]:
        """Make `holder` note, whenever it runs, whether another thread could take the
        cache lock at that moment."""
        seen: list[bool] = []

        def note(*_args: Any, **_kwargs: Any) -> Any:
            def try_lock() -> None:
                free = script_fixes._LOCK.acquire(blocking=False)
                if free:
                    script_fixes._LOCK.release()
                seen.append(free)

            probe = threading.Thread(target=try_lock)
            probe.start()
            probe.join()
            return holder.return_value

        holder.side_effect = note
        return seen


class TheSource(unittest.TestCase):
    def test_it_ships_with_a_switch_and_asks_nothing_of_a_game_by_itself(self) -> None:
        with fixes_apply_here(), built_ins_afresh():
            self.assertIn(script_fixes.ID, [one.id for one in sources.all_sources()])
        source = script_fixes.SOURCE
        self.assertFalse(source.always_on)
        self.assertIsNotNone(source.refresh)
        self.assertIsNone(source.offers)
        self.assertEqual(frozenset(), source.kinds)


class Checking(_Kept):
    def test_never_checked_it_is_due_and_answers_nothing_found(self) -> None:
        self.assertTrue(script_fixes.due())
        self.assertEqual({"reachable": False, "offered": [], "already": 0, "checked": 0,
                          "checked_at": ""}, script_fixes.answer())

    def test_a_check_keeps_what_it_found_and_when(self) -> None:
        self.assertTrue(script_fixes.check())

        found = script_fixes.answer()
        self.assertEqual(["Alpha"], found["offered"])
        self.assertEqual((1, 4, True), (found["already"], found["checked"], found["reachable"]))
        self.assertTrue(found["checked_at"])
        self.counted.assert_called_once_with([], INDEX)

    def test_a_second_check_that_finds_the_same_says_nothing_moved(self) -> None:
        script_fixes.check()

        self.assertFalse(script_fixes.check())

    def test_it_is_not_due_again_for_a_day(self) -> None:
        script_fixes.check()
        now = timestamps.iso_to_epoch(script_fixes.checked_at()) or 0

        self.assertFalse(script_fixes.due(now + 3600))
        self.assertTrue(script_fixes.due(now + 24 * 3600 + 1))

    def test_the_default_clock_decides_when_none_is_given(self) -> None:
        def stamped(ago: float) -> None:
            moment = timestamps.iso_to_epoch(timestamps.utc_now_iso()) or 0
            script_fixes._write(script_fixes.ANSWER_PATH, {"checked_at": timestamps.epoch_to_iso(
                moment - ago)})

        stamped(60)
        self.assertFalse(script_fixes.due())
        stamped(2 * 24 * 3600)
        self.assertTrue(script_fixes.due())

    def test_a_stamp_in_the_future_is_due_rather_than_waited_out(self) -> None:
        script_fixes.check()
        now = timestamps.iso_to_epoch(script_fixes.checked_at()) or 0

        self.assertTrue(script_fixes.due(now - 3600))
        self.assertTrue(script_fixes.due(now - 30 * 24 * 3600))

    def test_a_library_with_no_table_read_yet_is_not_a_day_checked(self) -> None:
        self.counted.return_value = {"reachable": True, "offered": [], "already": 0,
                                     "checked": 0}

        self.assertFalse(script_fixes.check())

        self.assertTrue(script_fixes.due())
        self.assertFalse(script_fixes.ANSWER_PATH.exists())
        self.assertFalse(script_fixes.INDEX_PATH.exists())

    def test_a_library_with_a_place_away_is_not_counted_and_asks_nothing(self) -> None:
        self.answering.return_value = False

        self.assertFalse(script_fixes.check())

        self.assertTrue(script_fixes.due())
        self.fetched.assert_not_called()
        self.counted.assert_not_called()

    def test_the_next_wake_counts_once_the_library_is_back(self) -> None:
        self.answering.return_value = False
        script_fixes.check()
        self.answering.return_value = True

        self.assertTrue(script_fixes.check())

        self.assertFalse(script_fixes.due())

    def test_an_index_that_cannot_be_read_keeps_the_last_answer_and_is_asked_again(self) -> None:
        script_fixes.check()
        stamp = script_fixes.checked_at()
        self.fetched.return_value = []

        self.assertFalse(script_fixes.check())

        self.assertEqual(["Alpha"], script_fixes.answer()["offered"])
        self.assertEqual(stamp, script_fixes.checked_at())

    def test_an_index_that_cannot_be_read_the_first_time_leaves_nothing_checked(self) -> None:
        self.fetched.return_value = []

        script_fixes.check()

        self.assertTrue(script_fixes.due())
        self.assertFalse(script_fixes.answer()["reachable"])

    def test_switched_off_it_answers_as_if_it_had_never_looked(self) -> None:
        script_fixes.check()
        self.policy.set("hidden_sources", [script_fixes.ID])

        self.assertEqual([], script_fixes.answer()["offered"])
        self.assertFalse(script_fixes.answer()["reachable"])

    def test_counting_again_asks_nobody_and_keeps_when_the_index_was_read(self) -> None:
        script_fixes.check()
        stamp = script_fixes.checked_at()
        self.fetched.reset_mock()
        self.counted.return_value = {**FOUND, "offered": [], "already": 2}

        script_fixes.recount()

        self.fetched.assert_not_called()
        self.assertEqual(([], 2, stamp), (script_fixes.answer()["offered"],
                                          script_fixes.answer()["already"],
                                          script_fixes.checked_at()))

    def test_the_count_and_the_write_are_one_step_but_the_request_is_not_under_the_lock(
            self) -> None:
        in_request = self.free_while(self.fetched)
        in_count = self.free_while(self.counted)

        script_fixes.check()
        script_fixes.recount()

        self.assertEqual([True], in_request)
        self.assertEqual([False, False], in_count)

    def test_an_index_entry_that_is_not_an_object_is_dropped(self) -> None:
        self.fetched.return_value = [None, "text", 4, *INDEX]

        script_fixes.check()

        self.counted.assert_called_once_with([], INDEX)

    def test_an_index_that_is_not_a_list_is_an_index_that_cannot_be_read(self) -> None:
        self.fetched.return_value = {"error": "rate limited"}

        self.assertFalse(script_fixes.check())

        self.assertTrue(script_fixes.due())

    def test_counting_again_before_any_check_writes_nothing(self) -> None:
        script_fixes.recount()

        self.assertFalse(script_fixes.ANSWER_PATH.exists())


class Upgrades(_Kept):
    def setUp(self) -> None:
        super().setUp()
        script_fixes.check()

    def test_a_table_script_is_offered_a_fix_by_its_folder(self) -> None:
        self.assertEqual({"folder": "Alpha"},
                         script_fixes.upgrades({"folder": "/library/Alpha"}, "script"))
        self.assertEqual({"folder": "Alpha"},
                         script_fixes.upgrades({"folder": "C:\\library\\Alpha\\"}, "script"))

    def test_a_folder_with_no_fix_and_another_kind_get_nothing(self) -> None:
        self.assertEqual({}, script_fixes.upgrades({"folder": "Beta"}, "script"))
        self.assertEqual({}, script_fixes.upgrades({"folder": "Alpha"}, "wheel"))
        self.assertEqual({}, script_fixes.upgrades({}, "script"))


    def test_the_registry_asks_it_though_it_names_no_version(self) -> None:
        self.assertFalse(script_fixes.SOURCE.versions)
        self.assertIn(script_fixes.ID, [one.id for one in sources.upgrade_sources()])
        self.assertEqual({script_fixes.ID: {"folder": "Alpha"}},
                         sources.upgrades({"folder": "/library/Alpha"}, "script"))

    def test_the_registry_leaves_it_out_when_it_has_nothing_for_the_game(self) -> None:
        self.assertEqual({}, sources.upgrades({"folder": "Beta"}, "script"))
        self.assertEqual({}, sources.upgrades({"folder": "Alpha"}, "wheel"))

    def test_switched_off_the_registry_does_not_ask_it(self) -> None:
        self.policy.set("hidden_sources", [script_fixes.ID])

        self.assertEqual({}, sources.upgrades({"folder": "Alpha"}, "script"))


class InTheWatch(_Kept):
    def setUp(self) -> None:
        super().setUp()
        for one in (patch.object(arrivals, "PATH", self.root / "arrivals.json"),
                    patch.object(sources_watch, "compare", return_value=True),
                    patch.object(sources_watch, "_comparison_owed", False),
                    patch.object(vpsdb_sync, "adopt_due", return_value=False),
                    patch.object(vpsdb_sync, "art_due", return_value=False)):
            one.start()
            self.addCleanup(one.stop)

    def test_a_wake_reads_the_index_when_it_is_due_and_not_again_that_day(self) -> None:
        with only(script_fixes.SOURCE):
            sources_watch.watch_once(MagicMock())
            sources_watch.watch_once(MagicMock())

        self.fetched.assert_called_once_with()
        self.assertEqual(["Alpha"], script_fixes.answer()["offered"])

    def test_a_source_switched_off_is_not_read(self) -> None:
        self.policy.set("hidden_sources", [script_fixes.ID])
        with only(script_fixes.SOURCE):
            sources_watch.watch_once(MagicMock())

        self.fetched.assert_not_called()


class Fetching(_Kept):
    def run_fetch(self, **kwargs: Any) -> None:
        def inline(kind: str, work: Any, title: str = "") -> None:
            work(MagicMock())

        with patch.object(library_ops, "start", side_effect=inline):
            library_ops.apply_script_patches(**kwargs)

    def test_the_answer_is_counted_again_once_the_fixes_are_written(self) -> None:
        script_fixes.check()
        self.counted.return_value = {**FOUND, "offered": [], "already": 2}

        with patch.object(game_service, "apply_vpx_patches") as applied:
            self.run_fetch(only=["Alpha"])

        self.assertEqual([], script_fixes.answer()["offered"])
        self.assertEqual(["Alpha"], applied.call_args.kwargs["only"])

    def test_a_fetch_that_fails_still_counts_again(self) -> None:
        script_fixes.check()
        self.counted.return_value = {**FOUND, "offered": ["Alpha"], "already": 3}

        with patch.object(game_service, "apply_vpx_patches", side_effect=OSError("disk")):
            with self.assertRaises(OSError):
                self.run_fetch()

        self.assertEqual(3, script_fixes.answer()["already"])


    def test_a_count_that_fails_does_not_stand_in_for_the_fetch_failure(self) -> None:
        with patch.object(game_service, "apply_vpx_patches", side_effect=OSError("disk")), \
                patch.object(script_fixes, "recount", side_effect=ValueError("count")):
            with self.assertRaises(OSError):
                self.run_fetch()

    def test_a_count_that_fails_after_a_good_fetch_is_not_the_fetch_failing(self) -> None:
        with patch.object(game_service, "apply_vpx_patches"), \
                patch.object(script_fixes, "recount", side_effect=ValueError("count")):
            self.run_fetch()


class RealCount(_Kept):
    """The count itself, over a library of folders with a `.info` and a script hash."""

    real = True

    def table(self, name: str, vbs_hash: str, sidecar: bool = False) -> Any:
        folder = self.root / name
        folder.mkdir()
        vpx = folder / "Table.vpx"
        vpx.write_bytes(b"table")
        if sidecar:
            vpx.with_suffix(".vbs").write_text("' mine")
        (folder / f"{name}.info").write_text(json.dumps(
            {"Info": {"Name": name}, "VPinFE": {}, "User": {},
             "tables": {"Table.vpx": {"filename": "Table.vpx", "vbs_hash": vbs_hash}}}))
        return type("Game", (), {"full_path_game": str(folder),
                                 "full_path_vpx_file": str(vpx), "game_dir_name": name})()

    def library(self) -> list[Any]:
        return [self.table("Alpha", ALPHA_HASH), self.table("Beta", "zzz"),
                self.table("Gamma", ALPHA_HASH, sidecar=True), self.table("Unread", "")]

    def test_the_check_counts_what_the_index_matches(self) -> None:
        with patch.object(script_fixes.game_repository, "all_games", return_value=self.library()):
            self.assertTrue(script_fixes.check())

        found = script_fixes.answer()
        self.assertEqual((["Alpha"], 1, 3), (found["offered"], found["already"],
                                              found["checked"]))

    def test_fetching_a_fix_and_counting_again_stops_offering_it(self) -> None:
        games = self.library()
        with patch.object(script_fixes.game_repository, "all_games", return_value=games):
            script_fixes.check()
            Path(games[0].full_path_vpx_file).with_suffix(".vbs").write_text("' fixed")
            script_fixes.recount()

        found = script_fixes.answer()
        self.assertEqual(([], 2, 3), (found["offered"], found["already"], found["checked"]))
        self.assertTrue(found["checked_at"])

    def test_counting_again_over_a_held_index_with_a_bad_entry_does_not_raise(self) -> None:
        games = self.library()
        with patch.object(script_fixes.game_repository, "all_games", return_value=games):
            script_fixes.check()
            script_fixes._write(script_fixes.INDEX_PATH, {"index": [None, "x", *INDEX]})
            script_fixes.recount()

        self.assertEqual(["Alpha"], script_fixes.answer()["offered"])


class OnTheSourcesPage(_Kept):
    def test_it_is_listed_with_a_switch_after_the_catalog_and_says_what_it_gives(self) -> None:
        client = TestClient(httpapi.create_api_app(), raise_server_exceptions=False)
        library = MagicMock()
        library.media_sources.return_value = client.get("/media-sources").json()["sources"]
        named = settings.KIND_PAGES["media_sources"][3](library)

        with patch.object(settings.panel, "note", side_effect=lambda text, hint="": ("note", text)):
            entries = settings._sources_arranged(
                [(key, label, lambda: None) for key, label in named.items()])

        self.assertEqual("VPX Standalone Scripts", named[script_fixes.ID])
        self.assertEqual(["VPinMediaDB", "VPX Standalone Scripts"],
                         [label for label, _draw in entries if label in named.values()][:2])
        self.assertEqual([t("manager.settings.vpinmediadb.help"),
                          t("manager.settings.script_fixes.help")],
                         [text for label, text in entries if label == "note"])


class OnWindows(_Kept):
    """The fixes are for the VPX Standalone engine, so Windows has no such source."""

    def setUp(self) -> None:
        super().setUp()
        script_fixes.check()
        windows = MagicMock()
        windows.platform = "win32"
        patcher = patch.object(script_fixes, "sys", windows)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_source_is_not_registered(self) -> None:
        with patch.object(sources, "_built_in_loaded", False), \
                patch.dict(sources._sources, {}, clear=True):
            sources._load_built_in()

            self.assertNotIn(script_fixes.ID, [one.id for one in sources.all_sources()])
            self.assertIn("vps", [one.id for one in sources.all_sources()])

    def test_it_is_registered_everywhere_else(self) -> None:
        for platform in ("darwin", "linux"):
            with self.subTest(platform=platform):
                script_fixes.sys.platform = platform
                with patch.object(sources, "_built_in_loaded", False), \
                        patch.dict(sources._sources, {}, clear=True):
                    sources._load_built_in()

                    self.assertIn(script_fixes.ID, [one.id for one in sources.all_sources()])

    def test_the_answer_offers_nothing_whatever_the_cache_holds(self) -> None:
        self.assertEqual({"reachable": False, "offered": [], "already": 0, "checked": 0,
                          "checked_at": ""}, script_fixes.answer())

    def test_the_api_reads_it_as_not_offered(self) -> None:
        jobs.reset_for_tests()
        self.addCleanup(jobs.reset_for_tests)
        found = TestClient(httpapi.create_api_app(),
                           raise_server_exceptions=False).get("/library/patches").json()

        self.assertEqual((False, []), (found["reachable"], found["offered"]))

    def test_a_fetch_is_refused_as_not_available_here_and_starts_no_job(self) -> None:
        jobs.reset_for_tests()
        self.addCleanup(jobs.reset_for_tests)
        with patch.object(game_service, "apply_vpx_patches") as applied:
            response = TestClient(httpapi.create_api_app(), raise_server_exceptions=False) \
                .post("/library/patches", json={})

        self.assertEqual(501, response.status_code)
        self.assertEqual(t("said.script_fixes_unavailable"), response.json()["error"]["message"])
        applied.assert_not_called()
        self.assertEqual([], jobs.recent())

    def test_the_sources_page_does_not_list_it(self) -> None:
        with patch.object(sources, "_built_in_loaded", False), \
                patch.dict(sources._sources, {}, clear=True):
            listed = TestClient(httpapi.create_api_app(), raise_server_exceptions=False) \
                .get("/media-sources").json()["sources"]

        self.assertNotIn(script_fixes.ID, [one["id"] for one in listed])

    def test_the_tables_grid_marks_no_table_where_it_is_not_available(self) -> None:
        from manager.kit.data import Library

        client = MagicMock()
        client.script_patches.return_value = script_fixes.answer()
        client.all_tables.return_value = []
        client.library_policy.return_value = {}
        library = Library(client)
        library.load_kept_kinds()
        library.load_tables_view()

        self.assertEqual((), library.script_fix_tables())


class TheApi(_Kept):
    def setUp(self) -> None:
        super().setUp()
        jobs.reset_for_tests()
        self.addCleanup(jobs.reset_for_tests)
        self.client = TestClient(httpapi.create_api_app(), raise_server_exceptions=False)

    def test_the_read_answers_from_the_cache_and_reaches_for_no_index(self) -> None:
        script_fixes.check()
        self.fetched.reset_mock()

        found = self.client.get("/library/patches").json()

        self.assertEqual(["Alpha"], found["offered"])
        self.assertEqual(script_fixes.checked_at(), found["checked_at"])
        self.fetched.assert_not_called()

    def test_before_the_first_check_it_is_not_reachable_rather_than_nothing_to_do(self) -> None:
        found = self.client.get("/library/patches").json()

        self.assertEqual((False, [], ""), (found["reachable"], found["offered"],
                                           found["checked_at"]))
        self.fetched.assert_not_called()


if __name__ == "__main__":
    unittest.main()
