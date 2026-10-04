"""Where VPinFE keeps its own files.

Resolved once at import, because a frozen build and a `--configdir` run have to agree
on the answer before anything else reads it.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from platformdirs import user_config_dir

from common.config_store import ConfigStore


def _resolve_config_dir() -> Path:
    # VPINFE_CONFIG_DIR lets you point the whole config directory (vpinfe.ini,
    # themes/, caches, logs, .nicegui storage) somewhere other than the OS
    # default. Read at import time so it also applies to frozen PyInstaller
    # builds. Falls back to the platformdirs location when unset.
    # Anchored here, once: a relative path would follow the working directory, and the
    # Manager UI changes that while it runs a script. Written back so a helper started
    # from another directory resolves the same one.
    override = os.environ.get("VPINFE_CONFIG_DIR", "").strip()
    if override:
        anchored = Path(override).expanduser().absolute()
        os.environ["VPINFE_CONFIG_DIR"] = str(anchored)
        return anchored
    if _unbootstrapped_test_run():
        raise RuntimeError(
            "This is a unittest run that skipped tests/__init__.py, so it would use the "
            "real config folder. Run: python -m unittest discover -t . -s tests"
            " (or: python -m tests)")
    return Path(user_config_dir("vpinfe", "vpinfe"))


def _unbootstrapped_test_run() -> bool:
    """A `python -m unittest` run that never imported tests/, which sets the override."""
    main = sys.modules.get("__main__")
    entry = getattr(getattr(main, "__spec__", None), "name", "")
    return entry == "unittest.__main__" and "tests" not in sys.modules


# Where the app itself lives, as opposed to the user's config. Bundled assets sit
# under it: frontend/static/, third_party/, main.py. Resolved here so no module has to count
# its own directory levels - doing that is what broke when common/ gained
# subpackages, and it broke silently everywhere a test did not happen to look.
APP_ROOT = Path(__file__).resolve().parent.parent


def bundled(*parts: str) -> Path:
    """A file the build ships, wherever this copy of VPinFE is running from.

    Measured rather than assumed, on a real frozen build of each kind: `APP_ROOT` and
    `sys._MEIPASS` are the same directory - `_internal/` for a onedir build,
    `Contents/Frameworks/` inside a macOS .app - and in a source checkout it is the
    repo. So one expression covers every case, and the callers that each grew their own
    chain of guesses do not need one.
    """
    return APP_ROOT.joinpath(*parts)

CONFIG_DIR = _resolve_config_dir()
VPINFE_INI_PATH = CONFIG_DIR / "vpinfe.ini"
COLLECTIONS_PATH = CONFIG_DIR / "collections.json"
TAGS_PATH = CONFIG_DIR / "tags.json"
DERIVED_TAGS_PATH = CONFIG_DIR / "derived_tags.json"
# Read once and converted; kept as a name so a restore can still find its backups.
COLLECTIONS_INI_PATH = CONFIG_DIR / "collections.ini"
THEMES_DIR = CONFIG_DIR / "themes"
THEME_CACHE_PATH = CONFIG_DIR / "cache" / "themes.json"
UPDATE_CHECK_PATH = CONFIG_DIR / "cache" / "update.json"
FRONTEND_BROWSER_PATH = CONFIG_DIR / "cache" / "frontend_browser.json"
COMMUNITY_KEPT_DIR = CONFIG_DIR / "cache" / "community"
PLUGIN_PROFILES_DIR = CONFIG_DIR / "plugin_profiles"
UPDATES_DIR = CONFIG_DIR / "updates"
USER_CONFIG_PATH = VPINFE_INI_PATH
USER_ROMS_PATH = CONFIG_DIR / "roms.json"


def ensure_config_dir() -> Path:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    return CONFIG_DIR


def configure_nicegui_storage() -> str:
    nicegui_storage_dir = ensure_config_dir() / ".nicegui"
    nicegui_storage_dir.mkdir(parents=True, exist_ok=True)
    storage_path = str(nicegui_storage_dir)
    os.environ["NICEGUI_STORAGE_PATH"] = storage_path
    return storage_path


def get_ini_config() -> ConfigStore:
    ensure_config_dir()
    return ConfigStore(str(VPINFE_INI_PATH))


def get_games_path(default: str = "~/tables") -> str:
    try:
        from common.config_access import cfg_get
        game_root = cfg_get(get_ini_config(), "Settings", "game_root_dir").strip()
        if game_root:
            return os.path.expanduser(game_root)
    except Exception:
        pass
    return os.path.expanduser(default)


def get_themes_dir() -> Path:
    return ensure_config_dir() / "themes"
