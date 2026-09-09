"""An extension's own settings, and the switch that keeps one from loading.

Follows `common/games/locations.py`: a small JSON file, written whole and atomically,
carrying its own schema version. Deliberately not `vpinfe.ini` - the ini holds what core
is configured with, and an extension writing into it would put a third party's values in
the file core reads its own from.

The stored switch is the user's. An extension disabled by an error is disabled for this
run only: a fault that happens once must not take the extension away until somebody
notices a setting they never set.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from common.atomic_write import write_atomic
from common.paths import CONFIG_DIR

logger = logging.getLogger("vpinfe.common.extensions.store")

EXTENSIONS_PATH = CONFIG_DIR / "extensions.json"
SCHEMA = 1
SCHEMA_KEY = "schema"
EXTENSIONS_KEY = "extensions"
ENABLED_KEY = "enabled"
SETTINGS_KEY = "settings"


class ExtensionStore:
    """What the user has said about each extension, keyed by its name."""

    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path is not None else EXTENSIONS_PATH
        self._lock = threading.RLock()

    def enabled(self, name: str) -> bool:
        """An extension nobody has said anything about is on: installing one is the
        act of asking for it."""
        with self._lock:
            return bool(self._entry(name).get(ENABLED_KEY, True))

    def set_enabled(self, name: str, on: bool) -> None:
        with self._lock:
            held = self._load()
            entry = dict(held.get(name) or {})
            entry[ENABLED_KEY] = bool(on)
            held[name] = entry
            self._write(held)

    def settings(self, name: str) -> dict[str, str]:
        with self._lock:
            raw = self._entry(name).get(SETTINGS_KEY) or {}
        return {str(key): str(value) for key, value in raw.items()} \
            if isinstance(raw, dict) else {}

    def set_setting(self, name: str, key: str, value: str) -> None:
        wanted = str(key or "").strip()
        if not wanted:
            return
        with self._lock:
            held = self._load()
            entry = dict(held.get(name) or {})
            settings = dict(entry.get(SETTINGS_KEY) or {})
            settings[wanted] = str(value)
            entry[SETTINGS_KEY] = settings
            held[name] = entry
            self._write(held)

    def forget(self, name: str) -> None:
        """Drop everything stored about one, for an extension that has been removed."""
        with self._lock:
            held = self._load()
            if held.pop(name, None) is not None:
                self._write(held)

    # -- the file ------------------------------------------------------------

    def _entry(self, name: str) -> dict:
        found = self._load().get(str(name or "").strip())
        return found if isinstance(found, dict) else {}

    def _load(self) -> dict:
        try:
            with open(self.path, encoding="utf-8") as handle:
                payload = json.load(handle) or {}
        except FileNotFoundError:
            return {}
        except Exception:
            logger.exception("Could not read %s; treating it as empty", self.path)
            return {}
        held = payload.get(EXTENSIONS_KEY)
        return dict(held) if isinstance(held, dict) else {}

    def _write(self, held: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {SCHEMA_KEY: SCHEMA, EXTENSIONS_KEY: held}
        write_atomic(self.path, lambda handle: json.dump(payload, handle, indent=2))


_store: ExtensionStore | None = None


def get_extension_store() -> ExtensionStore:
    """This install's extension settings. One per process, the way the launchers are."""
    global _store
    if _store is None:
        _store = ExtensionStore()
    return _store
