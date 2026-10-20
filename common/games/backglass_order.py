"""The order a table's backglass and score display draw in, kept to what its backglass file
places.

Every table gets a live DMD from the launcher's order. A table whose file places a Score
View DMD is given an order of its own in its settings so that file's art shows with the DMD
on it. The app says what to hold (`launcher_ops.backglass_order`); this writes it, from the
state the file and the settings are in, so running it again changes nothing.
"""

from __future__ import annotations

import logging

from common import failures, service_errors
from common.games import backglass_ops, game_repository, launcher_ops

logger = logging.getLogger("vpinfe.common.games.backglass_order")


def settle(game_id: str, launcher_id: str = "") -> list[dict[str, str]]:
    """Bring the order of each table of the game to what its file places. Answers the
    tables that could not be written, each with why, and never raises for one: the file or
    the launcher's settings the caller changed stand either way."""
    failed: list[dict[str, str]] = []
    try:
        wanted = backglass_ops.score_dmds(game_id, launcher_id)
    except (service_errors.ServiceError, OSError):
        logger.exception("Could not read the backglass files of %s", game_id)
        return failed
    for table_id, in_file in wanted.items():
        try:
            values = launcher_ops.backglass_order(table_id, in_file)
            if values:
                launcher_ops.write_table_settings(table_id, values)
        except (service_errors.ServiceError, OSError) as exc:
            logger.warning("Could not set the draw order of table %s: %s", table_id,
                           failures.why(exc))
            failed.append({"table": table_id, "reason": failures.why(exc)})
    return failed


def settle_launcher(launcher_id: str) -> None:
    """`settle` for every game that has a table this launcher plays."""
    for game_id in list(game_repository.catalog()):
        settle(game_id, launcher_id)
