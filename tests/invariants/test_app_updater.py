import tempfile
import unittest
from pathlib import Path

from common.atomic_write import STAGED_PREFIX, STAGED_SUFFIX
from common.online.app_updater import _build_posix_update_script, _clear_abandoned_downloads


class TestAppUpdaterScripts(unittest.TestCase):
    def test_build_posix_update_script_keeps_shell_env_expansion_literals(self) -> None:
        prepared = {
            "zip_path": "/tmp/vpinfe.zip",
            "stage_dir": "/tmp/stage",
            "install_root": "/tmp/install",
            "launch_target": "/tmp/install/vpinfe",
            "last_update_log": "/tmp/last_update.log",
        }

        script = _build_posix_update_script(prepared, current_pid=1234,
                                           log_path=Path("/tmp/apply_update.log"))

        self.assertIn("DISPLAY=${DISPLAY:-<unset>}", script)
        self.assertIn("WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-<unset>}", script)
        self.assertIn("XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-<unset>}", script)

    def test_build_posix_update_script_repairs_linux_chromium_permissions(self) -> None:
        prepared = {
            "zip_path": "/tmp/vpinfe.zip",
            "stage_dir": "/tmp/stage",
            "install_root": "/tmp/install",
            "launch_target": "/tmp/install/vpinfe",
            "last_update_log": "/tmp/last_update.log",
        }

        script = _build_posix_update_script(prepared, current_pid=1234,
                                           log_path=Path("/tmp/apply_update.log"))

        self.assertIn('CHROMIUM_ROOT="$INSTALL_ROOT/_internal/chromium/linux/chrome"', script)
        self.assertIn('find "$CHROMIUM_ROOT" -type d -exec chmod a+rx {} +', script)
        self.assertIn("chrome_crashpad_handler chrome-sandbox", script)


class TestAbandonedDownloads(unittest.TestCase):
    def test_a_killed_download_leaves_nothing_behind_the_next_one(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stage = Path(tmp)
            killed = stage / f"{STAGED_PREFIX}0123456789ab{STAGED_SUFFIX}"
            killed.write_bytes(b"half a zip")
            kept = stage / "vpinfe-3.0.zip"
            kept.write_bytes(b"a whole one")

            _clear_abandoned_downloads(stage)

            self.assertFalse(killed.exists())
            self.assertTrue(kept.exists())


if __name__ == "__main__":
    unittest.main()
