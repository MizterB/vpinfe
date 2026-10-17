"""Online places an extension says a game's files can be had from, which core draws.

A source is offered a kind of file for one game and answers what it has; taking one of
its rows is the source's own doing. Core keeps no address of its own for any of it, so
the registry holds functions and nothing else.
"""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("vpinfe.common.extensions.sources")

KEY_PATTERN = re.compile(r"[a-z][a-z0-9_]*")
# The slot a pick fills when a kind of file has no slot of its own: a table is added.
TABLE = "table"
# `backglass` is also the picture, so the file a game keeps is asked for under its own name.
BACKGLASS_FILE = "backglass_file"
# Asset kinds no Add or Replace dialog is opened for, so no source is ever asked for one.
NO_DIALOG = frozenset({"game_info", "patch", "media"})


@dataclass(frozen=True)
class Source:
    extension: str
    key: str
    name: str
    kinds: frozenset[str]
    offers: Callable[[dict, str], Any]
    take: Callable[[dict, str, str], Any]
    take_many: Callable[[dict, list[dict]], Any] | None = None
    act: Callable[[dict, str, str, str], Any] | None = None
    look: Callable[[dict, str, str], Any] | None = None

    @property
    def id(self) -> str:
        """What Settings stores to switch it off. Namespaced, so two extensions may name a
        source the same and a built-in id never collides with either."""
        return f"{self.extension}.{self.key}"


_lock = threading.RLock()
_sources: dict[str, Source] = {}


def slot_kinds() -> frozenset[str]:
    """Every kind a dialog is opened for, by the name it is opened with: a media kind, an
    asset kind, the name the asset lens gives a kind that is a folder of files, and
    `table`."""
    from common.games import asset_registry
    from common.media.media_specs import MEDIA_SPECS

    asked = [spec for spec in asset_registry.ASSET_SPECS if spec.kind not in NO_DIALOG]
    return frozenset({TABLE, BACKGLASS_FILE, *(spec.kind for spec in MEDIA_SPECS),
                      *(spec.kind for spec in asked),
                      *(asset_registry.lens_kind(spec.kind) for spec in asked)})


def file_kind(kind: str) -> str:
    """The name a source knows an asset slot by: the registry's, except where a media kind
    shares it."""
    return BACKGLASS_FILE if kind == "backglass" else kind


def names_for(kind: str) -> frozenset[str]:
    """Every name a source may have offered a dialog opened for `kind` under: the name the
    dialog was opened with, the registry's kind behind it and the name the lens gives it."""
    from common.games import asset_registry
    from common.media.media_specs import canonical_kind

    # `table` is also an old spelling of the playfield picture, which is not what a
    # table is here.
    names = {kind} if kind in (TABLE, BACKGLASS_FILE) else {kind, canonical_kind(kind)}
    try:
        for spec in asset_registry.specs_named(kind):
            names |= {spec.kind, asset_registry.lens_kind(spec.kind)}
    except KeyError:
        pass
    return frozenset(names)


def register(extension: str, key: str, name: str, kinds: frozenset[str],
             offers: Callable[[dict, str], Any], take: Callable[[dict, str, str], Any],
             take_many: Callable[[dict, list[dict]], Any] | None = None,
             act: Callable[[dict, str, str, str], Any] | None = None,
             look: Callable[[dict, str, str], Any] | None = None) -> None:
    if not KEY_PATTERN.fullmatch(key):
        raise ValueError(f"{key!r} is not a key: it is lower-case words joined by underscores")
    if not kinds:
        raise ValueError(f"{key!r} offers no kind of file")
    unknown = sorted(kinds - slot_kinds())
    if unknown:
        raise ValueError(f"{key!r} offers {', '.join(unknown)}, which core has no slot for: "
                         f"{', '.join(sorted(slot_kinds()))}")
    held = Source(extension, key, name, frozenset(kinds), offers, take, take_many, act, look)
    with _lock:
        _sources[held.id] = held
    logger.info("%s offers %s from %r", extension, ", ".join(sorted(kinds)), name)


def forget(extension: str) -> None:
    with _lock:
        for one in [one for one in _sources.values() if one.extension == extension]:
            _sources.pop(one.id, None)


def all_sources() -> list[Source]:
    """Every source, in the order they were contributed."""
    with _lock:
        return list(_sources.values())


def named(extension: str, key: str) -> Source | None:
    with _lock:
        return _sources.get(f"{extension}.{key}")


def enabled(source: Source) -> bool:
    """Whether this install has not switched the source off in Settings."""
    from common.games.library_policy import get_library_policy

    off = {name.lower() for name in get_library_policy().get("hidden_sources")}
    return source.id.lower() not in off


_changes: list[tuple[int, str]] = []
# Enough for a pane that was closed a while to learn what moved; past it, it redraws whole.
CHANGES_KEPT = 200


def changed(vps_id: str) -> None:
    """Note that what a source would offer for this VPS entry has moved, so an open
    Discovery pane draws it again. Safe from any thread."""
    vps_id = str(vps_id or "").strip()
    with _lock:
        _changes.append((_changes[-1][0] + 1 if _changes else 1, vps_id))
        del _changes[:-CHANGES_KEPT]


def changes_since(version: int) -> tuple[int, list[str]]:
    """The newest version, and the VPS ids that moved after `version`. An empty id means
    "any of them": the caller was too far behind to be told which."""
    with _lock:
        newest = _changes[-1][0] if _changes else 0
        if version > newest or (_changes and version < _changes[0][0] - 1):
            return newest, [""]
        return newest, sorted({vps_id for number, vps_id in _changes if number > version})


def clear() -> None:
    """For tests."""
    with _lock:
        _sources.clear()
        _changes.clear()
