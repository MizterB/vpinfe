"""PinMAME's own answer about a ROM set, from the library VPX ships.

Borrowed, never bundled: the library is located from the launcher the user
already configured, which ties it to the right install on the machine that
launches - the play host. A machine without VPX simply reports the audit
unavailable, through the same availability predicate as everything else.

The lookups run in one long-lived subprocess (see pinmame_worker), which loads the
library once for all of them, and each answer is cached against the roms folder's mtime
because a folder that has not changed gives the same audit.
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import subprocess
import sys
import threading
from pathlib import Path

from common.i18n import t

logger = logging.getLogger("vpinfe.common.host.pinmame_catalog")

ENV_OVERRIDE = "VPINFE_LIBPINMAME"
WORKER_TIMEOUT_SECONDS = 20.0

_cache: dict[tuple, dict] = {}
_helper: tuple[str, subprocess.Popen] | None = None
_helper_lock = threading.Lock()


def _candidate_dirs(vpx_bin_path: str) -> list[Path]:
    """Where the library plausibly lives, derived from the configured launcher."""
    binary = Path(vpx_bin_path)
    vpx_dir = binary.parent
    dirs = [vpx_dir, vpx_dir / "libs", vpx_dir / "plugins" / "pinmame"]
    # macOS app bundle: .../Contents/MacOS/<binary> with Frameworks beside MacOS.
    if vpx_dir.name == "MacOS" and vpx_dir.parent.name == "Contents":
        dirs.insert(0, vpx_dir.parent / "Frameworks")
        dirs.append(vpx_dir.parent / "PlugIns" / "pinmame")
    return dirs


def find_library(vpx_bin_path: str) -> Path | None:
    """The shipped libpinmame, or None. Never raises."""
    override = os.environ.get(ENV_OVERRIDE, "").strip()
    if override:
        path = Path(override)
        return path if path.is_file() else None
    if not (vpx_bin_path or "").strip():
        return None

    patterns = ("libpinmame*.dylib", "libpinmame*.so*", "libpinmame*.dll",
                "pinmame*.dll")
    for directory in _candidate_dirs(vpx_bin_path):
        try:
            for pattern in patterns:
                hits = sorted(directory.glob(pattern))
                if hits:
                    return hits[0]
        except OSError:
            continue
    return None


def availability(vpx_bin_path: str) -> tuple[bool, str | None]:
    """For discovery: can this instance audit ROM sets at all?"""
    if not (vpx_bin_path or "").strip():
        return False, t("error.pinmame.no_launcher")
    if find_library(vpx_bin_path) is None:
        return False, t("error.pinmame.library_not_found")
    return True, None


def _roms_dir_stamp(roms_dir: str) -> float:
    try:
        return os.stat(roms_dir).st_mtime
    except OSError:
        return 0.0


def lookup(vpx_bin_path: str, roms_dir: str, set_name: str) -> dict | None:
    """The catalog entry and audit for one set, or None when the audit cannot run.

    None means "no answer", never "no rom" - the caller falls back to what it
    knew without the library.
    """
    set_name = (set_name or "").strip()
    if not set_name:
        return None
    library = find_library(vpx_bin_path)
    if library is None:
        return None

    key = (str(library), roms_dir, set_name, _roms_dir_stamp(roms_dir))
    if key in _cache:
        return _cache[key]

    with _helper_lock:
        # A caller queued behind the lock may find its answer already made.
        if key in _cache:
            return _cache[key]
        try:
            payload = _ask(str(library), roms_dir, set_name)
        except (OSError, ValueError, RuntimeError) as exc:
            _stop_helper()
            logger.warning("PinMAME catalog worker failed: %s", str(exc) or type(exc).__name__)
            return None

        if "error" in payload:
            _stop_helper()
            logger.warning("PinMAME catalog worker: %s", payload["error"])
            return None
        entry = payload.get(set_name)
        if entry is not None:
            _cache[key] = entry
        return entry


def _helper_command(library: str) -> list[str]:
    """A frozen build has no `-m`: its executable starts VPinFE whatever it is handed."""
    if getattr(sys, "frozen", False):
        return [sys.executable, "--pinmame-helper", "--serve", library]
    return [sys.executable, "-m", "common.host.pinmame_worker", "--serve", library]


def _ask(library: str, roms_dir: str, set_name: str) -> dict:
    """One request to the helper, started on first use. Held under `_helper_lock`.

    A helper that does not answer in time is killed, which ends the read with an empty line.
    """
    global _helper
    if _helper is None or _helper[0] != library or _helper[1].poll() is not None:
        _stop_helper()
        process = subprocess.Popen(
            _helper_command(library),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, cwd=str(Path(__file__).resolve().parents[2]),
        )
        _helper = (library, process)
    process = _helper[1]
    watchdog = threading.Timer(WORKER_TIMEOUT_SECONDS, process.kill)
    watchdog.start()
    try:
        assert process.stdin is not None and process.stdout is not None
        process.stdin.write(json.dumps({"roms_dir": roms_dir, "names": [set_name]}) + "\n")
        process.stdin.flush()
        line = process.stdout.readline()
    finally:
        watchdog.cancel()
    if not line:
        raise BrokenPipeError
    payload = json.loads(line)
    if not isinstance(payload, dict):
        raise ValueError(line.strip())
    return payload


def _stop_helper() -> None:
    global _helper
    if _helper is None:
        return
    process = _helper[1]
    _helper = None
    try:
        if process.stdin is not None:
            process.stdin.close()
    except OSError:
        pass
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
    if process.stdout is not None:
        process.stdout.close()


atexit.register(_stop_helper)


def clear_cache() -> None:
    """For tests."""
    _cache.clear()
    with _helper_lock:
        _stop_helper()
