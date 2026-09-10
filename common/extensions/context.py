"""The curated facade an extension is handed, and nothing else.

`register(ctx)` never receives the application. Everything below is a narrow view over
one core facility, named for the extension that holds it, so that "which extension did
this?" is answerable from a log line, a config file or a scope.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from common import events as core_events

from .contract import ContractError, Manifest
from .games import ExtensionGames
from .store import ExtensionStore

LOG_ROOT = "vpinfe.ext"


def logger_for(name: str) -> logging.Logger:
    return logging.getLogger(f"{LOG_ROOT}.{name}")


class ExtensionConfig:
    """An extension's settings, under its own name."""

    def __init__(self, name: str, store: ExtensionStore) -> None:
        self._name = name
        self._store = store

    def get(self, key: str, default: str = "") -> str:
        return self.all().get(str(key or "").strip(), default)

    def all(self) -> dict[str, str]:
        return self._store.settings(self._name)

    def set(self, key: str, value: str) -> None:
        self._store.set_setting(self._name, key, value)


class ExtensionEvents:
    """The bus, seen from one extension: it is told what core did, and publishes under
    its own namespace so nothing it emits can be mistaken for a core event."""

    def __init__(self, name: str, declared: tuple[str, ...],
                 on_failure: Callable[[str], None]) -> None:
        self._name = name
        self._declared = frozenset(declared)
        self._on_failure = on_failure
        self._logger = logger_for(name)
        self.registered: list[tuple[str, Callable]] = []

    def subscribe(self, event: str, handler: Callable) -> None:
        def contained(**payload) -> None:
            try:
                handler(**payload)
            except Exception:
                self._logger.exception("Handling %s failed", event)
                self._on_failure(f"Failed while handling {event}")

        core_events.subscribe(event, contained)
        self.registered.append((event, contained))

    def publish(self, event: str, **payload) -> None:
        wanted = str(event or "").strip()
        if wanted not in self._declared:
            raise ContractError(f"{self._name} publishes {wanted!r}, which its manifest "
                                "does not declare")
        core_events.emit(f"{self._name}.{wanted}", **payload)


class ExtensionFiles:
    """The folders an extension works from, so core will accept a path inside one.

    Nothing here stops an extension reading a file - in-process Python cannot be
    prevented from opening one, and pretending otherwise would be theater. What it does
    is let core's own routes take a path the extension is working with: an importer
    converting somebody's old library has to hand core files that are nowhere near ours,
    and without this every one of them is refused.

    Declared rather than assumed, and only by an extension whose manifest asks for it, so
    what an install will read is something a person agreed to and can be shown.
    """

    def __init__(self, name: str, allowed: bool) -> None:
        self._name = name
        self._allowed = allowed
        self._roots: tuple[str, ...] = ()

    def roots(self) -> tuple[str, ...]:
        return self._roots

    def set_roots(self, paths) -> None:
        """Replace the set. The user moves a share or points somewhere else, and what
        core will accept has to follow rather than accumulate."""
        if not self._allowed:
            raise ContractError(f"{self._name} sets folders to read from, which needs "
                                "the fs:read capability its manifest does not declare")
        wanted = [str(one or "").strip() for one in paths]
        self._roots = tuple(str(Path(one).expanduser().resolve())
                            for one in wanted if one)


class ExtensionUI:
    """Guided tasks an extension offers, for core to put in front of somebody.

    Declared rather than drawn. An extension that painted its own page would tie the
    Console's look to whoever wrote it, and would stop working the moment that extension
    moved out of this process - where a task described as data still does. Core owns the
    treatment; the extension owns what is asked and what happens.

    Each task is three calls on the extension's own router, under the base it names:
    the form to ask with, a check that says what would happen, and a start that answers
    with a job. The shape is fixed at three because the thing being described is one
    thing - a guided job - and a general language for drawing anything is a different
    project.
    """

    def __init__(self, name: str, allowed: bool) -> None:
        self._name = name
        self._allowed = allowed
        self.tasks: list[dict] = []

    def task(self, key: str, label: str, base: str, description: str = "",
             confirm: str = "") -> None:
        if not self._allowed:
            raise ContractError(f"{self._name} offers a task, which needs the ui:mount "
                                "capability its manifest does not declare")
        wanted = str(key or "").strip()
        if not wanted:
            raise ContractError(f"{self._name} offers a task with no key")
        self.tasks.append({
            "key": wanted,
            "label": str(label or "").strip() or wanted,
            "description": str(description or "").strip(),
            # What the button says at the point of no return. The task knows what it is
            # about to do; a generic "Confirm" makes every one of them look the same.
            "confirm": str(confirm or "").strip(),
            "base": str(base or "").strip(),
        })


class ExtensionJobs:
    """Slow work, run the way core runs it.

    The kind carries the extension's name, so a job somebody is watching says which
    extension is doing it - the same reason the log namespace does. One at a time per
    kind, which is core's rule and is right here too: two imports of one library at once
    would race each other into the same folders.
    """

    def __init__(self, name: str) -> None:
        self._name = name

    def submit(self, kind: str, work):
        from common import jobs

        return jobs.submit(f"{self._name}.{str(kind or '').strip()}", work)

    def active(self) -> tuple[str, ...]:
        from common import jobs

        return tuple(job.id for job in jobs.active()
                     if job.kind.startswith(f"{self._name}."))


class ExtensionContext:
    """What `register(ctx)` is given."""

    def __init__(self, manifest: Manifest, store: ExtensionStore,
                 on_failure: Callable[[str], None]) -> None:
        self.name = manifest.name
        self.manifest = manifest
        self.logger = logger_for(manifest.name)
        self.config = ExtensionConfig(manifest.name, store)
        self.events = ExtensionEvents(manifest.name, manifest.events, on_failure)
        self.files = ExtensionFiles(manifest.name, "fs:read" in manifest.capabilities)
        self.jobs = ExtensionJobs(manifest.name)
        self.ui = ExtensionUI(manifest.name, "ui:mount" in manifest.capabilities)
        self.games = ExtensionGames(manifest.name, manifest.scopes, self.files)
        self.routers: list[tuple[Any, str]] = []
        # Registration is a moment, not a phase: routers are mounted once, so one added
        # after `register` returned would never be reachable and silently answer nothing.
        self.open = True

    def scope(self, action: str) -> str:
        """The scope for one of this extension's own actions."""
        return f"ext:{self.name}:{str(action or '').strip()}"

    def add_router(self, router: Any, *, scope: str) -> None:
        """Offer routes under `/api/v1/ext/<name>/`, gated on a scope this extension
        declared. Core attaches the gate; the extension cannot choose to have none."""
        if not self.open:
            raise ContractError(f"{self.name} added a router after registering")
        allowed = {self.scope(action) for action in self.manifest.provides}
        if scope not in allowed:
            raise ContractError(
                f"{self.name} gates a router on {scope!r}, which its manifest does not "
                f"provide. Declared: {', '.join(sorted(allowed)) or 'none'}")
        self.routers.append((router, scope))
