"""Discovery: the front page, in one read.

What `/library/discovery` answers is every catalog entry; this answers the shelves a front
page draws from them, cut to what a row of tiles shows, from the last comparison. The
gaps a source can fill are the library's games now and the index the fill uses as the
process already holds it; this read makes no request.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from common.games import library_ops

from . import models, scopes
from .auth import requires

router = APIRouter(prefix="/discovery", tags=["discovery"])

# The longest window a shelf looks back over. The page offers a week, two and a month.
MOST_DAYS = 366


@router.get("/home", summary="Discovery's front page",
            dependencies=[requires(scopes.GAMES_READ)])
def discovery_home(days: int = Query(7, ge=1, le=MOST_DAYS)) -> models.DiscoveryHome:
    """New in the last `days`, the authors whose work the library holds, and the games that
    lack a kind VPS lists. Never compared here: `counted` empty means the library has not
    been, and nothing then reads as held or lacking."""
    return models.DiscoveryHome.model_validate(library_ops.discovery_home(days))
