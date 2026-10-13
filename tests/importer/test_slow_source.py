"""A source on a slow share: what a check keeps, what a run reports, and how it stops."""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from common import jobs
from common.games import game_service
from tests.importer.test_adopt import FIXTURE, VPX, AdoptCase


class ListingTests(AdoptCase):
    def test_folders_are_listed_in_the_order_asked(self) -> None:
        from vpinfe_ext_library_importer import listing

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, files in (("a", ["1.png"]), ("b", ["2.png", "3.png"]), ("c", [])):
                (root / name).mkdir()
                for one in files:
                    (root / name / one).write_bytes(b"x")
            (root / "b" / "sub").mkdir()

            found = listing.files_across(root, ["b", "missing", "a", "c"])

        self.assertEqual([sorted(name for name, _path in one) for one in found],
                         [["2.png", "3.png"], [], ["1.png"], []])

    def test_nothing_asked_lists_nothing(self) -> None:
        from vpinfe_ext_library_importer import listing

        self.assertEqual(listing.files_across(Path("."), []), [])


class HeldTests(AdoptCase):
    def setUp(self) -> None:
        super().setUp()
        from vpinfe_ext_library_importer import held

        self.held = held.Held()
        self.held_module = held
        self.key = ("pinballx", "/lib", "")
        self.library = mock.Mock()

    def test_what_was_read_is_given_back_for_the_same_source(self) -> None:
        self.held.keep(self.key, self.library)

        self.assertIs(self.held.library_for(self.key), self.library)
        self.assertIsNone(self.held.library_for(("popper", "/lib", "")))

    def test_a_fresh_read_is_asked_for_by_name(self) -> None:
        self.held.keep(self.key, self.library)

        self.assertIsNone(self.held.library_for(self.key, fresh=True))

    def test_nothing_is_trusted_for_longer_than_it_is_kept(self) -> None:
        self.held.keep(self.key, self.library)

        with mock.patch.object(self.held_module.time, "monotonic",
                               return_value=time.monotonic() + self.held_module.KEPT + 1):
            self.assertIsNone(self.held.library_for(self.key))

    def test_a_new_library_drops_what_was_worked_out_about_the_old_one(self) -> None:
        self.held.keep(self.key, self.library)
        self.held.remember_companions(["/a.vpx"], {"/a.vpx": ("a.directb2s",)})
        self.held.sizes[Path("/a.vpx")] = 5

        self.held.keep(self.key, mock.Mock())

        self.assertEqual(self.held.unasked(["/a.vpx"]), ["/a.vpx"])
        self.assertEqual(self.held.sizes, {})

    def test_a_file_not_found_beside_is_one_that_is_not_there(self) -> None:
        self.held.remember_companions(["/a.vpx", "/gone.vpx"], {"/a.vpx": ()})

        self.assertEqual(self.held.companions_of("/a.vpx"), ())
        with self.assertRaises(FileNotFoundError):
            self.held.companions_of("/gone.vpx")
        self.assertEqual(self.held.unasked(["/a.vpx", "/gone.vpx", "/new.vpx"]),
                         ["/new.vpx"])

    def test_a_file_is_measured_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            one = Path(tmp) / "a.vpx"
            one.write_bytes(b"12345")
            progress = self.held_module.Progress()
            measure = self.held.measured(progress, "Measuring")

            self.assertEqual(measure([one, one]), {one: 5})
            one.write_bytes(b"123")

            self.assertEqual(measure([one]), {one: 5})

    def test_progress_says_where_it_has_got_to(self) -> None:
        progress = self.held_module.Progress()

        progress.stage("measuring", "Measuring", 40)
        progress.advance(20)

        self.assertEqual(progress.snapshot(),
                         {"stage": "measuring", "message": "Measuring",
                          "done": 20, "total": 40})
        progress.clear()
        self.assertEqual(progress.snapshot()["stage"], "")


class NamesTests(unittest.TestCase):
    def test_the_replacement_character_never_reaches_a_folder_name(self) -> None:
        self.assertEqual(game_service.sanitize_dir_name("Jack�Bot (Williams 1995)"),
                         "JackBot (Williams 1995)")

    def test_a_name_is_composed(self) -> None:
        self.assertEqual(game_service.sanitize_dir_name("Café"), "Café")

    def test_control_characters_are_dropped(self) -> None:
        self.assertEqual(game_service.sanitize_dir_name("Taxi\x00\x1f (Williams 1988)"),
                         "Taxi (Williams 1988)")


class RunTests(AdoptCase):
    def setUp(self) -> None:
        super().setUp()
        from common.extensions.context import ExtensionContext

        self._ctx = ExtensionContext(self.record.manifest, self.store,
                                     on_failure=lambda why: None)
        self._ctx.files.set_roots([str(FIXTURE)])

    def _run(self, **kinds):
        from vpinfe_ext_library_importer import adopt, pinballx

        return adopt.run(self._ctx, pinballx.read(FIXTURE), [VPX], **kinds)

    def test_each_game_is_reported_before_it_is_made(self) -> None:
        told = []

        self._run(report=told.append, weigh=lambda game: 10)

        self.assertEqual([one.games_done for one in told], [0, 1, 2])
        self.assertEqual([one.bytes_done for one in told], [0, 10, 20])
        self.assertTrue(all(one.bytes_total == 30 and one.games_total == 3 for one in told))
        self.assertTrue(all(one.name for one in told))

    def test_a_run_that_is_stopped_ends_after_the_game_in_hand(self) -> None:
        asked = []

        def halted() -> bool:
            asked.append(1)
            return len(asked) > 1

        report = self._run(halted=halted)

        self.assertTrue(report["stopped"])
        self.assertEqual(report["left"], 2)
        self.assertEqual(report["games"], 1)
        self.assertEqual(sum(1 for one in self.library.iterdir() if one.is_dir()), 1)

    def test_a_run_nobody_stopped_says_so(self) -> None:
        report = self._run()

        self.assertFalse(report["stopped"])
        self.assertEqual(report["left"], 0)


class StopTests(AdoptCase):
    def test_nothing_running_is_nothing_to_stop(self) -> None:
        reply = self.client.post("/ext/library_importer/jobs/import/stop")

        self.assertEqual(reply.json(), {"stopped": False})

    def test_progress_is_empty_when_nothing_is_going_on(self) -> None:
        reply = self.client.get("/ext/library_importer/actions/import/progress")

        self.assertEqual(reply.json()["stage"], "")

    def test_a_running_import_offers_its_stop_and_is_halted_by_it(self) -> None:
        from common.extensions.context import ExtensionContext

        release = []

        def work(job: jobs.Job) -> None:
            while not release:
                time.sleep(0.01)

        context = ExtensionContext(self.record.manifest, self.store,
                                   on_failure=lambda why: None)
        job = context.jobs.submit("import", work, stoppable=True)
        self.addCleanup(release.append, 1)
        self.assertTrue(job.stoppable)
        self.assertEqual(job.stop_link, "/api/v1/ext/library_importer/jobs/import/stop")
        self.assertEqual(self.client.get(f"/jobs/{job.id}").json()["links"]["stop"],
                         job.stop_link)

        self.assertTrue(self.client.post("/ext/library_importer/jobs/import/stop").json()["stopped"])

        self.assertTrue(job.halt.is_set())
        self.assertIn(job.id, [one.id for one in jobs.active("library_importer.import")])
