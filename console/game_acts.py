"""What a game and a table can be told to do, for the grid's row menu and the panel's
header menu alike.

`after` is the caller's way of putting its own surface right once a write has landed: the
Games and Tables pages refresh the rows they hold, the panel rebuilds itself. It is told
whether the table is gone, because a panel about a table that no longer exists has
nowhere to stay.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import partial
from pathlib import Path
from typing import Any

from nicegui import run, ui

from common.failures import why
from common.i18n import t
from console import collection_adds, confirm, game_tables, panel, verbs
from console.on_page import on_page

After = Callable[[bool], Awaitable[None]]
Collections = Callable[[Callable[[], Any]], None]


def game_acts(library: Any, game_id: str, name: str,
              collections: Collections | None) -> list[panel.Verb]:
    """What can be done to a game: play it, and file it in a collection."""
    @on_page
    async def launch() -> None:
        try:
            await run.io_bound(library.launch, game_id)
        except Exception as exc:  # noqa: BLE001
            ui.notify(t("console.workbench.launch_failed"), caption=why(exc), type="negative")
            return
        ui.notify(t("console.games.launching", name=name), type="positive")

    offered = [panel.Verb(t("console.games.launch"), launch)]
    if collections is not None:
        offered.append(panel.Verb(t("console.adds.verb"), draw=collections))
    return offered


def table_acts(library: Any, game_id: str, game_name: str, table: dict[str, Any],
               tables: list[dict[str, Any]], after: After,
               collections: Collections | None) -> list[panel.Verb]:
    """What can be done to one table of a game. `tables` is every table of that game,
    which says whether this one can be locked and what a forget would take with it."""
    table_id = str(table.get("id") or "")

    @on_page
    async def write(call: Callable[..., Any], *args: Any, said: str | Callable[[Any], str],
                    failed: str, gone: bool = False) -> None:
        try:
            answer = await run.io_bound(call, game_id, *args)
        except Exception as exc:  # noqa: BLE001
            ui.notify(failed, caption=why(exc), type="negative")
            return
        ui.notify(said(answer) if callable(said) else said, type="positive")
        await after(gone)

    def lock_said(lock: bool, answer: Any) -> str:
        return game_tables.lock_said(game_name, table, (answer or {}).get("tables") or [],
                                     lock=lock)

    @on_page
    async def drop_script() -> None:
        every = game_tables.shares_its_script(table)
        if not await confirm.ask(
                t("console.workbench.delete_question"),
                detail=t("console.game_tables.script_detail" if every
                         else "console.workbench.delete_detail"),
                lines=[f"{Path(table.get('filename') or '').stem}.vbs"]):
            return
        await write(library.delete_script, table_id,
                    said=t("console.game_tables.script_deleted" if every
                           else "console.workbench.delete_done"),
                    failed=t("console.workbench.delete_failed"))

    @on_page
    async def forget() -> None:
        detail = ("console.workbench.forget_keyed" if game_tables.is_keyed(table)
                  else "console.workbench.forget_reference" if game_tables.is_referenced(table)
                  else "console.workbench.forget_missing")
        made = game_tables.made_from_it_line(
            [game_tables.name_among(one, tables)
             for one in game_tables.made_from_it(table, tables)])
        if not await confirm.ask(
                t("console.workbench.forget_table"), detail=t(detail),
                lines=[game_tables.name_among(table, tables), *([made] if made else [])],
                confirm=t("word.forget"), icon=verbs.FORGET):
            return
        await write(library.forget_table, table_id, said=t("console.workbench.table_forgotten"),
                    failed=t("console.workbench.forget_failed"), gone=True)

    offered: list[panel.Verb] = []
    if not table.get("default"):
        if not game_tables.why_not_default(table):
            offered.append(panel.Verb(t("word.make_default"), partial(
                write, library.set_default_table, table_id,
                said=game_tables.now_plays(game_name, table),
                failed=t("console.workbench.change_failed"))))
    elif locking := game_tables.lock_act(table, tables):
        lock, words = locking
        offered.append(panel.Verb(words, partial(
            write, library.set_default_table, table_id if lock else "",
            said=partial(lock_said, lock), failed=t("console.workbench.change_failed"))))
    hidden = bool(table.get("hidden"))
    offered.append(panel.Verb(
        t("console.games.unhide") if hidden else t("console.games.hide"),
        partial(write, library.set_table_hidden, table_id, not hidden,
                said=lambda answer: game_tables.hidden_said(game_name, table, answer,
                                                            hidden=not hidden),
                failed=t("console.workbench.save_failed"))))
    if game_tables.runs_its_own_script(table):
        offered.append(panel.Verb(t("console.games.delete_script"), drop_script, danger=True))
    else:
        offered.append(panel.Verb(
            t("console.games.extract_script"),
            partial(write, library.extract_script, table_id,
                    said=t("console.workbench.extract_done"),
                    failed=t("console.workbench.extract_failed"))))
    if not table.get("available"):
        offered.append(panel.Verb(t("console.games.forget_table"), forget, danger=True))
    if collections is not None:
        offered.append(panel.Verb(t("console.adds.verb"), draw=collections))
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
