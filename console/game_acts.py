"""What games and tables can be told to do, for the grid's row menu, the panel's header menu
and the grid's selection menu alike.

Each list takes the rows it acts on: one, or every row selected. A verb shows when it applies
to any of them and acts on those it applies to; one with no meaning over several is `one`.

`refresh` and `after` are the caller's way of putting its own surface right once a write has
landed: the Games and Tables pages repaint the rows they hold, the panel rebuilds itself.
`after` is also told whether a table is gone, because a panel about a table that no longer
exists has nowhere to stay.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any

from nicegui import run, ui

from common.failures import why
from common.i18n import t
from console import (
    backup_rows,
    collection_adds,
    confirm,
    ext_verbs,
    game_tables,
    media_fill,
    offload,
    panel,
    send_to_device,
    stars,
    undo,
    verbs,
    vps_match,
)
from console import dialog as frame
from console import record as recorder
from console.on_page import on_page

Refresh = Callable[[list[str]], Awaitable[None]]
After = Callable[[list[str], bool], Awaitable[None]]
Rate = Callable[[list[str], int], Awaitable[bool]]
Collections = Callable[[Callable[[], Any]], None]

PLAYED = ("last_played", "play_count", "play_time_seconds")


def has_record(record: dict[str, Any] | None) -> bool:
    """Whether a play record holds anything to clear."""
    return any((record or {}).get(key) for key in PLAYED)


def auto_match_outcome(result: dict[str, Any]) -> tuple[str, bool]:
    """What Auto-match says when it is done, and whether any match moved."""
    moved = int(result.get("changed") or 0)
    waiting = int(result.get("unmatched") or 0)
    skipped = int(result.get("skipped") or 0)
    parts = [t(key, count=count) for key, count in (
        ("console.games.auto_matched", moved), ("console.games.unmatched", waiting),
        ("console.games.auto_match_skipped", skipped)) if count]
    if not parts:
        return t("console.vps_match.nothing_changed"), False
    if len(parts) == 1:
        return parts[0], bool(moved)
    if len(parts) == 2:
        return t("console.games.auto_matched_some", matched=parts[0], waiting=parts[1]), bool(moved)
    return t("console.games.auto_matched_all", matched=parts[0], waiting=parts[1],
             skipped=parts[2]), True


def _ids(rows: list[dict[str, Any]]) -> list[str]:
    return [str(one["id"]) for one in rows]


def _only_name(games: list[dict[str, Any]]) -> str:
    return str(games[0].get("name") or "") if len(games) == 1 else ""


# --- games ------------------------------------------------------------------------


def game_acts(library: Any, games: list[dict[str, Any]], state: dict[str, Any],
              refresh: Refresh, *, rate: Rate | None = None,
              match: Callable[[list[dict[str, Any]]], Awaitable[Any]] | None = None,
              collections: Collections | None = None) -> list[panel.Verb]:
    """What can be done to these games. `rate` writes a rating and repaints the grid's
    rows, absent where no grid holds them. `match` stands in for the walk through the VPS
    picker, for a caller with its own way of asking about one game. `state` is the page's,
    which the transfers and the media jobs use to start the drawer's job watch."""
    ids = _ids(games)
    name = _only_name(games)
    marked = [bool(one.get("private")) for one in games]

    @on_page
    async def launch() -> None:
        try:
            await run.io_bound(library.launch, ids[0])
        except Exception as exc:  # noqa: BLE001
            ui.notify(t("console.workbench.launch_failed"), caption=why(exc), type="negative")
            return
        ui.notify(t("console.games.launching", name=str(games[0].get("name") or "")),
                  type="positive")

    @on_page
    async def mark_private(private: bool) -> None:
        flipping = [str(one["id"]) for one in games if bool(one.get("private")) != private]
        try:
            await run.io_bound(library.set_games_private, flipping, private)
        except Exception as exc:  # noqa: BLE001 - said, and the grid is as it was
            ui.notify(t("said.save_failed"), caption=why(exc), type="negative")
            return
        await refresh(flipping)
        said = t("console.games.marked_private" if private
                 else "console.games.cleared_private", count=len(flipping))

        @on_page
        async def put_back() -> None:
            await run.io_bound(library.set_games_private, flipping, not private)
            await refresh(flipping)

        if flipping:
            undo.offer(said, put_back)
        else:
            ui.notify(said, type="positive")

    @on_page
    async def matched() -> None:
        if match is not None:
            await match(games)
            return
        await vps_match.walk(library, games)
        await refresh(ids)

    @on_page
    async def auto_match() -> None:
        try:
            result = await offload.io(library.auto_match, ids)
        except Exception as exc:  # noqa: BLE001 - said, and the grid is as it was
            ui.notify(t("console.games.match_failed"), caption=why(exc), type="warning")
            return
        said, moved = auto_match_outcome(result)
        ui.notify(said, type="positive" if moved else "info")
        if moved:
            await refresh(ids)

    @on_page
    async def placed() -> None:
        await run.io_bound(library.reread_media, ids)
        await refresh(ids)

    async def get_missing_media() -> None:
        await media_fill.ask(ids, state, placed, name=name)

    async def record_media() -> None:
        title = t("console.record.title", name=name) if name \
            else t("console.record.title_games", count=len(ids))
        await recorder.ask(library, [(game_id, "") for game_id in ids], title, state, placed)

    offered = [panel.Verb(t("console.games.launch"), launch, one=True)]
    if rate is not None:
        offered.append(panel.Verb(t("console.games.rate"), partial(_rate, games, rate)))
    if not all(marked):
        offered.append(panel.Verb(t("console.games.mark_private"), partial(mark_private, True)))
    if any(marked):
        offered.append(panel.Verb(t("console.games.clear_private"),
                                  partial(mark_private, False)))
    offered.append(panel.Verb(t("console.games.match_vps"), matched))
    offered.append(panel.Verb(t("console.games.auto_match"), auto_match,
                              tip=t("console.games.auto_match.help")))
    offered.append(panel.Verb(t("console.media_fill.get_missing"), get_missing_media))
    if recording := recorder.verb(library, record_media):
        offered.append(recording)
    offered.append(panel.Verb(t("console.games.send_device"),
                              lambda: send_to_device.ask_where(games, state)))
    offered.append(panel.Verb(
        t("console.backups.back_up_title"),
        lambda: backup_rows.back_up_games(library, games, lambda: refresh(ids))))
    if collections is not None:
        offered.append(panel.Verb(t("console.adds.verb"), draw=collections))
    if reset := reset_games(library, ids, refresh):
        offered.append(reset)
    if deleter := delete_games(library, games, refresh):
        offered.append(deleter)
    offered += ext_verbs.offered(
        state, "game", [{"game_id": one} for one in ids], lambda: refresh(ids),
        public=[{"game_id": str(one["id"])} for one in games if not one.get("private")])
    return offered


async def _rate(games: list[dict[str, Any]], rate: Rate) -> None:
    """Set a rating on every game passed in, through the writer the star click uses."""
    @on_page
    async def apply(value: int) -> None:
        was: dict[int, list[str]] = {}
        for one in games:
            was.setdefault(int(one.get("rating") or 0), []).append(str(one["id"]))
        if not await rate(_ids(games), value):
            return
        box.close()

        @on_page
        async def put_back() -> None:
            for prior, ids in was.items():
                await rate(ids, prior)

        undo.offer(t("console.games.rated_game_s", count=len(games), value=value), put_back)

    with frame.opened(t("console.games.rate_game_s", count=len(games))) as box:
        with ui.row().classes("px-3"):
            stars.draw(0, lambda n: asyncio.create_task(apply(n)))()
        with frame.footer():
            frame.cancel(box.close)
    box.open()


def reset_games(library: Any, game_ids: list[str], refresh: Refresh,
                label: str = "") -> panel.Verb | None:
    """Clear the play record of those of these games that hold one, or None where none does."""
    held = {str(one.get("id")): one.get("user") for one in library.games
            if str(one.get("id")) in game_ids}
    clearing = [game_id for game_id in game_ids if has_record(held.get(game_id))]
    if not clearing:
        return None

    @on_page
    async def reset() -> None:
        if not await confirm.ask(
                t("console.workbench.reset_game_question", count=len(clearing)),
                detail=t("console.workbench.reset_game_detail"),
                confirm=t("word.reset"), icon=verbs.RESET):
            return
        try:
            for game_id in clearing:
                await run.io_bound(library.reset_play_record, game_id)
        except Exception as exc:  # noqa: BLE001
            ui.notify(t("console.workbench.save_failed"), caption=why(exc), type="negative")
            return
        ui.notify(t("console.workbench.reset_done"), type="positive")
        await refresh(clearing)

    return panel.Verb(label or t("console.workbench.reset_action"), reset, danger=True)


def delete_games(library: Any, games: list[dict[str, Any]], refresh: Refresh) -> panel.Verb:
    """Remove each game's whole folder from the disk, after a question that names them."""
    @on_page
    async def delete() -> None:
        if not await confirm.ask(
                t("console.games.delete_question", count=len(games)),
                detail=t("console.games.delete_detail"),
                lines=[str(one.get("folder") or one.get("name") or "") for one in games]):
            return
        gone: list[str] = []
        try:
            for one in games:
                await run.io_bound(library.delete_game_folder, str(one["id"]))
                gone.append(str(one["id"]))
        except Exception as exc:  # noqa: BLE001 - said, with what was already removed
            ui.notify(t("console.games.delete_failed"), caption=why(exc), type="negative")
        if gone:
            ui.notify(t("console.games.deleted", count=len(gone)), type="positive")
            await refresh(gone)

    return panel.Verb(t("console.games.delete"), delete, danger=True)


# --- tables -----------------------------------------------------------------------


@dataclass(frozen=True)
class Target:
    """One table and what the acts on it need to know of its game: `siblings` is every
    table of that game, which says whether it can be locked and what a forget would take
    with it."""

    game_id: str
    game: str
    table: dict[str, Any]
    siblings: list[dict[str, Any]]

    @property
    def id(self) -> str:
        return str(self.table.get("id") or "")


def table_acts(library: Any, targets: list[Target], after: After, state: dict[str, Any],
               collections: Collections | None) -> list[panel.Verb]:
    """What can be done to these tables."""
    if not targets:
        return []
    one = len(targets) == 1
    first = targets[0]

    def games_of(some: list[Target]) -> list[str]:
        return list(dict.fromkeys(item.game_id for item in some))

    @on_page
    async def write(some: list[Target], call: Callable[..., Any],
                    args: Callable[[Target], tuple[Any, ...]], failed: str) -> list[Any] | None:
        """Write to each in turn. Answers what the writes returned, or None where one failed
        and said why; what was written before it is put right on screen either way."""
        answers: list[Any] = []
        try:
            for item in some:
                answers.append(await run.io_bound(call, item.game_id, *args(item)))
        except Exception as exc:  # noqa: BLE001
            ui.notify(failed, caption=why(exc), type="negative")
            if answers:
                await after(games_of(some[:len(answers)]), False)
            return None
        return answers

    @on_page
    async def make_default() -> None:
        answers = await write([first], library.set_default_table, lambda item: (item.id,),
                              t("console.workbench.change_failed"))
        if answers is not None:
            ui.notify(game_tables.now_plays(first.game, first.table), type="positive")
            await after([first.game_id], False)

    @on_page
    async def lock(locking: bool) -> None:
        answers = await write([first], library.set_default_table,
                              lambda item: (item.id if locking else "",),
                              t("console.workbench.change_failed"))
        if answers is not None:
            ui.notify(game_tables.lock_said(first.game, first.table,
                                            (answers[0] or {}).get("tables") or [],
                                            lock=locking), type="positive")
            await after([first.game_id], False)

    @on_page
    async def hide(hidden: bool) -> None:
        applies = [item for item in targets if bool(item.table.get("hidden")) != hidden]
        answers = await write(applies, library.set_table_hidden,
                              lambda item: (item.id, hidden), t("console.workbench.save_failed"))
        if answers is None:
            return
        said = (game_tables.hidden_said(applies[0].game, applies[0].table, answers[0],
                                        hidden=hidden)
                if len(applies) == 1 else
                t("console.game_tables.hid_n" if hidden else "console.game_tables.unhid_n",
                  count=len(applies)))
        await after(games_of(applies), False)

        @on_page
        async def put_back() -> None:
            await write(applies, library.set_table_hidden, lambda item: (item.id, not hidden),
                        t("console.workbench.save_failed"))
            await after(games_of(applies), False)

        undo.offer(said, put_back)

    @on_page
    async def extract() -> None:
        applies = [item for item in targets if not game_tables.runs_its_own_script(item.table)]
        if await write(applies, library.extract_script, lambda item: (item.id,),
                       t("console.workbench.extract_failed")) is not None:
            ui.notify(t("console.workbench.extract_done", count=len(applies)), type="positive")
            await after(games_of(applies), False)

    @on_page
    async def drop_script() -> None:
        applies = [item for item in targets if game_tables.runs_its_own_script(item.table)]
        every = all(game_tables.shares_its_script(item.table) for item in applies)
        if not await confirm.ask(
                t("console.workbench.delete_question", count=len(applies)),
                detail=t("console.game_tables.script_detail" if every
                         else "console.workbench.delete_detail"),
                lines=[f"{Path(item.table.get('filename') or '').stem}.vbs"
                       for item in applies]):
            return
        if await write(applies, library.delete_script, lambda item: (item.id,),
                       t("console.workbench.delete_failed")) is not None:
            ui.notify(t("console.game_tables.script_deleted" if every
                        else "console.workbench.delete_done", count=len(applies)),
                      type="positive")
            await after(games_of(applies), False)

    @on_page
    async def reset() -> None:
        applies = [item for item in targets if has_record(item.table.get("user"))]
        if not await confirm.ask(
                t("console.workbench.reset_table_question", count=len(applies)),
                detail=t("console.workbench.reset_table_detail"),
                confirm=t("word.reset"), icon=verbs.RESET):
            return
        if await write(applies, library.reset_play_record, lambda item: (item.id,),
                       t("console.workbench.save_failed")) is not None:
            ui.notify(t("console.workbench.reset_done"), type="positive")
            await after(games_of(applies), False)

    @on_page
    async def forget() -> None:
        applies = [item for item in targets if game_tables.can_forget(item.table)]
        if len(applies) == 1:
            only = applies[0]
            detail = ("console.workbench.forget_keyed" if game_tables.is_keyed(only.table)
                      else "console.workbench.forget_reference"
                      if game_tables.is_referenced(only.table)
                      else "console.workbench.forget_missing")
            made = game_tables.made_from_it_line(
                [game_tables.name_among(derived, only.siblings)
                 for derived in game_tables.made_from_it(only.table, only.siblings)])
            lines = [game_tables.name_among(only.table, only.siblings),
                     *([made] if made else [])]
        else:
            detail = "console.workbench.forget_several"
            lines = [game_tables.JOIN.join((item.game, game_tables.name_among(
                item.table, item.siblings))) for item in applies]
        if not await confirm.ask(
                t("console.workbench.forget_table", count=len(applies)), detail=t(detail),
                lines=lines, confirm=t("word.forget"), icon=verbs.FORGET):
            return
        if await write(applies, library.forget_table, lambda item: (item.id,),
                       t("console.workbench.forget_failed")) is not None:
            ui.notify(t("console.workbench.table_forgotten", count=len(applies)),
                      type="positive")
            await after(games_of(applies), True)

    @on_page
    async def placed() -> None:
        await run.io_bound(library.reread_media, games_of(targets))
        await after(games_of(targets), False)

    async def record_media() -> None:
        title = t("console.record.title_table", name=first.game,
                  table=game_tables.table_name(first.table)) if one \
            else t("console.record.title_tables", count=len(targets))
        await recorder.ask(library, [(item.game_id, item.id) for item in targets],
                           title, state, placed)

    offered: list[panel.Verb] = []
    table = first.table
    if not one:
        offered.append(panel.Verb(t("word.make_default"), one=True))
    elif not table.get("default"):
        if not game_tables.why_not_default(table):
            offered.append(panel.Verb(t("word.make_default"), make_default, one=True))
    elif locking := game_tables.lock_act(table, first.siblings):
        locks, words = locking
        offered.append(panel.Verb(words, partial(lock, locks), one=True))
    hidden = [bool(item.table.get("hidden")) for item in targets]
    if not all(hidden):
        offered.append(panel.Verb(t("console.games.hide"), partial(hide, True)))
    if any(hidden):
        offered.append(panel.Verb(t("console.games.unhide"), partial(hide, False)))
    if not all(game_tables.runs_its_own_script(item.table) for item in targets):
        offered.append(panel.Verb(t("console.games.extract_script"), extract))
    if recording := recorder.verb(library, record_media):
        offered.append(recording)
    if collections is not None:
        offered.append(panel.Verb(t("console.adds.verb"), draw=collections))
    if any(game_tables.runs_its_own_script(item.table) for item in targets):
        offered.append(panel.Verb(t("console.games.delete_script"), drop_script, danger=True))
    if any(has_record(item.table.get("user")) for item in targets):
        offered.append(panel.Verb(t("console.workbench.reset_action"), reset, danger=True))
    if reset_game := reset_games(library, games_of(targets),
                                 lambda ids: after(ids, False),
                                 t("console.workbench.reset_game_action")):
        offered.append(reset_game)
    if any(game_tables.can_forget(item.table) for item in targets):
        offered.append(panel.Verb(t("word.forget"), forget, danger=True))
    offered += ext_verbs.offered(
        state, "table", [{"game_id": item.game_id, "table_id": item.id} for item in targets],
        lambda: after(games_of(targets), False))
    return offered


def collections_of(offer: collection_adds.Offer,
                   known: collection_adds.Read | None) -> Collections | None:
    """The add-to-collection entries under a rule, drawn into whichever menu is being
    built. None until the library's collections have been read."""
    if known is None:
        return None

    def draw(close: Callable[[], Any]) -> None:
        ui.separator()
        collection_adds.draw(offer, known, close)

    return draw
