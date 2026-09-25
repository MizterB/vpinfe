"""Get missing art: which kinds, what each would fetch, then the fetch as a job.

The ticks are this browser's and only this dialog reads them. The fill for new games
never does.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from typing import Any, Literal

from nicegui import ui

from common.i18n import t
from common.media_specs import media_label_map
from console import dialog as frame
from console import offload, remembered, verbs
from console.api import ApiClient

TICKS = "art_fill.kinds"
_POLL_S = 1.0
_POLLS = 3600


def ticked(kinds: list[dict[str, Any]], held: dict[str, bool]) -> dict[str, bool]:
    """Which rows start ticked: a kind with nothing to get never is, and one this
    browser has not answered for yet is."""
    return {str(row["kind"]): int(row.get("available") or 0) > 0
            and bool(held.get(str(row["kind"]), True)) for row in kinds}


def remember(held: dict[str, bool], chosen: dict[str, bool],
             kinds: list[dict[str, Any]]) -> dict[str, bool]:
    """`held` with the answers given now. A dimmed row was not answered, so what was
    held for it stays."""
    open_rows = {str(row["kind"]) for row in kinds if int(row.get("available") or 0)}
    return {**held, **{kind: on for kind, on in chosen.items() if kind in open_rows}}


def outcome(result: dict[str, Any]) -> tuple[str, Literal["positive", "warning", "info"]]:
    """What the fill says when it ends, and the notice type to say it with."""
    got, failed = int(result.get("filled") or 0), int(result.get("failed") or 0)
    if got and failed:
        return t("console.art_fill.got_failed", got=t("console.art_fill.got", count=got),
                 failed=failed), "warning"
    if got:
        return t("console.art_fill.got", count=got), "positive"
    if failed:
        return t("console.art_fill.could_not_get", count=failed), "warning"
    return t("console.art_fill.got_nothing"), "info"


async def ask(game_ids: list[str] | None, state: dict[str, Any],
              then: Callable[[], Any], name: str = "") -> None:
    """Which kinds to get for these games, then get them. `None` is every game, and
    `name` stands for the count when the dialog is about one game."""
    try:
        found = await offload.io(ApiClient().missing_media, game_ids)
    except Exception as exc:  # noqa: BLE001 - said, and nothing was fetched
        ui.notify(t("console.art_fill.could_not_read", exc=exc), type="warning")
        return
    if not found.get("sources"):
        ui.notify(t("console.art_fill.no_sources"), type="warning")
        return
    kinds = await _choose(found, name)
    if kinds:
        await get(lambda: ApiClient().fill_media(game_ids, kinds), state, then)


async def _choose(found: dict[str, Any], name: str) -> list[str]:
    rows = list(found.get("kinds") or [])
    held = dict(remembered.get(TICKS) or {})
    chosen = ticked(rows, held)
    offered = {str(row["kind"]): int(row.get("available") or 0) for row in rows}
    games, unmatched = int(found.get("games") or 0), int(found.get("unmatched") or 0)

    def total() -> int:
        return sum(offered[kind] for kind, on in chosen.items() if on)

    def recount() -> None:
        go.text = t("console.art_fill.get", count=total())
        go.set_enabled(total() > 0)

    sources = list(found["sources"])
    with frame.opened(t("console.art_fill.title", source=sources[0]) if len(sources) == 1
                      else t("console.art_fill.title_several"), wide=True) as box:
        ui.label(name or t("console.art_fill.games", count=games)) \
            .classes("console-help px-3")
        with ui.grid(columns="minmax(0, 1fr) max-content max-content") \
                .classes("w-full items-center gap-x-4 gap-y-1 px-3"):
            labels = media_label_map()
            for row in rows:
                _kind_row(row, labels.get(str(row["kind"]), str(row["kind"])), chosen,
                          recount)
        if unmatched:
            ui.label(t("console.art_fill.game_unmatched") if games == 1
                     else t("console.art_fill.unmatched", count=unmatched)) \
                .classes("console-help px-3")
        if found.get("unreachable"):
            ui.label(t("console.art_fill.unreachable",
                       sources=", ".join(found["unreachable"]))) \
                .classes("console-help px-3")
        with frame.footer():
            frame.cancel(lambda: box.submit([]))
            go = frame.answer(t("console.art_fill.get", count=total()),
                              lambda: box.submit([kind for kind, on in chosen.items()
                                                  if on and offered[kind]]),
                              icon=verbs.FETCH)
            go.set_enabled(total() > 0)
        frame.enter_presses(go)

    picked = list(await box or [])
    if picked:
        remembered.put(TICKS, remember(held, chosen, rows))
    return picked


def _kind_row(row: dict[str, Any], label: str, chosen: dict[str, bool],
              changed: Callable[[], None]) -> None:
    """A kind, how many games lack it, and how many of those a source can fill."""
    kind = str(row["kind"])
    missing, available = int(row.get("missing") or 0), int(row.get("available") or 0)

    def picked(on: bool) -> None:
        chosen[kind] = on
        changed()

    box = ui.checkbox(label, value=chosen[kind]).props("dense")
    box.on_value_change(lambda event: picked(bool(event.value)))
    box.set_enabled(available > 0)
    if not missing:
        ui.label(t("console.art_fill.none_missing")).classes("console-member-qualifier")
        ui.element("div")
        return
    ui.label(t("console.art_fill.missing", count=missing)) \
        .classes("console-member-qualifier")
    ui.label(t("console.art_fill.available", count=available) if available
             else t("console.art_fill.none_available")) \
        .classes("console-member-qualifier")


async def get(start: Callable[[], dict], state: dict[str, Any],
              then: Callable[[], Any]) -> None:
    """Start the fill and say what it got once it ends; the footer line reports it
    while it runs. `then` runs only when something was placed."""
    client = ApiClient()
    try:
        job = await offload.io(start)
    except Exception as exc:  # noqa: BLE001 - said, and nothing was fetched
        ui.notify(t("console.art_fill.could_not_start", exc=exc), type="warning")
        return
    watch = state.get("watch_jobs")
    if callable(watch):
        watch()
    for _ in range(_POLLS):
        await asyncio.sleep(_POLL_S)
        try:
            found = await offload.io(client.job, str(job.get("id") or ""))
        except Exception:  # noqa: BLE001 - the footer line still reports it
            return
        if found.get("state") == "running":
            continue
        if found.get("state") == "failed":
            ui.notify(t("console.art_fill.failed",
                        error=found.get("error") or t("console.page.no_reason_given")),
                      type="negative")
            return
        result = found.get("result") or {}
        said, level = outcome(result)
        ui.notify(said, type=level)
        if int(result.get("filled") or 0):
            answer = then()
            if inspect.isawaitable(answer):
                await answer
        return
