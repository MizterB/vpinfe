"""What this install collects: media kinds, asset kinds, artwork catalogs, quiet checks.

A view over the `library` section of the settings file. The Manager writes through
`PUT /config`; `set` here writes the file directly and announces nothing, which is for
tests and for code that is not itself a settings change. Each list holds what is
switched off, so empty means everything and a kind or a source added in a later
version arrives switched on.
"""

from __future__ import annotations

import threading
from typing import Any

from common.config.config_store import ConfigStore
from common.config.paths import get_ini_config

SECTION = "library"

KEYS = ("hidden_media_kinds", "hidden_asset_kinds", "hidden_sources", "hidden_checks")


def _as_list(raw: Any) -> list[str]:
    """However the value arrives - a list, or the comma string a parser holds."""
    if isinstance(raw, str):
        raw = raw.split(",")
    return [str(item).strip() for item in (raw or []) if str(item).strip()]


class LibraryPolicy:
    """The four lists, read from and written to the settings store."""

    def __init__(self, store: ConfigStore | None = None) -> None:
        self._store = store
        self._lock = threading.RLock()

    def _config(self) -> ConfigStore:
        return self._store if self._store is not None else get_ini_config()

    def values(self) -> dict[str, list[str]]:
        config = self._config()
        return {key: _as_list(config.value(SECTION, key)) for key in KEYS}

    def get(self, key: str) -> list[str]:
        if key not in KEYS:
            return []
        return _as_list(self._config().value(SECTION, key))

    def set(self, key: str, value: Any) -> list[str]:
        """Stores `value`, empty included: empty is how "collect it all" is said."""
        if key not in KEYS:
            raise ValueError(f"not a library policy: {key}")
        with self._lock:
            config = self._config()
            config.set_value(SECTION, key, _as_list(value))
            config.save()
            return self.get(key)


_policy: LibraryPolicy | None = None


def get_library_policy() -> LibraryPolicy:
    global _policy
    if _policy is None:
        _policy = LibraryPolicy()
    return _policy


def reset_for_tests(store: ConfigStore | None = None) -> LibraryPolicy:
    global _policy
    _policy = LibraryPolicy(store)
    return _policy
