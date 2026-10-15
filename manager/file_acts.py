"""What media files and asset files can be told to do, for the grids' row menus, the panel's
header menu and the grids' selection menus alike.

Each list takes the files it acts on: one, or every row selected. A verb shows when it
applies to any of them and acts on those it applies to. `after` puts the caller's surface
right for the games a write touched: the grids repaint those games' rows, the panel rebuilds.

A file that nothing uses (a loose media file) has no media menu: the slot's acts would act on
the file the slot resolves to, which is another one.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import partial
from pathlib import PurePosixPath
from typing import Any

from nicegui import run, ui

from common.failures import why
from common.games import media_fill as gaps_in
from common.games.asset_resolver import VPX_ASSET_KINDS
from common.i18n import t
from common.media_specs import PAGED_KINDS
from common.online import vps_kinds
from manager import (
    confirm,
    game_tables,
    media_fill,
    media_ownership,
    media_rotate,
    mediasource,
    offload,
    panel,
    verbs,
    walks,
)
from manager import record as recorder
from manager.on_page import on_page

logger = logging.getLogger("vpinfe.manager.file_acts")

After = Callable[[list[str]], Awaitable[Any]]

# The kinds VPX finds by name, which a file can be placed as and removed from.
PLACEABLE = frozenset(one.key for one in VPX_ASSET_KINDS)
WHOLE_FOLDER = frozenset({"pup_pack", "alt_color", "alt_sound", "music"})
# Names listed before "...and N more" in a confirmation.
_NAMED = 8


@dataclass(frozen=True)
class File:
    """One row of the Media or Assets grid and the game it belongs to."""

    row: dict[str, Any]
    game: dict[str, Any]

    @property
    def id(self) -> str:
        return str(self.row["id"])

    @property
    def game_id(self) -> str:
        return str(self.row.get("game_id") or "")

    @property
    def kind(self) -> str:
        return str(self.row.get("kind") or "")

    @property
    def label(self) -> str:
        """What a person calls it: the kind, and for a later page which page."""
        return str(self.row.get("named") or self.row.get("label") or self.kind)

    @property
    def page(self) -> int:
        return int(self.row.get("page") or 1)

    @property
    def table(self) -> str:
        return str(self.row.get("table") or "")

    @property
    def path(self) -> str:
        return str(self.row.get("path") or "")

    @property
    def present(self) -> bool:
        return bool(self.row.get("present"))

    @property
    def tier(self) -> str:
        return tier_of(self.row)


def files_of(library: Any, rows: list[dict[str, Any]]) -> list[File]:
    """These grid rows as files, each with its game."""
    games = {str(one["id"]): one for one in library.games}
    return [File(row, games.get(str(row.get("game_id") or ""), {})) for row in rows]


def tier_of(row: dict[str, Any]) -> str:
    """Who uses this file, in `media_ownership`'s words, for either lens."""
    if "binding" not in row:
        return media_ownership.key_of(row.get("via"))
    binding = str(row.get("binding") or "")
    if binding == "orphaned":
        return media_ownership.ORPHAN
    if not row.get("present"):
        return media_ownership.MISSING
    if binding == "game":
        return media_ownership.UNUSED if row.get("serves") == 0 else media_ownership.GAME
    return media_ownership.TABLE


def is_loose(row: dict[str, Any]) -> bool:
    """A file nothing reads: named for a table that is not there, or for no slot."""
    return tier_of(row) in (media_ownership.ORPHAN, media_ownership.UNUSED)


def asset_has_acts(row: dict[str, Any]) -> bool:
    """Whether an asset row is of a kind VPX looks up by name, which is all a file here can
    be placed as or removed from."""
    kind = str(row.get("kind") or "")
    return kind in PLACEABLE or kind in WHOLE_FOLDER


def listed_as(kind: str, inventory: str) -> Any:
    """What VPSdb calls this kind in this inventory: `backglass` is a picture in media and
    a `.directb2s` in assets, and VPS lists only the second."""
    listed = vps_kinds.BY_OURS.get(kind)
    return listed if listed is not None and listed.held_in == inventory else None


def removal(tables: list[dict[str, Any]], game: dict[str, Any], table_id: str,
            tiers: list[dict[str, Any]] | None, entry: dict[str, Any],
            then: str | None = None) -> tuple[str, str] | None:
    """The file this lens's Remove takes and who loses it, or None where the lens has no
    file at its own tier and Remove takes nothing. `then` is the file shown after it.

    `tiers` is None when the slot's detail could not be read, and then only the file on
    show is known.
    """
    table = next((one for one in tables if one.get("id") == table_id), None)
    own = bool(table_id) and not game_tables.named_as_folder(table, game)
    tier = media_ownership.TABLE if own else media_ownership.GAME
    known = tiers is not None
    if tiers is None:
        tiers = [{"tier": entry.get("via"), "file": entry.get("file")}] \
            if entry.get("present") else []
    at = next((i for i, one in enumerate(tiers) if one.get("tier") == tier), None)
    if at is None:
        return None
    name = str(tiers[at].get("file") or "")
    if not own:
        return name, t("manager.workbench.remove_asset.game")
    if not known:
        return name, t("manager.workbench.remove_asset.table")
    if then:
        return name, t("manager.workbench.remove_asset.table_then", name=then)
    return name, t("manager.workbench.remove_asset.table_only")


def asset_removal_detail(kind: str, tier: str, files: int | None = None) -> str:
    """Who loses an asset when it is removed."""
    if files is not None:
        return t("manager.workbench.remove_asset.folder", count=files)
    falls_back = any(one.key == kind and one.folder_fallback for one in VPX_ASSET_KINDS)
    return {media_ownership.TABLE: t("manager.workbench.remove_asset.table" if falls_back
                                     else "manager.workbench.remove_asset.table_only"),
            media_ownership.GAME: t("manager.workbench.remove_asset.game")}.get(
                tier, t("manager.workbench.remove_asset.loose"))


def _games_of(files: list[File]) -> list[str]:
    return list(dict.fromkeys(one.game_id for one in files))


def _named(files: list[File]) -> list[str]:
    names = [game_tables.JOIN.join((str(one.game.get("name") or ""), one.label))
             for one in files]
    if len(names) <= _NAMED + 1:
        return names
    return [*names[:_NAMED], t("said.and_more", count=len(names) - _NAMED)]


def _position(index: int, total: int) -> str:
    return t("manager.walk.position", index=index, total=total) if total > 1 else ""


def _slot_label(some: list[File]) -> str:
    if all(one.present for one in some):
        return t("manager.files.replace")
    if not any(one.present for one in some):
        return t("manager.files.add")
    return t("manager.files.either")


async def _walk_dialogs(
        some: list[File],
        opened: Callable[[File, Callable[[], Awaitable[Any]], str], Awaitable[Any]],
        after: After) -> None:
    """Open each file's dialog in turn. A dialog writes for itself, so what this learns from
    it is only whether to go on, and the surface is put right once for every game a dialog
    saved to."""
    touched: list[str] = []
    for index, one in enumerate(some, 1):
        saved = partial(_noted, touched, one.game_id)
        if await opened(one, saved, _position(index, len(some))) == walks.STOPPED:
            break
    if touched:
        await after(list(dict.fromkeys(touched)))


async def _noted(touched: list[str], game_id: str) -> None:
    touched.append(game_id)


# --- media ------------------------------------------------------------------------


def media_acts(library: Any, files: list[File], state: dict[str, Any],
               after: After) -> list[panel.Verb]:
    """What can be done to these media files."""
    everyone = [one for one in files if not is_loose(one.row)]
    if not everyone:
        return []
    # A later page is a file of its own that can be replaced or taken out; the rest of
    # what a slot can do is done to the slot, which page 1 stands for.
    files = [one for one in everyone if one.page == 1]
    rows = [one.row for one in files]
    gaps = [one for one in files if gaps_in.is_gap(one.row)]
    recordable = [one for one in files if mediasource.records(library, one.kind) is not None]
    matchable = [one for one in files if one.present and one.path
                 and listed_as(one.kind, vps_kinds.MEDIA) is not None]
    sharable = [one for one in files if one.present and one.table
                and str(one.row.get("via") or "") == "table"]
    removable = [one for one in everyone if one.present]

    async def open_slot(one: File, done: Callable[[], Awaitable[Any]], place: str) -> Any:
        context = {"library": library, "game_id": one.game_id, "lens": one.table,
                   "game": one.game, "state": state}
        try:
            detail = await offload.io(library.media_detail, one.game_id, one.table or None,
                                      one.kind, one.page)
        except Exception:  # noqa: BLE001 - the dialog opens without what it would add
            logger.debug("No detail for %s", one.kind, exc_info=True)
            detail = {}
        return await mediasource.open_sources(
            context, one.kind, one.label, done, str(detail.get("path") or one.path),
            backglass_file=detail.get("backglass_file"), place=place, page=one.page)

    @on_page
    async def add_or_replace() -> None:
        await _walk_dialogs(everyone, open_slot, after)

    @on_page
    async def get_missing() -> None:
        await media_fill.confirm_slots([one.row for one in gaps], state,
                                       partial(after, _games_of(gaps)))

    async def record() -> None:
        applies = recordable
        missing = sorted({one.kind for one in applies if not one.present})
        ids = _games_of(applies)
        name = str(applies[0].game.get("name") or "") if len(ids) == 1 else ""
        if missing:
            title = t("manager.record.title_missing_one", name=name) if name \
                else t("manager.record.title_missing", count=len(ids))
        else:
            title = t("manager.record.title", name=name) if name \
                else t("manager.record.title_games", count=len(ids))
        wanted = list(dict.fromkeys((one.game_id, one.table) for one in applies))
        await recorder.ask(library, wanted, title, state, partial(after, ids),
                           only=missing or sorted({one.kind for one in applies}))

    @on_page
    async def matched() -> None:
        ready = [one for one in matchable if one.game.get("vps_id")]
        by_id = {one.id: one for one in ready}

        async def ask(row: dict[str, Any], place: str) -> Any:
            from manager import workbench

            one = by_id[str(row["id"])]
            return await workbench.ask_a_record(
                {"library": library, "game": one.game, "game_id": one.game_id},
                listed_as(one.kind, vps_kinds.MEDIA).listed_as, one.label, one.path,
                str(one.row.get("matched_to") or ""), place if len(ready) > 1 else "")

        async def write(row: dict[str, Any], answer: Any) -> None:
            one = by_id[str(row["id"])]
            await run.io_bound(library.set_asset_source, one.game_id, one.path, str(answer))

        changed = await walks.each([one.row for one in ready], ask, write,
                                   t("manager.workbench.save_failed"))
        if changed:
            await after(_games_of(ready))

    @on_page
    async def turn(way: str) -> None:
        await media_rotate.ask(rows, way, state, partial(after, _games_of(files)))

    @on_page
    async def give() -> None:
        given: list[File] = []
        try:
            for one in sharable:
                await run.io_bound(library.retier_media, one.game_id, one.kind, one.table, "")
                given.append(one)
        except Exception as exc:  # noqa: BLE001
            ui.notify(t("manager.workbench.move_failed"), caption=why(exc), type="negative")
        else:
            ui.notify(t("manager.workbench.give_done"), type="positive")
        await after(_games_of(given))

    @on_page
    async def remove() -> None:
        if len(removable) == 1:
            only = removable[0]
            try:
                tables = await offload.io(library.tables_for, only.game_id)
                detail = await offload.io(library.media_detail, only.game_id,
                                          only.table or None, only.kind, only.page)
            except Exception:  # noqa: BLE001 - only the file on show is known
                tables, detail = [], None
            taken = removal(tables, only.game, only.table, (detail or {}).get("tiers"),
                            only.row, (detail or {}).get("after_remove"))
            if taken is not None and not await confirm.ask(
                    t("manager.workbench.remove_asset", name=taken[0]), detail=taken[1],
                    confirm=t("word.remove"), icon=verbs.REMOVE):
                return
        elif not await confirm.ask(
                t("manager.files.remove_several", count=len(removable)),
                detail=t("manager.files.remove_detail"), lines=_named(removable),
                confirm=t("word.remove"), icon=verbs.REMOVE):
            return
        gone = 0
        try:
            # Later pages first: taking one out renumbers the ones after it.
            for one in sorted(removable, key=lambda one: -one.page):
                result = await offload.io(library.remove_media, one.game_id, one.table,
                                          one.kind,
                                          one.page if one.kind in PAGED_KINDS else None)
                gone += len(result.get("removed") or [])
        except Exception as exc:  # noqa: BLE001
            ui.notify(t("said.remove_failed"), caption=why(exc), type="negative")
        else:
            ui.notify(t("manager.workbench.removed_files", count=gone) if gone
                      else t("manager.workbench.nothing_removable"),
                      type="positive" if gone else "info")
        await after(_games_of(removable))

    offered = [panel.Verb(_slot_label(everyone), add_or_replace)]
    if gaps:
        offered.append(panel.Verb(t("manager.media_fill.get_missing"), get_missing))
    if recordable and (recording := recorder.verb(library, record)):
        offered.append(recording)
    if matchable:
        waiting = not any(one.game.get("vps_id") for one in matchable)
        offered.append(panel.Verb(t("manager.games.match_vps"), None if waiting else matched,
                                  hint=t("manager.workbench.files_unmatched") if waiting
                                  else ""))
    if media_rotate.turnable(rows):
        offered.append(panel.Verb(t("manager.media_rotate.turn"), choices=tuple(
            (t(word), partial(turn, way)) for way, word in media_rotate.MENU)))
    if sharable:
        offered.append(panel.Verb(t("manager.workbench.give_all"), give))
    if removable:
        offered.append(panel.Verb(t("word.remove"), remove, danger=True))
    return offered


# --- assets -----------------------------------------------------------------------


def asset_acts(library: Any, files: list[File], state: dict[str, Any],
               after: After) -> list[panel.Verb]:
    """What can be done to these asset files."""
    files = [one for one in files if asset_has_acts(one.row)]
    if not files:
        return []
    placeable = [one for one in files if not is_loose(one.row) or one.kind in WHOLE_FOLDER]
    scripts = [one for one in files if one.kind == "script" and one.present and one.path
               and one.table and one.tier == media_ownership.TABLE]
    taken = {one.id for one in scripts}
    removable = [one for one in files if one.present and one.path and one.id not in taken]

    async def open_slot(one: File, done: Callable[[], Awaitable[Any]], place: str) -> Any:
        context = {"library": library, "game_id": one.game_id, "lens": one.table,
                   "game": one.game, "state": state}
        opener = mediasource.open_folder_sources if one.kind in WHOLE_FOLDER \
            else mediasource.open_asset_sources
        return await opener(context, one.kind, one.label, done, one.path, place=place)

    @on_page
    async def add_or_replace() -> None:
        await _walk_dialogs(placeable, open_slot, after)

    @on_page
    async def remove() -> None:
        if len(removable) == 1:
            only = removable[0]
            count = None
            if only.kind in WHOLE_FOLDER:
                try:
                    found = await offload.io(library.asset_detail, only.game_id, only.path, 0)
                    count = int(found.get("files") or 0)
                except Exception:  # noqa: BLE001 - the ask is made without the count
                    logger.debug("No detail for %s", only.path, exc_info=True)
            ask = (t("manager.workbench.remove_asset", name=PurePosixPath(only.path).name),
                   asset_removal_detail(only.kind, only.tier, count))
            if not await confirm.ask(ask[0], detail=ask[1], confirm=t("word.remove"),
                                     icon=verbs.REMOVE):
                return
        elif not await confirm.ask(
                t("manager.files.remove_several", count=len(removable)),
                detail=t("manager.files.remove_detail"), lines=_named(removable),
                confirm=t("word.remove"), icon=verbs.REMOVE):
            return
        try:
            for one in removable:
                await run.io_bound(library.remove_asset, one.game_id, one.path)
        except Exception as exc:  # noqa: BLE001
            ui.notify(t("said.remove_failed"), caption=why(exc), type="negative")
        else:
            ui.notify(t("manager.workbench.removed_files", count=len(removable)),
                      type="positive")
        await after(_games_of(removable))

    @on_page
    async def delete_scripts() -> None:
        tables = {one.game_id: await offload.io(library.tables_for, one.game_id)
                  for one in scripts}
        owners = [(one, next((table for table in tables[one.game_id]
                              if table.get("id") == one.table), None)) for one in scripts]
        owned = [(one, table) for one, table in owners
                 if table is not None and game_tables.runs_its_own_script(table)]
        if not owned:
            ui.notify(t("manager.workbench.nothing_removable"), type="info")
            return
        every = all(game_tables.shares_its_script(table) for _one, table in owned)
        if not await confirm.ask(
                t("manager.workbench.delete_question", count=len(owned)),
                detail=t("manager.game_tables.script_detail" if every
                         else "manager.workbench.delete_detail"),
                lines=[f"{PurePosixPath(str(table.get('filename') or '')).stem}.vbs"
                       for _one, table in owned]):
            return
        try:
            for one, _table in owned:
                await run.io_bound(library.delete_script, one.game_id, one.table)
        except Exception as exc:  # noqa: BLE001
            ui.notify(t("manager.workbench.delete_failed"), caption=why(exc), type="negative")
        else:
            ui.notify(t("manager.game_tables.script_deleted" if every
                        else "manager.workbench.delete_done", count=len(owned)),
                      type="positive")
        await after(_games_of([one for one, _table in owned]))

    offered: list[panel.Verb] = []
    if placeable:
        offered.append(panel.Verb(_slot_label(placeable), add_or_replace))
    if removable:
        offered.append(panel.Verb(t("word.remove"), remove, danger=True))
    if scripts:
        offered.append(panel.Verb(t("word.delete"), delete_scripts, danger=True))
    return offered
