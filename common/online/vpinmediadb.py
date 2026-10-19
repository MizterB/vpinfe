"""VPinMediaDB, the catalog of pictures and videos, as a source.

One JSON manifest for everything it publishes, held whole so every size it carries can be
offered rather than the one the display happens to be set to. The URL never comes from a
caller: the source makes its own, which is what stops this being a way to make an install
fetch whatever somebody asks it to.
"""

from __future__ import annotations

from common.online import vpsdb_media
from common.online.sources import Offer, Source

ID = "vpinmediadb"

_MANIFEST: dict | None = None


def _manifest() -> dict:
    """The index, fetched once per process and kept.

    One file for the whole catalog, so re-fetching it per request would be a round
    trip to learn nothing. A failed fetch caches nothing and the next caller retries.
    """
    global _MANIFEST
    if _MANIFEST is None:
        from common.online.vpsdb_cache import VPinMediaDatabase
        _MANIFEST = VPinMediaDatabase(vpsdb_media.MANIFEST_URL).load()
    return _MANIFEST or {}


def refresh_manifest(fetched: dict | None = None) -> None:
    """Read the index again, or take `fetched`, a copy the caller has just read. A failed
    read keeps the copy already held."""
    global _MANIFEST
    from common.online.vpsdb_cache import VPinMediaDatabase

    fresh = fetched or VPinMediaDatabase(vpsdb_media.MANIFEST_URL).load()
    if fresh:
        _MANIFEST = fresh


def _offers(who: dict, kind: str) -> list[Offer]:
    found = vpsdb_media.offered(_manifest(), str(who.get("vps_id") or "")).get(kind) or []
    return [Offer(source=ID, name=str(item["url"]).rsplit("/", 1)[-1], url=item["url"],
                  kind=kind, size=item.get("size", ""), md5=item.get("md5", ""))
            for item in found]


SOURCE = Source(
    id=ID, name="VPinMediaDB", url="https://github.com/superhac/vpinmediadb",
    kinds=frozenset(vpsdb_media.MANIFEST_KINDS), offers=_offers,
    automatic=(("updates", "get_media_for_new_games"),
               ("updates", "update_downloaded_media")),
    reachable=lambda: bool(_manifest()))
