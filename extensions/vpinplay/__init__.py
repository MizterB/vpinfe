"""VPinPlay's cumulative rating, contributed to every entry.

Core makes the call. This used to be the browser's job - the endpoint was handed to the
page and every window on a cabinet asked the same question about the same game, losing
the answers on each reload. A theme reads `entry.ext.vpinplay`, and `item.vpinplay` is
still written from it for the themes that were built before there was an `ext` slot.

Only the rating. Signing in, submitting a score and syncing on exit are still core's, and
they move when this much has been run on a real cabinet.
"""

from __future__ import annotations

from . import client

# What the setting is called here. Core handed it over from its own configuration when
# this extension first loaded, so an install that was already using VPinPlay finds it
# already set.
ENDPOINT_KEY = "endpoint"

# Where VPinPlay lives unless somebody has said otherwise. The same default core carried,
# so an install that never changed it needs nothing handed over at all.
DEFAULT_ENDPOINT = "https://api.vpinplay.com:8888"


def register(ctx) -> None:
    def rating_for(game):
        """What VPinPlay says about one game, or None.

        Keyed on the catalog id, because that is what VPinPlay knows a table by. A game
        no catalog has matched has nothing to ask about, which is not a failure.
        """
        vps_id = str(game.get("vps_id") or "").strip()
        if not vps_id:
            return None
        endpoint = ctx.config.get(ENDPOINT_KEY, "") or DEFAULT_ENDPOINT
        return client.fetch(endpoint, vps_id)

    ctx.entries.contribute("vpinplay", rating_for)
    ctx.logger.info("Contributing ratings from %s",
                    ctx.config.get(ENDPOINT_KEY, "") or DEFAULT_ENDPOINT)
