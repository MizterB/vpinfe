"""Turning a DOF event on says why when it cannot, and never starts DOF under a table."""

from __future__ import annotations

import unittest
from unittest import mock

from common.host import dof_service, launch_state
from common.i18n import t


class _Helper:
    """The DOF helper, answering what it is told to."""

    def __init__(self, **replies: object) -> None:
        self.replies = {"start": {"ok": True, "started": True, "detail": "x"},
                        "send_event_token": {"ok": True, "sent": True},
                        "clear_event": {"ok": True, "cleared": True}, **replies}
        self.asked: list[tuple[str, dict]] = []

    def request(self, command: str, timeout: float = 0.0, **fields: object) -> object:
        self.asked.append((command, fields))
        return self.replies[command]

    def is_alive(self) -> bool:
        return True


class EventTests(unittest.TestCase):
    def setUp(self) -> None:
        self.helper = _Helper()
        self.running = False
        self.playing = False
        self.enabled = True
        for patch in (
                mock.patch.object(dof_service, "_is_enabled", lambda _ini: self.enabled),
                mock.patch.object(dof_service, "_get_helper", lambda: self.helper),
                mock.patch.object(dof_service, "is_running", lambda: self.running),
                mock.patch.object(dof_service, "_HELPER", None),
                mock.patch.object(dof_service, "_CURRENT_EVENT", None),
                mock.patch.object(dof_service.dof_config, "base_path", lambda: None),
                mock.patch.object(launch_state, "current",
                                  lambda: launch_state.LaunchState(launching=self.playing))):
            self.enterContext(patch)

    def _asked(self, command: str) -> list[dict]:
        return [fields for asked, fields in self.helper.asked if asked == command]

    def test_it_goes_out_and_reads_as_a_yes(self) -> None:
        outcome = dof_service.send_dof_event_token(None, "e905")

        self.assertTrue(outcome)
        self.assertEqual(self._asked("send_event_token"), [{"event_token": "E905"}])

    def test_off_says_so_and_asks_the_helper_nothing(self) -> None:
        self.enabled = False

        outcome = dof_service.send_dof_event_token(None, "E905")

        self.assertFalse(outcome)
        self.assertEqual(outcome.reason, dof_service.OFF)
        self.assertEqual(outcome.words(), t("dof.event.off"))
        self.assertEqual(self.helper.asked, [])

    def test_a_table_playing_stops_it_before_the_helper_starts(self) -> None:
        self.playing = True

        outcome = dof_service.send_dof_event_token(None, "E905")

        self.assertEqual(outcome.reason, dof_service.PLAYING)
        self.assertEqual(outcome.words(), t("dof.event.playing"))
        self.assertEqual(self.helper.asked, [])

    def test_the_event_already_on_is_not_sent_again(self) -> None:
        dof_service.send_dof_event_token(None, "E905")
        self.running = True

        again = dof_service.send_dof_event_token(None, "E905")

        self.assertFalse(again)
        self.assertEqual(len(self._asked("send_event_token")), 1)

    def test_a_test_fires_the_event_already_on_again(self) -> None:
        dof_service.send_dof_event_token(None, "E905")
        self.running = True

        outcome = dof_service.test_event(None, "E905")

        self.assertTrue(outcome)
        self.assertEqual([asked for asked, _ in self.helper.asked][-2:],
                         ["clear_event", "send_event_token"])
        self.assertEqual(len(self._asked("send_event_token")), 2)

    def test_a_runner_that_is_not_there_says_so(self) -> None:
        self.helper.replies["start"] = {"ok": True, "started": False,
                                        "detail": "runner_unavailable"}

        outcome = dof_service.send_dof_event_token(None, "E905")

        self.assertEqual(outcome.reason, dof_service.NO_RUNNER)
        self.assertEqual(self._asked("send_event_token"), [])

    def test_a_runner_that_would_not_start_gives_its_own_words(self) -> None:
        self.helper.replies["start"] = {"ok": True, "started": False,
                                        "detail": "start_failed:Could not open the boards"}

        outcome = dof_service.send_dof_event_token(None, "E905")

        self.assertEqual(outcome.reason, dof_service.FAILED)
        self.assertEqual(outcome.detail, "Could not open the boards")
        self.assertIn("Could not open the boards", outcome.words())

    def test_a_code_is_for_the_log_and_not_for_a_person(self) -> None:
        self.running = True
        self.helper.replies["send_event_token"] = {"ok": False, "error": "no such board"}

        outcome = dof_service.send_dof_event_token(None, "E905")

        self.assertEqual(outcome.reason, dof_service.FAILED)
        self.assertEqual(outcome.detail, "")
        self.assertEqual(outcome.words(), t("dof.event.failed"))

    def test_a_helper_already_up_without_a_runner_still_says_so(self) -> None:
        self.running = True
        self.helper.replies["send_event_token"] = {"ok": False, "error": "runner_not_running"}
        self.helper.replies["start"] = {"ok": True, "started": False,
                                        "detail": "runner_unavailable"}

        outcome = dof_service.send_dof_event_token(None, "E905")

        self.assertEqual(outcome.reason, dof_service.NO_RUNNER)

    def test_a_runner_that_comes_up_on_the_second_ask_sends(self) -> None:
        self.running = True
        answers = iter([{"ok": False, "error": "runner_not_running"}, {"ok": True}])
        self.helper.request = lambda command, timeout=0.0, **fields: (
            next(answers) if command == "send_event_token"
            else {"ok": True, "started": True, "detail": "x"})

        self.assertTrue(dof_service.send_dof_event_token(None, "E905"))

    def test_the_helper_does_not_start_under_a_table_by_any_road(self) -> None:
        self.playing = True

        self.assertFalse(dof_service.start_dof_service_if_enabled(None))
        self.assertFalse(dof_service.restart_dof_service_if_enabled(None))
        self.assertEqual(self._asked("start"), [])

    def test_the_event_a_test_finds_already_on_is_not_an_error(self) -> None:
        with mock.patch.object(dof_service, "test_event",
                               lambda _ini, _event: dof_service.Outcome(False, dof_service.SAME)):
            self.assertEqual(dof_service.turn_on(None, "e905"), "E905")

    def test_a_helper_that_does_not_answer_says_so(self) -> None:
        self.running = True
        self.helper.replies["send_event_token"] = None

        outcome = dof_service.send_dof_event_token(None, "E905")

        self.assertEqual(outcome.reason, dof_service.NO_HELPER)

    def test_a_token_that_is_not_one_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            dof_service.send_dof_event_token(None, "905")


class ReloadConfigTests(unittest.TestCase):
    """A pressed download starts the helper over so it reads the new files, and nothing else
    does."""

    def setUp(self) -> None:
        self.running = True
        self.playing = False
        self.restarted: list[object] = []
        for patch in (
                mock.patch.object(dof_service, "is_running", lambda: self.running),
                mock.patch.object(dof_service, "restart_dof_service_if_enabled",
                                  lambda ini: self.restarted.append(ini) or True),
                mock.patch.object(launch_state, "current",
                                  lambda: launch_state.LaunchState(launching=self.playing))):
            self.enterContext(patch)

    def test_a_running_helper_is_started_over(self) -> None:
        self.assertTrue(dof_service.reload_config("ini"))
        self.assertEqual(self.restarted, ["ini"])

    def test_a_helper_that_is_not_running_is_left_alone(self) -> None:
        self.running = False

        self.assertFalse(dof_service.reload_config("ini"))
        self.assertEqual(self.restarted, [])

    def test_a_table_playing_leaves_it_alone(self) -> None:
        self.playing = True

        self.assertFalse(dof_service.reload_config("ini"))
        self.assertEqual(self.restarted, [])


if __name__ == "__main__":
    unittest.main()
