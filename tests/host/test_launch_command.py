import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from common.host.launch import (
    build_masked_tableini_path,
    build_vpx_launch_command,
    resolve_launch_tableini_override,
)


class TestLauncherGameIniOverride(unittest.TestCase):
    def test_build_masked_tableini_path_enabled_builds_expected_name(self) -> None:
        stem = "300 (Gottlieb 1975) team scampa123 mod v1.1"
        vpx = os.path.join(os.sep, "games", f"{stem}.vpx")
        got = build_masked_tableini_path(vpx, True, "windows")
        self.assertEqual(got, os.path.join(os.sep, "games", f"{stem}.windows.ini"))

    def test_build_masked_tableini_path_disabled_returns_empty(self) -> None:
        vpx = "/games/example.vpx"
        self.assertEqual(build_masked_tableini_path(vpx, False, "windows"), "")

    def test_build_masked_tableini_path_empty_mask_returns_empty(self) -> None:
        vpx = "/games/example.vpx"
        self.assertEqual(build_masked_tableini_path(vpx, True, "  "), "")

    def test_resolve_launch_tableini_override_requires_existing_file(self) -> None:
        with TemporaryDirectory() as tmp:
            vpx = Path(tmp) / "Example Table.vpx"
            vpx.write_text("", encoding="utf-8")
            self.assertEqual(
                resolve_launch_tableini_override(str(vpx), True, "windows"),
                "",
            )

            masked = Path(tmp) / "Example Table.windows.ini"
            masked.write_text("[table]\n", encoding="utf-8")
            self.assertEqual(
                resolve_launch_tableini_override(str(vpx), True, "windows"),
                str(masked),
            )

    def test_build_vpx_launch_command_keeps_play_last_with_all_overrides(self) -> None:
        cmd = build_vpx_launch_command(
            launcher_path="/opt/vpinball/VPinballX",
            vpx_path="/games/example.vpx",
            global_ini_override="/cfg/VPinballX.ini",
            tableini_override="/games/example.windows.ini",
        )
        self.assertEqual(
            cmd,
            [
                "/opt/vpinball/VPinballX",
                "-ini",
                "/cfg/VPinballX.ini",
                "-tableini",
                "/games/example.windows.ini",
                "-play",
                "/games/example.vpx",
            ],
        )
        self.assertEqual(cmd[-2], "-play")

    def test_build_vpx_launch_command_keeps_play_last_without_overrides(self) -> None:
        cmd = build_vpx_launch_command(
            launcher_path="/opt/vpinball/VPinballX",
            vpx_path="/games/example.vpx",
        )
        self.assertEqual(
            cmd,
            ["/opt/vpinball/VPinballX", "-play", "/games/example.vpx"],
        )
        self.assertEqual(cmd[-2], "-play")


class TestLauncherIniOverride(unittest.TestCase):
    """One ini, from the launcher that is running.

    The class this replaced tested which of two overrides won. A plugin profile and the
    install-wide override both drove VPX's single -ini and had to be ranked; a launcher
    carries one, so which launcher is playing already answered it.
    """

    def test_the_launchers_ini_fills_the_slot_and_play_stays_last(self) -> None:
        cmd = build_vpx_launch_command(
            launcher_path="/opt/vpinball/VPinballX",
            vpx_path="/games/example.vpx",
            global_ini_override="/cfg/plugin_profiles/no-dmd.ini",
        )

        self.assertEqual(cmd, ["/opt/vpinball/VPinballX", "-ini",
                               "/cfg/plugin_profiles/no-dmd.ini",
                               "-play", "/games/example.vpx"])
        self.assertEqual(cmd[-2], "-play")

    def test_only_ever_one_ini(self) -> None:
        """VPX accepts a single -ini, and a second would be silently dropped by it
        rather than reported by us."""
        cmd = build_vpx_launch_command(
            launcher_path="/opt/vpinball/VPinballX",
            vpx_path="/games/example.vpx",
            global_ini_override="/cfg/VPinballX.ini",
            tableini_override="/games/example.windows.ini",
        )

        self.assertEqual(cmd.count("-ini"), 1)

