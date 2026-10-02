"""This device's folders and files, for a path field's Browse button.

`common/folder_browse.py` decides what is listed and how far it may look.
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Query, Request

from common import folder_browse
from common.i18n import t

from . import models, scopes
from .auth import ForbiddenError, caller_is_local, requires

router = APIRouter(prefix="/folders", tags=["folders"])


@router.get("", summary="This device's folders and files under a path",
            dependencies=[requires(scopes.CONFIG_WRITE)])
def list_folders(request: Request, path: str = Query(""), kind: str = Query("dir"),
                 suffix: list[str] = Query(default=[]),
                 hidden: bool = Query(False)) -> models.FolderListing:
    if not caller_is_local(request):
        raise ForbiddenError(t("error.folders.this_device_only"))
    return models.FolderListing.model_validate(
        folder_browse.listing(path, kind, tuple(suffix), hidden))


@router.post("", summary="Make a folder on this device",
             dependencies=[requires(scopes.CONFIG_WRITE)])
def make_folder(request: Request, body: dict = Body(...)) -> models.FolderListing:
    """The new folder's own listing, so a picker can go straight into it.

    Writes to the disk, so it takes the scope adding a library folder takes - the folder
    is made for the same reason.
    """
    if not caller_is_local(request):
        raise ForbiddenError(t("error.folders.this_device_only"))
    return models.FolderListing.model_validate(
        folder_browse.make_folder(str(body.get("parent") or ""), str(body.get("name") or "")))
