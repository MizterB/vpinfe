"""Where a `.directb2s` file places the DMD, written back into the file.

The file is the one the backglass server reads for every table that uses it, so a change
is refused while a table of the game is playing or the file is read-only, and is written
beside the file and renamed over it. Changes to one file run one at a time. Each change
keeps the bytes it put in and took out for one undo, in a journal bounded by count and by
size.
"""

from __future__ import annotations

import contextlib
import hashlib
import itertools
import os
import secrets
import stat
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from common import atomic_write, service_errors
from common.games import asset_lens, file_move, game_lens
from common.games.formats import directb2s_displays
from common.i18n import t
from common.media import sized_media

SUFFIX = ".directb2s"
_KEPT = 32
_MAX_BYTES = 8 * 1024 * 1024


@dataclass
class _Done:
    game_id: str
    key: str
    path: str
    serial: int
    change: directb2s_displays.Splice
    after: bytes

    @property
    def size(self) -> int:
        return len(self.change.removed) + len(self.change.inserted)


# Changes that can still be undone, oldest first. `_lock` guards it and `_file_locks`.
_done: OrderedDict[str, _Done] = OrderedDict()
_lock = threading.Lock()
_file_locks: dict[str, threading.Lock] = {}
_serials = itertools.count(1)


def _digest(data: bytes) -> bytes:
    return hashlib.blake2b(data, digest_size=16).digest()


def _file_lock(target: Path) -> threading.Lock:
    with _lock:
        return _file_locks.setdefault(os.path.realpath(target), threading.Lock())


def _target(game_dir: Path, path: str) -> Path:
    target = asset_lens.inside(game_dir, path)
    if target.suffix.lower() != SUFFIX:
        raise service_errors.RefusedError(t("error.backglass.not_a_backglass"),
                                          details={"path": path})
    if not target.is_file():
        raise service_errors.NotFoundError(t("error.assets.no_such_file", path=path),
                                           details={"path": path})
    return target


def _open_for_writing(game: Any, game_id: str, target: Path, path: str) -> None:
    """Called with the file's lock held."""
    if file_move.playing(game, game_id):
        raise service_errors.BlockedError(t("error.backglass.playing"))
    if not target.stat().st_mode & stat.S_IWRITE:
        raise service_errors.BlockedError(t("error.backglass.read_only"),
                                          details={"path": path})


def _write(target: Path, data: bytes) -> None:
    mode = stat.S_IMODE(target.stat().st_mode)
    with atomic_write.staged_for(target) as staged:
        with staged.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    with contextlib.suppress(OSError):
        os.chmod(target, mode)


def _answer(data: bytes, target: Path, token: str, refused: str = "") -> dict[str, Any]:
    return {"displays": [{"target": one.target, "x": one.placement.x, "y": one.placement.y,
                          "w": one.placement.w, "h": one.placement.h}
                         for one in directb2s_displays.read(data) if not one.source],
            "version": sized_media.version(target) or "", "undo": token,
            "undo_refused": refused}


def _keep(done: _Done) -> str:
    """Journal a change and return its token, or "" where it is too big to keep."""
    if done.size > _MAX_BYTES:
        return ""
    token = secrets.token_urlsafe(9)
    with _lock:
        _done[token] = done
        while len(_done) > _KEPT or sum(one.size for one in _done.values()) > _MAX_BYTES:
            _done.popitem(last=False)
    return token


def place(game_id: str, path: str, target_name: str,
          box: tuple[int | None, int | None, int | None, int | None]) -> dict[str, Any]:
    """Set the DMD of one window (`Backglass` or `ScoreView`) to `box`, which is x, y, width
    and height, or take it out when all four are None. The file keeps every other byte it
    had. Returns the DMDs the file now places, its new version, the token that undoes this
    change and, where no token could be kept, why (`too_large`)."""
    if any(one is None for one in box) and not all(one is None for one in box):
        raise service_errors.RefusedError(t("error.backglass.displays_incomplete"))
    where = None if box[0] is None else directb2s_displays.Placement(*box)  # type: ignore[arg-type]
    if where is not None and not (
            0 <= where.x <= directb2s_displays.LIMIT and 0 <= where.y <= directb2s_displays.LIMIT
            and 1 <= where.w <= directb2s_displays.LIMIT
            and 1 <= where.h <= directb2s_displays.LIMIT):
        raise service_errors.RefusedError(t("error.backglass.displays_range"))
    game = game_lens.game_for_writing(game_id)
    target = _target(Path(game.full_path_game or ""), path)
    with _file_lock(target):
        _open_for_writing(game, game_id, target, path)
        data = target.read_bytes()
        try:
            changed = directb2s_displays.place(data, target_name, where)
        except directb2s_displays.DisplaysError:
            raise service_errors.RefusedError(t("error.backglass.displays_unwritable"),
                                              details={"path": path}) from None
        if changed == data:
            return _answer(data, target, "")
        _write(target, changed)
        done = _Done(game_id, os.path.realpath(target), path, next(_serials),
                     directb2s_displays.splice_of(data, changed), _digest(changed))
        token = _keep(done)
        return _answer(changed, target, token, "" if token else "too_large")


def undo(game_id: str, token: str) -> dict[str, Any]:
    """Take back the change with this token, byte for byte. A change can be undone once,
    only while the file is as that change left it, and not after the server restarts. One
    followed by a newer change to the same file is refused until the newer is undone."""
    with _lock:
        done = _done.pop(token, None)
        if done is not None and done.game_id != game_id:
            _done[token] = done
            done = None
    if done is None:
        raise service_errors.NotFoundError(t("error.backglass.displays_expired"))
    try:
        game = game_lens.game_for_writing(game_id)
        target = _target(Path(game.full_path_game or ""), done.path)
        with _file_lock(target):
            _open_for_writing(game, game_id, target, done.path)
            data = target.read_bytes()
            if _digest(data) != done.after:
                with _lock:
                    newer = any(one.key == done.key and one.serial > done.serial
                                for one in _done.values())
                raise service_errors.BlockedError(
                    t("error.backglass.displays_superseded" if newer
                      else "error.backglass.displays_changed"),
                    details={"path": done.path,
                             "reason": "superseded" if newer else "changed"})
            _write(target, done.change.back(data))
    except (service_errors.ServiceError, OSError, directb2s_displays.DisplaysError) as exc:
        with _lock:
            _done[token] = done
        if isinstance(exc, directb2s_displays.DisplaysError):
            raise service_errors.RefusedError(t("error.backglass.displays_unwritable"),
                                              details={"path": done.path}) from None
        raise
    return _answer(target.read_bytes(), target, "")
