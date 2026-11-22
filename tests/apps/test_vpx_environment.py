"""Protects: (d) a table that starts paused on a Mac with several full screen windows.

Visual Pinball is started on a Mac without full screen Spaces, other systems get nothing
extra, and a launcher's own Environment setting still has the last word.
"""

from __future__ import annotations

import types
import unittest
from unittest import mock

from apps.vpx import environment
from common.games.launchers import Launcher
from common.host import launch

NAME = environment.FULLSCREEN_SPACES


def _on(system: str):
    return mock.patch.object(environment, "sys", types.SimpleNamespace(platform=system))


def _launcher(app: str = "vpx", launch_env: str = "") -> Launcher:
    return Launcher(launcher_id="l1", app=app, settings={"launch_env": launch_env})


class VPXEnvironmentTests(unittest.TestCase):
    def test_a_mac_turns_full_screen_spaces_off(self) -> None:
        with _on("darwin"):
            self.assertEqual(environment.VPXEnvironment().variables({}), {NAME: "0"})

    def test_other_systems_get_nothing(self) -> None:
        for system in ("linux", "win32"):
            with self.subTest(system), _on(system):
                self.assertEqual(environment.VPXEnvironment().variables({}), {})


class LaunchEnvironmentTests(unittest.TestCase):
    def test_a_visual_pinball_launch_on_a_mac_carries_it(self) -> None:
        with _on("darwin"), mock.patch.dict("os.environ", {}, clear=True):
            env = launch._launch_env(_launcher(), "/opt/vpx")
        self.assertEqual(env[NAME], "0")

    def test_the_launchers_own_environment_wins(self) -> None:
        with _on("darwin"), mock.patch.dict("os.environ", {}, clear=True):
            env = launch._launch_env(_launcher(launch_env=f"{NAME}=1"), "/opt/vpx")
        self.assertEqual(env[NAME], "1")

    def test_another_app_is_not_given_it(self) -> None:
        with _on("darwin"), mock.patch.dict("os.environ", {}, clear=True):
            env = launch._launch_env(_launcher(app="generic"), "/opt/other")
        self.assertNotIn(NAME, env)


if __name__ == "__main__":
    unittest.main()
