import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from apps.vpx.launch import VPXLaunch
from common.apps.contract import SESSION_CHILD_WITH_READINESS, Entry


def _command(table: str, own: Path | None = None, **settings) -> list[str]:
    with mock.patch("apps.vpx.launch.own_file", return_value=own):
        return VPXLaunch().command(Entry(table=table), settings)


class CommandTests(unittest.TestCase):
    def test_another_settings_file_is_passed(self) -> None:
        cmd = _command("/games/example.vpx",
                       bin_path="/opt/vpinball/VPinballX",
                       ini_path="/cfg/plugin_profiles/no-dmd.ini")

        self.assertEqual(cmd, ["/opt/vpinball/VPinballX",
                               "-ini", "/cfg/plugin_profiles/no-dmd.ini",
                               "-play", "/games/example.vpx"])

    def test_an_empty_one_leaves_the_program_to_its_own(self) -> None:
        cmd = _command("/games/example.vpx", bin_path="/opt/vpinball/VPinballX")

        self.assertEqual(cmd, ["/opt/vpinball/VPinballX", "-play", "/games/example.vpx"])

    def test_naming_its_own_passes_nothing(self) -> None:
        """Passing `-ini` for the file Visual Pinball reads anyway changes nothing today,
        and pins the launcher to that version's folder after an upgrade."""
        with TemporaryDirectory() as tmp:
            own = Path(tmp) / "10.8" / "VPinballX.ini"
            own.parent.mkdir()
            own.write_text("[Player]\n", encoding="utf-8")

            cmd = _command("/games/example.vpx", own=own,
                           bin_path="/opt/vpinball/VPinballX", ini_path=str(own))

        self.assertNotIn("-ini", cmd)

    def test_play_is_last(self) -> None:
        cmd = _command("/games/example.vpx",
                       bin_path="/opt/vpinball/VPinballX", ini_path="/cfg/VPinballX.ini")

        self.assertEqual(cmd[-2:], ["-play", "/games/example.vpx"])
        self.assertEqual(cmd.count("-ini"), 1)


class SessionTests(unittest.TestCase):
    def test_the_session_waits_for_the_startup_marker(self) -> None:
        """The process exists well before the player is looking at anything."""
        session = VPXLaunch().session({})

        self.assertEqual(session.kind, SESSION_CHILD_WITH_READINESS)
        self.assertEqual(session.readiness_marker, "Startup done")


if __name__ == "__main__":
    unittest.main()
