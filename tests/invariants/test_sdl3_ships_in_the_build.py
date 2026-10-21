"""SDL3 is in every release build, at one pinned version, and the build proves it loads.

The suite cannot see a native library that did not reach a build, so what these hold is
the wiring: the spec ships the folder, the workflow fetches it for every runner and checks
the finished build, and the version the workflow names is one the fetch script has digests
for. The script's own behavior is read with a stand-in archive and no network.
"""

from __future__ import annotations

import importlib.util
import io
import pathlib
import re
import tempfile
import unittest
import zipfile
from types import ModuleType
from unittest import mock

from tests.invariants.test_build_ships_its_data import _declared_roots

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
WORKFLOW = REPO / ".github" / "workflows" / "build.yml"
SCRIPT = REPO / "scripts" / "fetch_sdl3_bundle.py"
CHECK = "fetch_sdl3_bundle.py check"
PYINSTALLER = "pyinstaller packaging/vpinfe.spec"


def _script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("fetch_sdl3_bundle", SCRIPT)
    assert spec is not None and spec.loader is not None, "scripts/fetch_sdl3_bundle.py is gone"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _steps() -> list[str]:
    """The build job's steps, each as its own text."""
    build = WORKFLOW.read_text(encoding="utf-8").split("\n  release_bundle:")[0]
    return re.split(r"\n      - name:", build)[1:]


class WorkflowTests(unittest.TestCase):
    def test_the_spec_ships_the_folder_the_fetch_fills(self) -> None:
        self.assertIn("third_party/sdl3", _declared_roots())

    def test_the_version_the_workflow_names_is_one_the_script_has_digests_for(self) -> None:
        named = re.search(r"^\s+SDL3_VERSION: (\S+)$", WORKFLOW.read_text(encoding="utf-8"),
                          re.MULTILINE)
        self.assertIsNotNone(named)
        assert named is not None
        release = _script().RELEASES[named.group(1)]
        self.assertEqual({"win-x64", "macos-arm64", "source"}, set(release))
        for kind, digest in release.items():
            self.assertRegex(digest, r"^[0-9a-f]{64}$")
            self.assertIn("{version}", _script().ASSETS[kind])

    def test_every_runner_fetches_the_version_for_its_own_triplet(self) -> None:
        (fetching,) = [step for step in _steps() if "fetch_sdl3_bundle.py fetch" in step]
        self.assertNotIn("if:", fetching)
        self.assertIn('--version "${SDL3_VERSION}"', fetching)
        self.assertIn('--triplet "${DOF_TRIPLET}"', fetching)

    def test_the_linux_build_is_cached_by_version_and_by_the_script(self) -> None:
        (caching,) = [step for step in _steps() if "actions/cache" in step]
        self.assertIn("runner.os == 'Linux'", caching)
        self.assertIn("third_party/sdl3", caching)
        self.assertIn("env.SDL3_VERSION", caching)
        self.assertIn("env.DOF_TRIPLET", caching)
        self.assertIn("hashFiles('scripts/fetch_sdl3_bundle.py')", caching)

    def test_every_pyinstaller_run_is_followed_by_a_load_check(self) -> None:
        steps = _steps()
        building = [at for at, step in enumerate(steps) if PYINSTALLER in step]
        self.assertEqual(2, len(building), "the full build and the slim one")
        for at in building:
            self.assertTrue(CHECK in steps[at] or CHECK in steps[at + 1],
                            steps[at].splitlines()[0])

    def test_the_signed_macos_app_is_checked_before_it_is_wrapped(self) -> None:
        signing = [step for step in _steps() if "codesign --verify" in step]
        self.assertEqual(2, len(signing), "the full build and the slim one")
        for step in signing:
            self.assertLess(step.index("codesign --verify"), step.index(CHECK))
            self.assertLess(step.index(CHECK), step.index("create-dmg"))


class ScriptTests(unittest.TestCase):
    def test_the_windows_zip_gives_the_dll_and_its_license_and_nothing_else(self) -> None:
        script = _script()
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as zf:
            for name in ("SDL3.dll", "LICENSE.txt", "README.md", "INSTALL.txt"):
                zf.writestr(name, name.encode())
        with tempfile.TemporaryDirectory() as td:
            zip_path = pathlib.Path(td) / "sdl.zip"
            zip_path.write_bytes(archive.getvalue())
            out = pathlib.Path(td) / "out"
            out.mkdir()
            script.take_from_zip(zip_path, out)
            self.assertEqual(["LICENSE.txt", "SDL3.dll"], sorted(p.name for p in out.iterdir()))

    def test_a_version_without_digests_is_refused_before_anything_is_fetched(self) -> None:
        script = _script()
        with mock.patch.object(script, "_download") as download:
            with self.assertRaises(SystemExit):
                script.fetch("0.0.1", "win-x64", pathlib.Path("unused"))
            download.assert_not_called()

    def test_a_triplet_without_a_library_name_is_refused(self) -> None:
        script = _script()
        with self.assertRaises(SystemExit):
            script.fetch(next(iter(script.RELEASES)), "freebsd-x64", pathlib.Path("unused"))

    def test_a_copy_already_in_place_is_not_fetched_again(self) -> None:
        script = _script()
        version = next(iter(script.RELEASES))
        with tempfile.TemporaryDirectory() as td:
            out = pathlib.Path(td)
            (out / script.LIBRARY["linux-x64"]).write_bytes(b"")
            (out / script.MARKER).write_text(f"{version} linux-x64\n")
            with mock.patch.object(script, "_download") as download:
                script.fetch(version, "linux-x64", out)
            download.assert_not_called()

    def test_another_triplets_copy_is_replaced(self) -> None:
        """A cache key that missed a triplet would otherwise ship the wrong library."""
        script = _script()
        version = next(iter(script.RELEASES))
        with tempfile.TemporaryDirectory() as td:
            out = pathlib.Path(td) / "sdl3"
            out.mkdir()
            (out / script.LIBRARY["linux-x64"]).write_bytes(b"")
            (out / script.MARKER).write_text(f"{version} linux-x64\n")
            with mock.patch.object(script, "_download", side_effect=RuntimeError("fetched")):
                with self.assertRaises(RuntimeError):
                    script.fetch(version, "win-x64", out)

    def test_the_check_wants_the_library_where_the_build_puts_it(self) -> None:
        script = _script()
        with tempfile.TemporaryDirectory() as td:
            dist = pathlib.Path(td)
            with self.assertRaises(SystemExit):
                script.check("3.4.16", dist)
            stray = dist / "_internal" / "elsewhere" / "sdl3"
            stray.mkdir(parents=True)
            (stray / "SDL3.dll").write_bytes(b"")
            with self.assertRaises(SystemExit):
                script.check("3.4.16", dist)

    def test_the_check_compares_the_version_the_library_reports(self) -> None:
        script = _script()
        with tempfile.TemporaryDirectory() as td:
            dist = pathlib.Path(td)
            home = dist / "_internal" / "third_party" / "sdl3"
            home.mkdir(parents=True)
            (home / "libSDL3.so.0").write_bytes(b"")
            with mock.patch.object(script, "_reported_version", return_value=(3, 4, 16)):
                script.check("3.4.16", dist)
                with self.assertRaises(SystemExit):
                    script.check("3.4.17", dist)


if __name__ == "__main__":
    unittest.main()
