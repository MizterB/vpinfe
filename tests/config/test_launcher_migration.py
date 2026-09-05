"""The configuration an install already had, read out as launchers.

The case that matters is a 2.x cabinet with plugin profiles: it should come up with the
launcher it was running plus one per profile, each carrying the environment and overrides
it already had rather than a bare copy of Visual Pinball.
"""

import configparser
import os
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import patch

from common.games import launcher_migration, launchers


def _config(**values) -> configparser.ConfigParser:
    parser = configparser.ConfigParser()
    parser.add_section("Settings")
    for key, value in {"vpxbinpath": "/usr/bin/VPinballX_GL",
                       "vpxlaunchenv": "SDL_VIDEODRIVER=wayland",
                       **values}.items():
        parser.set("Settings", key, str(value))
    return parser


class SeedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = launchers.LauncherStore(
            os.path.join(self.tmp.name, "launchers.json"))
        self.profiles = os.path.join(self.tmp.name, "plugin_profiles")

    def _seed(self, config=None) -> bool:
        from pathlib import Path
        with patch.object(launcher_migration, "PLUGIN_PROFILES_DIR",
                          Path(self.profiles)):
            return launcher_migration.seed(self.store, config or _config())

    def _profile(self, name: str) -> None:
        os.makedirs(self.profiles, exist_ok=True)
        with open(os.path.join(self.profiles, name), "w", encoding="utf-8") as handle:
            handle.write("[Plugin.DMD]\n")

    def test_an_install_gets_the_launcher_it_was_already_running(self) -> None:
        self._seed()

        held = self.store.launchers()
        self.assertEqual(len(held), 1)
        self.assertEqual(held[0].value("bin_path"), "/usr/bin/VPinballX_GL")
        self.assertEqual(held[0].value("launch_env"), "SDL_VIDEODRIVER=wayland")
        self.assertEqual(held[0].display_name, launcher_migration.SHIPPED_NAME)

    def test_an_install_with_nothing_configured_still_gets_one(self) -> None:
        """A launcher with no binary is something a person can fix from the Console. No
        launcher at all is a machine with nothing to point at."""
        self._seed(configparser.ConfigParser())

        self.assertEqual(len(self.store.launchers()), 1)

    def test_each_plugin_profile_becomes_a_launcher(self) -> None:
        self._profile("no-dmd.ini")
        self._profile("Loud.ini")

        self._seed()

        held = self.store.launchers()
        self.assertEqual([one.display_name for one in held],
                         [launcher_migration.SHIPPED_NAME, "Loud", "no-dmd"])

    def test_a_profile_keeps_what_the_install_was_already_set_to(self) -> None:
        """A profile was a copy of the ini, not a different Visual Pinball. Dropping the
        environment would leave it launching differently in ways nobody asked for."""
        self._profile("no-dmd.ini")

        self._seed()

        profile = self.store.launchers()[1]
        self.assertEqual(profile.value("bin_path"), "/usr/bin/VPinballX_GL")
        self.assertEqual(profile.value("launch_env"), "SDL_VIDEODRIVER=wayland")
        self.assertTrue(profile.value("ini_override").endswith("no-dmd.ini"))

    def test_only_the_profiles_are_claimed_as_ours_to_delete(self) -> None:
        """Removing a launcher offers to delete the ini it owns. The shipped one points
        at Visual Pinball's own file and must never be offered."""
        self._profile("no-dmd.ini")

        self._seed()

        shipped, profile = self.store.launchers()
        self.assertFalse(shipped.owns_ini)
        self.assertTrue(profile.owns_ini)

    def test_the_shipped_launcher_leads_so_it_is_the_default(self) -> None:
        self._profile("aaa-sorts-first.ini")

        self._seed()

        self.assertEqual(self.store.launchers()[0].display_name,
                         launcher_migration.SHIPPED_NAME)

    def test_a_file_that_is_not_an_ini_is_not_a_profile(self) -> None:
        self._profile("real.ini")
        os.makedirs(self.profiles, exist_ok=True)
        with open(os.path.join(self.profiles, "notes.txt"), "w",
                  encoding="utf-8") as handle:
            handle.write("hello")

        self._seed()

        self.assertEqual(len(self.store.launchers()), 2)

    def test_it_runs_once(self) -> None:
        """Somebody who deletes a launcher they did not want must not find it back on
        the next start."""
        self.assertTrue(self._seed())
        self.store.remove(self.store.launchers()[0].launcher_id)

        self.assertFalse(self._seed())
        self.assertEqual(self.store.launchers(), [])

    def test_launchers_added_later_are_left_alone(self) -> None:
        self._seed()
        self.store.put(launchers.Launcher(launcher_id="mine", app="vpx"))

        self._seed()

        self.assertEqual([one.launcher_id for one in self.store.launchers()][-1],
                         "mine")


if __name__ == "__main__":
    unittest.main()
