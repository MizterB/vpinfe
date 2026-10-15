"""The line the terminal prints at start names VPinFE and lists where the Console answers.

NiceGUI prints its own welcome message unless it is told not to, and the two together would
put two lines on the screen, one of them naming a library the person never chose.
"""

from __future__ import annotations

import contextlib
import io
import unittest
from types import SimpleNamespace
from unittest import mock

from managerui import managerui


def _printed(urls: set[str]) -> str:
    out = io.StringIO()
    with mock.patch.object(managerui, "app", SimpleNamespace(urls=urls)), \
         contextlib.redirect_stdout(out):
        managerui._say_ready()
    return out.getvalue()


class TheReadyLineTests(unittest.TestCase):
    def test_it_lists_localhost_first_and_then_the_other_addresses(self) -> None:
        line = _printed({"http://192.168.1.50:8001", "http://localhost:8001",
                         "http://10.0.0.7:8001"})

        self.assertEqual(
            line,
            "VPinFE ready to go on http://localhost:8001, http://10.0.0.7:8001, "
            "and http://192.168.1.50:8001\n")

    def test_two_addresses_read_as_one_and_another(self) -> None:
        line = _printed({"http://localhost:8001", "http://192.168.1.50:8001"})

        self.assertEqual(
            line,
            "VPinFE ready to go on http://localhost:8001, and http://192.168.1.50:8001\n")

    def test_an_install_that_answers_one_address_lists_only_that(self) -> None:
        self.assertEqual(_printed({"http://127.0.0.1:8001"}),
                         "VPinFE ready to go on http://127.0.0.1:8001\n")

    def test_https_addresses_keep_their_scheme(self) -> None:
        self.assertEqual(_printed({"https://localhost:8001"}),
                         "VPinFE ready to go on https://localhost:8001\n")


class StartingTheServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.addCleanup(setattr, managerui, "_ui_port", managerui._ui_port)

    def _start(self) -> tuple[mock.Mock, mock.Mock]:
        with mock.patch.object(managerui, "ui") as nicegui, \
             mock.patch.object(managerui, "app") as app, \
             mock.patch.object(managerui, "_manager_ui_urls", return_value=[]):
            managerui._run_ui()
        return nicegui, app

    def test_nicegui_is_told_to_keep_its_own_message_to_itself(self) -> None:
        nicegui, _ = self._start()

        self.assertIs(nicegui.run.call_args.kwargs["show_welcome_message"], False)

    def test_the_ready_line_runs_when_the_server_starts(self) -> None:
        _, app = self._start()

        app.on_startup.assert_any_call(managerui._say_ready)


if __name__ == "__main__":
    unittest.main()
