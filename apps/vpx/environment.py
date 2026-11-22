"""What Visual Pinball's process is started with."""

from __future__ import annotations

import sys
from collections.abc import Mapping
from typing import Any

# SDL's hint, read from the environment. Dropping it brings back a table that starts paused
# on a Mac with a full screen window on each of several displays.
FULLSCREEN_SPACES = "SDL_VIDEO_MAC_FULLSCREEN_SPACES"


class VPXEnvironment:
    def variables(self, settings: Mapping[str, Any]) -> dict[str, str]:
        if sys.platform != "darwin":
            return {}
        return {FULLSCREEN_SPACES: "0"}
