"""Every copy VPinFE keeps of a file, over the wire.

A copy is an id the listing gave. Putting one back keeps what it replaces as another copy
and says which, so an undo is the same call on that id.

`common/backups/ops.py` is what answers.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException

from common import lifecycle
from common.backups import going_back, ops
from common.host import action_ops

from . import scopes
from .auth import requires
from .models import BackupNote, BackupRequest

router = APIRouter(prefix="/backups", tags=["backups"])


@router.get("", summary="Every copy VPinFE has kept",
            dependencies=[requires(scopes.CONFIG_READ)])
def list_backups(subject_kind: Literal["game", "launcher", "theme", ""] = "",
                 subject_id: str = "") -> dict[str, Any]:
    """The copies newest first, and the ids of those that go in when VPinFE next closes.
    `subject_kind` and `subject_id` narrow it to one game, launcher or theme."""
    if bool(subject_kind) != bool(subject_id):
        raise HTTPException(422, "subject_kind and subject_id go together")
    return ops.listing(subject_kind, subject_id)


def _quit_for_2x() -> None:
    """A request left behind by a quit that did not happen would turn the next ordinary exit
    into going back."""
    try:
        quit_done = action_ops.perform(lifecycle.VPINFE, lifecycle.STOP, "going back to 2.x")
    except Exception:
        going_back.clear()
        raise
    if not quit_done:
        going_back.clear()


@router.get("/going-back", summary="What going back to 2.x would put back",
            dependencies=[requires(scopes.CONFIG_READ)])
def going_back_plan() -> dict[str, Any]:
    """`games` is how many hold a 2.x copy and `collections` whether yours do."""
    return going_back.plan()


@router.post("/going-back", summary="Go back to 2.x",
             dependencies=[requires(scopes.SYSTEM_ADMIN)])
def go_back_to_2x(background: BackgroundTasks) -> dict[str, Any]:
    """Quit VPinFE, and put back each game's newest 2.x copy and the 2.x collections as it
    exits. Nothing is deleted: what is replaced is kept as a copy. Refused with `400` where
    there is no 2.x copy. Answers with what will be put back, and VPinFE quits after the
    answer."""
    action_ops.check(lifecycle.VPINFE, lifecycle.STOP)
    found = going_back.request()
    background.add_task(_quit_for_2x)
    return found


@router.post("", summary="Back up now",
             dependencies=[requires(scopes.CONFIG_WRITE)])
def take_backup(body: BackupRequest) -> dict[str, Any]:
    """One zip of the games, records or settings named, as the copy that lists it. A blank
    `name` is left to the listing, which calls the backup after what it holds."""
    return ops.take(body.scope, game_ids=body.games, launcher_id=body.launcher,
                    note=body.note, name=body.name).as_dict()


@router.patch("/{copy_id}", summary="Change a backup's note",
              dependencies=[requires(scopes.CONFIG_WRITE)])
def change_note(copy_id: str, body: BackupNote) -> dict[str, Any]:
    """The backup as listed, with its new note. Only a backup from `POST /backups` has one;
    a file in it and a copy VPinFE took are refused with `400`."""
    return ops.set_note(copy_id, body.note).as_dict()


@router.post("/{copy_id}/restore", summary="Put a copy back",
             dependencies=[requires(scopes.CONFIG_WRITE)])
def restore_backup(copy_id: str) -> dict[str, Any]:
    """The copy, what it replaced as `kept`, whether the restore waits on a close, and what a
    backup had nowhere to put as `skipped`."""
    return ops.restore(copy_id).as_dict()


@router.delete("/{copy_id}", summary="Delete a copy",
               dependencies=[requires(scopes.CONFIG_WRITE)])
def delete_backup(copy_id: str) -> dict[str, Any]:
    return ops.delete(copy_id).as_dict()
