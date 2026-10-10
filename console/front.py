"""The top of Overview: the game last played or playing now, a job that is running, and the
games played before it.

Read by `Library.load_overview` into `Library.front()`; this module only draws it. The
hero and the Now card are the live part: they poll while the page is open, and a game
starting or ending draws the whole page again, since what was last played changes with it.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from nicegui import run, ui

from common import icons
from common.failures import why
from common.i18n import t
from common.labels import humanize
from console import (
    art,
    deeplink,
    dropdown,
    game_tables,
    needs,
    offload,
    panel,
    verbs,
    when,
)
from console.api import ApiClient
from console.data import FRONT_FRESH_S, Library
from console.on_page import on_page

STRIP = 4
POLL_S = FRONT_FRESH_S


def _playing(front: dict[str, Any]) -> bool:
    return bool((front.get("play") or {}).get("launching"))


def _address(game_id: str) -> str:
    return "/console?" + deeplink.query({"view": "games", "game": game_id})


def _workbench() -> Any:
    from console import workbench

    return workbench


def _elapsed(started_at: str | None) -> str:
    began = when.parsed(started_at)
    if began is None:
        return ""
    seconds = max(1, int((datetime.now(UTC) - began).total_seconds()))
    return t("console.front.so_far", time=_workbench()._played_for(seconds))


def _plays(record: dict[str, Any]) -> list[str]:
    count = int(record.get("play_count") or 0)
    seconds = int(record.get("play_time_seconds") or 0)
    parts = [t("console.front.plays", count=count)] if count else []
    if seconds:
        parts.append(_workbench()._played_for(seconds))
    return parts


def _backdrop(library: Library, game_id: str) -> str:
    """The backglass behind the hero, or the playfield where there is none; "" for neither."""
    held = library.media.get(game_id) or {}
    for kind in ("backglass", "playfield"):
        entry = held.get(kind) or {}
        if entry.get("present"):
            return art.media(game_id, kind, version=entry.get("version"), size=art.PANEL)
    return ""


def _top_score(front: dict[str, Any]) -> tuple[str, str]:
    """The initials and the score of the machine's best entry, or two blanks."""
    entry = front.get("top")
    if not entry:
        return "", ""
    return str(entry.get("initials") or ""), _workbench()._score_lines(entry)[0]


def _subject(library: Library, front: dict[str, Any]) -> dict[str, Any]:
    """The game the hero is about, with what to say of it: the one playing, else the one
    played last."""
    play = front.get("play") or {}
    games = {str(one["id"]): one for one in library.games}
    if _playing(front):
        game_id = str(play.get("game_id") or "")
        game = games.get(game_id, {})
        name = str(game.get("name") or play.get("game_name") or "")
        return {"id": game_id, "game": game, "name": name,
                "record": (front.get("records") or {}).get(game_id) or {}}
    game_id = (front.get("recent") or [""])[0]
    game = games.get(game_id, {})
    return {"id": game_id, "game": game, "name": str(game.get("name") or ""),
            "record": (front.get("records") or {}).get(game_id) or {}}


def hero(library: Library, front: dict[str, Any], quit_table: Callable[[], Any]) -> None:
    """Last Played, or Playing Now while a table runs."""
    playing = _playing(front)
    if not playing and not front.get("recent"):
        return
    subject = _subject(library, front)
    game, record, game_id = subject["game"], subject["record"], subject["id"]
    line = [game_tables.made(game)] if game else []
    line.append(_elapsed((front.get("play") or {}).get("started_at")) if playing
                else (_workbench()._played_when(record.get("last_played"))))
    line += _plays(record)
    initials, score = _top_score(front)
    backdrop = _backdrop(library, game_id) if game_id else ""
    with ui.element("div").classes("console-hero") as card:
        card.classes(add="console-hero--playing" if playing else "")
        if backdrop:
            card.classes("console-hero--pictured")
            card.style(f"--hero-picture: url('{backdrop}')")
        with ui.element("div").classes("console-hero-body"):
            ui.label(t("console.front.playing_now" if playing else "console.front.last_played")) \
                .classes("console-hero-caption")
            if game_id and game:
                panel.link(subject["name"], to=_address(game_id), classes="console-hero-name")()
            else:
                ui.label(subject["name"]).classes("console-hero-name")
            ui.label(game_tables.JOIN.join(part for part in line if part)) \
                .classes("console-hero-line")
        with ui.element("div").classes("console-hero-side"):
            if score:
                with ui.element("div").classes("console-hero-score"):
                    ui.label(t("console.front.top_score")).classes("console-hero-caption")
                    ui.label(" ".join(part for part in (initials, score) if part)) \
                        .classes("console-hero-figure")
            if playing:
                panel.action(t("console.remote.quit_table"), quit_table, icon=verbs.STOP,
                             danger=True, hint=t("console.front.quit_hint"))()


def now(state: dict[str, Any], front: dict[str, Any]) -> None:
    """Each job still running: its name, its progress and the way to Jobs."""
    for job in front.get("jobs") or []:
        with ui.element("div").classes("console-card console-now"):
            with ui.element("div").classes("console-now-head"):
                ui.label(t("console.front.now")).classes("console-card-title")
                panel.action(t("console.front.to_jobs"),
                             lambda: state["open_on"](needs.Opens(view="jobs")),
                             icon=verbs.GO, inline=True, hint=t("console.front.jobs_hint"))()
            ui.label(str(job.get("title") or "")
                     or humanize(str(job.get("kind") or "").replace(".", " "))) \
                .classes("console-now-name")
            ui.linear_progress(value=float(job.get("pct") or 0) / 100, show_value=False) \
                .props("rounded")
            if job.get("message"):
                ui.label(str(job["message"])).classes("console-help")


def _signature(front: dict[str, Any]) -> tuple[Any, ...]:
    play = front.get("play") or {}
    minute = int(time.time() // 60) if play.get("launching") else 0
    return (bool(play.get("launching")), play.get("game_id"), bool(play.get("paused")), minute,
            tuple((one.get("id"), int(float(one.get("pct") or 0)), one.get("message"))
                  for one in front.get("jobs") or []))


def top(library: Library, state: dict[str, Any], go: Callable[[str], None]) -> None:
    """The hero and the Now card, kept current while the page is open."""
    shown = {"signature": _signature(library.front())}

    @on_page
    async def quit_table() -> None:
        try:
            await run.io_bound(ApiClient().stop_play)
        except Exception as exc:  # noqa: BLE001 - the reason belongs on screen
            ui.notify(t("console.remote.quit_failed"), caption=why(exc), type="negative")
            return
        library.forget_front()
        if state.get("view") == "overview":
            go("overview")

    @ui.refreshable
    def region() -> None:
        front = library.front()
        hero(library, front, quit_table)
        now(state, front)

    @on_page
    async def poll() -> None:
        front = library.front()
        try:
            play = await offload.io(ApiClient().play_state)
            jobs = [one for one in await offload.io(ApiClient().jobs)
                    if one.get("state") == "running"]
        except Exception:  # noqa: BLE001 - the next poll tries again
            return
        before = front.get("play") or {}
        library.refresh_front(play, jobs)
        if bool(play.get("launching")) != bool(before.get("launching")) \
                or play.get("game_id") != before.get("game_id"):
            library.forget_front()
            if state.get("view") == "overview":
                go("overview")
            return
        now_signature = _signature(library.front())
        if now_signature != shown["signature"]:
            shown["signature"] = now_signature
            region.refresh()

    region()
    ui.timer(POLL_S, poll)


def strip(library: Library, go: Callable[[str], None]) -> None:
    """The next games played after the one in the hero: wheel, name and when."""
    front = library.front()
    recent = list(front.get("recent") or [])
    if _playing(front):
        recent = [one for one in recent if one != (front.get("play") or {}).get("game_id")]
    else:
        recent = recent[1:]
    games = {str(one["id"]): one for one in library.games}
    shown = [one for one in recent if one in games][:STRIP]
    if not shown:
        return
    roster = [one for one in front.get("players") or []]
    chosen = front.get("player") or {}

    def pick(event: Any) -> None:
        library.pick_front_player(str(event.value))
        go("overview")

    with ui.element("div").classes("console-front-strip"):
        with ui.element("div").classes("console-front-strip-head"):
            ui.label(t("console.front.recently_played")).classes("console-card-title")
            if len(roster) > 1:
                dropdown.Select({str(one["id"]): str(one.get("name") or "") for one in roster},
                                value=str(chosen.get("id") or ""), on_change=pick,
                                look=dropdown.OUTLINED).classes("console-front-player")
        with ui.element("div").classes("console-front-items"):
            for game_id in shown:
                game = games[game_id]
                held = (library.media.get(game_id) or {}).get("wheel") or {}
                picture = art.media(game_id, "wheel", version=held.get("version"),
                                    size=art.CELL) if held.get("present") else ""
                with panel.link_tile(to=_address(game_id), classes="console-front-item"):
                    if picture:
                        ui.image(picture).classes("console-front-wheel")
                    else:
                        ui.icon(icons.GAMES).classes("console-front-wheel console-front-glyph")
                    ui.label(str(game.get("name") or "")).classes("console-front-name")
                    ui.label(_workbench()._played_when(
                        (front.get("records") or {}).get(game_id, {}).get("last_played"))) \
                        .classes("console-help")
