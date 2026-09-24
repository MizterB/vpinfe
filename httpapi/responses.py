"""Responses several routers need to send, shaped the same way each time."""

from __future__ import annotations

from pathlib import Path

from fastapi import Query
from starlette.requests import Request
from starlette.responses import FileResponse, Response

from common.games import sized_media
from common.games.sized_media import Served

FOREVER = "public, max-age=31536000, immutable"

ART_SIZE = Query(None, description="The longest edge in pixels, for an image: "
                                   + " or ".join(str(one) for one in sized_media.SIZES))
ART_VERSION = Query("", description="The `version` the listing gave; a match is kept "
                                    "for good")


def art_file(served: Served, request: Request, sent_version: str) -> Response:
    """Kept for good when the address names the file's current version, and asked
    about every time otherwise."""
    if sent_version and sent_version == served.version:
        return FileResponse(served.path, headers={"Cache-Control": FOREVER})
    return revalidating_file(served.path, request)


def revalidating_file(path: Path, request: Request) -> Response:
    """A file that is always asked about and rarely re-sent.

    These URLs name a slot rather than a file, so a replacement changes the bytes
    behind an unchanged address; without `no-cache` a browser guesses freshness from
    Last-Modified and can serve stale art for days.

    The 304 is not optional with it. Starlette answers conditional requests only from
    `StaticFiles`, so a bare `FileResponse` re-sends the whole file every time - which
    on a media map of thirteen tiles turns "sometimes stale" into megabytes per draw.
    """
    # Stat here and hand it over: FileResponse only fills in etag and last-modified
    # when it is given one, otherwise they appear while the response is being sent -
    # too late to compare against.
    response = FileResponse(path, stat_result=path.stat(),
                            headers={"Cache-Control": "no-cache"})
    sent = request.headers.get("if-none-match") if request is not None else ""
    etag = response.headers.get("etag", "")
    if sent and etag and etag in [tag.strip().removeprefix("W/")
                                  for tag in sent.split(",")]:
        return Response(status_code=304,
                        headers={"Cache-Control": "no-cache", "ETag": etag})
    return response
