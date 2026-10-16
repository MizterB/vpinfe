"""A machine's high score table, read again when somebody looks at it.

The launch reads the table after every game. A game played outside VPinFE, or a score file
copied in, leaves the file newer than the read, and the file's own time is what says so.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from common import service_errors
from common.failures import why
from common.games import em_scores, game_lens, high_scores, score_parser
from common.games.game import Game
from common.games.game_metadata import default_table, load_game_meta, persist_game_meta
from common.games.game_repository import reread_game
from common.games.tables import TABLE_ID_KEY, table_entries
from common.i18n import t
from common.timestamps import iso_to_epoch, utc_now_iso

logger = logging.getLogger("vpinfe.common.games.high_score_reads")


def for_game(game_id: str) -> dict[str, Any] | None:
    """The default table's, whose ROM a launch of the game plays."""
    game = game_lens.game_or_refuse(game_id)
    _name, entry = default_table(load_game_meta(game))
    return look(game, entry)


def for_table(game_id: str, table_id: str) -> dict[str, Any] | None:
    game = game_lens.game_or_refuse(game_id)
    entry = table_entries(load_game_meta(game)).get(table_id)
    if entry is None:
        raise service_errors.NotFoundError(t("error.games.table_not_found"),
                                           details={"table": table_id})
    return look(game, entry)


def look(game: Game, entry: dict[str, Any]) -> dict[str, Any] | None:
    """What can be shown for `entry`'s machine, as `high_scores.shown` gives it, or None
    where there is nothing to show and nothing a game would change."""
    rom = high_scores.rom_of(entry)
    game_dir = str(game.full_path_game or "")
    source = _score_file(rom, game_dir) if rom else None
    found = None
    if source is None and not (rom and em_scores.in_the_map(rom)):
        found = em_scores.find(game, entry)
        source = str(found.path) if found else None
    key = rom or (found.path.name if found else "")
    if not key:
        return None
    table_id = str(entry.get(TABLE_ID_KEY, "") or "")
    held = high_scores.kept(load_game_meta(game), key)

    if source and _newer(source, held):
        try:
            parsed, path = em_scores.read_with_source(game, entry)
            reading = score_parser.result_to_jsonable(key, parsed, path, "")
        except KeyError:
            return high_scores.shown(key, table_id, None, state=high_scores.UNSUPPORTED)
        except Exception as exc:  # noqa: BLE001 - the reason is the answer
            logger.warning("Could not read the high scores of %s for %s: %s", key,
                           game.game_dir_name, exc)
            return high_scores.shown(key, table_id, held, state=high_scores.UNREADABLE,
                                     reason=why(exc))
        if not reading:
            return high_scores.shown(key, table_id, None, state=high_scores.NONE_YET)
        held = high_scores.record(reading, high_scores.as_reading(held), utc_now_iso())
        _keep(game, key, held)

    if held is not None:
        return high_scores.shown(key, table_id, held)
    if source is None and not em_scores.in_the_map(key):
        return None
    return high_scores.shown(key, table_id, None, state=high_scores.NONE_YET)


def _score_file(rom: str, game_dir: str) -> str | None:
    try:
        return score_parser.resolve_score_input_path(rom, game_dir)
    except (FileNotFoundError, KeyError):
        return None


def _newer(path: str, held: dict[str, Any] | None) -> bool:
    read_at = iso_to_epoch((held or {}).get("read_at"))
    if read_at is None:
        return True
    try:
        return os.path.getmtime(path) > read_at
    except OSError:
        return False


def _keep(game: Game, rom: str, held: dict[str, Any]) -> None:
    config = load_game_meta(game)
    high_scores.keep(config, rom, held)
    persist_game_meta(game, config)
    reread_game(game)
    logger.info("Read the high scores of %s for %s again: the score file was newer",
                rom, game.game_dir_name)
