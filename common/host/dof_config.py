"""Where DOF's config lives: Visual Pinball's `directoutputconfig`.

Visual Pinball's DOF plugin reads it from its preferences folder, and the frontend's own
DOF is given the same folder as its base path, so the two read the same files.
"""

from __future__ import annotations

from pathlib import Path

from apps.vpx import config as vpx_config

FOLDER = "directoutputconfig"


def base_path() -> Path | None:
    """The folder DOF is given as its base path, or None where the platform names none."""
    return vpx_config.preferences_folder()


def config_folder() -> Path | None:
    """The folder holding DOF's config files, or None where the platform names none."""
    base = base_path()
    return base / FOLDER if base is not None else None
