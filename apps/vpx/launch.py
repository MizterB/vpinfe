"""Building Visual Pinball's command line, and how one of its sessions is watched."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from common.apps.contract import (
    SESSION_CHILD_WITH_READINESS,
    Entry,
    Session,
)

from .config import own_file

logger = logging.getLogger("vpinfe.apps.vpx.launch")

# VPX writes this once the table is actually up. Before it, the process exists but the
# player is looking at nothing.
STARTUP_MARKER = "Startup done"


def _is_own(named: str, bin_path: str) -> bool:
    own = own_file(bin_path)
    if own is None:
        return False
    try:
        return Path(named).expanduser().resolve() == own.resolve()
    except OSError:
        return False


class VPXLaunch:
    """`settings` is the launcher's, with `bin_path` already resolved to the executable -
    on macOS what a person picks is a `.app` directory, and VPX is inside it."""

    def command(self, entry: Entry, settings: Mapping[str, Any]) -> list[str]:
        """`-play <table>` is guaranteed last, and there is only ever one `-ini`.

        VPX accepts a single `-ini` and silently drops a second, which would make us the
        one who lost the setting without saying so.
        """
        bin_path = str(settings.get("bin_path") or "")
        cmd = [bin_path]

        named = str(settings.get("ini_path") or "").strip()
        if named and not _is_own(named, bin_path):
            cmd.extend(["-ini", named])

        cmd.extend(["-play", str(entry.table)])
        return cmd

    def session(self, settings: Mapping[str, Any]) -> Session:
        return Session(kind=SESSION_CHILD_WITH_READINESS,
                       readiness_marker=STARTUP_MARKER)
