"""Every copy VPinFE keeps of a file, over the wire.

A copy is an id the listing gave. Putting one back keeps what it replaces as another copy
and says which, so an undo is the same call on that id.

`common/backups/ops.py` is what answers.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from common.backups import ops

from . import scopes
from .auth import requires
from .models import BackupRequest

router = APIRouter(prefix="/backups", tags=["backups"])


@router.get("", summary="Every copy VPinFE has kept",
            dependencies=[requires(scopes.CONFIG_READ)])
def list_backups() -> dict[str, Any]:
    """The copies newest first, and the ids of those that go in when VPinFE next closes."""
    return ops.listing()


@router.post("", summary="Back up now",
             dependencies=[requires(scopes.CONFIG_WRITE)])
def take_backup(body: BackupRequest) -> dict[str, Any]:
    """One zip of the games, records or settings named, as the copy that lists it."""
    return ops.take(body.scope, game_ids=body.games, launcher_id=body.launcher,
                    note=body.note).as_dict()


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
