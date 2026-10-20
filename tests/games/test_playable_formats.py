"""The formats a library's enabled launchers play."""

from __future__ import annotations

import unittest
from unittest import mock

from common.games import launchers


def _launcher(**over: object) -> launchers.Launcher:
    return launchers.Launcher(launcher_id="l1", app="vpx", **over)  # type: ignore[arg-type]


class PlayableFormats(unittest.TestCase):
    def test_they_are_what_the_enabled_launchers_apps_play(self) -> None:
        self.assertEqual(("VPX",), launchers.playable_formats([_launcher()]))

    def test_a_disabled_launcher_adds_nothing(self) -> None:
        self.assertEqual((), launchers.playable_formats([_launcher(enabled=False)]))

    def test_an_app_declaring_none_plays_everything_so_nothing_narrows(self) -> None:
        with mock.patch.object(launchers.apps, "vps_formats", return_value=()):
            self.assertEqual((), launchers.playable_formats([_launcher()]))


if __name__ == "__main__":
    unittest.main()
