"""The Backups row on the panel of a game, a launcher or a theme.

The row says how many copies there are and when the newest was taken. Back up now takes
one without asking anything, and Restore... opens the copies of this one thing in the
grid System > Backups draws, so the verbs and the Undo on a restore are the same there.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlencode

from nicegui import run, ui

from common.backups import copies as kept_copies
from common.failures import why
from common.i18n import t
from console import backups, offload, panel, verbs, when
from console import dialog as frame
from console import grid as grid_module
from console.data import Library
from console.on_page import on_page

SCOPE = "backups.subject"

COLUMNS = [
    grid_module.identifier("taken", t("console.backups.taken"), 190, pinned="left",
                           tooltipField="taken_utc", help=t("console.backups.taken.help"),
                           **backups.TAKEN_FILTER),
    grid_module.column("file", t("word.file"), 260, tooltipField="path",
                       help=t("console.backups.file.help")),
    grid_module.column("reason_text", t("console.backups.reason"), 150,
                       help=t("console.backups.reason.help")),
    grid_module.column("note", t("console.backups.note"), 200,
                       help=t("console.backups.note.help")),
    grid_module.column("size", t("word.size"), 100, type="numericColumn",
                       help=t("console.backups.size.help"),
                       **{":valueFormatter": "params => (params.data || {}).size_text || ''"}),
]


def said(found: list[dict[str, Any]]) -> str:
    """How many copies, and when the newest was taken: `2, newest 4 Oct 02:06:30`."""
    if not found:
        return t("word.none")
    newest = max(str(one.get("taken") or "") for one in found)
    return t("console.backups.row", count=len(found), newest=when.local_seconds(newest))


async def listed(library: Library, subject_kind: str, subject_id: str) -> list[dict[str, Any]]:
    """The copies of one thing, or none where they cannot be read: the row still draws."""
    try:
        said = await offload.io(library.backups, subject_kind, subject_id)
        return list(said.get("copies") or [])
    except Exception:  # noqa: BLE001 - a row that cannot count says None, never breaks the panel
        return []


@on_page
async def back_up(library: Library, subject_kind: str, subject_id: str, name: str,
                  after: Callable[[], Awaitable[None]]) -> None:
    """One copy of this game or launcher's settings file, named as `name` suggests."""
    games = [subject_id] if subject_kind == kept_copies.SUBJECT_GAME else []
    launcher = subject_id if subject_kind == kept_copies.SUBJECT_LAUNCHER else ""

    @on_page
    async def take(chosen: str, note: str) -> None:
        try:
            await run.io_bound(lambda: library.take_backup(
                "games" if games else "launcher", games=games, launcher=launcher,
                name=chosen, note=note))
        except Exception as exc:  # noqa: BLE001 - the reason belongs on the page
            ui.notify(t("console.backups.back_up_failed"), caption=why(exc), type="negative")
            return
        ui.notify(t("console.backups.backed_up"), type="positive")
        await after()

    await backups.ask_details(name, take)


@on_page
async def back_up_games(library: Library, games: list[dict[str, Any]],
                        after: Callable[[], Awaitable[None]] | None = None) -> None:
    """One backup of these games, chosen where the games are."""
    ids = [str(one["id"]) for one in games]

    @on_page
    async def take(chosen: str, note: str) -> None:
        try:
            await run.io_bound(lambda: library.take_backup(
                "games", games=ids, name=chosen, note=note))
        except Exception as exc:  # noqa: BLE001 - the reason belongs on the page
            ui.notify(t("console.backups.back_up_failed"), caption=why(exc), type="negative")
            return
        ui.notify(t("console.backups.done_games", count=len(ids)), type="positive")
        if after is not None:
            await after()

    await backups.ask_details(
        kept_copies.games_named(str(one.get("name") or "") for one in games), take)


def row(library: Library, subject_kind: str, subject_id: str, name: str,
        found: list[dict[str, Any]], after: Callable[[], Awaitable[None]], *,
        back_up_now: bool = True, hint: str = "") -> Callable[[], None]:
    """The value of the Backups row. A non-empty `hint` says why both verbs are off."""
    async def take() -> None:
        await back_up(library, subject_kind, subject_id, name, after)

    async def choose() -> None:
        await open_for(library, subject_kind, subject_id, name, after)

    def draw() -> None:
        with ui.row().classes("items-center gap-2 no-wrap"):
            ui.label(said(found)).classes("console-fact-value truncate min-w-0")
            if back_up_now:
                panel.action(t("console.backups.back_up_title"), take, icon=verbs.ADD,
                             inline=True, enabled=not hint, hint=hint)()
            panel.action(t("console.backups.restore_dialog"), choose, icon=verbs.RESTORE,
                         inline=True, enabled=bool(found) and not hint,
                         hint=hint or ("" if found else t("console.backups.nothing_to_restore")))()
    return draw


def _open_in_backups(name: str) -> None:
    ui.navigate.to("/console?" + urlencode([("view", "backups"), ("find", name)]))


async def open_for(library: Library, subject_kind: str, subject_id: str, name: str,
                   after: Callable[[], Awaitable[None]]) -> None:
    """The copies of one thing, to restore from."""
    built = backups.rows(await listed(library, subject_kind, subject_id), parts=True)
    if not built:
        ui.notify(t("console.backups.nothing_to_restore"), type="warning")
        return
    by_id = {one["id"]: one for one in built}
    seek = next((str(one["subject_name"]) for one in built if one.get("subject_name")), name)

    with frame.opened(t("console.backups.title", name=name),
                      classes="console-backups-card") as box:
        with ui.element("div").classes("w-full grow min-h-0 flex flex-col px-3"):
            table: ui.aggrid = grid_module.build(
                COLUMNS, built, SCOPE,
                on_select_rows=lambda picked: go.set_enabled(bool(picked)),
                on_context=lambda row_in: fill(row_in),
                on_header_context=lambda col_id: header(col_id))
            menu: ui.context_menu = ui.context_menu()

        def picked_rows() -> list[dict[str, Any]]:
            return [by_id[str(one["id"])] for one in grid_module.selection(table)
                    if str(one.get("id")) in by_id]

        def fill(row_in: dict | None) -> None:
            one = by_id.get(str((row_in or {}).get("id") or ""))
            if one is None:
                menu.clear()
                return
            on = grid_module.menu_rows(table, one)
            panel.verb_menu(menu, backups.name_of(one) if len(on) == 1
                            else t("console.backups.selected_n", count=len(on)),
                            panel.for_selection(
                                backups.acts(library, on, refresh,
                                             check=len(on) > 1
                                             and bool(grid_module.hidden_count(table))),
                                len(on)))

        async def header(col_id: str | None) -> None:
            await grid_module.header_menu(menu, table, COLUMNS, col_id)

        @on_page
        async def refresh() -> None:
            fresh = backups.rows(await listed(library, subject_kind, subject_id), parts=True)
            if not fresh:
                box.close()
            else:
                by_id.clear()
                by_id.update({one["id"]: one for one in fresh})
                table.run_grid_method("setGridOption", "rowData", fresh)
            await after()

        @on_page
        async def put_back() -> None:
            await backups.restore(library, picked_rows(), refresh,
                                  check=bool(grid_module.hidden_count(table)))

        with frame.footer():
            frame.aside(t("console.backups.open_in"), lambda: _open_in_backups(seek),
                        icon=verbs.GO)
            frame.cancel(box.close, t("word.close"))
            go = frame.answer(t("word.restore"), put_back, icon=verbs.RESTORE)
        go.set_enabled(False)
    box.open()
