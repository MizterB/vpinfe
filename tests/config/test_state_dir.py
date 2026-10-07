import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import common.paths

ENV_VAR = "VPINFE_CONFIG_DIR"


class TestStateDir(unittest.TestCase):
    """common.paths.STATE_DIR on each platform, with platformdirs' answers stubbed."""

    def setUp(self) -> None:
        self._saved = os.environ.get(ENV_VAR)

    def tearDown(self) -> None:
        if self._saved is None:
            os.environ.pop(ENV_VAR, None)
        else:
            os.environ[ENV_VAR] = self._saved
        importlib.reload(common.paths)

    def _resolve(self, config: str, state: str, platform: str):
        os.environ.pop(ENV_VAR, None)
        with (patch("platformdirs.user_config_dir", lambda *a, **k: config),
              patch("platformdirs.user_state_dir", lambda *a, **k: state),
              patch.object(sys, "platform", platform)):
            return importlib.reload(common.paths)

    def test_linux_keeps_state_in_the_xdg_state_folder(self) -> None:
        paths = self._resolve("/srv/vpinfe/config", "/srv/vpinfe/state",
                              "linux")

        self.assertEqual(paths.STATE_DIR, Path("/srv/vpinfe/state"))

    def test_macos_keeps_state_in_a_folder_of_the_config_folder(self) -> None:
        both = "/Library/Application Support/vpinfe"

        paths = self._resolve(both, both, "darwin")

        self.assertEqual(paths.STATE_DIR, Path(both) / "state")

    def test_windows_keeps_state_beside_its_cache_and_logs(self) -> None:
        both = "/ProgramData/vpinfe/vpinfe"

        paths = self._resolve(both, both, "win32")

        self.assertEqual(paths.STATE_DIR, Path(both) / "State")

    def test_an_override_keeps_state_beside_it(self) -> None:
        override = Path(tempfile.gettempdir()) / "vpinfe-override"
        os.environ[ENV_VAR] = str(override)
        paths = importlib.reload(common.paths)

        self.assertEqual(paths.STATE_DIR, override.absolute() / "state")


if __name__ == "__main__":
    unittest.main()
