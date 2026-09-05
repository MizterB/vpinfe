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
from pathlib import Path

from common.config_access import SettingsConfig
from common.games import game_metadata, launchers, tables
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


ASSIGNED = "assignments-from-info"


def migrate_assignments(store: launchers.LauncherStore, games) -> dict[str, int]:
    """Turn each table's own override into a launcher and an assignment.

    `alt_launcher` carried a raw binary path and `plugin_profile` a named ini, and they
    were two partial ways of saying the same thing: this table launches differently. A
    launcher id says it once.

    Distinct binaries are de-duplicated by path, so a library where forty tables name one
    alternative build gets one launcher rather than forty. A profile already became a
    launcher when the install was seeded, so a table naming one is matched to it rather
    than making a second.

    The assignment lands on every table in the game, because the override was written per
    game and there is no record of which of its tables it was meant for. Splitting them
    afterwards is a thing a person can do; guessing here is not.

    The two keys are left in the `.info` rather than stripped. Nothing reads them after
    this, so removing them would be a write to every affected folder in somebody's library
    for no change in behaviour - and `Medias` is the precedent for a key that stays listed
    once nothing writes it. They remain machine-local, so import and export still leave
    them behind.
    """
    if ASSIGNED in store.migrations():
        return {}

    held = store.launchers()
    mappings = dict(store.mappings())
    shipped = held[0] if held else None
    by_path: dict[str, str] = {}
    counts = {"launchers": 0, "tables": 0, "games": 0}

    for game in games or []:
        meta = getattr(game, "meta_config", None)
        if not isinstance(meta, dict):
            continue
        vpinfe = game_metadata.vpinfe_section(meta)
        alt = str(vpinfe.get("alt_launcher", "") or "").strip()
        profile = str(vpinfe.get("plugin_profile", "") or "").strip()
        if not alt and not profile:
            continue

        wanted = ""
        if alt:
            wanted = by_path.get(alt, "")
            if not wanted:
                made = _for_binary(alt, shipped)
                held.append(made)
                by_path[alt] = wanted = made.launcher_id
                counts["launchers"] += 1
        elif profile:
            wanted = _profile_launcher(profile, held)

        if not wanted:
            logger.warning("No launcher for plugin profile %r; leaving %s on the default",
                           profile, getattr(game, "gameDirName", "?"))
            continue

        for table_id in tables.table_entries(meta):
            mappings[str(table_id)] = wanted
            counts["tables"] += 1
        counts["games"] += 1

    store.save(held, mappings)
    store.mark_migration(ASSIGNED)
    if counts["games"]:
        logger.info("Moved %d game(s) onto launchers: %d table(s), %d new launcher(s)",
                    counts["games"], counts["tables"], counts["launchers"])
    return counts


def _for_binary(path: str, shipped: launchers.Launcher | None) -> launchers.Launcher:
    """A launcher for a binary a table named, copied from the shipped one.

    A copy because `alt_launcher` only ever replaced the program: everything else about
    the launch - the ini, the environment, the overrides - came from the install, and a
    bare launcher would silently drop all of it.
    """
    base = shipped or launchers.Launcher(launcher_id="", app="vpx")
    return launchers.replace(
        base,
        launcher_id=launchers.mint_launcher_id(),
        display_name=Path(path).stem or path,
        owns_ini=False,
        settings={**base.settings, "bin_path": path},
    )


def _profile_launcher(name: str, held) -> str:
    """The launcher the seeding pass made from this profile, by the name it gave it."""
    wanted = name.strip().lower()
    found = next((one for one in held
                  if one.display_name.strip().lower() == wanted), None)
    return found.launcher_id if found is not None else ""


def ensure_seeded(config) -> None:
    """Seed at startup, and never let it be the thing that stops an install starting."""
    try:
        seed(launchers.get_launcher_store(), config)
    except Exception:
        logger.exception("Could not seed launchers from the configuration")
