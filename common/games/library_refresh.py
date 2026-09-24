"""Bringing what VPinFE knows in line with what is on disk.

Three passes, and the order is the point: re-read the folders, reconcile the tables each
one holds, then read the ones nothing has read. Discovery works from the listing the scan
took, so without the re-read in front of it a second run finds what the first one did.

Refresh, not scan: `POST /library/scan` already means the VPSdb rebuild.
"""

from __future__ import annotations

import logging
import threading

from common import jobs, shutdown
from common.games.library_discovery import discover
from common.games.library_enrichment import enrich
from common.games.table_identity import ensure_unique_table_ids
from common.jobs import JobReporter

logger = logging.getLogger("vpinfe.common.games.library_refresh")

_stop = threading.Event()
_ticker: threading.Thread | None = None


def refresh(reporter: JobReporter | None = None) -> dict:
    """Reconcile the library, and read whatever that turns up."""
    from common.games import auto_match, game_identity, watching
    from common.games.game_repository import all_games

    if reporter:
        reporter.progress(0, 4, "Reading the library")
    games = all_games(reload=True)
    # Taken straight after the read: any request that reaches the catalog gives these
    # an id, and then nothing can tell they are new.
    unseen = [game for game in games if not game_identity.game_id(game)]

    if reporter:
        reporter.progress(1, 4, "Reconciling tables")
    found = discover(games)
    # Between the halves, not after: this is what makes a discovered entry addressable.
    ensure_unique_table_ids(games)

    if reporter:
        reporter.progress(2, 4, "Matching new games")
    matched = auto_match.match_new(unseen)

    if reporter:
        reporter.progress(3, 4, "Reading new tables")
    read = enrich(games, reporter)

    # Stamped here because this is the pass that knows a game is new. A game added
    # next year must not arrive holding a year of upstream activity it was not around
    # for - and a read path that stamped would make asking the question change it.
    watching.note_games(game_identity.ensure_unique_ids(games))

    result = {"games": len(games), **{f"discovered_{k}": v for k, v in found.items()},
              **{f"enriched_{k}": v for k, v in read.items()},
              **{f"new_{k}": v for k, v in matched.items()}}
    if reporter:
        reporter.progress(4, 4, "Done")
    logger.info("Library refresh: %s games, %s tables found, %s read, %s of %s new "
                "games matched", len(games), found["found"], read["read"],
                matched["matched"], matched["games"])
    return result


def read_at_startup(games: list, unseen: list, reporter: JobReporter | None = None) -> dict:
    """Startup's half of a refresh, after its ids: match the games it found new, then
    read what nothing has read."""
    from common.games import auto_match

    matched = auto_match.match_new(unseen)
    read = enrich(games, reporter)
    return {**{f"enriched_{k}": v for k, v in read.items()},
            **{f"new_{k}": v for k, v in matched.items()}}


def start_periodic(minutes: int) -> None:
    """Refresh every `minutes`, forever. Zero or less never runs, which is the default.

    A tick that finds the library busy is dropped rather than queued: the thing it
    would have done is already being done, and a queue would mean a run for every
    tick that passed while the first one worked.
    """
    global _ticker
    if minutes <= 0 or _ticker is not None:
        return
    _stop.clear()

    def _tick() -> None:
        while not _stop.wait(minutes * 60):
            if shutdown.requested():
                return
            try:
                jobs.submit(jobs.KIND_LIBRARY_SCAN, lambda job: refresh(job.reporter()))
            except jobs.JobBusyError:
                logger.debug("Periodic refresh skipped; the library is busy")
            except Exception:
                logger.exception("Periodic refresh could not start")

    _ticker = threading.Thread(target=_tick, daemon=True, name="library-refresh")
    _ticker.start()
    logger.info("Looking for new tables every %s minutes", minutes)


def stop_periodic() -> None:
    global _ticker
    _stop.set()
    _ticker = None
