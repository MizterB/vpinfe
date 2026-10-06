"""This install's row in the device registry is filed only when its config sits beside it."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpapi
from common import device_registry, install_identity, paths
from common.device_registry import Device, DeviceRegistry


class OwnRowTests(unittest.TestCase):
    def setUp(self) -> None:
        # Stands for the default config folder: where the registry is, and not where the
        # configs below are.
        self.default = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.addCleanup(device_registry.reset_for_tests)
        device_registry.reset_for_tests(self.default / "devices.json")
        # Seeding writes at paths fixed at import, which a test that is about the
        # registry has no business reaching.
        self.enterContext(patch("httpapi.instance.launcher_migration.ensure_seeded"))
        self.enterContext(patch("httpapi.instance.library_folders.ensure_seeded"))

    def _start_with_config_in(self, folder: Path) -> str:
        """What building the API does, against a config that lives in `folder`."""
        with patch.object(paths, "VPINFE_INI_PATH", folder / "vpinfe.ini"):
            httpapi.instance.mint_identity()
            return install_identity.install_id(paths.get_ini_config())

    def _rows(self) -> list[Device]:
        return DeviceRegistry(self.default / "devices.json").devices()

    def test_a_config_in_another_folder_files_no_row(self) -> None:
        for _ in range(5):
            elsewhere = Path(self.enterContext(tempfile.TemporaryDirectory()))
            self.assertTrue(self._start_with_config_in(elsewhere))

        self.assertEqual(self._rows(), [])

    def test_a_config_beside_the_registry_keeps_one_row_however_often_it_starts(self) -> None:
        ids = {self._start_with_config_in(self.default) for _ in range(3)}

        self.assertEqual([row.device_id for row in self._rows()], list(ids))
        self.assertEqual(len(ids), 1)


if __name__ == "__main__":
    unittest.main()
