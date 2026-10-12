"""How Visual Pinball pauses: its own Pause key, and the lines it writes on either side."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from . import keys
from .config import own_file

logger = logging.getLogger("vpinfe.apps.vpx.pause")

# `Player::SetPlayState` writes these as the game stops and starts again.
PAUSED_MARKER = "Pausing Game"
RESUMED_MARKER = "Unpausing Game"

# What VPX pauses on where its settings file maps nothing to Pause.
DEFAULT_KEY = "KeyP"


class VPXPause:
    paused_marker = PAUSED_MARKER
    resumed_marker = RESUMED_MARKER

    def key(self, settings: Mapping[str, Any]) -> str:
        """`settings` is the launcher's: its `ini_path`, or VPX's own file where it has
        none. A file that cannot be read maps nothing."""
        named = str(settings.get("ini_path") or "").strip()
        if not named:
            found = own_file(str(settings.get("bin_path") or ""))
            named = str(found) if found is not None else ""
        try:
            return keys.mappings(named).get("Pause", "") or DEFAULT_KEY
        except (OSError, UnicodeError) as error:
            logger.warning("Could not read %s (%s), so Pause is the key VPX uses on its own",
                           named, error)
            return DEFAULT_KEY
