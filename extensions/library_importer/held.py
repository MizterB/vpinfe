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

from .beside import Beside
from .plan import file_bytes
from .saved import Saved
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
        # The ROM each game file names, by path, and the files already asked about:
        # reading one means opening the table, so each is read once per library.
        self.roms: dict[str, str] = {}
        self._roms_asked: set[str] = set()
        # Which of the saved names each game file's script mentions, for the names asked.
        # A different list is a different question, so the files are read again.
        self.named: dict[str, tuple[str, ...]] = {}
        self._names: tuple[str, ...] = ()
        self._saved: dict[str, Saved] = {}
        self.name_maps: dict[str, Beside] = {}
        # What the look found for each game of one library, by the game's identity, and
        # the state of the catalog it looked in. Kept with the library it was made for.
        self.look: tuple[SourceLibrary, dict, dict[int, dict]] | None = None
        self._asked_about: tuple | None = None
        self.generation = 0
        # The rows of games already in the library that the person ticked with that game
        # showing as one, which a Matches pick does not stand for. Per generation.
        self.deliberate: set[str] = set()

    def asked_about(self, scope: tuple) -> int:
        """Which generation of the Tables and Matches answers belongs to `scope`.

        The wizard keeps an answer under its field key and never replaces it, so answers
        given about one source or set of systems would carry over to the next. Asking
        about something else moves to a new key, and so to the page's own defaults.
        """
        with self._lock:
            if self._asked_about is not None and scope != self._asked_about:
                self.generation += 1
                self.deliberate = set()
            self._asked_about = scope
            return self.generation

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
            self.roms, self._roms_asked = {}, set()
            self.named, self._names, self._saved = {}, (), {}
            self.name_maps = {}
            self.look = None

    def forget(self) -> None:
        with self._lock:
            self._key, self.library = None, None
            self.companions, self._asked, self.sizes = {}, set(), {}
            self.roms, self._roms_asked = {}, set()
            self.named, self._names, self._saved = {}, (), {}
            self.name_maps = {}
            self.look = None

    def remember_look(self, library: SourceLibrary, catalog: dict,
                      looked: dict[int, dict]) -> None:
        """Keep a look only while `library` is the one held: the look is keyed by the
        identity of its games, and a library read since has other games."""
        with self._lock:
            if self.library is library:
                self.look = (library, catalog, looked)

    def look_of(self, library: SourceLibrary) -> tuple[dict, dict[int, dict]] | None:
        with self._lock:
            if self.look is not None and self.look[0] is library:
                return self.look[1], self.look[2]
            return None

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

    def remember_roms(self, asked: list[str], found: dict[str, str],
                      named: dict[str, tuple[str, ...]] | None = None) -> None:
        with self._lock:
            self.roms.update(found)
            self.named.update(named or {})
            self._roms_asked.update(asked)

    def saved_in(self, folder: str, read: Callable[[str], Saved]) -> Saved:
        """What the folder of saved files holds, read once per library."""
        with self._lock:
            found = self._saved.get(folder)
        if found is None:
            found = read(folder)
            with self._lock:
                self._saved[folder] = found
        return found

    def ask_for(self, names: tuple[str, ...]) -> None:
        """Note which names the scripts are read for. A different list is read again."""
        with self._lock:
            if names != self._names:
                self._names = names
                self.named = {}
                self._roms_asked = set()

    def unread_roms(self, paths: list[str]) -> list[str]:
        """The game files whose ROM has not been read."""
        return [path for path in dict.fromkeys(paths) if path not in self._roms_asked]

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
