"""The play section: plays, high scores and the table chosen to play."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from functools import partial
from typing import Any

from nicegui import ui

from common.failures import why
from common.i18n import t
from manager import ext_groups, pictures
from manager.kit import offload, panel, play_facts, when
from manager.workbench.core import HEADING, _rows, _table_line


def _game_play_rows(context: dict[str, Any]) -> list[tuple[Any, Any]]:
    """The game's own record."""
    return _play_rows(context["game"].get("user") or {})


def _table_play_rows(table: dict[str, Any]) -> list[tuple[Any, Any]]:
    """This file's own record."""
    return _play_rows(table.get("user") or {})


def _play_entries(context: dict[str, Any]) -> list[tuple[Any, Any]]:
    """Under a table both levels show, each under its own heading."""
    chosen = _chosen_table(context)
    if chosen is None:
        return _game_play_rows(context)
    return [(HEADING, t("manager.workbench.game_section")),
            *_game_play_rows(context),
            (HEADING, t("manager.workbench.table_section")),
            *_table_play_rows(chosen)]


def _chosen_table(context: dict[str, Any]) -> dict[str, Any] | None:
    return next((row for row in context["tables"] if row.get("id") == context["lens"]),
                None)


async def _play_block(context: dict[str, Any]) -> None:
    """What has been done with this, the machine's high score table after it, the
    pictures players took, and the groups extensions add."""
    scores = await _high_scores(context)
    shots = await pictures.read(context)
    with ui.column().classes("gap-0 manager-form"):
        _rows(ui, _play_section(context, scores, shots))
        ext_groups.fill(context, "play")


def _play_section(context: dict[str, Any], scores: dict[str, Any],
                  shots: dict[str, Any]) -> list[tuple[Any, ...]]:
    return panel.headed([*_play_entries(context), *_high_score_rows(context, scores),
                         *pictures.rows(context, shots)],
                        t("manager.workbench.game_section"))


async def _high_scores(context: dict[str, Any]) -> dict[str, Any]:
    chosen = _chosen_table(context)
    try:
        return await offload.io(context["library"].high_scores, context["game_id"],
                                str((chosen or {}).get("id") or ""))
    except Exception as exc:  # noqa: BLE001 - the reason belongs on the page
        return {"state": "unreadable", "reason": why(exc), "sections": []}


def _high_score_rows(context: dict[str, Any],
                     scores: dict[str, Any]) -> list[tuple[Any, Any]]:
    """The High Scores group, or nothing where the table has no ROM and no score file."""
    if not scores:
        return []
    tables = context["tables"]
    table: dict[str, Any] = next(
        (row for row in tables if row.get("id") == scores.get("table_id")), {})
    lines: list[tuple[str, str]] = []
    roms = {str(((row.get("dependencies") or {}).get("pinmame") or {}).get("declared") or "")
            for row in tables} - {""}
    if not context["lens"] and table and len(roms) > 1:
        lines.append((t("manager.workbench.high_scores_from",
                        table=_table_line(table, tables)), ""))
    said = HIGH_SCORE_STATES.get(str(scores.get("state") or ""))
    if said is not None:
        text, why_key = said
        lines.append((t(text), t(why_key, rom=str(scores.get("rom") or "")) if why_key
                      else str(scores.get("reason") or "")))
    else:
        clears = bool((table.get("overrides") or {}).get("delete_nvram_on_close"))
        lines.append(_high_scores_read(str(scores.get("read_at") or ""), clears))
    rows: list[tuple[Any, Any]] = [(HEADING, t("manager.workbench.high_scores")),
                                   (panel.LEDE, partial(_high_scores_aside, lines))]
    return rows if said is not None else [*rows, *_high_score_entries(scores)]


def _high_scores_aside(lines: list[tuple[str, str]]) -> None:
    with ui.column().classes("gap-0"):
        for text, hint in lines:
            panel.line(text, hint=hint)


# Each state with nothing to list: its line, and the key of its detail. None for the detail
# the answer carries itself.
HIGH_SCORE_STATES: dict[str, tuple[str, str | None]] = {
    "none": ("manager.workbench.high_scores_none", "manager.workbench.scores_pending"),
    "unsupported": ("manager.workbench.high_scores_unsupported",
                    "manager.workbench.scores_no_map"),
    "unreadable": ("manager.workbench.high_scores_unreadable", None),
}


def _high_scores_read(read_at: str, clears: bool) -> tuple[str, str]:
    """(line, detail)."""
    at = when.parsed(read_at)
    if clears:
        text, hint = t("manager.workbench.high_scores_cleared"), ""
    elif at is None:
        text, hint = t("manager.workbench.scores_undated"), ""
    elif (datetime.now(UTC) - at).total_seconds() < 60:
        text, hint = t("manager.workbench.scores_fresh"), when.local(read_at)
    else:
        text = t("manager.workbench.high_scores_read", when=when.ago(read_at, inline=True))
        hint = when.local(read_at)
    return text, hint


def _high_score_entries(scores: dict[str, Any]) -> list[tuple[Any, Any]]:
    """Rank and New are a column on every row or on none: a row without one would end its
    score somewhere else."""
    sections = scores.get("sections") or []
    entries = [entry for section in sections for entry in section.get("entries") or []]
    columns = {"ranked": any(entry.get("rank") is not None for entry in entries),
               "marked": any(entry.get("new") for entry in entries)}
    at = when.parsed(scores.get("read_at"))
    day = when.day(at.astimezone()) if at else ""
    rows: list[tuple[Any, Any]] = []
    for section in sections:
        for place, entry in enumerate(section.get("entries") or []):
            first, *rest = play_facts.score_lines(entry)
            rows.append((str(section.get("name") or "") if place == 0 else "",
                         _score_row(entry, first, day, **columns)))
            rows.extend((panel.ASIDE, partial(_score_caption, line)) for line in rest)
    return rows


def _score_row(entry: dict[str, Any], value: str, day: str, *, ranked: bool,
               marked: bool) -> Callable[[], None]:
    def draw() -> None:
        with ui.element("div").classes("manager-score-row"):
            if ranked:
                rank = entry.get("rank")
                ui.label("" if rank is None else str(rank)).classes("manager-score-rank")
            ui.label(str(entry.get("initials") or "")) \
                .classes("manager-score-initials manager-cell-identifier")
            ui.label(value).classes("manager-score-value")
            if marked:
                chip = ui.label(t("manager.workbench.high_scores_new")) \
                    .classes("manager-tier manager-tier--off manager-score-new")
                if entry.get("new"):
                    chip.tooltip(t("manager.workbench.scores_dated", day=day))
                else:
                    chip.classes(add="manager-score-new--held")

    return draw


def _score_caption(line: str) -> None:
    ui.label(line).classes("manager-help")


def _play_rows(record: dict[str, Any]) -> list[tuple[Any, Any]]:
    """What has been done with this."""
    return [
        (t("word.last_played"), play_facts.played_when(record.get("last_played"))),
        (t("manager.workbench.times_played"),
                str(int(record.get("play_count") or 0) or t("word.never"))),
        (t("manager.workbench.play_time"),
                play_facts.played_for(int(record.get("play_time_seconds") or 0))),
    ]
