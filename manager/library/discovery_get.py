"""Getting files from Discovery: what is ticked on an entry, and what it takes to get it.

What is ticked lives with the page rather than the pane. Every step of a batch redraws the
pane, and the rows it draws find the ticks, and how far each has got, where they were left.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Collection
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from nicegui import run, ui

from common.failures import why
from common.i18n import t
from common.media.media_specs import MEDIA_SPECS
from common.online import vps_kinds
from manager.kit import offload, panel, verbs
from manager.kit.on_page import on_page
from manager.library import import_dialog, mediasource, uploads

logger = logging.getLogger("vpinfe.manager.library.discovery_get")

QUEUED = "queued"
DOWNLOADING = "downloading"
IN = "in"
FAILED = "failed"

_LEVELS = {QUEUED: "unknown", DOWNLOADING: "unknown", IN: "on", FAILED: "bad"}
_WORDS = {QUEUED: "manager.discovery.state.queued",
          DOWNLOADING: "manager.discovery.state.downloading",
          IN: "manager.discovery.state.in", FAILED: "manager.discovery.state.failed"}

FIRST_MEDIA = ("wheel", "topper")
_STATUS = "status"
_BAR = "bar"

# What an import leaves as a single file, which a record can be tied to by its path.
_FILE_ACTIONS = ("copy", "replace_b2s", "zip_rom")


@dataclass(frozen=True)
class Pick:
    """One thing that can be ticked: a file an online source will hand over."""

    key: str
    kind: str
    source: str
    size: str = ""


@dataclass
class Move:
    state: str
    reason: str = ""


@dataclass
class Tray:
    """What is ticked on one entry, and how far each tick has got."""

    picks: dict[str, Pick] = field(default_factory=dict)
    moves: dict[str, Move] = field(default_factory=dict)
    batch: int = 0
    running: bool = False
    stopping: bool = False
    _painters: dict[str, list[tuple[Any, Callable[[], None]]]] = field(default_factory=dict)

    def waiting(self) -> list[Pick]:
        """The ticks nothing has taken yet, and the ones that failed and may be taken again."""
        return [one for key, one in self.picks.items()
                if key not in self.moves or self.moves[key].state == FAILED]

    def paint(self, key: str, holder: Any, draw: Callable[[], None]) -> None:
        """Draw `draw` in `holder` now, and again each time `repaint` is told `key` changed."""
        live = [one for one in self._painters.get(key, []) if not one[0].is_deleted]
        self._painters[key] = [*live, (holder, draw)]
        with holder:
            draw()

    def repaint(self, *keys: str) -> None:
        for key in keys:
            live = [(holder, draw) for holder, draw in self._painters.get(key, [])
                    if not holder.is_deleted]
            self._painters[key] = live
            for holder, draw in live:
                holder.clear()
                with holder:
                    draw()

    def repaint_all(self) -> None:
        self.repaint(*self._painters)

    def set(self, pick: Pick, ticked: bool) -> None:
        """Tick or untick. A slot holds one file, so ticking one unticks its rival, unless
        the rival is already in: that one stays."""
        if ticked:
            rivals = [key for key, one in self.picks.items()
                      if one.kind == pick.kind and key != pick.key
                      and (key not in self.moves or self.moves[key].state == FAILED)]
            for key in rivals:
                del self.picks[key]
                self.moves.pop(key, None)
            self.picks[pick.key] = pick
            self.repaint(*rivals)
        else:
            self.picks.pop(pick.key, None)
        self.repaint(_BAR)

    def release(self, kinds: Collection[str]) -> None:
        """Let go of what is in for a kind the game no longer holds, so the row can be
        ticked again."""
        for key in [key for key, move in self.moves.items()
                    if move.state == IN and key in self.picks and self.picks[key].kind in kinds]:
            del self.moves[key]
            del self.picks[key]

    def move(self, key: str, state: str, reason: str = "") -> None:
        self.moves[key] = Move(state, reason)
        self.repaint(key, _STATUS, _BAR)

    def forget(self, key: str) -> None:
        self.moves.pop(key, None)
        self.repaint(key, _STATUS, _BAR)


def tray_of(state: dict[str, Any], vps_id: str) -> Tray:
    return state.setdefault("downloads", {}).setdefault(vps_id, Tray())


def key_of(source: str, kind: str, size: str) -> str:
    return f"{source}:{kind}:{size}"


def pick_of(offer: dict[str, Any]) -> Pick:
    kind, source, size = str(offer["kind"]), str(offer["source"]), str(offer.get("size") or "")
    return Pick(key_of(source, kind, size), kind, source, size)


def media_order(kind: str) -> tuple[int, int]:
    kinds = [spec.kind for spec in MEDIA_SPECS]
    first = FIRST_MEDIA.index(kind) if kind in FIRST_MEDIA else len(FIRST_MEDIA)
    return (first, kinds.index(kind) if kind in kinds else len(kinds))


async def offers_for(library: Any, vps_id: str) -> tuple[dict[str, list[dict[str, Any]]],
                                                         dict[str, dict[str, Any]],
                                                         BaseException | None]:
    """What the sources being asked have for this game, by media kind, in the order the
    kinds are drawn; the sources by id; and what went wrong.

    Only the kinds some source holds and the library keeps are asked about, each once.
    """
    try:
        sources = await offload.io(library.media_sources)
    except Exception as exc:  # noqa: BLE001 - the Files group still draws
        logger.warning("manager: could not read the media sources", exc_info=True)
        return {}, {}, exc
    asked = {str(one["id"]): one for one in sources if one.get("enabled")}
    holds = {kind for one in asked.values() for kind in one.get("kinds") or ()}
    kinds = sorted(holds & library.kept_kinds()["media"], key=media_order)
    found = await asyncio.gather(
        *(offload.io(library.media_offers, vps_id, kind) for kind in kinds),
        return_exceptions=True)
    failed = next((one for one in found if isinstance(one, BaseException)), None)
    if failed is not None:
        logger.warning("manager: could not read what the sources have for %s", vps_id,
                       exc_info=failed)
    by_kind = {kind: list(one) for kind, one in zip(kinds, found, strict=True)
               if not isinstance(one, BaseException) and one}
    return by_kind, asked, failed


def mark(held: bool = False) -> None:
    """The column a check sits in, drawn on every row so the words line up."""
    with ui.element("span").classes("manager-record-mark"):
        if held:
            ui.icon("check").tooltip(t("manager.discovery.held"))


def _mark_of(move: Move) -> None:
    with ui.element("span").classes("manager-record-mark"):
        if move.state == IN:
            ui.icon("check")
        elif move.state == FAILED:
            ui.icon("error").classes("text-negative")
        elif move.state == DOWNLOADING:
            ui.spinner(size="xs")
        else:
            ui.icon("schedule").classes("manager-help")


def tick_cell(tray: Tray, pick: Pick) -> None:
    """The cell at the head of a row: a box to tick the row's file, and its state once it
    has moved. The box is withheld while a batch runs, so what is under way does not change."""
    holder = ui.element("span").classes("manager-record-tick")

    def draw() -> None:
        move = tray.moves.get(pick.key)
        if move is not None:
            _mark_of(move)
        elif tray.running:
            mark()
        else:
            ui.checkbox(value=pick.key in tray.picks,
                        on_change=lambda event: tray.set(pick, bool(event.value))) \
                .props("dense")

    tray.paint(pick.key, holder, draw)


def aside(tray: Tray, pick: Pick, rest: Callable[[], None],
          retry: Callable[[], Awaitable[Any]]) -> None:
    """The end of a row: what the row says of its file, until it has moved, and then the
    state it is in and the one thing to do about a failure."""
    holder = ui.column().classes("gap-0 items-end shrink-0 manager-record-aside")

    def draw() -> None:
        move = tray.moves.get(pick.key)
        if move is None:
            rest()
            return
        panel.state(t(_WORDS[move.state]), _LEVELS[move.state], hint=move.reason)()
        if move.state == FAILED:
            panel.action(t("manager.page.try_again"), retry, icon=verbs.RESET, inline=True,
                         hint=t("manager.discovery.try_again.help"))()

    tray.paint(pick.key, holder, draw)


def _said(tray: Tray) -> str:
    """One line for a batch on its way: how many, and where they have got to."""
    counts = [(state, sum(1 for one in tray.moves.values() if one.state == state))
              for state in (IN, DOWNLOADING, QUEUED, FAILED)]
    words = {IN: "manager.discovery.part.in", DOWNLOADING: "manager.discovery.part.downloading",
             QUEUED: "manager.discovery.part.queued", FAILED: "manager.discovery.part.needs_you"}
    parts = ", ".join(t(words[state], count=count) for state, count in counts if count)
    return t("manager.discovery.getting", count=tray.batch, parts=parts)


def status_row(tray: Tray, normal: Callable[[], None]) -> None:
    """The game's status row, which says how a batch is getting on while one is, with the
    way to end it, and `normal` otherwise."""
    holder = ui.row().classes("items-center gap-3 w-full no-wrap manager-vps-status")

    def draw() -> None:
        if not tray.running:
            normal()
            return
        ui.label(_said(tray)).classes("grow")
        panel.action(t("word.stop"), _stop(tray), icon=verbs.STOP, enabled=not tray.stopping,
                     hint=t("manager.discovery.stop.help"))()

    tray.paint(_STATUS, holder, draw)


def _stop(tray: Tray) -> Callable[[], None]:
    def stop() -> None:
        tray.stopping = True
        tray.repaint(_STATUS)

    return stop


def bar(context: dict[str, Any], tray: Tray, game_id: str,
        add: Callable[[], Awaitable[Any]]) -> None:
    """The foot of the pane, which is where the ticks are acted on. A game that is not in
    the library is added here, with whatever is ticked; one that is has nothing to ask
    until something is ticked."""
    in_library = bool(context["discovery"]["is_in_library"])
    holder = ui.row().classes("items-center gap-x-3 gap-y-1 w-full manager-draft-bar")

    def draw() -> None:
        waiting = tray.waiting()
        holder.set_visibility(not tray.running and (bool(waiting) or not in_library))
        if tray.running or not (waiting or not in_library):
            return
        with ui.row().classes("items-center gap-2 no-wrap min-w-0"):
            if waiting:
                ui.label(t("manager.discovery.ticked", count=len(waiting))) \
                    .classes("manager-draft-said")
        with ui.row().classes("items-center gap-2 no-wrap ml-auto"):
            if not waiting:
                panel.draft_button(t("manager.discovery.add"), add, icon=verbs.ADD,
                                   primary=True)
            else:
                panel.draft_button(
                    t("manager.discovery.add_with" if not in_library
                      else "manager.discovery.get_n", count=len(waiting)),
                    lambda: get(context, tray, game_id),
                    icon=verbs.ADD if not in_library else verbs.FETCH, primary=True,
                    hint=t("manager.discovery.add_with.help" if not in_library
                           else "manager.discovery.get_n.help"))

    tray.paint(_BAR, holder, draw)


async def redraw(state: dict[str, Any]) -> None:
    again = state.get("redraw_discovery")
    if not callable(again):
        return
    try:
        await again()
    except RuntimeError:
        logger.info("manager: the page was left before it could be redrawn")


@on_page
async def make_game(context: dict[str, Any]) -> dict[str, Any] | None:
    """A game from this entry, in the place new games go; None where the person declined
    the choice of place or the game could not be made, which is said on screen."""
    library, row = context["library"], context["discovery"]
    where = await import_dialog.ask_where(library)
    if where is None:
        return None
    try:
        made = await offload.io(library.add_game_from_vps, row["id"], where)
    except Exception as exc:  # noqa: BLE001
        logger.warning("manager: could not add %s", row["id"], exc_info=True)
        ui.notify(t("manager.discovery.add_failed", name=row["name"]), caption=why(exc),
                  type="negative")
        return None
    return made


@on_page
async def get(context: dict[str, Any], tray: Tray, game_id: str,
              only: Pick | None = None) -> None:
    """Get what is ticked, one file after another, in the game that holds this entry.

    A game not in the library is made first. Ending it with Stop leaves the files not yet
    started ticked, so the bar offers them again.
    """
    library, row, state = context["library"], context["discovery"], context["state"]
    if tray.running:
        return
    picks = [only] if only else tray.waiting()
    if not picks:
        return
    in_library = bool(row["is_in_library"])
    if in_library and not game_id:
        ui.notify(t("manager.discovery.game_unread"), type="negative")
        return
    tray.running, tray.stopping, tray.batch = True, False, len(picks)
    tray.repaint(_BAR, _STATUS, *(one.key for one in picks))
    for one in picks:
        tray.move(one.key, QUEUED)
    try:
        if not in_library:
            made = await make_game(context)
            if made is None:
                return
            game_id = str(made.get("id") or "")
            await redraw(state)
        for one in picks:
            if tray.stopping:
                break
            tray.move(one.key, DOWNLOADING)
            try:
                await offload.io(library.fetch_media, game_id, None, one.kind, one.source,
                                 row["id"], one.size)
            except Exception as exc:  # noqa: BLE001 - one refusal does not end the rest
                logger.warning("manager: could not get %s for %s", one.key, row["id"],
                               exc_info=True)
                tray.move(one.key, FAILED, why(exc))
                continue
            tray.move(one.key, IN)
    finally:
        tray.running = False
        for key in [key for key, one in tray.moves.items() if one.state in (QUEUED, DOWNLOADING)]:
            del tray.moves[key]
        tray.repaint_all()
    if any(tray.moves[one.key].state == IN for one in picks if one.key in tray.moves):
        await redraw(state)


def try_again(context: dict[str, Any], tray: Tray, game_id: str,
              pick: Pick) -> Callable[[], Awaitable[Any]]:
    async def again() -> None:
        if tray.running:
            return
        tray.forget(pick.key)
        await get(context, tray, game_id, only=pick)

    return again


def of_listing(listed_as: str) -> tuple[tuple[str, ...], str]:
    """Our kinds behind a VPS kind, and which inventory holds them. A table is an asset kind
    of its own, which `asset_kind` restricts an import to like any other."""
    kind = vps_kinds.BY_LISTING.get(listed_as)
    return (kind.ours, kind.held_in) if kind else (("table",), vps_kinds.ASSET)


def use_a_file(context: dict[str, Any], game_id: str, holder: Any, *, ours: tuple[str, ...],
               held_in: str, vps_file_id: str = "", add_table: bool = False) -> Callable[[], None]:
    """Make `holder` take a file dropped on it as this kind, and return the control that
    asks for one. The file is tied to `vps_file_id` when it has one, and goes into the game
    whether or not it is in the library yet.
    """
    single = ours[0] if len(ours) == 1 else ""

    @on_page
    async def arrived(drop: uploads.Drop) -> None:
        library, state = context["library"], context["state"]
        analysis = await uploads.analyzed(library, drop.upload_id)
        if analysis is None:
            return
        made, folder = game_id, ""
        if not context["discovery"]["is_in_library"]:
            added = await make_game(context)
            if added is None:
                await run.io_bound(library.abort_upload, drop.upload_id)
                return
            made, folder = str(added.get("id") or ""), str(added.get("folder") or "")
            await redraw(state)
        elif not made:
            await run.io_bound(library.abort_upload, drop.upload_id)
            ui.notify(t("manager.discovery.game_unread"), type="negative")
            return
        else:
            found: dict[str, Any] = next(
                (one for one in library.games if str(one.get("id")) == made), {})
            folder = str(found.get("folder") or "")

        async def tie(report: dict[str, Any], plan: dict[str, Any]) -> None:
            await _tie(library, made, folder, vps_file_id, ours, report, plan)

        async def done() -> None:
            await redraw(state)

        await uploads.confirmed_import(
            library, drop.upload_id, analysis, source=drop.name, file_count=drop.count,
            on_done=done, game_id=made, game_dir=folder,
            asset_kind=single if held_in == vps_kinds.ASSET else "",
            media_kind=single if held_in == vps_kinds.MEDIA else "",
            add_table=add_table, on_imported=tie)

    mediasource.take_drops(holder, arrived)

    def draw() -> None:
        heard = uploads.listener(arrived)
        panel.action(t("manager.discovery.use_file"), heard, icon=verbs.FROM_FILE,
                     hint=t("manager.discovery.use_file.help"),
                     js="() => window.__managerChoose(false, emit)")()

    return draw


@on_page
async def _tie(library: Any, game_id: str, folder: str, vps_file_id: str,
               ours: tuple[str, ...], report: dict[str, Any], plan: dict[str, Any]) -> None:
    """Record that what an import imported is this record. A tree of files is not one
    file, so a kind that arrives as one has nothing to tie."""
    if not vps_file_id or not game_id:
        return
    brought = set(report.get("imported") or ())
    try:
        if "table" in ours:
            await _tie_tables(library, game_id, vps_file_id, report, plan)
            return
        for item in plan.get("items") or ():
            if item.get("kind") not in brought or item.get("kind") not in ours:
                continue
            if item.get("action") not in _FILE_ACTIONS:
                continue
            path = PurePosixPath(Path(str(item["destination"])).relative_to(folder)).as_posix()
            await run.io_bound(library.set_asset_source, game_id, path, vps_file_id)
    except Exception as exc:  # noqa: BLE001 - the file is in; only the tracking failed
        logger.warning("manager: could not tie %s to %s", vps_file_id, game_id, exc_info=True)
        ui.notify(t("manager.discovery.tie_failed"), caption=why(exc), type="warning")


async def _tie_tables(library: Any, game_id: str, vps_file_id: str,
                      report: dict[str, Any], plan: dict[str, Any]) -> None:
    tables = list(report.get("added_tables") or ())
    if not tables:
        names = {Path(str(item["destination"])).name for item in plan.get("items") or ()
                 if item.get("action") == "replace_vpx"}
        rows = await offload.io(library.tables_for, game_id)
        tables = [str(one["id"]) for one in rows if one.get("filename") in names]
    for table_id in tables:
        await run.io_bound(library.set_table_source, game_id, str(table_id), vps_file_id)
