"""A kill signal takes the same way out as a user closing a window."""

from __future__ import annotations

import configparser
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from common import shutdown
from frontend import runtime
from frontend.chromium_manager import ChromiumManager

# `install_setup.pending()` reads this as false: no `install.setup_pending` option means
# `cfg_bool`'s own fallback answers.
_NOT_PENDING = mock.Mock(config=configparser.ConfigParser())


def _browser_that_waits():
    """A stand-in for ChromiumManager: blocks until request_exit is called."""
    exited = threading.Event()
    browser = mock.Mock()
    browser.request_exit.side_effect = exited.set

    def _wait_for_exit(**_kwargs):
        deadline = time.monotonic() + 10.0
        while not exited.wait(0.05):
            if time.monotonic() > deadline:
                raise AssertionError("the signal never reached request_exit")

    browser.wait_for_exit.side_effect = _wait_for_exit
    return browser


# Windows defines SIGTERM but does not deliver it: os.kill falls through to
# TerminateProcess and the whole run dies, with no failure and no summary. Same guard,
# same reason, as tests/host/test_shutdown.py.
@unittest.skipIf(sys.platform.startswith("win"),
                 "Windows terminates the process instead of delivering SIGTERM")
@unittest.skipIf(not hasattr(signal, "SIGTERM"), "no SIGTERM on this platform")
class TerminationSignalTests(unittest.TestCase):
    def setUp(self):
        for name in ("SIGTERM", "SIGINT", "SIGBREAK"):
            sig = getattr(signal, name, None)
            if sig is not None:
                self.addCleanup(signal.signal, sig, signal.getsignal(sig))
        # Absorb the signal here first. If run_frontend_loop ever stops installing its
        # own handler, these tests have to fail - not kill the whole run, which is what
        # SIGTERM does by default to the process sending it to itself.
        signal.signal(signal.SIGTERM, lambda *_args: None)
        shutdown.reset_for_tests()
        self.addCleanup(shutdown.reset_for_tests)

    def _send_sigterm_shortly(self):
        killer = threading.Timer(0.2, os.kill, (os.getpid(), signal.SIGTERM))
        killer.start()
        self.addCleanup(killer.cancel)

    def test_sigterm_closes_the_windows_and_returns_for_shutdown(self):
        browser = _browser_that_waits()
        self._send_sigterm_shortly()

        with mock.patch.object(runtime, "get_display_monitors", return_value=[]):
            runtime.run_frontend_loop(
                False,
                _NOT_PENDING,
                browser,
                threading.Event(),
                mock.Mock(),
            )

        browser.terminate_all.assert_called_once_with()

    def test_sigterm_ends_the_headless_loop(self):
        shutdown_event = threading.Event()
        self._send_sigterm_shortly()
        failsafe = threading.Timer(10.0, shutdown_event.set)
        failsafe.start()
        self.addCleanup(failsafe.cancel)
        started = time.monotonic()

        runtime.run_frontend_loop(True, mock.Mock(), mock.Mock(), shutdown_event, mock.Mock())

        self.assertLess(time.monotonic() - started, 5.0, "the signal never ended the loop")

    def test_a_closed_window_still_ends_the_loop_without_a_signal(self):
        browser = mock.Mock()
        browser.wait_for_exit.side_effect = lambda **_kwargs: None

        with mock.patch.object(runtime, "get_display_monitors", return_value=[]):
            runtime.run_frontend_loop(
                False,
                _NOT_PENDING,
                browser,
                threading.Event(),
                mock.Mock(),
            )

        browser.launch_all_windows.assert_called_once()
        browser.terminate_all.assert_called_once_with()

    def test_a_signal_during_startup_stops_the_frontend_opening_at_all(self):
        browser = _browser_that_waits()
        shutdown.watch_during_startup()
        os.kill(os.getpid(), signal.SIGTERM)

        with mock.patch.object(runtime, "get_display_monitors", return_value=[]):
            runtime.run_frontend_loop(
                False,
                _NOT_PENDING,
                browser,
                threading.Event(),
                mock.Mock(),
            )

        browser.launch_all_windows.assert_not_called()
        browser.wait_for_exit.assert_not_called()


class SetupPendingTests(unittest.TestCase):
    """While Setup is pending the one window is Setup itself, and the real ones wait."""

    def test_the_window_opens_setup_and_says_it_is_the_frontends_own(self):
        browser = _browser_that_waits()
        threading.Timer(0.05, browser.request_exit).start()

        with mock.patch.object(runtime, "get_display_monitors",
                               return_value=[mock.Mock()]), \
             mock.patch.object(runtime, "install_setup") as fake_pending, \
             mock.patch("common.paths.get_ini_config", return_value=mock.Mock()):
            fake_pending.pending.return_value = True
            runtime.run_frontend_loop(False, mock.Mock(), browser, threading.Event(),
                                      mock.Mock())

        url = browser.launch_window.call_args.kwargs["url"]
        self.assertTrue(url.startswith("http://localhost:"), url)
        self.assertTrue(url.endswith("/?setup=window"), url)

    def test_closing_the_window_while_still_pending_quits(self):
        browser = _browser_that_waits()
        threading.Timer(0.05, browser.request_exit).start()

        with mock.patch.object(runtime, "get_display_monitors",
                               return_value=[mock.Mock()]), \
             mock.patch.object(runtime, "install_setup") as fake_pending, \
             mock.patch("common.paths.get_ini_config", return_value=mock.Mock()):
            fake_pending.pending.return_value = True
            runtime.run_frontend_loop(False, mock.Mock(), browser, threading.Event(),
                                      mock.Mock())

        browser.launch_all_windows.assert_not_called()

    def test_setup_finishing_under_the_window_opens_the_real_ones(self):
        browser = _browser_that_waits()
        seen = {"n": 0}

        def _still_pending(_config) -> bool:
            seen["n"] += 1
            return seen["n"] < 3

        with mock.patch.object(runtime, "get_display_monitors",
                               return_value=[mock.Mock()]), \
             mock.patch.object(runtime, "SETUP_POLL_S", 0.01), \
             mock.patch.object(runtime, "install_setup") as fake_pending, \
             mock.patch("common.paths.get_ini_config", return_value=mock.Mock()):
            fake_pending.pending.side_effect = _still_pending
            runtime.run_frontend_loop(False, mock.Mock(), browser, threading.Event(),
                                      mock.Mock())

        browser.launch_all_windows.assert_called_once()

    def test_a_signal_while_setup_closes_does_not_open_the_real_windows(self):
        self.addCleanup(shutdown.reset_for_tests)
        browser = mock.Mock()
        browser.wait_for_exit.side_effect = lambda **_kwargs: None
        browser.terminate_all.side_effect = shutdown._requested.set

        with mock.patch.object(runtime, "get_display_monitors",
                               return_value=[mock.Mock()]), \
             mock.patch.object(runtime, "install_setup") as fake_setup, \
             mock.patch("common.paths.get_ini_config", return_value=mock.Mock()):
            fake_setup.pending.side_effect = [True, False, False]
            runtime.run_frontend_loop(False, mock.Mock(), browser, threading.Event(),
                                      mock.Mock())

        browser.launch_all_windows.assert_not_called()

    def test_the_real_windows_wait_after_the_setup_window_has_closed(self):
        """The real manager's exit flag is set by closing the Setup window and stays set,
        so a wait that opened the real windows next returned at once and took them down."""
        with mock.patch("frontend.chromium_manager.sweep_stale_profiles"):
            manager = ChromiumManager()
        setup_finished = threading.Event()
        real_windows_open = threading.Event()
        loop_returned = threading.Event()
        opened: list[str] = []

        def _open_a_window(name: str) -> None:
            process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
            profile = tempfile.mkdtemp(prefix="vpinfe-test-profile-")
            manager._processes.append((name, process, profile, None))
            opened.append(name)

        self.addCleanup(lambda: [p.kill() for _n, p, _d, _m in manager._processes])
        browser = mock.Mock(wraps=manager)
        browser.launch_window.side_effect = lambda **kwargs: (
            _open_a_window("setup"), setup_finished.set())
        browser.launch_all_windows.side_effect = lambda _config: (
            _open_a_window("real"), real_windows_open.set())

        def _run() -> None:
            with mock.patch.object(runtime, "get_display_monitors",
                                   return_value=[mock.Mock()]), \
                 mock.patch.object(runtime, "SETUP_POLL_S", 0.01), \
                 mock.patch.object(runtime, "install_setup") as fake_setup, \
                 mock.patch("common.paths.get_ini_config", return_value=mock.Mock()):
                fake_setup.pending.side_effect = lambda _config: not setup_finished.is_set()
                runtime.run_frontend_loop(False, mock.Mock(), browser, threading.Event(),
                                          mock.Mock())
            loop_returned.set()

        self.addCleanup(manager.request_exit)
        threading.Thread(target=_run, daemon=True).start()

        self.assertTrue(real_windows_open.wait(10), "the real windows never opened")
        self.assertFalse(loop_returned.wait(0.5),
                         "the real windows' wait returned the moment they opened")
        self.assertEqual(opened, ["setup", "real"])
        self.assertTrue(manager.is_running)

        manager.request_exit()
        self.assertTrue(loop_returned.wait(10), "asking to exit did not end the wait")


if __name__ == "__main__":
    unittest.main()
