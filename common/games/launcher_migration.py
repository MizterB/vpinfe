"""Turning what an install already had into launchers.

Two things become launchers on the way to 3.0: the seven Visual Pinball settings that sat
flat in `general`, and the plugin profiles, which were a full copy of `VPinballX.ini`
saved under a name and opted into per table. Both were one idea written twice - a way of
running Visual Pinball differently - so a profile is not carried alongside launchers, it
is one.

The per-table half is separate and runs where the library is read: a table's assignment
needs a table, and this module only needs the config directory.

Marked once so it never runs twice. Somebody who deletes a launcher they did not want
should not find it back on the next start.
"""

from __future__ import annotations

import logging

from common.config_access import SettingsConfig
from common.games import launchers
from common.paths import PLUGIN_PROFILES_DIR

logger = logging.getLogger("vpinfe.common.games.launcher_migration")

SEEDED = "seeded-from-config"

# What the shipped launcher is called before anybody renames it. Its app's name rather
# than something invented: on an install with one launcher, "Visual Pinball X" is what a
# person would call the thing that runs their tables.
SHIPPED_NAME = "Visual Pinball X"


def seed(store: launchers.LauncherStore, config) -> bool:
    """Give an install its launchers, once. Returns whether it wrote anything.

    The shipped one is written first, and that is what makes it the default: an
    unassigned table resolves to the first enabled launcher for its app.
    """
    if SEEDED in store.migrations():
        return False

    settings = SettingsConfig.from_config(config)
    shipped = launchers.seeded_from(settings)
    found = [launchers.replace(shipped, display_name=SHIPPED_NAME)]
    found += _from_profiles(shipped)

    store.save(found, {})
    store.mark_migration(SEEDED)
    logger.info("Seeded %d launcher(s) from the existing configuration", len(found))
    return True


def _from_profiles(shipped: launchers.Launcher) -> list[launchers.Launcher]:
    """One launcher per plugin profile, each a copy of the shipped one pointed at its ini.

    A copy rather than a bare launcher because that is what a profile was: the same
    Visual Pinball, the same binary, one file different. Anything else would silently
    drop the environment and the overrides a person had set.

    `owns_ini` is True - VPinFE wrote these files, so removing the launcher may offer to
    delete them. The shipped launcher's ini is Visual Pinball's own and is never offered.
    """
    if not PLUGIN_PROFILES_DIR.exists():
        return []

    found = []
    for path in sorted(PLUGIN_PROFILES_DIR.iterdir(), key=lambda p: p.name.lower()):
        if not path.is_file() or path.suffix.lower() != ".ini":
            continue
        found.append(launchers.replace(
            shipped,
            launcher_id=launchers.mint_launcher_id(),
            display_name=path.stem,
            owns_ini=True,
            settings={**shipped.settings, "ini_override": str(path)},
        ))
    return found


def ensure_seeded(config) -> None:
    """Seed at startup, and never let it be the thing that stops an install starting."""
    try:
        seed(launchers.get_launcher_store(), config)
    except Exception:
        logger.exception("Could not seed launchers from the configuration")
