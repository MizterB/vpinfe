"""The folder Back up now writes to: one setting, and every folder it has ever used.

Changing the setting moves nothing, so what matters is that a backup taken before the change
is still found after it, and that a folder nobody can write to refuses before anything is
written.
"""

from __future__ import annotations

import pathlib
import shutil
import unittest
from unittest.mock import patch

from common import service_errors
from common.backups import archive, places
from common.backups import folder as backup_folder
from common.config_access import cfg_set
from common.config_store import ConfigStore
from tests.support.library import TempTree


class BackupFolderCase(TempTree):
    def setUp(self) -> None:
        super().setUp()
        self.config = self.root / "config"
        self.config.mkdir()
        (self.config / "tags.json").write_text("{}", encoding="utf-8")
        self.default = self.config / "backups"
        self.store = ConfigStore(str(self.root / "vpinfe.ini"))
        for patcher in (patch.object(backup_folder, "DEFAULT_DIR", self.default),
                        patch.object(backup_folder, "get_ini_config",
                                     side_effect=lambda: ConfigStore(self.store.ini_path)),
                        patch.object(archive, "CONFIG_DIR", self.config)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def choose(self, folder: pathlib.Path | str) -> None:
        cfg_set(self.store, backup_folder.SECTION, backup_folder.FOLDER, str(folder))
        self.store.save()

    def take(self) -> pathlib.Path:
        return archive.take(archive.SCOPE_RECORDS)


class WhereABackupGoesTests(BackupFolderCase):
    def test_a_backup_goes_to_the_default_folder_until_one_is_chosen(self) -> None:
        path = self.take()

        self.assertEqual(path.parent, self.default)
        self.assertEqual(backup_folder.known(), [self.default])

    def test_a_backup_goes_to_the_chosen_folder(self) -> None:
        bigger = self.root / "bigger"
        bigger.mkdir()
        self.choose(bigger)

        self.assertEqual(self.take().parent, bigger)

    def test_a_chosen_folder_that_is_not_there_is_refused_and_nothing_is_made(self) -> None:
        """A missing chosen folder is refused, never created."""
        gone = self.root / "gone"
        self.choose(gone)

        with self.assertRaises(service_errors.BlockedError) as raised:
            self.take()

        self.assertIn("backups folder", str(raised.exception))
        self.assertFalse(gone.exists())
        self.assertFalse(self.default.exists())


    def test_a_folder_typed_with_dots_is_written_to_and_its_backup_found_again(self) -> None:
        bigger = self.root / "bigger"
        bigger.mkdir()
        self.choose(f"{self.root}/elsewhere/../bigger")

        path = self.take()

        self.assertEqual(path.parent, bigger)
        self.assertIsNotNone(places.archive_copy(path))

    def test_a_relative_folder_is_made_absolute_before_it_is_used(self) -> None:
        self.assertTrue(backup_folder._spelled("rel/../there").is_absolute())


class EarlierFoldersTests(BackupFolderCase):
    def test_a_backup_taken_before_the_folder_changed_is_still_listed(self) -> None:
        first = self.take()
        bigger = self.root / "bigger"
        bigger.mkdir()
        self.choose(bigger)
        second = archive.take(archive.SCOPE_RECORDS)

        self.assertEqual(sorted(archive.listed()), sorted([first, second]))

    def test_a_chosen_folder_is_remembered_when_it_is_written_to(self) -> None:
        bigger = self.root / "bigger"
        bigger.mkdir()
        self.choose(bigger)
        self.take()
        self.choose("")

        self.assertIn(bigger, backup_folder.known())

    def test_a_chosen_folder_nothing_was_written_to_is_not_remembered(self) -> None:
        bigger = self.root / "bigger"
        bigger.mkdir()
        self.choose(bigger)
        self.choose("")

        self.assertEqual(backup_folder.known(), [self.default])

    def test_a_folder_with_a_comma_in_its_name_is_remembered_whole(self) -> None:
        odd = self.root / "one, two"
        odd.mkdir()
        self.choose(odd)
        self.take()
        self.choose("")

        self.assertIn(odd, backup_folder.known())

    def test_a_folder_that_no_longer_answers_is_left_out_of_the_listing(self) -> None:
        bigger = self.root / "bigger"
        bigger.mkdir()
        self.choose(bigger)
        self.take()
        self.choose("")
        shutil.rmtree(bigger)

        self.assertEqual(backup_folder.listable(), [])


class WhichBackupsAreBelievedTests(BackupFolderCase):
    def test_a_backup_in_a_folder_nobody_chose_is_not_found(self) -> None:
        """An id carries a path, so a zip in some other folder must not be read as ours."""
        stranger = self.root / "stranger"
        stranger.mkdir()
        alien = stranger / "vpinfe-backup-20261001T010203Z.zip"
        alien.write_bytes(b"not ours")

        self.assertIsNone(places.archive_copy(alien))

    def test_a_backup_in_the_chosen_folder_is_found(self) -> None:
        bigger = self.root / "bigger"
        bigger.mkdir()
        self.choose(bigger)
        path = self.take()

        found = places.archive_copy(path)

        self.assertIsNotNone(found)
        self.assertEqual(found.path, str(path))  # type: ignore[union-attr]


class StatusTests(BackupFolderCase):
    def test_the_default_is_fine_before_it_exists(self) -> None:
        self.assertEqual(backup_folder.status(),
                         {"path": str(self.default), "problem": ""})

    def test_a_chosen_folder_that_is_not_there_says_so(self) -> None:
        self.choose(self.root / "gone")

        found = backup_folder.status()

        self.assertEqual(found["path"], str(self.root / "gone"))
        self.assertIn("Nothing is at that path", found["problem"])

    def test_a_chosen_folder_that_works_has_no_problem(self) -> None:
        bigger = self.root / "bigger"
        bigger.mkdir()
        self.choose(bigger)

        self.assertEqual(backup_folder.status()["problem"], "")


if __name__ == "__main__":
    unittest.main()
