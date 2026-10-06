"""Putting back a copy of the file an app keeps its settings in.

Restoring the wrong one is a mistake somebody makes once, and without a copy of what was
there it is the last one they get to make.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from common.games import config_backups as backups


class _Case(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / "backups"
        self.home.mkdir()
        self.ini = self.root / "VPinballX.ini"
        self.ini.write_text("[A]\nB = 1\n")
        self.files = {"application": str(self.ini)}
        self.copy = self.home / "VPinballX.ini.vpinfe-20260101T000000Z"
        self.copy.write_text("[A]\nB = 1\n")


class RestoreTests(_Case):
    def test_putting_one_back_restores_what_it_held(self) -> None:
        self.ini.write_text("[A]\nB = 2\n")

        backups.restore(self.copy.name, self.files, home=self.home)

        self.assertEqual(self.ini.read_text(), "[A]\nB = 1\n")

    def test_and_keeps_what_was_there_first(self) -> None:
        """So putting the wrong one back is something to undo rather than regret."""
        self.ini.write_text("[A]\nB = 2\n")

        safety = backups.restore(self.copy.name, self.files, home=self.home)

        self.assertIsNotNone(safety)
        self.assertEqual(safety.read_text(), "[A]\nB = 2\n")
        self.assertRegex(safety.name, r"^VPinballX\.ini\.vpinfe-\d{8}T\d{6}Z-restore$")

    def test_a_file_that_is_not_there_is_put_back_without_a_safety_copy(self) -> None:
        self.ini.unlink()

        safety = backups.restore(self.copy.name, self.files, home=self.home)

        self.assertIsNone(safety)
        self.assertEqual(self.ini.read_text(), "[A]\nB = 1\n")

    def test_a_copy_taken_before_a_restore_can_be_put_back_too(self) -> None:
        self.ini.write_text("[A]\nB = 2\n")
        safety = backups.restore(self.copy.name, self.files, home=self.home)

        backups.restore(safety.name, self.files, home=self.home)

        self.assertEqual(self.ini.read_text(), "[A]\nB = 2\n")

    def test_a_name_that_is_not_there_is_refused(self) -> None:
        with self.assertRaises(FileNotFoundError):
            backups.restore("nothing.ini", self.files, home=self.home)

    def test_a_name_that_climbs_out_of_the_folder_is_refused(self) -> None:
        with self.assertRaises(FileNotFoundError):
            backups.restore("../../../etc/passwd", self.files, home=self.home)

    def test_a_copy_of_a_file_this_app_does_not_keep_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            backups.restore(self.copy.name, {"other": str(self.root / "Other.ini")},
                            home=self.home)


class TargetTests(_Case):
    def test_the_file_is_the_one_the_copy_was_taken_under(self) -> None:
        self.assertEqual(backups.target_for(self.copy, self.files), self.ini)

    def test_a_file_the_app_does_not_keep_has_no_target(self) -> None:
        self.assertIsNone(backups.target_for(self.copy, {"other": "/x/Other.ini"}))


class SafeTests(unittest.TestCase):
    def test_a_label_cannot_carry_anything_into_a_filename(self) -> None:
        label = backups.safe("../../etc/passwd")

        self.assertNotIn("/", label)
        self.assertNotIn("..", label)


if __name__ == "__main__":
    unittest.main()
