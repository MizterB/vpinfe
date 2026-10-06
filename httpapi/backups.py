"""Every copy VPinFE keeps of a file, over the wire.

A copy is an id the listing gave. Putting one back keeps what it replaces as another copy
and says which, so an undo is the same call on that id.

`common/backups/ops.py` is what answers.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException

from common.backups import ops

from . import scopes
from .auth import requires
from .models import BackupNote, BackupRequest

router = APIRouter(prefix="/backups", tags=["backups"])


@router.get("", summary="Every copy VPinFE has kept",
            dependencies=[requires(scopes.CONFIG_READ)])
def list_backups(of_kind: Literal["game", "launcher", "theme", ""] = "",
                 of: str = "") -> dict[str, Any]:
    """The copies newest first, and the ids of those that go in when VPinFE next closes.
    `of_kind` and `of` narrow it to one game, launcher or theme."""
    if bool(of_kind) != bool(of):
        raise HTTPException(422, "of_kind and of go together")
    return ops.listing(of_kind, of)


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
