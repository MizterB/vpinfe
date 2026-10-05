"""What a client does with a kept copy: list them, put one back, delete one.

A copy is named by the id the listing gave. Nothing here believes a path it was not given
by `places.find`, so an id built by hand reaches nothing.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from common import service_errors
from common.failures import why
from common.games import (
    config_backups,
    game_repository,
    info_maintenance,
    launcher_ops,
    launchers,
)
from common.games.info_migration import copied_from
from common.host import launch_state
from common.i18n import t
from common.jobs import KIND_LIBRARY_SCAN, track

from . import pending, places
from .copies import (
    PLACE_BESIDE,
    PLACE_GAME,
    PLACE_LAUNCHER,
    PLACE_RECORDS,
    PLACE_THEME,
    PLACE_VPX_2X,
    Copy,
    make_id,
    read_id,
)


@dataclass(frozen=True)
class Restored:
    """`kept` is the copy of what the restore replaced, so putting it back is another
    restore of that id. `pending` is a restore that waits for VPinFE to close."""

    copy: Copy
    kept: Copy | None
    pending: bool

    def as_dict(self) -> dict[str, Any]:
        return {"copy": self.copy.as_dict(),
                "kept": self.kept.as_dict() if self.kept else None,
                "pending": self.pending}


def listing() -> dict[str, Any]:
    return {"copies": [one.as_dict() for one in places.scan()],
            "pending": [make_id(PLACE_RECORDS, path) for path in pending.held().values()]}


def _found(copy_id: str) -> Copy:
    one = places.find(copy_id)
    if one is None:
        raise service_errors.NotFoundError(t("error.backups.gone"))
    return one


def _kept_copy(path: str | None, place: str) -> Copy | None:
    return places.find(make_id(place, path)) if path else None


def _while_nothing_plays() -> None:
    if launch_state.current().launching:
        raise service_errors.BlockedError(t("error.backups.playing"))


def restore(copy_id: str) -> Restored:
    one = _found(copy_id)
    place, path = read_id(copy_id) or ("", Path())
    if place == PLACE_GAME:
        return _restore_game(one, path)
    if place == PLACE_RECORDS:
        return _restore_record(one, path)
    if place == PLACE_THEME:
        return _restore_theme(one, path)
    return _restore_launcher(one, place, path)


def _restore_game(one: Copy, path: Path) -> Restored:
    folder = path.parent
    target = folder / f"{folder.name}.info"
    try:
        with track(KIND_LIBRARY_SCAN):
            kept = info_maintenance.restore_file(target, path, keep_id=True)
    except ValueError as exc:
        raise service_errors.RefusedError(why(exc)) from exc
    game_repository.refresh_games()
    return Restored(one, _kept_copy(kept, PLACE_GAME), False)


def _restore_record(one: Copy, path: Path) -> Restored:
    target = copied_from(path)
    pending.add(target, path)
    return Restored(one, None, True)


def _launcher_of(one: Copy) -> launchers.Launcher:
    found = launchers.get_launcher_store().get(one.of_id)
    if found is None:
        raise service_errors.NotFoundError(t("error.backups.no_owner", name=one.of_name))
    return found


def _restore_launcher(one: Copy, place: str, path: Path) -> Restored:
    _while_nothing_plays()
    owner = _launcher_of(one)
    files = launcher_ops.config_files(owner)
    if place == PLACE_LAUNCHER:
        try:
            safety = config_backups.restore(owner.launcher_id, path.name, files,
                                            owner.display_name, home=path.parent)
        except FileNotFoundError as exc:
            raise service_errors.NotFoundError(why(exc)) from exc
        except ValueError as exc:
            raise service_errors.RefusedError(why(exc)) from exc
        return Restored(one, _kept_copy(safety.path if safety else None, PLACE_LAUNCHER),
                        False)
    target = _target_for_aside(place, path, files)
    if target is None:
        raise service_errors.RefusedError(t("error.launchers.copy_unmatched"))
    kept = info_maintenance.restore_file(target, path)
    return Restored(one, _kept_copy(kept, PLACE_BESIDE), False)


def _target_for_aside(place: str, path: Path, files: dict[str, str]) -> Path | None:
    if place == PLACE_VPX_2X:
        found = places.INI_2X_NAME.match(path.stem)
        stem = found.group("stem") if found else path.stem
        return next((Path(held).expanduser() for held in files.values()
                     if Path(held).expanduser().stem == stem), None)
    return config_backups.target_for(path, files)


def _restore_theme(one: Copy, path: Path) -> Restored:
    """Swap the theme with its `.previous` folder, so each is the other's undo."""
    live = path.parent / one.of_id
    if not live.exists():
        os.rename(path, live)
        return Restored(one, None, False)
    parked = Path(tempfile.mkdtemp(prefix=".swapping-", dir=path.parent))
    parked.rmdir()
    os.rename(live, parked)
    os.rename(path, live)
    os.rename(parked, path)
    with contextlib.suppress(OSError):
        os.utime(path)
    return Restored(one, _kept_copy(str(path), PLACE_THEME), False)


def delete(copy_id: str) -> Copy:
    one = _found(copy_id)
    place, path = read_id(copy_id) or ("", Path())
    if place == PLACE_THEME:
        shutil.rmtree(path)
    else:
        path.unlink()
    pending.drop(path)
    return one

