"""What a check works out about a source, kept for the steps that follow it.

Holds the library, what sits beside each game file and each file's size. A check that
starts from the first step reads afresh, and nothing is kept longer than `KEPT` seconds.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .plan import file_bytes
from .source import SourceLibrary

KEPT = 600.0
MEASURING_THREADS = 16


class Progress:
    """Where a check or a run has got to, for whoever is asking while it goes."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._now: dict[str, object] = {"stage": "", "message": "", "done": 0, "total": 0}

    def stage(self, stage: str, message: str, total: int = 0) -> None:
        with self._lock:
            self._now = {"stage": stage, "message": message, "done": 0, "total": total}

    def advance(self, done: int) -> None:
        with self._lock:
            self._now = {**self._now, "done": done}

    def clear(self) -> None:
        self.stage("", "")

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return dict(self._now)


class Held:
    """The last source read, and what was worked out about it."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._key: tuple[str, str, str] | None = None
        self._at = 0.0
        self.library: SourceLibrary | None = None
        self.companions: dict[str, tuple[str, ...]] = {}
        self._asked: set[str] = set()
        self.sizes: dict[Path, int] = {}

    def library_for(self, key: tuple[str, str, str], fresh: bool = False,
                    ) -> SourceLibrary | None:
        """The library read for this source, if one was and is still worth trusting."""
        with self._lock:
            if (fresh or self._key != key or self.library is None
                    or time.monotonic() - self._at > KEPT):
                return None
            return self.library

    def keep(self, key: tuple[str, str, str], library: SourceLibrary) -> None:
        with self._lock:
            self._key, self._at, self.library = key, time.monotonic(), library
            self.companions, self._asked, self.sizes = {}, set(), {}

    def forget(self) -> None:
        with self._lock:
            self._key, self.library = None, None
            self.companions, self._asked, self.sizes = {}, set(), {}

    def companions_of(self, table_file: str) -> tuple[str, ...]:
        """What sits beside a game file, as `companions_for` found it. A file it did not
        find is one that is not there."""
        try:
            return self.companions[str(table_file)]
        except KeyError:
            raise FileNotFoundError(table_file) from None

    def remember_companions(self, asked: list[str],
                            found: dict[str, tuple[str, ...]]) -> None:
        with self._lock:
            for path in asked:
                if path in found:
                    self.companions[path] = found[path]
            self._asked.update(asked)

    def unasked(self, paths: list[str]) -> list[str]:
        """The game files not yet looked beside."""
        return [path for path in dict.fromkeys(paths) if path not in self._asked]

    def measured(self, progress: Progress, message: str,
                 ) -> Callable[[list[Path]], dict[Path, int]]:
        """A function that measures files together, remembering what it measured."""
        def measure(paths: list[Path]) -> dict[Path, int]:
            todo = [one for one in dict.fromkeys(paths) if one not in self.sizes]
            if todo:
                progress.stage("measuring", message, len(todo))
            with ThreadPoolExecutor(max_workers=MEASURING_THREADS) as pool:
                for done, (path, size) in enumerate(zip(todo, pool.map(file_bytes, todo),
                                                        strict=True), 1):
                    self.sizes[path] = size
                    if done % 20 == 0:
                        progress.advance(done)
            return {one: self.sizes.get(one, 0) for one in paths}

        return measure
