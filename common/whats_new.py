"""Whether this start is the first after an update, and what there is to tell about it.

`install.last_version` is the release this install last started as. A start under a later
release marks the review pending, once, and reading it clears the mark.
`install.whats_new_since` is where that review begins: the oldest version not yet read.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from common import install_setup, migration_ledger, release_notes, upgrade_needs
from common.config_access import ConfigSource, cfg_bool, cfg_get
from common.config_store import ConfigStore

SECTION = "install"
LAST_KEY = "last_version"
PENDING_KEY = "whats_new_pending"
SINCE_KEY = "whats_new_since"


@dataclass(frozen=True)
class Review:
    since: str
    releases: list[release_notes.Release] = field(default_factory=list)
    files: list[migration_ledger.Entry] = field(default_factory=list)
    needs: list[upgrade_needs.Need] = field(default_factory=list)


def last_version(config: ConfigSource) -> str:
    return str(cfg_get(config, SECTION, LAST_KEY, "") or "")


def since(config: ConfigSource) -> str:
    return str(cfg_get(config, SECTION, SINCE_KEY, "") or "")


def due(config: ConfigSource) -> bool:
    """Whether an update is waiting to be read. Never while Setup is, because a new
    install has nothing to catch up on."""
    return cfg_bool(config, SECTION, PENDING_KEY, False) and not install_setup.pending(config)


def note_start(config: ConfigStore, running: str) -> None:
    """Record this start. A build that is not a tagged release is not an update and
    writes nothing, so a person running from source or a CI build is never interrupted.
    """
    if not release_notes.is_release(running):
        return
    last = last_version(config)
    if last == running:
        return
    if not install_setup.pending(config) and (not last or release_notes.newer(running, last)):
        if not cfg_bool(config, SECTION, PENDING_KEY, False):
            config.set_value(SECTION, SINCE_KEY, last)
        config.set_value(SECTION, PENDING_KEY, True)
    config.set_value(SECTION, LAST_KEY, running)
    config.save()


def mark_seen(config: ConfigStore) -> None:
    if not cfg_bool(config, SECTION, PENDING_KEY, False):
        return
    config.set_value(SECTION, PENDING_KEY, False)
    config.set_value(SECTION, SINCE_KEY, "")
    config.save()


def review(config: ConfigSource, running: str, *, again: bool = False,
           folder: Path | None = None, current: Path | None = None,
           ledger: Path | None = None,
           needs: tuple[upgrade_needs.Need, ...] | None = None) -> Review:
    """Everything since the version this install last read about. Asked again, it is the
    running version alone: its notes, what it did to the files, and what is still open."""
    began = "" if again else since(config)
    files = migration_ledger.entries(began, ledger)
    if again:
        files = [one for one in files if one.version == running]
    return Review(
        since=began,
        releases=release_notes.crossed(began, running, folder=folder, current=current),
        files=files,
        needs=upgrade_needs.open_for(config, began, needs),
    )
