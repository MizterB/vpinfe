"""The online catalogs that will give you artwork, and what they have for a game.

VPinMediaDB was the first and is not the shape of the feature. A source declares what
it can serve and answers what it holds for one game; this reports all of them together
so a client picks a picture rather than picking a website.

Which sources are asked is a setting. Which exist is not - a source that ships is
always listed, so an install that turned one off can see that it did.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query

from common.extensions import sources as extension_sources
from common.online import asset_sources

from . import models, scopes
from .auth import requires

logger = logging.getLogger("vpinfe.httpapi.mediasources")

router = APIRouter(prefix="/media-sources", tags=["media-sources"])


def _contributed() -> list[dict]:
    return [{"id": source.id, "name": source.name, "url": "",
             "enabled": extension_sources.enabled(source), "kinds": sorted(source.kinds),
             "extension": source.extension, "key": source.key}
            for source in extension_sources.all_sources()]


@router.get("", summary="The online sources this install knows",
            dependencies=[requires(scopes.VPS_READ)])
def list_sources() -> models.MediaSourceList:
    """Every source that ships, and whether it is one of the ones being asked.

    Disabled ones are listed rather than hidden, because "why is that catalog not
    coming up" is answered by seeing it sitting there switched off.
    """
    asked = {source.id for source in asset_sources.sources(asset_sources.enabled_ids())}
    built_in = [{"id": source.id, "name": source.name, "url": source.url,
                 "enabled": source.id in asked, "kinds": sorted(source.kinds)}
                for source in asset_sources.BUILT_IN]
    return models.MediaSourceList.model_validate(
        {"sources": built_in + _contributed()})


@router.get("/changes", summary="Which games' online offers have moved since a version",
            dependencies=[requires(scopes.VPS_READ)])
def get_changes(since: int = Query(0, ge=0)) -> models.MediaSourceChanges:
    """What an open Discovery pane asks about on a timer: an extension's download began,
    finished or needs the person, so the rows it drew for that game are stale."""
    version, moved = extension_sources.changes_since(since)
    return models.MediaSourceChanges(version=version, vps_ids=moved)


@router.get("/offers", summary="What the catalogs have for one game and kind",
            dependencies=[requires(scopes.VPS_READ)])
def get_offers(vps_id: str = Query(...),
               kind: str = Query(...)) -> models.MediaOfferList:
    """Asked per kind, because that is the question a slot has.

    VPS_READ rather than a scope of its own: that scope exists because the call goes
    out to a catalog on the caller's behalf, which is exactly what this is.
    """
    found = asset_sources.offers(kind, vps_id, asset_sources.enabled_ids())
    return models.MediaOfferList.model_validate(
        {"offers": [{"source": offer.source, "name": offer.name, "url": offer.url,
                     "kind": offer.kind, "size": offer.size}
                    for offer in found]})
