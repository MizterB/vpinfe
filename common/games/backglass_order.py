"""The order a table's backglass and score display draw in, kept to what its backglass file
places.

Every table gets a live DMD from the launcher's order. A table whose file places a Score
View DMD is given an order of its own in its settings so that file's art shows with the DMD
on it. The app says what to hold (`launcher_ops.backglass_order`) and this writes it, from
the state the file and the settings are in, so running it again changes nothing. What was
written is recorded (`order_record`), and only a pair still equal to its record is changed
or taken out.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from common import failures, service_errors
from common.games import (
    backglass_ops,
    game_identity,
    game_repository,
    launcher_ops,
    order_record,
)
from common.i18n import t
from common.runtime import jobs, shutdown

logger = logging.getLogger("vpinfe.common.games.backglass_order")

# One pass at a time, whoever starts it: two reading the same table's settings would each
# write over the other's.
_SETTLING = threading.RLock()


def settle(game_id: str, launcher_id: str = "") -> list[dict[str, str]]:
    """Bring the order of each table of the game to what its file places. Answers the
    tables that could not be written, each with why, and never raises for one: the file or
    the settings the caller changed stand either way."""
    game = game_repository.game_by_id(game_id)
    return _settle([game], launcher_id)["failed"] if game is not None else []


def settle_table(table_id: str) -> list[dict[str, str]]:
    """`settle` for the game that holds this table."""
    from common.games.table_identity import find_table_by_id

    found = find_table_by_id(game_repository.all_games(), table_id)
    return _settle([found[0]])["failed"] if found is not None else []


def refuse_while_running() -> None:
    """Refuse, before anything is written, while a pass over the library is still going."""
    if jobs.active(jobs.KIND_BACKGLASS_ORDER):
        raise jobs.JobBusyError(t("error.jobs.order_busy"))


def settle_launcher(launcher_id: str) -> jobs.Job | None:
    """`settle` for every game that has a table this launcher plays, as a job: the library
    is read once and each backglass file only when it has changed. None where a pass was
    started in the moment since `refuse_while_running` said there was none."""
    def work(job: jobs.Job) -> dict[str, Any]:
        return _settle(list(game_repository.catalog().values()), launcher_id, job)

    try:
        return jobs.submit(jobs.KIND_BACKGLASS_ORDER, work)
    except jobs.JobBusyError:
        logger.warning("A pass over the library was already running for %s", launcher_id)
        return None


def _settle(games: Iterable[Any], launcher_id: str = "",
            job: jobs.Job | None = None) -> dict[str, Any]:
    """A table is looked at only where its file places a Score View DMD or a record says
    this wrote its order; every other table has nothing to bring or take back."""
    games = list(games)
    written: list[str] = []
    failed: list[dict[str, str]] = []
    with _SETTLING:
        record = order_record.held()
        changes: dict[str, dict[str, str]] = {}
        for index, game in enumerate(games):
            if shutdown.requested():
                break
            if job is not None:
                job.reporter().progress(index, len(games), t("said.table_order"))
            try:
                tables = backglass_ops.score_dmds(game, launcher_id)
            except (service_errors.ServiceError, OSError):
                logger.exception("Could not read the backglass files of %s",
                                 game_identity.game_id(game))
                continue
            for one in tables:
                kept = record.get(one.table, {})
                if not (one.in_file or kept):
                    continue
                try:
                    order = launcher_ops.backglass_order(one.launcher, one.file, one.in_file,
                                                         kept)
                    if order.write:
                        launcher_ops.write_table_settings(one.table, order.write, settle=False)
                        written.append(one.table)
                except (service_errors.ServiceError, OSError) as exc:
                    logger.warning("Could not set the draw order of table %s: %s", one.table,
                                   failures.why(exc))
                    failed.append({"table": one.table, "name": Path(one.file).name,
                                   "reason": failures.why(exc)})
                    continue
                if order.ours != kept:
                    changes[one.table] = order.ours
        order_record.keep(changes)
    if job is not None:
        job.problems = len(failed)
    return {"games": len(games), "written": written, "failed": failed}
