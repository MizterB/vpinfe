"""The draw order this install wrote into tables' own settings, by table id.

A rank in a table's settings looks the same whoever put it there, so what was written is
kept here, in STATE_DIR: it belongs to this install's tables and never goes into the table's
folder. Only a pair still equal to its record is taken back.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Mapping
from typing import Any

from common.atomic_write import write_atomic
from common.config.paths import STATE_DIR

logger = logging.getLogger("vpinfe.common.games.order_record")

PATH = STATE_DIR / "draw_order.json"
SCHEMA = 1

_LOCK = threading.Lock()


def _load() -> dict[str, dict[str, str]]:
    try:
        data = json.loads(PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception:
        logger.warning("Could not read %s; treating it as empty", PATH)
        return {}
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        return {}
    return {str(table): {str(key): str(value) for key, value in (pair or {}).items()}
            for table, pair in (data.get("tables") or {}).items() if pair}


def held() -> dict[str, dict[str, str]]:
    """What was written, by table id. A table nothing was written for is absent."""
    with _LOCK:
        return _load()


def keep(changes: Mapping[str, Mapping[str, str]]) -> None:
    """Replace the record of each table named; an empty pair takes the table out. The file
    is held against another writer for the whole read-modify-write."""
    if not changes:
        return
    with _LOCK:
        record: dict[str, Any] = dict(_load())
        for table, pair in changes.items():
            if pair:
                record[str(table)] = dict(pair)
            else:
                record.pop(str(table), None)
        PATH.parent.mkdir(parents=True, exist_ok=True)
        try:
            write_atomic(PATH, lambda out: json.dump({"schema": SCHEMA, "tables": record},
                                                     out, indent=2))
        except Exception:
            logger.exception("Could not write %s", PATH)
