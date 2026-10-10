"""The panel that follows the selection.

Sections are declared, grouped by what they belong to, and remember which of them are
open. That last part is what makes stepping down a list a comparison rather than a run
of unrelated screens: the panel is rebuilt for every selection, so without a record the
shape you arranged is gone on the next arrow key.

The grouping is the answer to how a game and its tables sit together. Not a toggle
between them - which things are whose. A section under "This table" follows the lens
above it; the rest are the game's whatever build you are looking at.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import time
from collections import Counter
from collections.abc import Awaitable, Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from itertools import groupby
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlencode, urlparse

from nicegui import run, ui

from common import apps, config_schema, i18n, icons, install_identity, path_state, tokens
from common.apps import OWN_FIELDS
from common.failures import why
from common.games import asset_registry, tag_registry
from common.games.asset_registry import ALWAYS_KEPT as _ALWAYS_KEPT
from common.games.asset_resolver import VPX_ASSET_KINDS
from common.games.collection_filters import group_kind
from common.games.collection_store import (
    BUILTIN_ALL,
    DEFAULT_DIRECTION,
    DEFAULT_ORDER_BY,
    DIRECTION_WORDS,
    MANUAL_ORDER,
    NATURAL_DIRECTION,
    SORT_LABELS,
)
from common.i18n import t
from common.labels import field_label, humanize
from common.media_specs import PAGED_KINDS, media_family, media_label_map
from common.online import vps_kinds
from console import arrange as arranging
from console import (
    art,
    backglass_view,
    backup_rows,
    busy,
    candidates,
    collection_adds,
    collection_rules,
    community,
    confirm,
    deeplink,
    dof,
    dropdown,
    file_acts,
    game_acts,
    game_tables,
    grid,
    media_fill,
    media_ownership,
    mediamap,
    mediapages,
    mediasource,
    mediaview,
    offload,
    panel,
    pictures,
    plays_on,
    row_drag,
    screens,
    stars,
    table_features,
    tag_chips,
    tageditor,
    text_editor,
    thumbnails,
    undo,
    verbs,
    vps_match,
    vpx_displays,
    vpx_input,
    when,
)
from console import backups as backups_page
from console import commands as commands_help
from console import devices as devices_page
from console import dialog as frame
from console import launchers as launchers_page
from console import players as players_page
from console import record as recorder
from console import settings as settings_page
from console import themes as themes_page
from console.data import Library, config_groups, read_state, tag_source
from console.on_page import on_page

logger = logging.getLogger("vpinfe.console.workbench")

# Which group a section belongs to, in the order they are shown.
# Short, because the outline and the body would otherwise say the same three phrases
# twice on one screen. What each group means is carried by the lens sitting in it and
# by the sections themselves, not by shouting the scope.
# Where the split sits until somebody drags it. Enough for a preview and the facts
# under it without taking the map's room.
DOCK_PX = 300

# Where the open section sits among the rows where they stack. Three buckets rather
# than one order per row: flex keeps document order inside a bucket, so the rows above
# the open one and the rows below it each need only a number, and the work goes between.
_WORK = 1
_AFTER_WORK = 2

# Dragged in the browser, reported once on release - a round trip per pointer move
# would lag badly. Guarded, because the panel is rebuilt on every section change.
_GRIP = """
if (!window.__hubDockGrip) {
  window.__hubDockGrip = true;
  let drag = null;
  document.addEventListener('pointerdown', (e) => {
    const grip = e.target.closest && e.target.closest('.console-dock-grip');
    if (!grip) return;
    const main = grip.closest('.console-section-work');
    const dock = main && main.querySelector('.console-dock');
    if (!dock) return;
    e.preventDefault();
    drag = { y: e.clientY, from: dock.getBoundingClientRect().height, main };
    grip.setPointerCapture(e.pointerId);
  });
  document.addEventListener('pointermove', (e) => {
    if (!drag) return;
    e.preventDefault();
    const room = drag.main.getBoundingClientRect().height;
    // Both regions keep a floor, so a drag cannot leave either as a sliver.
    const next = Math.min(room - 160, Math.max(140, drag.from - (e.clientY - drag.y)));
    drag.main.style.setProperty('--dock-h', Math.round(next) + 'px');
  });
  const done = () => {
    if (!drag) return;
    const px = parseInt(drag.main.style.getPropertyValue('--dock-h'), 10);
    const drag_section = drag.main.dataset.dockSection || '';
    drag = null;
    if (px) emitEvent('hub_dock_px', {section: drag_section, px});
  };
  document.addEventListener('pointerup', done);
  document.addEventListener('pointercancel', done);
}
"""

# Dragging one member to a new place. Pointer events, not HTML5 drag-and-drop, for the
# reason the dock grip uses them: HTML5 drag fires no move events over its own source
# and is inert on touch.
# The panel is rebuilt on every write, so its scroll position has to be carried across
# by hand. Remembered on the window rather than in the panel's state: the value changes
# on every scroll frame and none of those are worth a round trip to Python.
_KEEP_SCROLL = """
(() => {
  const body = document.querySelector('.console-workbench-body');
  if (!body) return;
  const held = window.__hubListTop || (window.__hubListTop = {});
  const key = '%s';
  if (held[key]) body.scrollTop = held[key];
  if (body.dataset.scrollWired) return;
  body.dataset.scrollWired = '1';
  body.addEventListener('scroll', () => { held[key] = body.scrollTop; },
                        {passive: true});
})()
"""

_ADD_BOX = """
(() => {
  let tries = 0;
  const wire = () => {
    const vm = getElement(%d);
    const box = vm && vm.$refs.qRef;
    if (!box) { if (++tries < 40) setTimeout(wire, 25); return; }
    vm.findFilteredOptions = () => {
      const needle = vm.$el.querySelector('input[type=search]')?.value.toLocaleLowerCase();
      const joined = said => String(said ?? '').toLocaleLowerCase().replace(/[\\s.]+/g, '');
      return needle ? vm.initialOptions.filter(one =>
        String(one.label ?? '').toLocaleLowerCase().includes(needle)
        || joined(one.also).includes(joined(needle))) : vm.initialOptions;
    };
    vm.$watch('filteredOptions', () => setTimeout(() => {
      const typed = vm.$el.querySelector('input')?.value;
      if (typed && box.getOptionIndex() === -1) box.moveOptionSelection(1, true);
    }));
    if (%s) { box.focus(); box.showPopup(); }
  };
  wire();
})()
"""

_FOCUSABLE = "input:not(.hidden), textarea, button, [tabindex='0']"

# Where focus is on a setting, [[setting, which of its controls], which row]; [] for
# elsewhere in the panel or a dialog over it, null for outside both. Marks every setting
# drawn so far, so the one found afterwards is one the new draw made.
_FOCUSED_SETTING = """(() => {
  for (const one of document.querySelectorAll('[data-setting]')) one.dataset.drawn = '1';
  const at = document.activeElement;
  const one = at && at.closest('[data-setting]');
  if (!one) return at && at.closest('.console-workbench-body, .q-dialog') ? [] : null;
  const lines = [...document.querySelectorAll('.console-field-line[data-setting]')];
  return [[one.dataset.setting, [...one.querySelectorAll(FOCUSABLE)].indexOf(at)],
          lines.indexOf(at.closest('.console-field-line'))];
})()""".replace("FOCUSABLE", json.dumps(_FOCUSABLE))

_REFOCUS_SETTING = """(() => {
  const [places, row] = %s;
  let tries = 0;
  const look = () => {
    const drawn = [...document.querySelectorAll(
      '.console-field-line[data-setting]:not([data-drawn])')];
    if (!drawn.length) {
      if (++tries < 40) setTimeout(look, 25);
      return;
    }
    for (const [key, index] of places) {
      const one = document.querySelector(
        `[data-setting="${CSS.escape(key)}"]:not([data-drawn])`);
      if (!one) continue;
      const controls = [...one.querySelectorAll(FOCUSABLE)];
      (controls[index] || controls[0])?.focus();
      return;
    }
    if (row >= 0) drawn[Math.min(row, drawn.length - 1)].querySelector(FOCUSABLE)?.focus();
  };
  look();
})()""".replace("FOCUSABLE", json.dumps(_FOCUSABLE))


def _rebuilds(context: dict[str, Any], subject: str,
              again: Callable[[], Any], refresh_with: str = "refresh_game",
              refresh_of: str = "game_id", grid_first: bool = False) -> Callable[[], Any]:
    """A rebuild that puts the grid behind the panel right too. `grid_first` where the
    panel is drawn from what the grid holds, as a selection's menu is."""
    async def behind() -> None:
        """The grid, put right. Every write needs this; only some need a rebuild."""
        refresh = context.get("state", {}).get(refresh_with)
        if callable(refresh) and context.get(refresh_of):
            await refresh(context[refresh_of])

    async def rebuild() -> None:
        if grid_first:
            await behind()
            await again()
            return
        # Send nothing to the browser below this line. The slot is gone.
        await again()
        await behind()

    context["saved"] = behind
    return rebuild



# Where a fresh client lands, per rail. Identity, because selecting a row is usually
# navigation rather than curation: the first question a selection asks is what this is,
# and the answer is also where the things you can do to it live.
#
# Per rail rather than one value, because a rail declares its own landing place - and a
# table selected on purpose should not open on the machine that contains it.
DEFAULT_SECTION = {"game": "game_details", "table": "table_details",
                   # Games, not Details: a collection is opened to see
                   # what is in it far more often than to rename it.
                   "collection": "collection_games",
                   "theme": "theme_details", "player": "player_details"}
# Every section closed. No rail click reaches it, so it comes only from an address that
# says `section=none`. Named, because it travels in the state and the address, and
# "" appearing in either wants to be findable as a decision rather than as a blank.
COLLAPSED = ""

# Below this the outline costs more than it gives: 132px of it against a 320px
# workbench leaves the map too narrow to read, and the section headers are already
# a list of what is here. It earns its place once there is room for both.
#
# Enforced in CSS by a container query, not here. Quasar resizes the pane live while
# you drag and only tells the server on release, so a server-side threshold changed
# the layout a beat after you let go - which is exactly when you can no longer see
# what you were aiming at.
OUTLINE_FROM_PX = 520

# The panel's own vocabulary, which this surface no longer keeps a second copy of.
# Still named here because the call sites below read better for it.
HEADING = panel.HEADING
FULL = panel.FULL



@dataclass(frozen=True)
class Section:
    """One block in the panel: what it is called and how to draw it.

    One name, on the row that opens it. There is no second heading over the content,
    because the row is the heading.

    `label` takes the context, since a name that counts something has to count this
    game's. `build` is async because a section may need a fetch.
    """

    key: str
    label: Callable[[dict[str, Any]], str]
    build: Callable[[dict[str, Any]], Any]
    # What this section is about. The rail is what the selected subject can be asked,
    # so a section that only makes sense for one of them says so and is simply absent
    # for the other - rather than being present and answering a question nobody asked.
    # Keys stay unique across every rail, so `section=` in an address means one thing.
    subjects: frozenset[str] = frozenset({"game", "table"})
    # Whether this subject can answer for it right now. A section that would open onto
    # nothing leaves the rail rather than sitting there empty - offering a settings
    # editor for a program that is not on this machine is a form of lying, and an empty
    # row is a place somebody goes once and learns to stop trusting.
    shown: Callable[[dict[str, Any]], bool] | None = None
    # Whether this section works on a picked thing beside its browse region. Only the
    # one that has something to pick declares it: reserving the room everywhere left
    # a section like Game details as four lines of text over an empty half-panel,
    # with the sections under it pushed to the bottom edge. A predicate on the context
    # where it depends on the subject: a file with nothing to show has no stage.
    dock: bool | Callable[[dict[str, Any]], bool] = False
    # A heading over the run of sections it starts. Empty for a rail short enough to
    # read without one, which every rail now is.
    group: str = ""


def sections_for(subject: str) -> tuple[Section, ...]:
    """The rail for this subject, in order."""
    return tuple(item for item in SECTIONS if subject in item.subjects)


def _docked(item: Section, context: dict[str, Any]) -> bool:
    return item.dock(context) if callable(item.dock) else item.dock


def dock_height(state: dict[str, Any], section: str) -> int:
    """The height the user dragged this section's dock to, or the default."""
    return int((state.get("dock_px") or {}).get(section) or DOCK_PX)


def dock_dragged(state: dict[str, Any], args: Any) -> None:
    """The browser's report of a drag: the section it was in and the height it ended at."""
    if not isinstance(args, dict):
        return
    section = str(args.get("section") or "")
    px = args.get("px")
    if section and isinstance(px, (int, float)) and px > 0:
        state.setdefault("dock_px", {})[section] = int(px)


def chosen_section(state: dict[str, Any], subject: str = "game",
                   rail: tuple[Section, ...] | None = None) -> str:
    """The section this client is on, seeded once and kept across games.

    "" when every section is closed, which is a place like any other.

    Held across games so stepping down a list does not re-pick a section at every stop,
    which is what looking at one kind across a library needs. Held across subjects too
    where it can be - but a section the new subject has no answer for is not one of
    those, and then the rail's own default is where you land rather than wherever the
    list happens to start.
    """
    rail = sections_for(subject) if rail is None else rail
    known = {item.key for item in rail}
    if state.get("section") == COLLAPSED:
        # Asked for by the address, so it is kept - including across a change of subject.
        # Seeding a default here would reopen a panel the address said to leave closed.
        return COLLAPSED
    if subject == "all_games":
        return rail[0].key
    if state.get("section") not in known:
        wanted = DEFAULT_SECTION.get(subject, "")
        state["section"] = wanted if wanted in known else rail[0].key
    return state["section"]


async def build(container: ui.column, title: ui.column, library: Library,
                game_id: str | None, state: dict[str, Any] | None = None,
                table_id: str = "") -> None:
    """Fill the panel, and the name that lives up in the panel's header row.

    `table_id` is the subject when the Tables lens is what selected it. Empty means the
    game itself, which is what the Games lens selects.
    """
    state = state if state is not None else {}
    await _pane_build(container, state,
                      lambda: _draw(container, title, library, game_id, state, table_id))


async def _pane_build(container: ui.column, state: dict[str, Any],
                      draw: Callable[[], Awaitable[None]]) -> None:
    """One pane build, after any already running, with the pane busy from the call
    until the build that draws has drawn.

    Builds are serialized, and a superseded one gives up rather than drawing. Without
    this the panel doubles: clearing happens after the reads and the drawing after that,
    so two builds that overlap both clear an empty container and then both append. A
    drag can start three - the divider, the mode it settles, and the window listener -
    so this is the ordinary case, not the rare one.
    """
    lock: asyncio.Lock = state.setdefault("build_lock", asyncio.Lock())
    state["build_seq"] = mine = state.get("build_seq", 0) + 1
    with busy.held(container, over=True):
        async with lock:
            if state["build_seq"] != mine:
                return
            await draw()


async def _draw(container: ui.column, title: ui.column, library: Library,
                game_id: str | None, state: dict[str, Any], table_id: str = "") -> None:
    if game_id is None:
        _blank(container, title, t("console.page.game"),
               t("console.page.select_game"))
        return
    game = next((entry for entry in library.games if entry["id"] == game_id), None)
    if game is None:
        _blank(container, title, t("console.page.game"),
               t("console.page.not_library"))
        return
    # Off the loop, always. This is an HTTP call to our own process: made on the
    # event loop it blocks the server from answering it, the request times out
    # after 15s, and the browser reports the socket as lost rather than slow.
    #
    # And read *before* clearing. Clearing first leaves the panel empty for the whole
    # round trip, which after a write reads as the panel flashing black - the write,
    # the reread and the redraw are one act to the person who asked for it.
    tables = await offload.io(library.tables_for, game_id)
    # Off the loop and once, beside the tables: every table row offers the same list, so
    # asking per row would be one blocking HTTP call per table - and the Console consumes
    # its own process, so a blocking call here does not just cost time, it deadlocks.
    launcher_listing = await offload.io(_launchers_for_panel, library)
    await offload.io(library.media_for, game_id, None)
    # The header menu's collections, read here for the same reason as the tables.
    collections = await collection_adds.read(library, str(state.get("collection") or ""))
    in_collections = await _collections_held(library, game_id)

    container.clear()
    title.clear()
    with container:
        made = game_tables.made(game)
        _title(title, game.get("name") or "", made)
        # Named under the game once a file is the subject, so the header says which of
        # the four you are looking at without a control to read.
        chosen = next((t for t in tables if t.get("id") == table_id), None)
        if chosen is not None:
            with title:
                ui.label(_table_line(chosen, tables)).classes("console-workbench-table") \
                    .tooltip(str(chosen.get("filename") or ""))
        # `lens` is a table id or "" for the folder's shared files, and it resets per
        # game because a table id means nothing to the next one. `redraws` is how the
        # lens reaches the sections that follow it without rebuilding the panel.
        # The picked slot lives with the client, not this build of the panel: a mode
        # change rebuilds and would otherwise forget it. Kept across games too, which
        # is what sweeping one kind down a list needs.
        state.setdefault("slot", {"kind": None})
        # The lens is the grid's selection, not a control in here. Under Games that is
        # the game and the panel answers for shared files; under Tables it is one file
        # and the panel answers for that.
        context = {"library": library, "game": game, "game_id": game_id,
                   "tables": tables, "launchers": launcher_listing, "state": state,
                   "collections": collections, "in_collections": in_collections,
                   "lens": table_id, "redraws": [], "slot": state["slot"]}

        # The subject has to survive a rebuild. Left off, every rail click fell
        # back to the game and the table's own sections vanished under the cursor.
        context["rebuild"] = _rebuilds(
            context, f"{game_id}:{table_id}",
            lambda: build(container, title, library, game_id, state, table_id))
        # The panel showing now, for a message that outlives the one that raised it.
        state["panel_rebuild"] = context["rebuild"]
        await _rail(context, "table" if table_id else "game", state)


async def build_collection(container: ui.column, title: ui.column, library: Library,
                           name: str | None, state: dict[str, Any] | None = None) -> None:
    """The panel, for a collection rather than a game.

    Its own entry point rather than a branch inside `build`: a collection has no game,
    no tables and no media lens, so everything that build assembles for those would be
    a chain of empty values threaded through to sections that never read them.
    """
    state = state if state is not None else {}
    await _pane_build(container, state,
                      lambda: _draw_collection(container, title, library, name, state))


async def build_all_games(container: ui.column, title: ui.column, library: Library,
                          state: dict[str, Any] | None = None) -> None:
    """The panel for the whole library: not a collection, so it carries the one setting
    that is about it and nothing a collection edits."""
    state = state if state is not None else {}
    await _pane_build(container, state,
                      lambda: _draw_all_games(container, title, library, state))


async def build_selection(container: ui.column, title: ui.column, library: Library,
                          table_ids: Sequence[str], state: dict[str, Any] | None = None,
                          ) -> None:
    """The panel, for the tables ticked in the Tables grid: one subject that answers for
    all of them."""
    state = state if state is not None else {}
    await _pane_build(container, state,
                      lambda: _draw_selection(container, title, library, table_ids, state))


async def _draw_selection(container: ui.column, title: ui.column, library: Library,
                          table_ids: Sequence[str], state: dict[str, Any]) -> None:
    wanted = set(table_ids)
    rows = await offload.io(library.load_tables)
    tables = [row for row in rows if row.get("id") in wanted]
    if not tables:
        _blank(container, title, t("console.page.table"), t("console.page.select_table"))
        return
    launcher_listing = await offload.io(_launchers_for_panel, library)
    container.clear()
    title.clear()
    with container:
        _title(title, t("console.games.tables", count=len(tables)),
               t("console.page.selection"))
        context: dict[str, Any] = {
            "library": library, "tables": tables, "launchers": launcher_listing,
            "state": state, "redraws": [], "dock": None,
            "game_ids": sorted({str(one.get("game_id") or "") for one in tables})}
        context["rebuild"] = _rebuilds(
            context, "selection",
            lambda: build_selection(container, title, library, table_ids, state),
            refresh_with="refresh_tables", refresh_of="game_ids", grid_first=True)
        # The rail's one section is not a place to come back to: the table that is shown
        # next lands where the last one did.
        kept = state.get("section")
        await _rail(context, "selection", state)
        if kept is None:
            state.pop("section", None)
        else:
            state["section"] = kept


async def build_game_selection(container: ui.column, title: ui.column, library: Library,
                               game_ids: Sequence[str],
                               state: dict[str, Any] | None = None) -> None:
    """The panel, for the games ticked in the Games grid."""
    state = state if state is not None else {}
    await _pane_build(container, state,
                      lambda: _draw_game_selection(container, title, library, game_ids,
                                                   state))


async def _draw_game_selection(container: ui.column, title: ui.column, library: Library,
                               game_ids: Sequence[str], state: dict[str, Any]) -> None:
    wanted = set(game_ids)
    games = [game for game in library.games if game.get("id") in wanted]
    if not games:
        _blank(container, title, t("console.page.game"), t("console.page.select_game"))
        return
    container.clear()
    title.clear()
    with container:
        _title(title, t("console.games.games", count=len(games)),
               t("console.page.selection"))
        context: dict[str, Any] = {
            "library": library, "games": games, "state": state, "redraws": [],
            "dock": None, "game_ids": sorted(wanted)}
        context["rebuild"] = _rebuilds(
            context, "game_selection",
            lambda: build_game_selection(container, title, library, game_ids, state),
            refresh_with="refresh_games", refresh_of="game_ids", grid_first=True)
        kept = state.get("section")
        await _rail(context, "game_selection", state)
        if kept is None:
            state.pop("section", None)
        else:
            state["section"] = kept


async def build_tag(container: ui.column, title: ui.column, library: Library,
                    name: str | None, state: dict[str, Any] | None = None) -> None:
    """The panel, for one tag."""
    state = state if state is not None else {}
    await _pane_build(container, state,
                      lambda: _draw_tag(container, title, library, name, state))


async def _draw_tag(container: ui.column, title: ui.column, library: Library,
                    name: str | None, state: dict[str, Any]) -> None:
    if not name:
        _blank(container, title, t("console.page.tag"), t("console.page.select_tag"))
        return
    look = library.tag_looks().get(name)
    if look is None:
        _blank(container, title, t("console.page.tag"), t("console.page.gone"))
        return
    container.clear()
    title.clear()
    with container:
        count, tables = int(look.get("games") or 0), int(look.get("tables") or 0)
        _title(title, name, t("console.tags.on_games", count=count) if count
               else t("console.tags.on_tables", count=tables) if tables
               else t("console.tags.on_no_games"))
        context: dict[str, Any] = {"library": library, "name": name, "tag": look,
                                   "state": state, "redraws": [], "dock": None}
        context["rebuild"] = _rebuilds(
            context, f"tag:{name}",
            lambda: build_tag(container, title, library, state.get("tag"), state))
        await _rail(context, "tag", state)


async def _tag_changed(context: dict[str, Any], name: str | None) -> None:
    """The grid and the panel, after a write - the panel following the tag to `name`."""
    context["state"]["tag"] = name
    refresh = context["state"].get("refresh_tags")
    if callable(refresh):
        await refresh()
    await context["rebuild"]()


async def _tag_details(context: dict[str, Any]) -> None:
    library, name, look = context["library"], context["name"], context["tag"]

    @on_page
    async def rename(value: str) -> None:
        said = " ".join(str(value or "").split())
        if not said or said == name:
            return
        if said in library.tag_looks() and not await confirm.ask(
                t("console.tageditor.merge", into=said),
                detail=t("console.tageditor.merge_detail"),
                confirm=t("word.merge"), icon=verbs.MERGE):
            await context["rebuild"]()
            return
        try:
            await run.io_bound(library.merge_tags, [name], said)
        except Exception as exc:  # noqa: BLE001
            ui.notify(t("said.action_failed"), caption=why(exc), type="negative")
            return
        await _tag_changed(context, said)

    @on_page
    async def describe(value: str) -> None:
        try:
            await run.io_bound(library.put_tag, name, {"description": value})
        except Exception as exc:  # noqa: BLE001
            ui.notify(t("said.action_failed"), caption=why(exc), type="negative")
            return
        refresh = context["state"].get("refresh_tags")
        if callable(refresh):
            await refresh()

    sources = list(look.get("sources") or [])
    _rows(ui, [
        (t("console.tageditor.tag"), name if sources else panel.field(name, rename)),
        *[(t("console.tags.from"), partial(_tag_source, one)) for one in sources],
        (t("console.workbench.description"), panel.field(str(look.get("description") or ""),
                                            describe, lines=2)),
        (t("console.tags.color"), partial(_swatches, context)),
    ])


def _tag_source(said: dict[str, Any]) -> None:
    with ui.column().classes("gap-0 min-w-0"):
        panel.link(tag_source(said), to=community.address(str(said.get("extension") or ""),
                                                          str(said.get("list") or "")))()
        panel.line(read_state(said), hint=str(said.get("error") or ""))


def _swatches(context: dict[str, Any]) -> None:
    library, name, look = context["library"], context["name"], context["tag"]
    chosen = str(look.get("color") or "") if look.get("chosen") else ""

    @on_page
    async def pick(color: str) -> None:
        try:
            await run.io_bound(library.put_tag, name, {"color": color})
        except Exception as exc:  # noqa: BLE001
            ui.notify(t("said.action_failed"), caption=why(exc), type="negative")
            return
        await _tag_changed(context, name)

    tag_chips.swatches(chosen, tag_registry.derived_color(name), pick)


def _carried(row: dict[str, Any]) -> list[str]:
    return [*((row.get("user") or {}).get("tags") or []), *(row.get("derived_tags") or [])]


async def _tag_games(context: dict[str, Any]) -> None:
    name = context["name"]
    library = context["library"]
    carrying = [one for one in library.games if name in _carried(one)]
    wants_tables = context["tag"].get("tables")
    listing = (await offload.io(library.load_tables)
               if wants_tables or library.thumbnail() else [])
    tables = [one for one in listing if name in _carried(one)] if wants_tables else []
    shown = library.game_art()
    look = library.thumbnail_look()
    with ui.column().classes("gap-0 console-form w-full min-w-0"):
        if not carrying and not tables:
            ui.label(t("console.tags.on_no_games")).classes("console-help px-3")
        for game in sorted(carrying, key=lambda one: str(one.get("name") or "").lower()):
            to = "/console?" + deeplink.query({"view": "games", "game": game["id"]})
            with ui.row().classes("items-center gap-2 w-full no-wrap console-member-row"), \
                    thumbnails.beside(None if shown is None else shown.get(game["id"], ""),
                                      icons.GAMES, to=to, look=look), \
                    ui.column().classes("gap-0 grow min-w-0"):
                panel.link(str(game.get("name") or ""), to=to)()
                _said_line(game_tables.made(game))
        if tables:
            ui.label(t("console.tageditor.tables")).classes("console-group px-3 mt-2")
        for table in tables:
            to = "/console?" + deeplink.query({"view": "tables",
                                               "game": str(table.get("game_id") or ""),
                                               "table": str(table.get("id") or "")})
            with ui.row().classes("items-center gap-2 w-full no-wrap console-member-row"), \
                    thumbnails.beside(None if shown is None else thumbnails.address(table),
                                      icons.TABLES, to=to, look=look), \
                    ui.column().classes("gap-0 grow min-w-0"):
                panel.link(str(table.get("game") or table.get("name") or ""), to=to)()
                _said_line(game_tables.made(table), table)


async def build_file(container: ui.column, title: ui.column, library: Library,
                     row: dict[str, Any] | None, state: dict[str, Any] | None = None,
                     family: str = "media") -> None:
    """The panel, for one media or asset file. `family` is `media` or `assets`."""
    state = state if state is not None else {}
    await _pane_build(container, state,
                      lambda: _draw_file(container, title, library, row, state, family))


def _same_file(rows: list[dict[str, Any]], wanted: dict[str, Any]) -> dict[str, Any] | None:
    """The row `wanted` was, read again: by id; else by table and kind, which is all an
    address names; else the kind's shared row, which is what a table's own file that
    was just removed leaves behind; else, when it names no table, the kind's row on any
    table."""
    exact = next((one for one in rows if wanted.get("id") and one.get("id") == wanted["id"]),
                 None)
    if exact is not None:
        return exact
    kind = [one for one in rows if one.get("kind") == wanted.get("kind")]
    table = str(wanted.get("table") or "")
    for alike in ([one for one in kind if (one.get("table") or "") == table],
                  [one for one in kind if not one.get("table")],
                  [] if table else kind):
        if alike:
            return next((one for one in alike if one.get("present")), alike[0])
    return None


async def _draw_file(container: ui.column, title: ui.column, library: Library,
                     row: dict[str, Any] | None, state: dict[str, Any],
                     family: str) -> None:
    media = family == "media"
    heading = t("console.page.media" if media else "console.page.assets")
    if not row:
        _blank(container, title, heading, t("console.page.select_media" if media
                                             else "console.page.select_asset"))
        return
    game_id = str(row.get("game_id") or "")
    game = next((one for one in library.games if one["id"] == game_id), None)
    if game is None:
        _blank(container, title, heading, t("console.page.not_library"))
        return
    files = await offload.io(library.files_of, "media" if media else "asset", game_id)
    found = _same_file(files, row)
    if found is None:
        _blank(container, title, heading, t("console.page.gone"))
        return
    tables = await offload.io(library.tables_for, game_id)
    table_id = str(found.get("table") or "")
    detail = {} if media else await _asset_detail_of(library, game_id, found)
    settings = None if media else await _file_settings(library, found, files, tables, detail)
    container.clear()
    title.clear()
    with container:
        _file_title(title, found, game, next((one for one in tables
                                              if one.get("id") == table_id), None))
        context: dict[str, Any] = {"library": library, "game": game, "game_id": game_id,
                                   "tables": tables, "state": state, "lens": table_id,
                                   "redraws": [], "dock": None, "row": found,
                                   "served": _served(found, files, tables),
                                   "kind": str(found.get("kind") or ""), "detail": detail,
                                   "slot": {"kind": found.get("kind")}}
        context["rebuild"] = _rebuilds(
            context, f"file:{found.get('id')}",
            lambda: build_file(container, title, library, found, state, family),
            refresh_with="refresh_files")
        if settings is not None:
            context["file_settings"] = {**settings, "state": state,
                                        "rebuild": context["rebuild"],
                                        "refresh_grid": context["saved"], "fits": {}}
        await _rail(context, "media_file" if media else "asset_file", state)


def _file_title(target: ui.column, row: dict[str, Any], game: dict[str, Any],
                table: dict[str, Any] | None) -> None:
    with target:
        ui.label(str(row.get("named") or row.get("label") or row.get("kind") or "")) \
            .classes("text-base console-workbench-title leading-tight truncate")
        with ui.element("div").classes("text-xs console-workbench-label "
                                       "console-workbench-links"):
            panel.link(str(game.get("name") or ""), to="/console?" + deeplink.query(
                {"view": "games", "game": game["id"]}))()
        orphan = file_acts.tier_of(row) == media_ownership.ORPHAN
        if table is None and not orphan:
            return
        with ui.element("div").classes("console-workbench-table console-workbench-links"):
            if table is not None:
                panel.link(_table_line(table), to="/console?" + deeplink.query(
                    {"view": "tables", "game": game["id"], "table": table["id"]}))()
            else:
                ui.label(str(row.get("table_file") or ""))


async def _asset_detail_of(library: Library, game_id: str,
                           row: dict[str, Any]) -> dict[str, Any]:
    path = str(row.get("path") or "")
    if not (row.get("present") and path):
        return {}
    try:
        detail = await offload.io(library.asset_detail, game_id, path)
    except Exception:  # noqa: BLE001 - the panel draws without what it would add
        logger.debug("No detail for %s", path, exc_info=True)
        return {}
    if text_editor.edits(str(row.get("kind") or "")):
        try:
            detail = {**detail, "text": await offload.io(library.asset_text, game_id, path)}
        except Exception:  # noqa: BLE001 - not text, or not readable: the head stands in
            logger.debug("No text for %s", path, exc_info=True)
    return detail


def _media_has_stage(context: dict[str, Any]) -> bool:
    """A loose file is drawn from its path, so one with no path or no game folder has
    nothing to put in the stage."""
    row = context.get("row") or {}
    if not row.get("present"):
        return False
    if file_acts.is_loose(row):
        return bool((context.get("game") or {}).get("folder") and row.get("path"))
    return True


def _asset_has_stage(context: dict[str, Any]) -> bool:
    """A picture or the head of a text file: what is drawn from the file itself. A
    folder, a ROM, a damaged backglass or an absent file is only an icon, which the
    column carries."""
    detail = context.get("detail") or {}
    glass = detail.get("backglass") if context.get("kind") == "backglass" else None
    return (bool(glass and not glass["damaged"]) or bool(detail.get("head"))
            or bool(detail.get("text")))


def _stage(context: dict[str, Any]) -> ui.element:
    """The dock's one child: a box with a size of its own, so what is drawn in it can
    fill it."""
    with context["dock"]:
        return ui.element("div").classes("console-stage")


async def _media_file_block(context: dict[str, Any]) -> None:
    library, game_id, table_id = context["library"], context["game_id"], context["lens"]
    row, kind = context["row"], context["kind"]
    if file_acts.is_loose(row):
        _loose_media(context)
        return
    page = int(row.get("page") or 1)
    entries = await offload.io(library.media_for, game_id, table_id or None)
    context["media"] = entries
    context["devices"] = await offload.io(library.known_devices)
    try:
        detail = await offload.io(library.media_detail, game_id, table_id or None, kind,
                                  page)
    except Exception:
        logger.debug("No detail for %s", kind, exc_info=True)
        detail = None
    overrides = {} if table_id else await run.io_bound(library.media_overrides, game_id)
    links = (await offload.io(library.outside_links, game_id, "", str(row["path"]))
             if row.get("present") and row.get("path") else [])
    entry = entries.get(kind) or {}
    matched = await _match_line(context, kind, (detail or {}).get("matched_to")
                                or entry.get("matched_to"))
    if context["dock"] is not None:
        with _stage(context):
            _slot_art(context, kind, entry, page)
    _slot(context, kind, entry, detail, context["rebuild"],
          (overrides or {}).get(kind) or [], titled=False, in_place=False, scope_chip=False,
          links=links, matched=matched, draw_art=False, page=page,
          waiting=await recorder.waiting_on(library, game_id, table_id or "", kind))


def _loose_media(context: dict[str, Any]) -> None:
    """No acts here: the slot's would act on the file the slot resolves to, which is
    another one."""
    row, kind = context["row"], context["kind"]
    tier = file_acts.tier_of(row)
    folder = str(context["game"].get("folder") or "")
    path = str(row.get("path") or "")
    if context["dock"] is not None and folder and path:
        with _stage(context), ui.element("div").classes("console-slot-art"):
            mediaview.preview("/api/v1/filesystem/file?" + urlencode(
                {"path": str(PurePosixPath(folder) / path)}), kind,
                str(row.get("label") or kind))
    with ui.column().classes("w-full gap-1 console-slot p-2"):
        with ui.column().classes("w-full gap-0 console-slot-facts"):
            with ui.row().classes("items-start gap-2 w-full no-wrap"):
                where = _on_disk(context, path)
                named = ui.label(path or str(row.get("file") or "")) \
                    .classes("console-slot-file grow min-w-0")
                if where:
                    named.tooltip(where)
                    panel.copy_text(where)
                media_ownership.badge(tier)
            ui.label(t(media_ownership.tier_for(tier).why)).classes("console-help")


def _on_disk(context: dict[str, Any], path: str) -> str:
    """Where a file the game's folder holds is on this machine, from the path it is
    addressed by there. Empty when the folder or the path is not known."""
    folder = str((context.get("game") or {}).get("folder") or "")
    return str(Path(folder) / path) if folder and path else ""


def _file_line(context: dict[str, Any], kind: str, name: str, view: str,
               path: str = "") -> None:
    """A file's name, which opens the file's own panel in `view` where a dock draws it,
    with the whole path on hover and Copy path after it. `view` is "" in the file's own
    panel, where the name is already that panel's."""
    classes = "console-slot-file grow min-w-0"
    where = _on_disk(context, path)
    if not view:
        named = ui.label(name).classes(classes)
        if where:
            named.tooltip(where)
    else:
        table = str((context.get("row") or {}).get("table") or context["lens"] or "")
        to = "/console?" + deeplink.query({"view": view, "game": context["game_id"],
                                           "table": table, "slot": {"kind": kind}})
        panel.link(name, to=to, classes=classes, hint=where)()
    if where:
        panel.copy_text(where)


def _asset_said(context: dict[str, Any], tier: str) -> str:
    """Who uses the file in the panel, from what it serves.

    Unused is two things: a kind no table loads by the folder's name, and a shared file
    every table has its own beside.
    """
    lens = context["lens"]
    if tier == media_ownership.UNUSED:
        if any(one.key == context["kind"] and one.folder_fallback
               for one in VPX_ASSET_KINDS):
            return t(media_ownership.tier_for(tier).why)
        return t("console.workbench.inert_asset")
    if (tier == media_ownership.GAME and not lens
            and len(context["served"]) < len(context["tables"])):
        return t("console.workbench.shared_by_some")
    return media_ownership.sentence(tier, viewing_a_table=bool(lens))


async def _asset_file_block(context: dict[str, Any]) -> None:
    row, kind, detail = context["row"], context["kind"], context["detail"]
    present, path = bool(row.get("present")), str(row.get("path") or "")
    library, game_id = context["library"], context["game_id"]
    label = str(row.get("label") or _asset_name(kind))
    tier = file_acts.tier_of(row)
    links = (await offload.io(library.outside_links, game_id, "", path)
             if present and path else [])
    glass = detail.get("backglass") if kind == "backglass" else None
    spoken: dict[str, ui.label] = {}

    async def after_save() -> None:
        """The size and date under the name, as the file is now."""
        try:
            fresh = await offload.io(library.asset_detail, game_id, path)
        except Exception:  # noqa: BLE001 - the line stays as it was
            return
        detail.update({one: fresh[one] for one in fresh if one != "text"})
        if "spec" in spoken and not spoken["spec"].is_deleted:
            spoken["spec"].text = _asset_spec(detail)

    context["after_save"] = after_save
    if context["dock"] is not None:
        with _stage(context):
            await _asset_stage(context, path, glass, str(detail.get("head") or ""), label)

    def identity(*, facts: bool) -> None:
        if not present:
            ui.label(t("console.workbench.missing_table", kind=label)
                     if context["lens"]
                     else t("console.workbench.missing_game", kind=label)) \
                .classes("console-help")
            return
        with ui.row().classes("items-start gap-2 w-full no-wrap"):
            _file_line(context, kind, path, str(context.get("link_view") or ""), path)
            if tier not in media_ownership.SCOPES:
                media_ownership.badge(tier)
            if glass and not glass["damaged"]:
                _backglass_chips(glass)
        spec = _asset_spec(detail)
        if spec:
            spoken["spec"] = ui.label(spec).classes("console-help")
        if glass and glass["damaged"]:
            _alert(t("console.backglass.damaged"), None)()
        elif glass and facts:
            panel.facts(ui, _backglass_facts(context, glass))
        said = _asset_said(context, tier)
        if said:
            ui.label(said).classes("console-help")
        origin = str(row.get("origin") or "")
        if origin and origin not in ("unknown", "user"):
            ui.label(t("console.workbench.source",
                       source_name=media_ownership.source_name(origin))) \
                .classes("console-help")
        _outside_lines(links)

    def acts() -> None:
        _asset_actions(context, kind, label, present, path, tier, detail)

    if context.get("link_view"):
        with ui.column().classes("w-full gap-1 console-slot p-2"):
            with ui.column().classes("w-full gap-0 console-slot-facts"):
                identity(facts=True)
            acts()
        return
    async def form_entries() -> list[tuple[Any, Any]]:
        entries: list[tuple[Any, Any]] = [
            (panel.HEADING, t("word.file")),
            (panel.FULL, lambda: identity(facts=False))]
        if kind in file_acts.WHOLE_FOLDER or kind in file_acts.PLACEABLE:
            entries.append((panel.FULL, acts))
        if glass and not glass["damaged"] and (about := _backglass_facts(context, glass)):
            entries += [(panel.HEADING, t("console.workbench.details")),
                        *((panel.READ, entry) for entry in about)]
        if "file_settings" in context:
            entries += await _file_settings_entries(context)
        return entries

    first = await form_entries()
    with ui.column().classes("w-full gap-0 console-form") as form:
        panel.facts(ui, first)

    async def redraw_form() -> None:
        entries = await form_entries()
        form.clear()
        with form:
            panel.facts(ui, entries)
    if "file_settings" in context:
        context["file_settings"]["redraw_form"] = redraw_form


async def text_lock(library: Library, kind: str,
                     found: dict[str, Any]) -> tuple[str, str]:
    """Why a text file cannot be saved right now and what to say about it, or two blanks."""
    if kind == "ini" and await offload.io(_playing, library):
        return t(PLAYING_NOTE), t(PLAYING_WHY)
    if not found["editable"]:
        return str(found["why"]), ""
    return "", ""


async def _asset_stage(context: dict[str, Any], path: str, glass: dict[str, Any] | None,
                       head: str, label: str) -> None:
    if glass and not glass["damaged"]:
        await _backglass_picture(context, path, glass, label)
        return
    if found := context["detail"].get("text"):
        locked, help_ = await text_lock(context["library"], context["kind"], found)
        text_editor.editor(context, path, label, found, locked, help_)
        return
    with ui.element("div").classes("console-slot-art console-slot-art--text"):
        ui.label(head).classes("console-file-text")
        _enlarge(lambda: _open_whole(context, path, label))


def _enlarge(act: Callable[[], Any]) -> None:
    ui.button(icon=verbs.ENLARGE, on_click=act).props("flat dense round size=sm") \
        .classes("console-slot-zoom").tooltip(t("word.enlarge"))


async def _backglass_picture(context: dict[str, Any], path: str, glass: dict[str, Any],
                             label: str) -> None:
    """The file's picture: the window as VPX draws it where the program's settings are
    known, and otherwise the picture with the lamps lit at start."""
    game_id = context["game_id"]
    if (inner := context.get("file_settings")) is not None:
        try:
            held = backglass_view.flat(await _config_values(inner))
        except Exception:  # noqa: BLE001 - the picture stands without the settings
            logger.exception("Could not read the settings behind the backglass preview")
        else:
            memory = inner["state"].setdefault("backglass_preview", {}).setdefault(path, {})
            backglass_view.preview(game_id, path, glass, label, held,
                                   inner.setdefault("followers", []), _enlarge,
                                   None if inner.get("playing") else partial(_write_overlay, inner),
                                   memory, inner["fits"])
            return
    with ui.element("div").classes("console-slot-art"):
        mediaview.preview(art.backglass(game_id, path, version=glass["version"],
                                        size=art.PANEL), "backglass", label)
        _enlarge(lambda: mediaview.open_image(
            art.backglass(game_id, path, version=glass["version"]), label))


async def config_applied(write: Callable[..., Any], values: dict[str, str]) -> Any:
    """`values` through a panel's `config_write`, which is a coroutine function where the
    write waits on a job and a plain one, to run off the loop, where it does not."""
    if inspect.iscoroutinefunction(write):
        return await write(values)
    return await run.io_bound(write, values)


@on_page
async def _write_overlay(inner: dict[str, Any], values: dict[str, str], *,
                         in_place: bool = False) -> None:
    """Write a box dragged or found on the preview where the settings panel beside it
    writes, then draw again from what is now held: the file's form and the preview where
    `in_place` and the form can be drawn on its own, the whole panel otherwise."""
    try:
        if (write := inner.get("config_write")) is not None:
            wrote = await config_applied(write, values)
        else:
            wrote = await run.io_bound(
                partial(inner["library"].write_launcher_config,
                        inner["launcher"]["launcher_id"], values,
                        table=str(inner.get("config_table") or ""),
                        scope=str(inner.get("config_scope") or "launcher")))
    except Exception as exc:  # noqa: BLE001
        ui.notify(t("said.save_failed"), caption=why(exc), type="negative")
        return
    if cut := (wrote or {}).get("cut"):
        no_longer_reads_game(cut, inner.get("tables"))
    inner.pop("config_values", None)
    if in_place and (redraw := inner.get("redraw_form")) is not None:
        try:
            fresh = await _config_values(inner)
        except Exception:  # noqa: BLE001 - what cannot be read is drawn from the top
            logger.exception("Could not read the settings after a box was written")
        else:
            for follow in list(inner.get("followers", ())):
                follow(fresh)
            await redraw()
            if (behind := inner.get("refresh_grid")) is not None:
                await behind()
            return
    await _keeping_place(ui.context.client, inner["rebuild"], next(iter(values)))


def _backglass_chips(glass: dict[str, Any]) -> None:
    if glass["two_versions"]:
        ui.label(t("console.backglass.two_versions")) \
            .classes("console-tier console-tier--unknown") \
            .tooltip(t("console.backglass.two_versions.hint"))
    if glass["still"]:
        ui.label(t("console.backglass.still")).classes("console-tier console-tier--unknown") \
            .tooltip(t("console.backglass.still.hint"))


def _backglass_roms(context: dict[str, Any]) -> list[str]:
    """The ROMs of the tables that read this file."""
    roms = {str(((one.get("dependencies") or {}).get("pinmame") or {})
                .get("effective") or "") for one in context["served"]}
    return sorted(rom for rom in roms if rom)


def _backglass_facts(context: dict[str, Any], glass: dict[str, Any]) -> list[tuple[Any, Any]]:
    entries: list[tuple[Any, Any]] = []
    if glass["author"]:
        entries.append((t("word.author"), glass["author"]))
    if glass["artwork"] and glass["artwork"] != glass["author"]:
        entries.append((t("console.backglass.artwork"), glass["artwork"]))
    if glass["rom"]:
        roms = _backglass_roms(context)
        differs = any(rom.lower() != glass["rom"].lower() for rom in roms)
        entries.append((t("console.backglass.rom"),
                        _state(t("console.backglass.different"), "warn", beside=glass["rom"],
                               hint=t("console.backglass.different.hint", rom=", ".join(roms)))
                        if differs else glass["rom"]))
    if glass["players"]:
        entries.append((t("console.backglass.players"), str(glass["players"])))
    if glass["size"]:
        wide, high = glass["size"]
        shown = t("console.workbench.width_by_height", width=wide, height=high)
        entries.append((t("console.backglass.picture"), _hinted(
            shown, t("console.backglass.picture.hint", grill=glass["grill"]))
            if glass["grill"] else shown))
    if glass["scoreview_art"]:
        wide, high = glass["scoreview_art"]
        entries.append((t("console.backglass.score_art"),
                        t("console.workbench.width_by_height", width=wide, height=high)))
    return entries


def _hinted(text: str, hint: str) -> Callable[[], None]:
    def draw() -> None:
        ui.label(text).classes("console-fact-value truncate min-w-0").tooltip(hint)

    return draw


def _served(row: dict[str, Any], files: Sequence[dict[str, Any]],
            tables: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """The tables a file is the one used by: its own table, or each the game's file
    serves that has no file of that kind of its own."""
    if not row.get("present") or row.get("binding") not in ("table", "game"):
        return []
    if row.get("binding") == "table":
        return [one for one in tables if one.get("id") == row.get("table")]
    own = {one.get("table") for one in files
           if one.get("kind") == row.get("kind") and one.get("binding") == "table"}
    return [one for one in tables if one.get("id") not in own]


async def _file_settings(library: Library, row: dict[str, Any],
                         files: Sequence[dict[str, Any]],
                         tables: Sequence[dict[str, Any]],
                         detail: dict[str, Any]) -> dict[str, Any] | None:
    """What a file's Settings section draws from: the program settings its tables'
    launchers tie to the file's kind, read at each table it is the one used by, and for a
    file of two versions the row that picks one. None where it has none, or where one of
    those tables runs another program or cannot be read."""
    served = _served(row, files, tables)
    if not served or not all(one.get("launcher_app_configurable") for one in served):
        return None
    kind = str(row.get("kind") or "")
    listing = await offload.io(_launchers_for_panel, library)
    held = {one["launcher_id"]: one for one in listing.get("launchers") or []}
    runs = [launcher for table in served
            if (launcher := held.get(table.get("launcher"))) is not None
            and launcher.get("has_config") and _program_state(launcher) == path_state.OK]
    if len(runs) != len(served) or len({one.get("app") for one in runs}) != 1:
        return None
    launcher, table_id = runs[0], str(served[0].get("id") or "")
    try:
        found = await offload.io(library.launcher_config, launcher["launcher_id"],
                                 table_id, "entry")
    except Exception:  # noqa: BLE001 - the file's panel draws without its settings
        logger.debug("No settings for %s", table_id, exc_info=True)
        return None
    groups = config_groups(found)
    versioned = bool((detail.get("backglass") or {}).get("two_versions"))
    tied = [SimpleNamespace(
        settings=group.settings,
        curated=[SimpleNamespace(**{**vars(one), "keys": (*one.keys, *one.versions)})
                 if versioned else one for one in group.curated if kind in one.kinds])
        for group in groups]
    tied = [group for group in tied if group.curated]
    if not tied:
        return None
    settings = {"library": library, "launcher": launcher, "config_groups": groups,
                "config_values": dict(found.get("values") or {}), "config_scope": "entry",
                "config_table": table_id, "tied": tied, "tables": list(tables),
                "playing": await offload.io(_playing, library)}
    if len(served) > 1:
        from console import app_settings
        shared = [{"table": table, "launcher_id": one["launcher_id"]}
                  for table, one in zip(served, runs, strict=True)]
        settings.update(
            config_values={}, shared=shared,
            config_read=partial(app_settings.as_one, library, shared, groups),
            config_write=partial(app_settings.write_shared, library, shared, groups))
    return settings


async def _file_settings_entries(context: dict[str, Any]) -> list[tuple[Any, Any]]:
    inner = context["file_settings"]
    values = await _config_values(inner)
    shown = [block for group in inner["tied"] for block in curated_blocks(group, values)]
    entries = await _setting_entries(
        inner, [(heading.label, heading.note, fields) for heading, fields in shown],
        curated=True, redraw_on=switches(heading for heading, _ in shown),
        pairs=[pair for heading, _ in shown for pair in heading.pairs],
        ahead={field.key: [_fit_row(inner, part)] for _, fields in shown for field in fields
               if (part := _dmd_part(field.key))})
    if shared := inner.get("shared"):
        entries[:0] = [(panel.HEADING, t("console.section.settings")), panel.intro(
            t("console.workbench.writes_to_tables", count=len(shared)),
            hint="\n".join(_table_line(one["table"], inner["tables"]) for one in shared))]
    return entries


def _dmd_part(key: str) -> str:
    """The window a DMD position setting belongs to, and blank for any other setting. Only
    the first of a window's four numbers is named, so the button is drawn once."""
    name = key.rsplit(".", 1)[-1]
    part = name.removesuffix("DMDX") if key.startswith("Plugin.") else ""
    return part if name.endswith("DMDX") and part in (
        backglass_view.GLASS_PART, backglass_view.SCORE_PART) else ""


def _fit_row(inner: dict[str, Any], part: str) -> tuple[Any, Any]:
    """The button that sizes a window's DMD box to the picture, above the box's numbers.
    The preview supplies the action once it is drawn."""
    async def press() -> None:
        if (fit := inner["fits"].get(part)) is None:
            ui.notify(t("console.backglass.damaged"), type="warning")
        else:
            await fit()

    return panel.FULL, panel.action(
        t("console.backglass.dmd_fit"), press, icon=verbs.FIT,
        hint=t("console.backglass.dmd_fit.hint"), enabled=not inner.get("playing"))


def _asset_actions(context: dict[str, Any], kind: str, label: str, present: bool,
                   path: str, tier: str, detail: dict[str, Any]) -> None:
    if kind in file_acts.WHOLE_FOLDER:
        _folder_actions(context, kind, label, present, path,
                        int(detail.get("files") or 0))
        return
    if kind not in file_acts.PLACEABLE:
        return
    loose = tier in (media_ownership.ORPHAN, media_ownership.UNUSED)
    table = next((one for one in context["tables"]
                  if one.get("id") == context["lens"]), None)
    with ui.row().classes("items-center gap-2 w-full console-slot-actions"):
        if not loose:
            ui.button(t("word.replace") if present else t("word.add"),
                      icon=verbs.REPLACE if present else verbs.ADD,
                      on_click=lambda: mediasource.open_asset_sources(
                          context, kind, label, context["rebuild"], path)) \
                .props("flat dense no-caps size=sm").classes("console-action")
        if not (present and path):
            return
        if kind == "script" and table is not None and tier == media_ownership.TABLE:
            ui.button(t("word.delete"), icon=verbs.DELETE,
                      on_click=lambda: _drop_script(context, table)) \
                .props("flat dense no-caps size=sm") \
                .classes("console-action console-action--danger")
        else:
            ui.button(t("word.remove"), icon=verbs.REMOVE,
                      on_click=lambda: _remove_asset(context, kind, path, tier)) \
                .props("flat dense no-caps size=sm") \
                .classes("console-action console-action--danger")


def _folder_actions(context: dict[str, Any], kind: str, label: str, present: bool,
                    path: str, files: int) -> None:
    with ui.row().classes("items-center gap-2 w-full console-slot-actions"):
        panel.action(t("word.replace") if present else t("word.add"),
                     lambda: mediasource.open_folder_sources(context, kind, label,
                                                             context["rebuild"], path),
                     icon=verbs.REPLACE if present else verbs.ADD,
                     hint=t("console.workbench.folder_source.help"))()
        if present and path:
            ui.button(t("word.remove"), icon=verbs.REMOVE,
                      on_click=lambda: _remove_asset(context, kind, path, "", files=files)) \
                .props("flat dense no-caps size=sm") \
                .classes("console-action console-action--danger")


@on_page
async def _remove_asset(context: dict[str, Any], kind: str, path: str, tier: str,
                        files: int | None = None) -> None:
    detail = file_acts.asset_removal_detail(kind, tier, files)
    if not await confirm.ask(t("console.workbench.remove_asset", name=PurePosixPath(path).name),
                             detail=detail, confirm=t("word.remove"), icon=verbs.REMOVE):
        return
    try:
        await run.io_bound(context["library"].remove_asset, context["game_id"], path)
    except Exception as exc:  # noqa: BLE001
        ui.notify(t("said.remove_failed"), caption=why(exc), type="negative")
        return
    await context["rebuild"]()


def _asset_icon(kind: str) -> str:
    try:
        return asset_registry.spec_for(kind).icon
    except KeyError:
        return "description"


def _asset_spec(detail: dict[str, Any]) -> str:
    parts = []
    if detail.get("folder"):
        parts.append(t("console.workbench.files_in_folder", count=int(detail.get("files") or 0)))
    elif detail.get("format"):
        parts.append(str(detail["format"]))
    size = mediasource._size(detail.get("size_bytes"))
    if size:
        parts.append(size)
    if detail.get("modified"):
        parts.append(when.ago(detail["modified"]))
    return " \u00b7 ".join(parts)


@on_page
async def _open_whole(context: dict[str, Any], path: str, label: str) -> None:
    try:
        found = await offload.io(context["library"].asset_detail, context["game_id"], path, 0)
    except Exception as exc:  # noqa: BLE001
        ui.notify(t("console.workbench.read_failed"), caption=why(exc),
                  type="negative")
        return
    text_editor.show_whole(label, str(found.get("head") or ""))


async def build_backup(container: ui.column, title: ui.column, library: Library,
                       backup_id: str | None,
                       state: dict[str, Any] | None = None) -> None:
    """The panel, for a copy VPinFE keeps rather than a game."""
    state = state if state is not None else {}
    await _pane_build(container, state,
                      lambda: _draw_backup(container, title, library, backup_id, state))


async def _draw_backup(container: ui.column, title: ui.column, library: Library,
                       backup_id: str | None, state: dict[str, Any]) -> None:
    if not backup_id:
        _blank(container, title, t("console.page.backup"), t("console.page.select_backup"))
        return
    # Read fresh: a part's `gone` and a note are answers about this moment.
    found = await offload.io(library.backups)
    held = backups_page.rows(list(found.get("copies") or []), parts=True)
    row = next((one for one in held if one["id"] == backup_id and not one["within_id"]), None)
    if row is None:
        _blank(container, title, t("console.page.backup"), t("console.page.not_found"))
        return

    container.clear()
    title.clear()
    with container:
        _title(title, backups_page.name_of(row), row["taken_text"])
        context: dict[str, Any] = {
            "library": library, "backup": row, "state": state, "redraws": [], "dock": None,
            "parts": [one for one in held if one["within_id"] == backup_id]}
        context["rebuild"] = _rebuilds(context, f"backup:{backup_id}",
                                       lambda: build_backup(container, title, library,
                                                            backup_id, state))
        await _rail(context, "backup", state)


async def build_launcher(container: ui.column, title: ui.column, library: Library,
                         launcher_id: str | None,
                         state: dict[str, Any] | None = None) -> None:
    """The panel, for a launcher rather than a game."""
    state = state if state is not None else {}
    await _pane_build(container, state,
                      lambda: _draw_launcher(container, title, library, launcher_id, state))


async def _draw_launcher(container: ui.column, title: ui.column, library: Library,
                         launcher_id: str | None, state: dict[str, Any]) -> None:
    if not launcher_id:
        _blank(container, title, t("console.page.launcher"),
               t("console.page.select_launcher"))
        return
    # Read fresh rather than from the grid's copy: every control in here writes, and a
    # rebuild that redrew from a stale row would show the edit undoing itself.
    found = await offload.io(library.launchers)
    held = list(found.get("launchers") or [])
    row = next((one for one in held if one.get("launcher_id") == launcher_id), None)
    if row is None:
        _blank(container, title, t("console.page.launcher"),
               t("console.page.not_found"))
        return

    groups = await offload.io(library.launcher_config_groups, launcher_id)
    playing = await offload.io(_playing, library)

    container.clear()
    title.clear()
    with container:
        _title(title, row.get("display_name") or "", row.get("app_name") or "")
        context: dict[str, Any] = {
            "library": library, "launcher": row, "launchers": held,
            "config_groups": list(groups or []), "state": state, "playing": playing,
            "defaults": dict(found.get("defaults") or {}),
            "redraws": [], "dock": None,
        }

        def retitle(name: str) -> None:
            title.clear()
            _title(title, name, row.get("app_name") or "")

        context["retitle"] = retitle
        context["rebuild"] = _rebuilds(
            context, f"launcher:{launcher_id}",
            lambda: build_launcher(container, title, library, launcher_id, state))
        await _rail(context, "launcher", state)


async def build_player(container: ui.column, title: ui.column, library: Library,
                       player_id: str | None, state: dict[str, Any]) -> None:
    """The panel, for a player."""
    await _pane_build(container, state,
                      lambda: _draw_player(container, title, library, player_id, state))


async def _draw_player(container: ui.column, title: ui.column, library: Library,
                       player_id: str | None, state: dict[str, Any]) -> None:
    if not player_id:
        _blank(container, title, t("console.page.player"), t("console.page.select_player"))
        return
    # Read fresh rather than from the grid's copy: who is up moves from a phone and from
    # the frontend as well as from here.
    roster = await offload.io(library.players)
    player = next((one for one in roster if one.get("id") == player_id), None)
    if player is None:
        _blank(container, title, t("console.page.player"), t("console.page.not_found"))
        return
    try:
        held = await offload.io(library.player_accounts, player_id)
    except Exception:  # noqa: BLE001 - the player is still worth drawing without them
        logger.warning("Could not read a player's accounts", exc_info=True)
        held = []

    container.clear()
    title.clear()
    with container:
        _title(title, players_page.shown_name(player), players_page.kind_word(player))
        fixed = sections_for("player")
        accounts = tuple(Section(key, label, build, subjects=frozenset({"player"}))
                         for key, label, build in map(players_page.account_section, held))
        context: dict[str, Any] = {
            "library": library, "player": player, "roster": roster, "state": state,
            "accounts": held,
            "rail": (*fixed[:1], *accounts, *fixed[1:]), "redraws": [], "dock": None,
        }

        def retitle(name: str) -> None:
            title.clear()
            _title(title, name, players_page.kind_word(player))

        context["retitle"] = retitle

        async def again() -> None:
            """The grid first, so its row menus hold the accounts as they are now."""
            await players_page.changed(context, again=False)
            await build_player(container, title, library, player_id, state)

        context["rebuild"] = _rebuilds(context, f"player:{player_id}", again)
        await _rail(context, "player", state)


async def build_device(container: ui.column, title: ui.column, library: Library,
                       device: dict[str, Any] | None, state: dict[str, Any],
                       local_device_id: str | None = None,
                       device_capabilities: list[str] | None = None,
                       local_capabilities: set[str] | None = None) -> None:
    """The panel, for a device rather than a game.

    Its own entry point for the same reason a collection has one: a device has no game,
    no tables and no media lens, so everything `build` assembles would be a chain of
    empty values threaded through to sections that never read them.
    """
    await _pane_build(container, state, lambda: _draw_device(
        container, title, library, device, state, local_device_id,
        device_capabilities or [], local_capabilities or set()))


async def _draw_device(container: ui.column, title: ui.column, library: Library,
                       device: dict[str, Any] | None, state: dict[str, Any],
                       local_device_id: str | None,
                       device_capabilities: list[str],
                       local_capabilities: set[str]) -> None:
    if not device:
        _blank(container, title, t("console.page.device"),
               t("console.page.select_device"))
        return

    container.clear()
    title.clear()
    with container:
        _title(title, devices_page.device_label(device),
               devices_page.KIND_LABELS.get(str(device.get("kind") or "vpinfe"),
                                            "VPinFE"))
        reach = (state.get("device_reach") or {}).get(str(device.get("device_id") or ""))
        context: dict[str, Any] = {
            "library": library, "device": device, "state": state,
            "local_device_id": local_device_id,
            "device_capabilities": device_capabilities,
            "local_capabilities": local_capabilities,
            "reach": reach, "redraws": [], "dock": None,
            "actions": (state.get("device_actions") or {}).get(
                str(device.get("device_id") or "")),
        }
        if context["actions"] is None:
            context["actions"] = await devices_page.load_actions(
                library, device, local_device_id, reach)
            state.setdefault("device_actions", {})[
                str(device.get("device_id") or "")] = context["actions"]

        context["rebuild"] = _rebuilds(
            context, f"device:{local_device_id}",
            lambda: build_device(container, title, library, device, state,
                                 local_device_id, device_capabilities,
                                 local_capabilities))
        await _rail(context, "device", state)


async def build_theme(container: ui.column, title: ui.column, library: Library,
                      key: str | None, state: dict[str, Any]) -> None:
    """The panel, for a frontend theme."""
    await _pane_build(container, state,
                      lambda: _draw_theme(container, title, library, key, state))


async def _draw_theme(container: ui.column, title: ui.column, library: Library,
                      key: str | None, state: dict[str, Any]) -> None:
    if not key:
        _blank(container, title, t("console.page.theme"), t("console.page.select_theme"))
        return
    found = await offload.io(library.themes, False)
    theme = next((one for one in found.get("themes") or [] if one.get("key") == key), None)
    if theme is None:
        _blank(container, title, t("console.page.theme"),
               t("console.page.gone"))
        return
    container.clear()
    title.clear()
    with container:
        _title(title, str(theme.get("name") or key),
               themes_page.STATES[themes_page.status(theme)]["label"])
        context: dict[str, Any] = {"library": library, "theme": theme, "state": state,
                                   "redraws": [], "dock": None}
        context["rebuild"] = _rebuilds(
            context, f"theme:{key}",
            lambda: build_theme(container, title, library, key, state))
        await _rail(context, "theme", state)


def _blank(container: ui.column, title: ui.column, heading: str, said: str) -> None:
    """The panel with nothing to show. Its own helper so the drawing paths can read
    their subject before clearing, and still say this when there is none."""
    container.clear()
    title.clear()
    with container:
        _title(title, heading, said)


async def _draw_collection(container: ui.column, title: ui.column, library: Library,
                           name: str | None, state: dict[str, Any]) -> None:
    if not name:
        _blank(container, title, t("console.page.collection"),
               t("console.page.select_collection"))
        with container:
            _note_unsaved(state, set(state.get("unsaved_rules") or ())
                          & set(state.get("collection_drafts") or {}))
        return
    # Read fresh rather than from the grid's copy: every control in here writes,
    # and a rebuild that redrew the values it just changed from a stale row would
    # show the edit undoing itself.
    #
    # All of it before the container is cleared. Clearing first holds the panel empty
    # across three round trips, which is a black flash after changing a member's table:
    # the old panel stays up until the new one is ready to replace it.
    rows = await offload.io(library.load_collections)
    row = next((entry for entry in rows if entry.get("name") == name), None)
    if row is None:
        _blank(container, title, t("console.page.collection"),
               t("console.page.gone"))
        return
    # Independent of each other, so one wait rather than four.
    membership, axes, settings, _ = await asyncio.gather(
        run.io_bound(library.collection_members, name),
        run.io_bound(library.filter_axes),
        run.io_bound(library.config_values),
        run.io_bound(library.load_thumbnails))
    membership = library.with_entry_art(membership)
    known = collection_rules.fields(axes or [])
    # The rules being edited, which are not always the rules that are stored. Held on
    # the client rather than in this build of the panel, so a section change or a
    # redraw does not discard an edit in progress.
    drafts = state.setdefault("collection_drafts", {})
    draft = drafts.setdefault(name, {})
    if draft.get("rules") == collection_rules.rows_from(row.get("filters"), known):
        draft.pop("rules")
    if "rules" not in draft:
        draft.pop("order", None)
    waiting = unsaved(drafts, rows, known)
    preview: dict[str, Any] | None = None
    if name in waiting:
        try:
            preview = library.with_entry_art(await offload.io(
                library.preview_collection, name,
                collection_rules.filters_from(draft["rules"], known)))
        except Exception as exc:  # noqa: BLE001 - the list says why in its place
            preview = {"error": why(exc)}

    container.clear()
    title.clear()
    with container:
        size = int(row.get("count") or 0)
        smart = (row.get("type") or "") == "filter"
        with title:
            ui.label(row.get("name") or "") \
                .classes("text-base console-workbench-title leading-tight truncate")
            with ui.row().classes("items-center gap-1 no-wrap"):
                if smart:
                    ui.icon(verbs.SMART).classes("console-heading-mark") \
                        .tooltip(t("console.collections.smart.help"))
                ui.label(t("console.workbench.smart_games", count=size) if smart
                         else t("console.workbench.hand_picked", count=size)) \
                    .classes("text-xs console-workbench-label leading-none truncate")
        _note_unsaved(state, waiting)
        context: dict[str, Any] = {"library": library, "collection": row,
                                   "membership": membership, "fields": known,
                                   "settings": settings or {}, "preview": preview,
                                   "unsaved": name in waiting, "state": state,
                                   "draft": draft, "redraws": [], "dock": None,
                                   "games_by_id": {str(one.get("id") or ""): one
                                                   for one in library.games}}

        context["rebuild"] = _rebuilds(
            context, f"collection:{name}",
            lambda: build_collection(container, title, library, state.get("collection"),
                                     state))
        await _rail(context, "collection", state)


async def _draw_all_games(container: ui.column, title: ui.column, library: Library,
                          state: dict[str, Any]) -> None:
    settings = await run.io_bound(library.config_values)
    container.clear()
    title.clear()
    with container:
        _title(title, t("console.collections.all_games"),
               t("console.workbench.all_games.count", count=len(library.games)))
        _note_unsaved(state, set())
        context: dict[str, Any] = {"library": library, "collection": {"name": BUILTIN_ALL},
                                   "settings": settings or {}, "state": state,
                                   "redraws": [], "dock": None}
        context["rebuild"] = _rebuilds(
            context, "collection:all",
            lambda: build_all_games(container, title, library, state))
        await _rail(context, "all_games", state)


async def _all_games_details(context: dict[str, Any]) -> None:
    entries: list[tuple[Any, Any]] = [
        (HEADING, t("console.workbench.frontend")),
        (t("console.workbench.open_on"), _open_on(context, {"name": ""}, all_games=True)),
        panel.note(t("console.workbench.open_on.help")),
        panel.note(t("console.workbench.all_games.paging")),
    ]
    with ui.column().classes("gap-0 console-form"):
        _rows(ui, entries)


def _note_unsaved(state: dict[str, Any], names: set[str]) -> None:
    """`names` as the page's `unsaved_rules`, the grid's marks and the browser's flag."""
    state["unsaved_rules"] = set(names)
    mark = state.get("mark_unsaved")
    if callable(mark):
        mark(set(names))
    text_editor.flag(state)


async def _rail(context: dict[str, Any], subject: str,
                state: dict[str, Any]) -> None:
    """The rail and the open section, for whatever subject the panel is about.

    Three regions, in reading order: which mode you are in, what that mode gives you to
    browse, and what you are working on. The outline must not scroll with what it
    points at, so this row is the fixed frame and only the body scrolls.

    Wide, the rail is a column down the left and the work fills the space beside it, and
    the rows are wrapped so they scroll without dragging the work along - a rail longer
    than the panel would otherwise take the work with it when it scrolled.

    Narrow, the same rows are a strict accordion with the work under the row that opened
    it. The wrapper would break that, so the stylesheet drops it there and `order` puts
    the work back in its place among the rows. Three buckets is all it takes: rows down
    to the open one, the work, then the rest. The markup is the same at either width, so
    nothing is rebuilt on a drag.
    """
    header = state.get("subject_menu")
    verbs_of = SUBJECT_VERBS.get(subject)
    if header is not None and verbs_of is not None:
        panel.subject_menu(header, verbs_of(context))
    declared = context.get("rail") or sections_for(subject)
    rows = tuple(item for item in declared if item.shown is None or item.shown(context))
    # One entry is a section that is always open, so it takes the width and has no row.
    # Counted before `shown`, so a subject's rail does not come and go between two rows.
    bare = len(declared) == 1
    section = chosen_section(state, subject, rows)
    # A section this subject has no answer for is not a place to land, so an address or a
    # remembered choice that names one opens the rail's own default instead.
    if bare or (section != COLLAPSED and section not in {item.key for item in rows}):
        section = rows[0].key if rows else COLLAPSED
    body = None
    open_item = next((item for item in rows if item.key == section), None)
    docked = open_item is not None and _docked(open_item, context)
    with ui.element("div").classes("w-full grow min-h-0 console-sections") as sections:
        if bare:
            sections.classes(add="console-sections--bare")
        if subject == "collection":
            sections._props[row_drag.TARGET] = context["collection"]["name"]
        if subject in ("game", "table"):
            mediasource.take_table_drops(sections, context, _after_an_add(context))
        # The rows are their own region so they can scroll without taking the work with
        # them. A rail longer than the panel is the ordinary case for a device, and one
        # that moves what you are reading is the wrong half to move.
        if not bare:
            with ui.element("div").classes("min-h-0 console-section-rail"):
                heading = ""
                after = 0
                for item in rows:
                    if item.group and item.group != heading:
                        ui.label(item.group).classes("console-group console-rail-group") \
                            .style(f"order: {after}")
                    heading = item.group
                    _section_row(context, item, item.key == section, order=after)
                    if item.key == section:
                        after = _AFTER_WORK
        if open_item is not None:
            work = ui.element("div").classes("min-w-0 console-section-work") \
                .style(f"order: {_WORK}")
            if docked:
                work.classes(add="console-has-dock")
                work.style(f"--dock-h: {dock_height(state, section)}px")
                work._props["data-dock-section"] = section
            with work:
                body = ui.column().classes("min-w-0 overflow-auto gap-0 "
                                           "console-workbench-body")
                if docked:
                    ui.element("div").classes("console-dock-grip") \
                        .tooltip(t("console.workbench.drag_resize"))
                    context["dock"] = ui.column().classes("min-w-0 gap-0 console-dock")
                else:
                    context["dock"] = None
    if body is not None:
        with body, busy.held(body):
            await _one_section(context, section, rows)
        if context.get("dock") is not None:
            ui.run_javascript(_GRIP)


async def _one_section(context: dict[str, Any], key: str,
                       rows: tuple[Section, ...] = ()) -> None:
    """The chosen section's content. No heading - the row that opened it is the
    heading, and a second copy of the same words under it is furniture."""
    await next(item for item in rows or SECTIONS if item.key == key).build(context)


def _section_row(context: dict[str, Any], section: Section, open_now: bool,
                 *, order: int = 0) -> None:
    """One section's name - the rail entry, at either width.

    The name is text: a badge said nothing about a game's identity, and the sections
    still to come would each need a picture that means only itself. Words already do.

    The chevron is the exception, and it is not the same thing - it says the row opens,
    which is a fact about the control rather than a label for the section. Without it
    the stacked rows are four words with no sign that any of them do anything.
    """
    row = ui.row().classes("items-stretch gap-0 no-wrap console-section-row") \
        .style(f"order: {order}")
    if open_now:
        row.classes(add="console-section-on")
    with row:
        name = ui.row().classes("items-center grow min-w-0 console-section-hit")
        with name:
            text = ui.label(section.label(context)).classes("truncate")
        # Shown only where the rows stack, because only there does one open under
        # another. Beside its content it would be pointing at nothing.
        with ui.row().classes("items-center console-section-caret"):
            ui.icon("expand_more", size="18px")
    # The whole band, name and chevron alike - a header that answers on the word but
    # not on the arrow is a control with two rules to learn.
    row.on("click", lambda key=section.key: _pick(context, key))

    async def relabel() -> None:
        # A count in the name has to follow the thing it counts.
        text.text = section.label(context)

    context["redraws"].append(relabel)
    context.setdefault("relabels", []).append(relabel)


def _pick(context: dict[str, Any], key: str) -> None:
    """Open this section. The row that is already open stays open: a rail names where
    you are, so a click on it must never blank the pane."""
    if context["state"].get("section") != key:
        _choose(context, key)


def _choose(context: dict[str, Any], key: str) -> None:
    """Make it the section on screen."""
    context["state"]["section"] = key
    deeplink.sync(context["state"])
    asyncio.create_task(context["rebuild"]())


def _title(target: ui.column, name: str, subtitle: str) -> None:
    with target:
        ui.label(name).classes("text-base console-workbench-title leading-tight truncate")
        ui.label(subtitle).classes("text-xs console-workbench-label leading-none truncate")


def _media_label(context: dict[str, Any]) -> str:
    present, borrowed, total = mediamap.summary(
        context["library"].media.get(context["game_id"], {}))
    label = (t("console.workbench.media_borrowed", present=(present), total=(total),
               borrowed=(borrowed)) if borrowed
             else t("console.workbench.media", present=(present), total=(total)))
    return label + _media_scope(context)


def _media_scope(context: dict[str, Any]) -> str:
    """The lens used to be repeated here. The header states it now, once."""
    return ""


def _table_address(context: dict[str, Any], table_id: str) -> str:
    """Where `_go_to_table` would land, as an address a browser can follow.

    Built through `deeplink.query` rather than by formatting a string here, so the link
    and the state the click produces cannot drift a field apart.
    """
    return "/console?" + deeplink.query({"view": "tables",
                                         "game": context.get("game_id") or "",
                                         "table": table_id})


def _go_to_table(context: dict[str, Any], table_id: str) -> None:
    """Follow a differing table into its own lens.

    The way out of the game's view and into the file's, rather than a second editor
    for one table's art embedded in a panel that is about the game.
    """
    if not table_id:
        return
    state = context["state"]
    # The Tables grid is a place now, so going to one file is going there.
    state["view"] = "tables"
    state["table"] = table_id
    deeplink.sync(state)
    asyncio.create_task(context["rebuild"]())


def _said_line(made: str, table: dict[str, Any] | None = None) -> None:
    said = game_tables.table_name(table) if table else ""
    if not (made or said):
        return
    with ui.row().classes("items-center gap-1 w-full no-wrap min-w-0 console-member-table"):
        if made:
            ui.label(made).classes("console-cell-made whitespace-nowrap")
        if made and said:
            ui.label(game_tables.JOIN.strip()).classes("console-cell-join")
        if said:
            _built_label(table or {}, said).classes("min-w-0")


def _built_label(table: dict[str, Any], said: str) -> ui.element:
    return _said_name(table, said).classes("console-cell-built")


def _said_name(table: dict[str, Any], said: str) -> ui.element:
    tip = str(table.get("filename") or "")
    if not game_tables.names_a_file(table):
        return ui.label(said).classes("truncate").tooltip(tip)
    with ui.element("div").classes(grid.FILE_CLASS).tooltip(tip) as box:
        ui.label(said)
    return box


def _table_line(table: dict[str, Any], tables: list[dict[str, Any]] | None = None) -> str:
    """Which of a game's tables this is, told apart from the rest of `tables`. One form,
    owned by `subject`.

    The header is the one place a long filename cannot ellipse gracefully, so the
    fallback is trimmed from the end - where the part that separates two tables of a
    game sits.
    """
    said = game_tables.table_name(table)
    if said == str(table.get("filename") or ""):
        return _tail(said, 40)
    return game_tables.name_among(table, tables or [])


def _tail(name: str, limit: int) -> str:
    """A filename cut from the front, keeping the end.

    The tables in one game share a long prefix and differ at the tail - "(Williams
    1993)12" against "(Williams 1993)lw" - so trimming the end trims the only half
    that tells them apart.
    """
    stem = name[:-4] if name.lower().endswith(".vpx") else name
    return stem if len(stem) <= limit else "\u2026" + stem[-(limit - 1):]


async def _media_block(context: dict[str, Any]) -> None:
    """The map, and whatever tile is picked out of it."""
    library, game_id = context["library"], context["game_id"]
    holder = ui.column().classes("w-full gap-0")

    async def draw() -> None:
        table_id = context["lens"]
        entries = await offload.io(library.media_for, game_id, table_id or None)
        # Only from the game's lens. Looking at one table, the badge on a slot already
        # says whose file it is, and marking the others would be noise about tables
        # that are not the subject.
        overrides = ({} if table_id else
                     await run.io_bound(library.media_overrides, game_id))
        offered = await offload.io(_offered_media, context)
        kept = _kept_kinds(context, "media")
        context["devices"] = await offload.io(library.known_devices)
        wont_play = await _wont_play(context)
        holder.clear()
        with holder:
            mediamap.build(entries, game_id, table_id or "",
                           on_pick=lambda kind: _pick_slot(context, kind, draw),
                           selected=context["slot"]["kind"],
                           overrides=overrides, offered=offered, kept=kept,
                           wont_play=wont_play)
            # A slot arrived at by link can be anywhere in a map of twenty tiles,
            # including below the fold - and a selection you cannot see is not one.
            # `nearest` moves the least that makes it visible, so a tile already on
            # screen does not jolt the map, and clicking one never scrolls at all.
            #
            # Inside `with holder`, and that is not tidiness. `run_javascript` reaches
            # for the client through the current slot, and a redraw scheduled from a
            # click runs on a bare task with no slot at all - so out here it raises,
            # takes the rest of this function with it, and the dock below is never
            # cleared. The map updates, the editor keeps whatever it had, and nothing
            # says why.
            if context["slot"]["kind"]:
                ui.run_javascript("""
                requestAnimationFrame(() => {
                  const tile = document.querySelector('.console-mediatile--on');
                  if (tile) tile.scrollIntoView({block: 'nearest', inline: 'nearest'});
                });
                """)
        dock = context.get("dock")
        if dock is not None:
            dock.clear()
            # Kept for the sources dialog, which says whether a file it is offering
            # is already serving one of this game's slots.
            context["media"] = entries
            kind = context["slot"]["kind"]
            detail = None
            matched = ""
            if kind and kind in entries:
                try:
                    detail = await offload.io(library.media_detail, game_id,
                                                table_id or None, kind)
                except Exception:
                    logger.debug("No detail for %s", kind, exc_info=True)
                matched = await _match_line(context, kind,
                                            (detail or {}).get("matched_to")
                                            or entries[kind].get("matched_to"))
            waiting = (await recorder.waiting_on(library, game_id, table_id or "", kind)
                       if kind and kind in entries else [])
            with dock:
                if kind and kind in entries:
                    _slot(context, kind, entries[kind], detail, written,
                          (overrides or {}).get(kind) or [], matched=matched,
                          waiting=waiting)
                else:
                    # The region is reserved either way, so it says what it is for
                    # rather than sitting there as an empty box. Named for what the
                    # user is looking at - the user sees - rather than for the slot
                    # they fill, which is our word and not theirs. No "above" or
                    # "beside" either: this region moves depending on the width.
                    with ui.column().classes("console-dock-empty items-center gap-1"):
                        ui.label(t("console.workbench.no_media")).classes("console-empty-title")
                        ui.label(t("console.workbench.media_hint")) \
                            .classes("console-help")

    async def written() -> None:
        await draw()
        saved = context.get("saved")
        if callable(saved):
            await saved()

    async def placed() -> None:
        library.forget_media(game_id)
        await offload.io(library.media_for, game_id, None)
        if not holder.is_deleted:
            for redraw in context["redraws"]:
                await redraw()

    context["redraws"].append(written)
    await draw()
    recording = _record_media(context, placed)
    if context["lens"] and recording is None:
        return
    with ui.element("div").classes("console-slot-actions px-3"):
        if not context["lens"]:
            panel.action(t("console.media_fill.get_missing"),
                         lambda: media_fill.ask([game_id], context["state"], placed,
                                              name=str(context["game"].get("name") or "")),
                         icon=verbs.FETCH,
                         hint=t("console.media_fill.get_missing.help"))()
        if recording is not None:
            recording()


def _record_media(context: dict[str, Any],
                  placed: Callable[[], Any]) -> Callable[[], None] | None:
    """Record Media for the game or the table in view, dimmed with why where this install
    records nothing; None where recording is not something it does."""
    able = recorder.capability(context["library"])
    if able is None:
        return None
    table = next((one for one in context["tables"] if one.get("id") == context["lens"]),
                 None)
    name = str(context["game"].get("name") or "")
    title = t("console.record.title_table", name=name,
              table=_table_line(table, context["tables"])) if table is not None \
        else t("console.record.title", name=name)
    return panel.action(t("console.record.record_media"),
                        lambda: recorder.ask(context["library"],
                                             [(context["game_id"], context["lens"] or "")],
                                             title, context["state"], placed),
                        icon=verbs.RECORD, enabled=bool(able.get("available")),
                        hint=str(able.get("reason") or ""))


def _local_id(context: dict[str, Any]) -> str:
    return str(context["library"].discovery().get("install_id") or "")


async def _wont_play(context: dict[str, Any]) -> dict[str, list[str]]:
    """Each video in the lens that some device won't play, and those devices in words."""
    devices = context["devices"]
    if not plays_on.asks_codecs(devices):
        return {}
    try:
        codecs = await offload.io(context["library"].video_codecs, context["game_id"],
                                  context["lens"] or None)
    except Exception:  # noqa: BLE001 - a codec not read is no warning
        logger.debug("No codecs for %s", context["game_id"], exc_info=True)
        return {}
    local = _local_id(context)
    found = {kind: [one.label for one in plays_on.refusals(codec, devices, local)]
             for kind, codec in codecs.items()}
    return {kind: labels for kind, labels in found.items() if labels}


def _kept_kinds(context: dict[str, Any], family: str) -> set[str] | None:
    """The kinds this library collects, or None to filter nothing: an empty set would
    blank the surface."""
    return set(context["library"].kept_kinds()[family]) or None


def _offered_media(context: dict[str, Any]) -> dict[str, int]:
    """What the catalog lists for this game's empty slots.

    Swallowed on failure rather than taken as zero being reported: the map is about the
    library, and a catalog that cannot be reached should mark nothing rather than say
    the catalog has nothing.
    """
    try:
        return context["library"].offered_media(context["game_id"])
    except Exception:
        return {}


def _pick_slot(context: dict[str, Any], kind: str, draw: Any) -> None:
    """Pick a slot to see the detail of. Clicking the picked one again does nothing.

    Putting the panel away would make one control mean two things and cost the selection
    to a mis-click. The detail sits beside the map rather than over it, so there is
    nothing to dismiss - a slot stays picked until another is.
    """
    slot = context["slot"]
    if slot["kind"] == kind:
        return
    slot["kind"] = kind
    deeplink.sync(context["state"])
    asyncio.create_task(draw())


# An empty slot still shows what shape of thing belongs in it. Not the map's glyph
# rule, which returns nothing for a kind that normally has a frame to show - here
# there is no frame, which is the point.
_BLANK_ICON = {"image": "image", "video": "movie",
               "audio": "graphic_eq", "doc": "description"}


def _spec(detail: dict[str, Any]) -> str:
    """Size, shape, running time and date on one line - what tells two files of a kind
    apart when both look right in a thumbnail."""
    parts = []
    if detail.get("width") and detail.get("height"):
        parts.append(t("console.workbench.width_by_height", width=detail["width"],
                       height=detail["height"]))
    if detail.get("duration_s"):
        parts.append(running_time(float(detail["duration_s"])))
    name = str(detail.get("file") or "")
    if detail.get("format"):
        parts.append(str(detail["format"]))
    elif "." in name:
        parts.append(name.rsplit(".", 1)[1].upper())
    size = mediasource._size(detail.get("size_bytes"))
    if size:
        parts.append(size)
    if detail.get("modified"):
        parts.append(when.ago(detail["modified"]))
    return " \u00b7 ".join(parts)


def running_time(seconds: float) -> str:
    """As a player shows it. Never 0:00 - a sound that is there runs for something."""
    minutes, rest = divmod(max(1, round(seconds)), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02}:{rest:02}" if hours else f"{minutes}:{rest:02}"


def _used_as(candidate: dict[str, Any]) -> str:
    """Who a file in a slot's detail answers for: its own tier while some table is shown
    it, otherwise Unused."""
    return str(candidate.get("tier") or "") if candidate.get("serves") \
        else media_ownership.UNUSED


def _slot_art(context: dict[str, Any], kind: str, entry: dict[str, Any],
              page: int = 1) -> None:
    """The slot's picture, player or blank outline. `page` is the page of a paged kind
    to show; Enlarge then steps through all of them, starting there."""
    game_id, table_id = context["game_id"], context["lens"]
    label = media_label_map().get(kind, kind)
    with ui.element("div").classes("console-slot-art"):
        if entry.get("present"):
            version = entry.get("version")
            mediaview.preview(art.media(game_id, kind, table_id or "", version=version,
                               size=art.PANEL, page=page), kind, label)
            # On the picture, where the map puts it. Images only: a video keeps its
            # native controls here, and those carry a full-screen button already.
            if media_family(kind) == "image":
                if mediapages.count(kind, entry) >= mediapages.STRIP_FROM:
                    enlarge = partial(
                        mediaview.open_pages,
                        mediapages.addresses(game_id, kind, table_id or "", entry),
                        label, page)
                else:
                    enlarge = partial(
                        mediaview.open_viewer,
                        art.media(game_id, kind, table_id or "", version=version),
                        kind, label)
                ui.button(icon=verbs.ENLARGE, on_click=lambda: enlarge()) \
                    .props("flat dense round size=sm") \
                    .classes("console-slot-zoom").tooltip(t("word.enlarge"))
        else:
            with ui.column().classes("console-slot-blank items-center gap-1"):
                ui.icon(_BLANK_ICON.get(media_family(kind), "help_outline")) \
                    .classes("console-slot-blank-icon")


def _slot(context: dict[str, Any], kind: str, entry: dict[str, Any],
          detail: dict[str, Any] | None, draw: Any,
          differing: list[dict[str, Any]] | None = None, *,
          titled: bool = True, in_place: bool = True, scope_chip: bool = True,
          links: Sequence[dict[str, Any]] = (), matched: str = "", draw_art: bool = True,
          waiting: Sequence[dict[str, Any]] = (), page: int = 1) -> None:
    """One slot: the art at the size of the room, and what there is to know about it.
    `draw_art=False` leaves the picture to the caller, which draws it somewhere else.
    `waiting` are the recordings kept for a decision on this slot. `page` is the page of a
    paged kind that `detail` describes, where the panel is one page's file.

    The picture is the subject. Everything else is one line each underneath, because
    the questions this panel answers - what is this, why this one, what else is here -
    are each a sentence, and a table of fields makes the reader do the joining.
    """
    library, game_id = context["library"], context["game_id"]
    table_id = context["lens"]
    label = media_label_map().get(kind, kind)
    # The map already knows the slot; detail only adds to it. A failed read should
    # cost the spec line, never the panel.
    detail = detail or {}
    present = bool(entry.get("present"))
    file_name = detail.get("file") or entry.get("file") or ""
    also_here = list(detail.get("tiers") or [])
    pages = mediapages.count(kind, entry)
    many = pages >= mediapages.STRIP_FROM
    # The strip carries the acts on each page, so the slot's own act is to take them all.
    in_strip = many and draw_art
    # A file panel for one page of several acts on that page and nothing else.
    one_page = many and not draw_art
    slot_label = mediapages.named(kind, page) if many or page > 1 else label

    @on_page
    async def remove() -> None:
        if one_page:
            owner = mediapages.owner_of(entry, table_id)
            if not mediapages.removable(entry):
                ui.notify(t("console.workbench.nothing_removable"), type="info")
                return
            if not await mediapages.confirm_remove(kind, page, pages, owner):
                return
            taken = None
        else:
            taken = file_acts.removal(context["tables"], context["game"], table_id,
                                      detail.get("tiers"), entry,
                                      detail.get("after_remove"))
        if taken is not None and not await confirm.ask(
                t("console.mediapages.remove_all", name=label, count=pages)
                if in_strip else t("console.workbench.remove_asset", name=taken[0]),
                detail=taken[1], confirm=t("word.remove"), icon=verbs.REMOVE):
            return
        try:
            result = await offload.io(
                library.remove_media, game_id,
                mediapages.owner_of(entry, table_id) if one_page else table_id, kind,
                page if one_page else None)
        except Exception as exc:
            ui.notify(t("said.remove_failed"), caption=why(exc), type="negative")
            return
        gone = len(result.get("removed") or [])
        ui.notify(t("console.workbench.removed_files", count=gone) if gone
                  else t("console.workbench.nothing_removable"),
                  type="positive" if gone else "info")
        await draw()

    # Widening only, and only from the table you are looking at. The other direction -
    # a shared file becoming one table's - reads as a move but takes the file away from
    # every other table in the folder, and in the shared lens there is no table in view
    # to say which one would get it. That one needs a decision, not a default.
    can_share = present and table_id and str(entry.get("via") or "") == "table"

    @on_page
    async def share() -> None:
        """The table's own file takes the folder's name, so every table resolves it."""
        try:
            await run.io_bound(library.retier_media, game_id, kind, table_id, "")
        except Exception as exc:
            ui.notify(t("console.workbench.move_failed"), caption=why(exc), type="negative")
            return
        ui.notify(t("console.workbench.give_done"), type="positive")
        for redraw in context["redraws"]:
            await redraw()

    with ui.column().classes("w-full gap-1 console-slot p-2"):
        if titled:
            ui.label(label).classes("console-card-title")

        if draw_art:
            if in_strip:
                mediapages.strip(context, kind, entry, draw)
            else:
                _slot_art(context, kind, entry)

        with ui.column().classes("w-full gap-0 console-slot-facts"):
            if present:
                with ui.row().classes("items-start gap-2 w-full no-wrap"):
                    _file_line(context, kind, str(file_name), "media" if in_place else "",
                               str(detail.get("path") or entry.get("path") or ""))
                    via = detail.get("via") or entry.get("via")
                    if scope_chip or media_ownership.key_of(via) not in media_ownership.SCOPES:
                        media_ownership.badge(via)
                refused = plays_on.refusals(detail.get("video_codec"),
                                            context.get("devices") or [], _local_id(context))
                if refused:
                    with ui.row().classes("items-center gap-1 w-full"):
                        for one in refused:
                            ui.label(one.label) \
                                .classes("console-tier console-tier--warn").tooltip(one.why)
                spec = _spec(detail)
                if spec:
                    ui.label(spec).classes("console-help")
                ui.label(media_ownership.sentence(detail.get("via") or entry.get("via"),
                                        viewing_a_table=bool(table_id))) \
                    .classes("console-help")
                origin = str(detail.get("origin") or entry.get("origin") or "")
                # "unknown" is the ledger's honest answer and a useless line to read:
                # most files predate the ledger, so it would be on nearly every slot.
                if origin and origin not in ("unknown", "user"):
                    ui.label(t("console.workbench.source",
                            source_name=(media_ownership.source_name(origin)))) \
                        .classes("console-help")
                # Only when somebody has said - "not matched" is true of nearly every
                # file, and the button below is where the unanswered case belongs.
                if matched:
                    ui.label(matched).classes("console-help")
                _outside_lines(links)
            else:
                ui.label(t("console.workbench.missing_table", kind=label)
                         if table_id
                         else t("console.workbench.missing_game", kind=label)) \
                    .classes("console-help")

        # Only when there is more than one, because with one the sentence above has
        # already said where it is. Two is the case worth a list: the second file is
        # why an edit appeared to do nothing.
        if len(also_here) > 1:
            with ui.column().classes("w-full gap-0 console-slot-others"):
                ui.label(t("console.workbench.not_used")).classes("console-slot-others-title")
                for item in also_here:
                    if item.get("wins"):
                        continue
                    with ui.row().classes("items-center gap-2 w-full no-wrap"):
                        ui.label(item.get("file") or "").classes("console-slot-other-file")
                        media_ownership.badge(_used_as(item))
                ui.label(t("console.workbench.shadowed_hint")) \
                    .classes("console-help")

        # Only from the game's lens, and only when somebody differs. This is the whole
        # of Model B in the panel: the shared file above, and who is not using it.
        for other in (differing or []):
            with ui.row().classes("items-center gap-2 w-full no-wrap console-slot-differs"):
                media_ownership.badge("table")
                said = _table_line(other) or other.get("filename") or ""
                # Bound here rather than as a lambda default: the default is how a loop
                # variable is usually captured, and it makes the callable take an
                # argument that `panel.link` does not pass.
                other_id = str(other.get("table") or "")
                panel.link(said, to=_table_address(context, other_id),
                           on_click=partial(_go_to_table, context, other_id)
                           if in_place else None,
                           hint=other.get("file") or "")()

        if waiting:
            recorder.waiting_line(library, waiting, draw)

        with ui.row().classes("items-center gap-2 w-full console-slot-actions") \
                .style("flex-wrap:wrap"):
            if not in_strip:
                ui.button(t("word.replace") if present else t("word.add"),
                          icon=verbs.ADD_ART,
                          on_click=lambda: mediasource.open_sources(
                              context, kind, slot_label, draw,
                              str(detail.get("path") or entry.get("path") or ""),
                              backglass_file=detail.get("backglass_file"), page=page)) \
                    .props("flat dense no-caps size=sm").classes("console-action")
            if present and in_place and kind in PAGED_KINDS and not many:
                mediapages.add_button(context, kind, entry, draw)
            able = mediasource.records(library, kind) if page == 1 else None
            if able is not None:
                panel.action(t("console.record.record"),
                             lambda: mediasource.open_sources(
                                 context, kind, label, draw,
                                 str(detail.get("path") or entry.get("path") or ""),
                                 recording_it=True,
                                 backglass_file=detail.get("backglass_file")),
                             icon=verbs.RECORD, enabled=bool(able.get("available")),
                             hint=str(able.get("reason") or ""))()
            if present:
                # Beside the acts on the bytes: a slot holding nothing has no identity.
                # Of the slot, which page 1 stands for.
                if page == 1:
                    _match_button(context, kind, label,
                                  detail if detail.get("path") else entry, draw)
                ui.button(t("console.mediapages.clear") if in_strip
                          else t("word.remove"), icon=verbs.REMOVE, on_click=remove) \
                    .props("flat dense no-caps size=sm") \
                    .classes("console-action console-action--danger")
            if can_share and page == 1:
                ui.button(t("console.workbench.give_all"),
                    icon=verbs.SHARE, on_click=share) \
                    .props("flat dense no-caps size=sm").classes("console-action")


def _game_label(context: dict[str, Any]) -> str:
    """Game, or Game - not matched where there is no match and none was declared."""
    game = context["game"]
    declared = (game.get("overrides") or {}).get("alt_vps_id", "") is None
    if game.get("vps_id") or declared:
        return t("console.workbench.game_section")
    return t("console.workbench.game_unmatched")


async def _game_block(context: dict[str, Any]) -> None:
    """What the game is - the machine, not the file.

    Shown whichever subject is selected. A table belongs to a game, and the VPS match,
    the manufacturer and the theme are as true while you are looking at one of its files
    as they are otherwise. Substituting one for the other throws away half of what
    somebody is looking at.
    """
    game = context["game"]
    library = context["library"]
    vps_id = str(game.get("vps_id") or "")
    found: dict[str, Any] = await offload.io(library.vps_entry, vps_id) if vps_id else {}
    differs = (await offload.io(library.vps_details, context["game_id"])
               if found.get("name") else [])
    held = bool(found) or not vps_id or await offload.io(library.vps_catalog_held)
    links = await offload.io(library.outside_links, context["game_id"])
    copies = await backup_rows.listed(library, "game", context["game_id"])
    # Under Tables the table's own section leads with them, and saying each twice on
    # one panel is what teaches a reader to skip the block.
    findings = [] if context["lens"] else await _findings(context, context["tables"])
    # Test lights the cabinet, so it is offered where this device has a frontend.
    lights = install_identity.FRONTEND in (library.discovery().get("features") or ())
    dof_state = await dof.event_state(library) if lights else None
    with ui.column().classes("gap-0 console-form"):
        _rows(ui, findings + _game_entries(context, found, differs, held, links, copies,
                                           dof_state))
        _tables_block(context, held)


async def _table_block(context: dict[str, Any]) -> None:
    """What this table is - the file somebody built, and what it needs to run."""
    chosen = next((t for t in context["tables"] if t.get("id") == context["lens"]),
                  None)
    match = await _release_match(context, chosen) if chosen is not None else []
    links = (await offload.io(context["library"].outside_links, context["game_id"],
                              str(chosen.get("id") or ""))
             if chosen is not None and chosen.get("id") else [])
    findings = await _findings(context, [chosen]) if chosen is not None else []
    with ui.column().classes("gap-0 console-form"):
        if chosen is None:
            ui.label(t("console.workbench.none_selected")).classes("console-help")
            return
        _rows(ui, _table_entries(chosen, context, match, links, findings))
    ui.run_javascript(_KEEP_SCROLL % f"table:{chosen.get('id') or ''}".replace("'", "\\'"))


async def _table_settings(context: dict[str, Any]) -> None:
    from console import app_settings

    await app_settings.section(context)


async def _selection_marks(context: dict[str, Any]) -> None:
    from console import selection_marks

    await selection_marks.section(context, selection_marks.TABLES)


async def _game_selection_marks(context: dict[str, Any]) -> None:
    from console import selection_marks

    await selection_marks.section(context, selection_marks.GAMES)


async def _selection_settings(context: dict[str, Any]) -> None:
    from console import app_settings

    await app_settings.selection_section(context)


async def _release_match(context: dict[str, Any],
                         table: dict[str, Any]) -> list[tuple[Any, Any]]:
    """Which build of the machine this file is, as the table's Match group."""
    entry = str(context["game"].get("vps_id") or "")
    source = table.get("source") or {}
    bound = str(source.get("vps_file_id") or "")
    rows: list[tuple[Any, Any]] = [(HEADING, t("console.workbench.matched_to"))]
    if not entry:
        return rows + _unmatched(release_match_gap(entry, bound, True))

    async def pick() -> None:
        await _pick_a_release(context, table)

    if not bound:
        return rows + _unmatched(release_match_gap(entry, bound, True)) \
            + [(FULL, _change_match(pick, matched=False))]
    releases, unread = await _read_releases(context, entry)
    release = next((one for one in releases
                    if str(one.get("vps_file_id") or "") == bound), None)
    # Found across the whole catalog, though no longer under this entry.
    if release is None and (source.get("version") or source.get("authors")):
        release = {"version": source.get("version"), "authors": source.get("authors")}
    if release is not None:
        rows.append((FULL, partial(_release_shown, release)))
        if source.get("mod_of"):
            rows.append((FULL, partial(_based_on, source["mod_of"])))
    else:
        try:
            held = not unread and await offload.io(context["library"].vps_catalog_held)
        except Exception as exc:
            logger.warning("console: could not read VPS for %s", entry, exc_info=True)
            held, unread = False, why(exc)
        rows += _unmatched(release_match_gap(entry, bound, held, read=not unread),
                           hint=unread)
    return rows + [(FULL, _change_match(pick, matched=True))]


@on_page
async def _write(context: dict[str, Any], call: Callable[..., Any],
                 *args: Any, shape: bool = True) -> None:
    """One write, off the loop, then put right whatever it changed.

    Off the loop because this is an HTTP call to our own process: made on the event
    loop it blocks the server from answering it, and the browser reports the socket as
    lost rather than slow.

    `shape=False` where the panel is unchanged but for the value just saved.
    """
    try:
        await run.io_bound(call, *args)
    except Exception as exc:
        ui.notify(t("console.workbench.save_failed"), caption=why(exc), type="negative")
        return
    await (context["rebuild"]() if shape else context["saved"]())


@on_page
async def _save_overrides(context: dict[str, Any], changes: dict[str, Any], *,
                          table: bool) -> bool:
    """Write one field and rebuild; False where the write was refused. Off the loop:
    this is an HTTP call to our own process, and made on the event loop it blocks the
    server from answering it."""
    library = context["library"]
    try:
        if table:
            await run.io_bound(library.set_table_overrides, context["game_id"],
                               context["lens"], changes)
        else:
            await run.io_bound(library.set_game_overrides, context["game_id"], changes)
    except Exception as exc:
        ui.notify(t("console.workbench.save_failed"), caption=why(exc), type="negative")
        return False
    await context["rebuild"]()
    return True


def _override(effective: str, found: str | None, source: str,
              save: Callable[[str], Any], *, shown: str | None = None,
              hint: str = "", beside: str = "", placeholder: str = "",
              after: Callable[[ui.input], Any] | None = None) -> Callable[[], None]:
    """One field the user may override, drawn into a fact row.

    A field the whole time. The read state and the edit state are one element, so there
    is nothing for the alignment to drift against and nothing moves on the first click.

    `found` is what the field would say with no override, or None where nothing but the
    user ever supplies one. Where there is a `found`, an amber revert appears exactly
    when the value differs from it, and typing that value back clears the override -
    so the mark's presence always means "this differs from the default".

    `placeholder` is what an empty field stands for. `after` is handed the field once it
    is drawn and draws what sits inline after it.
    """
    current = effective if shown is None else shown

    def draw() -> None:
        with ui.element("div").classes("console-fact-edit"):
            field = ui.input(value=current, placeholder=placeholder) \
                .props("dense borderless").classes("console-edit-field")
            if hint:
                field.tooltip(hint)
            if beside:
                panel.link_out("", to=beside)()
            if after is not None:
                after(field)
            icon = ui.icon(verbs.REVERT).classes("console-revert")
            if found is not None:
                target = f'"{found}"' if found else "empty"
                icon.tooltip(t("console.workbench.revert", target=(target),
                        source=(source)))
            differs = found is not None and current != found
            icon.visible = differs
            if differs:
                field.classes("console-edit-field--differs")
            held = {"value": current}

            async def commit() -> None:
                value = str(field.value or "").strip()
                if value == held["value"]:
                    return
                saved, held["value"] = held["value"], value
                # Sending the discovered value is how an override is cleared, so the
                # two cases are one request rather than a delete and a write.
                if await save("" if found is not None and value == found else value) is False:
                    held["value"] = saved

            def cancel() -> None:
                field.value = held["value"]
                field.run_method("blur")

            async def revert() -> None:
                held["value"] = found or ""
                await save("")

            field.on("blur", commit)
            field.on("keydown.enter", lambda: field.run_method("blur"))
            field.on("keydown.escape", cancel)
            icon.on("click", revert)

    return draw


def game_match_gap(vps_id: str, declared: bool, held: bool) -> tuple[str, str, str]:
    """What a game's Match group says when there is no entry to draw: the state's key,
    what its absence costs, and the key of the line under it."""
    if declared:
        return ("console.workbench.no_match", "off", "console.workbench.cleared_match")
    if not vps_id:
        return ("console.workbench.not_matched", "warn", "")
    if not held:
        return ("word.unknown", "unknown", "console.workbench.no_vps_data")
    return ("console.workbench.not_listed", "warn",
            "console.workbench.game_unlisted")


def release_match_gap(entry: str, bound: str, held: bool,
                      read: bool = True) -> tuple[str, str, str]:
    """The same for a table's release, which has none to draw. `read` is whether the
    entry's releases could be read."""
    if not entry:
        return ("console.workbench.not_matched", "off",
                "console.workbench.releases_unmatched")
    if not bound:
        return ("console.workbench.not_matched", "off", "")
    if not read:
        return ("word.unknown", "unknown", "console.workbench.vps_failed")
    if not held:
        return ("word.unknown", "unknown", "console.workbench.no_vps_data")
    return ("console.workbench.not_listed", "warn",
            "console.workbench.release_unlisted")


def _match(found: dict[str, Any], vps_id: str, declared: bool,
           held: bool, how: str = "") -> list[tuple[Any, Any]]:
    """The machine this game is matched to, drawn the way the picker drew it, and how
    the match was made."""
    if found.get("name"):
        return [(FULL, lambda: vps_match.entry_row(found, trailing=_how_matched(how)))]
    return _unmatched(game_match_gap(vps_id, declared, held))


def _how_matched(how: str) -> Callable[[], None] | None:
    if how not in game_tables.HOW_MATCHED:
        return None
    hint = t("console.game_tables.auto_matched.help") if how == "auto" else ""
    return _state(game_tables.HOW_MATCHED[how], "on", hint=hint)


def _unmatched(gap: tuple[str, str, str], hint: str = "") -> list[tuple[Any, Any]]:
    said, level, under = gap
    rows: list[tuple[Any, Any]] = [(FULL, _state(t(said), level, hint=hint))]
    return rows + [panel.intro(t(under))] if under else rows


def _outside(links: Sequence[dict[str, Any]]) -> list[tuple[Any, Any]]:
    return [(str(one.get("name") or ""),
             panel.link_out(urlparse(str(one["url"])).netloc.removeprefix("www."),
                            to=str(one["url"])))
            for one in links if one.get("url")]


def _outside_lines(links: Sequence[dict[str, Any]]) -> None:
    for one in links:
        if one.get("url"):
            with ui.element("div").classes("console-help"):
                panel.link_out(str(one.get("name") or ""), to=str(one["url"]))()


def _game_entries(context: dict[str, Any], entry: dict[str, Any],
                  differs: list[dict[str, Any]], held: bool,
                  links: Sequence[dict[str, Any]] = (),
                  copies: list[dict[str, Any]] | None = None,
                  dof_state: dict[str, Any] | None = None) -> list[tuple[Any, Any]]:
    game = context["game"]
    folder = str(game.get("folder") or "")
    found = game.get("discovered") or {}

    def save(key: str) -> Callable[[str], Awaitable[None]]:
        async def write(value: str) -> None:
            await _save_overrides(context, {key: value}, table=False)
        return write

    def field(label: str, key: str, alt: str) -> tuple[Any, Any]:
        return (label, _override(str(game.get(key) or ""), str(found.get(key) or ""),
                                 "VPS", save(alt)))

    vps_id = str(game.get("vps_id") or "")
    declared = (game.get("overrides") or {}).get("alt_vps_id", "") is None
    entries: list[tuple[Any, Any]] = [(HEADING, t("console.workbench.matched_to"))]
    entries += _match(entry, vps_id, declared, held, game_tables.how_matched(game))
    entries.append((FULL, _change_match(lambda: _pick_a_match(context),
                                        matched=bool(vps_id) or declared)))
    if differs:
        entries.append((FULL, _details_differ(context, differs)))

    ipdb = str(game.get("ipdb_id") or "")
    entries += [
        (HEADING, t("console.workbench.details")),
        (t("word.name"), _override(game.get("name") or "",
                found.get("name") or "",
                           "VPS", save("alt_title"))),
        field(t("word.manufacturer"), "manufacturer", "alt_manufacturer"),
        field(t("word.year"), "year", "alt_year"),
        field(t("console.workbench.type"), "type", "alt_type"),
        (t("console.workbench.themes"), ", ".join(game.get("themes") or []) or "-"),
        (t("console.workbench.ipdb"),
         _override(ipdb, str(found.get("ipdb_id") or ""), "VPS", save("alt_ipdb_id"),
                   beside=IPDB_URL.format(id=ipdb) if ipdb else "")),
        *_outside(links),
        (t("word.folder"), panel.path_value(folder) if folder else "-"),
    ]
    if copies is not None:
        entries.append((t("console.section.backups"), backup_rows.row(
            context["library"], "game", context["game_id"], str(game.get("name") or folder),
            copies, context["rebuild"])))
    return entries + _game_marks(context) + _game_frontend(context, dof_state)


def _game_frontend(context: dict[str, Any],
                   dof_state: dict[str, Any] | None = None) -> list[tuple[Any, Any]]:
    """The game's DOF event, and Test beside it where this device has a frontend to light
    it for. `dof_state` is `dof.event_state`'s answer there and None elsewhere."""
    overrides = context["game"].get("overrides") or {}

    async def save_dof(value: str) -> bool:
        return await _save_overrides(context, {"frontend_dof_event": value}, table=False)

    def test(field: ui.input) -> None:
        tester = dof.Tester(context["library"], dof_state or {},
                            lambda: str(field.value or ""))
        tester()
        field.on_value_change(tester.refresh)

    # Empty is the revert: nothing but the user supplies this, and clearing it asks for
    # a different event on every selection.
    entry = _override(overrides.get("frontend_dof_event") or "", None, "", save_dof,
                      placeholder=t("console.workbench.dof_random"),
                      after=test if dof_state is not None else None)

    def draw() -> None:
        with ui.column().classes("gap-1 min-w-0"):
            entry()
            ui.label(t("console.workbench.dof_event_hint")).classes("console-help")

    return [
        (HEADING, game_tables.FRONTEND),
        (t("console.workbench.dof_event"), draw),
    ]


def _game_marks(context: dict[str, Any]) -> list[tuple[Any, Any]]:
    game = context["game"]
    record = game.get("user") or {}

    async def rate(value: int) -> None:
        await _write(context, context["library"].set_game_rating,
                     context["game_id"], value)

    async def favorite(event: Any) -> None:
        await _write(context, context["library"].set_game_favorite,
                     context["game_id"], bool(event.value), shape=False)
        await _recounted(context)

    async def private(event: Any) -> None:
        await _write(context, context["library"].set_game_private,
                     context["game_id"], bool(event.value), shape=False)
        await _recounted(context)

    async def retag(chosen: list[str]) -> None:
        await _write(context, context["library"].set_game_tags,
                     context["game_id"], chosen)

    return [
        (HEADING, t("console.workbench.yours")),
        (t("console.workbench.game_rating"), stars.draw(int(game.get("rating") or 0), rate)),
        (t("word.favorite"),
         lambda: _switch(bool(record.get("favorite")), favorite,
                         hint=t("console.workbench.filter_hint"))),
        (game_tables.PRIVATE_WORDS[0], lambda: _switch(bool(game.get("private")), private)),
        panel.note(game_tables.PRIVATE_HELP),
        (t("console.workbench.tags"),
         _tag_picker(list(record.get("tags") or []), context["library"], retag,
                     list(game.get("derived_tags") or []))),
    ]


def _table_marks(context: dict[str, Any], table: dict[str, Any]) -> list[tuple[Any, Any]]:
    record = table.get("user") or {}
    table_id = str(table.get("id") or "")

    async def rate(value: int) -> None:
        await _write(context, context["library"].set_table_rating,
                     context["game_id"], table_id, value)

    async def retag(chosen: list[str]) -> None:
        await _write(context, context["library"].set_table_tags,
                     context["game_id"], table_id, chosen)

    return [
        (HEADING, t("console.workbench.yours")),
        (t("console.workbench.table_rating"),
         stars.draw(int(table.get("rating") or 0), rate)),
        (t("console.workbench.tags"),
         _tag_picker(list(record.get("tags") or []), context["library"], retag,
                     list(table.get("derived_tags") or []))),
    ]


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
    return [(HEADING, t("console.workbench.game_section")),
            *_game_play_rows(context),
            (HEADING, t("console.workbench.table_section")),
            *_table_play_rows(chosen)]


def _chosen_table(context: dict[str, Any]) -> dict[str, Any] | None:
    return next((row for row in context["tables"] if row.get("id") == context["lens"]),
                None)


async def _play_block(context: dict[str, Any]) -> None:
    """What has been done with this, the machine's high score table after it, and the
    pictures players took."""
    scores = await _high_scores(context)
    shots = await pictures.read(context)
    with ui.column().classes("gap-0 console-form"):
        _rows(ui, _play_section(context, scores, shots))


def _play_section(context: dict[str, Any], scores: dict[str, Any],
                  shots: dict[str, Any]) -> list[tuple[Any, ...]]:
    return panel.headed([*_play_entries(context), *_high_score_rows(context, scores),
                         *pictures.rows(context, shots)],
                        t("console.workbench.game_section"))


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
        lines.append((t("console.workbench.high_scores_from",
                        table=_table_line(table, tables)), ""))
    said = HIGH_SCORE_STATES.get(str(scores.get("state") or ""))
    if said is not None:
        text, why_key = said
        lines.append((t(text), t(why_key, rom=str(scores.get("rom") or "")) if why_key
                      else str(scores.get("reason") or "")))
    else:
        clears = bool((table.get("overrides") or {}).get("delete_nvram_on_close"))
        lines.append(_high_scores_read(str(scores.get("read_at") or ""), clears))
    rows: list[tuple[Any, Any]] = [(HEADING, t("console.workbench.high_scores")),
                                   (panel.LEDE, partial(_high_scores_aside, lines))]
    return rows if said is not None else [*rows, *_high_score_entries(scores)]


def _high_scores_aside(lines: list[tuple[str, str]]) -> None:
    with ui.column().classes("gap-0"):
        for text, hint in lines:
            panel.line(text, hint=hint)


# Each state with nothing to list: its line, and the key of its detail. None for the detail
# the answer carries itself.
HIGH_SCORE_STATES: dict[str, tuple[str, str | None]] = {
    "none": ("console.workbench.high_scores_none", "console.workbench.scores_pending"),
    "unsupported": ("console.workbench.high_scores_unsupported",
                    "console.workbench.scores_no_map"),
    "unreadable": ("console.workbench.high_scores_unreadable", None),
}


def _high_scores_read(read_at: str, clears: bool) -> tuple[str, str]:
    """(line, detail)."""
    at = when.parsed(read_at)
    if clears:
        text, hint = t("console.workbench.high_scores_cleared"), ""
    elif at is None:
        text, hint = t("console.workbench.scores_undated"), ""
    elif (datetime.now(UTC) - at).total_seconds() < 60:
        text, hint = t("console.workbench.scores_fresh"), when.local(read_at)
    else:
        text = t("console.workbench.high_scores_read", when=when.ago(read_at, inline=True))
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
            first, *rest = _score_lines(entry)
            rows.append((str(section.get("name") or "") if place == 0 else "",
                         _score_row(entry, first, day, **columns)))
            rows.extend((panel.ASIDE, partial(_score_caption, line)) for line in rest)
    return rows


def _score_lines(entry: dict[str, Any]) -> list[str]:
    """A number the machine writes its own way - hex - is left as `text` has it."""
    score, text = entry.get("score"), str(entry.get("text") or "")
    prefix, suffix = str(entry.get("prefix") or ""), str(entry.get("suffix") or "")
    if isinstance(score, int) and text == f"{prefix}{score:,}{suffix}":
        return [f"{prefix}{i18n.number(score)}{suffix}"]
    return text.split("\n") or [""]


def _score_row(entry: dict[str, Any], value: str, day: str, *, ranked: bool,
               marked: bool) -> Callable[[], None]:
    def draw() -> None:
        with ui.element("div").classes("console-score-row"):
            if ranked:
                rank = entry.get("rank")
                ui.label("" if rank is None else str(rank)).classes("console-score-rank")
            ui.label(str(entry.get("initials") or "")) \
                .classes("console-score-initials console-cell-identifier")
            ui.label(value).classes("console-score-value")
            if marked:
                chip = ui.label(t("console.workbench.high_scores_new")) \
                    .classes("console-tier console-tier--off console-score-new")
                if entry.get("new"):
                    chip.tooltip(t("console.workbench.scores_dated", day=day))
                else:
                    chip.classes(add="console-score-new--held")

    return draw


def _score_caption(line: str) -> None:
    ui.label(line).classes("console-help")


HELD_HOW = {"added": "console.workbench.held_manually_added",
            "matched": "console.workbench.held_rule_matched",
            "taken_out": "console.workbench.held_manually_removed"}


async def _collections_block(context: dict[str, Any]) -> None:
    """Every collection holding this game, the ones keeping it out, and the way to add
    it to another."""
    library, game_id = context["library"], context["game_id"]
    try:
        held = await offload.io(library.game_collections, game_id)
        every = await offload.io(library.load_collections)
        members = await offload.io(library.held_members,
                                   [str(one.get("name") or "") for one in every])
    except Exception as exc:  # noqa: BLE001 - the panel says why, never raises
        panel.line(t("console.workbench.collections_failed"), hint=why(exc),
                   classes="console-help px-3")
        return
    with ui.column().classes("gap-0 console-form w-full min-w-0"):
        if not held["collections"] and not held["taken_out"]:
            ui.label(t("console.workbench.no_collections")).classes("console-help px-3")
        for one in held["collections"]:
            _collection_row(context, one)
        for one in held["taken_out"]:
            _collection_row(context, {**one, "how": "taken_out"})
        with ui.element("div").classes("console-slot-actions px-3"):
            _add_to_collection(context, every, members)


def _collection_row(context: dict[str, Any], one: dict[str, Any]) -> None:
    library, game_id = context["library"], context["game_id"]
    name = str(one.get("name") or "")
    how = str(one.get("how") or "")

    @on_page
    async def act() -> None:
        if how != "taken_out":
            await collection_adds.remove(library, name, [game_id],
                                         then=partial(_game_redrawn, context))
            return
        try:
            await run.io_bound(library.unexclude_from_collection, name, game_id, None)
        except Exception as exc:  # noqa: BLE001
            ui.notify(t("console.workbench.save_failed"), caption=why(exc), type="negative")
            return
        ui.notify(t("console.workbench.restore_into", name=name), type="positive")
        await context["rebuild"]()

    with ui.row().classes("items-center gap-2 w-full no-wrap console-member-row"):
        with ui.row().classes("items-center gap-2 grow min-w-0 no-wrap"):
            panel.link(name, to="/console?" + deeplink.query(
                {"view": "collections", "collection": name}))()
            ui.label(t(HELD_HOW.get(str(one.get("how")),
                                    "console.workbench.held_manually_added"))) \
                .classes("console-member-chip console-tier console-tier--off")
        with ui.element("div").classes("console-row-action"):
            if how == "taken_out":
                ui.button(icon=verbs.REVERT, on_click=act) \
                    .props("flat dense round size=sm") \
                    .tooltip(t("console.workbench.put_back_2"))
            else:
                ui.button(icon=verbs.REMOVE if how == "added" else verbs.EXCLUDE,
                          on_click=act) \
                    .props("flat dense round size=sm") \
                    .tooltip(t("console.workbench.remove_collection"))


def _add_to_collection(context: dict[str, Any], every: list[dict[str, Any]],
                       members: dict[str, list[dict[str, Any]]]) -> None:
    library, game_id, table_id = context["library"], context["game_id"], context["lens"]
    offer = collection_adds.Offer(
        library, [collection_adds.Row(game_id, table_id)],
        collection_adds.TABLES if table_id else collection_adds.GAMES,
        "", then=partial(_game_redrawn, context))
    button = ui.button(t("console.workbench.to_collection"), icon=verbs.ADD_TO_LIST) \
        .props("flat dense no-caps size=sm").classes("console-action")
    with button, ui.menu() as menu:
        collection_adds.draw_every(offer, every, members, menu.close)


async def _game_redrawn(context: dict[str, Any]) -> None:
    """The panel redrawn if it still shows this game, and the grid's row either way. Run
    again by an Undo, when the panel may have moved on."""
    state, game_id = context["state"], context["game_id"]
    if state.get("view") not in ("games", "tables"):
        return
    if state.get("game") == game_id:
        await context["rebuild"]()
        return
    refresh = state.get("refresh_game")
    if callable(refresh):
        await refresh(game_id)


def _rule_sheet(context: dict[str, Any]) -> dict[str, Any]:
    slot = (context["library"].media.get(context["game_id"]) or {}).get("rule_sheet") or {}
    return slot if slot.get("present") else {}


async def _collections_held(library: Library, game_id: str) -> int | None:
    """How many collections hold this game; None where the read failed."""
    try:
        held = await offload.io(library.game_collections, game_id)
    except Exception:  # noqa: BLE001 - a count in a label is not worth the panel
        logger.warning("console: could not count the collections of a game", exc_info=True)
        return None
    return len(held["collections"])


async def _recounted(context: dict[str, Any]) -> None:
    """The rail's Collections count after a write that can move the game in or out of a
    smart collection without rebuilding the panel."""
    context["in_collections"] = await _collections_held(context["library"],
                                                        context["game_id"])
    for relabel in context.get("relabels", []):
        await relabel()


def _collections_label(context: dict[str, Any]) -> str:
    held = context["in_collections"]
    return t("console.workbench.collections") if held is None \
        else t("console.workbench.collections_counted", count=held)


def _guides_label(context: dict[str, Any]) -> str:
    held = len(_guides(context)[0]) + bool(_rule_sheet(context))
    return t("console.workbench.guides_counted", count=held) if held \
        else t("console.workbench.guides")


def _guide_kind(kind: str) -> str:
    said = t(f"guide.kind.{kind}.label")
    return humanize(kind) if said == f"guide.kind.{kind}.label" else said


def _guides(context: dict[str, Any]) -> tuple[list[dict], list[dict]]:
    """(shown, hidden), each in the game's order."""
    held = [one for one in context["game"].get("guides") or [] if one.get("url")]
    return ([one for one in held if not one.get("hidden")],
            [one for one in held if one.get("hidden")])


async def _guides_block(context: dict[str, Any]) -> None:
    sheet = _rule_sheet(context)
    shown, hidden = _guides(context)
    with ui.column().classes("gap-0 console-form w-full"):
        if not sheet and not shown:
            ui.label(t("console.workbench.no_guides")).classes("console-help px-3")
        if sheet:
            _guide_row(media_label_map().get("rule_sheet", "rule_sheet"),
                       art.media(context["game_id"], "rule_sheet",
                                 version=sheet.get("version")),
                       t("console.workbench.in_folder"))
        with ui.column().classes("gap-0 w-full").props('data-arrange="hub_guide_moved"'):
            for one in shown:
                _guide_row(*guide_words(one), arrange=len(shown) > 1,
                           act=_guide_act(context, one))
        if hidden:
            with panel.disclosure(t("console.workbench.hidden_guides", count=len(hidden))) \
                    .classes("console-disclosure-rows pt-2"):
                for one in hidden:
                    _guide_row(*guide_words(one), act=_guide_act(context, one))
        with ui.element("div").classes("console-slot-actions px-3"):
            panel.action(t("console.workbench.add_guide"),
                         lambda: _add_guide(context), icon=verbs.ADD,
                         hint=t("console.workbench.add_guide.help"))()
    # Read at the drop by the page's listener, `guide_moved`.
    context["state"]["guide_move"] = context
    if len(shown) > 1:
        ui.run_javascript(arranging.SCRIPT)


def _as_sent(guides: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"url": one["url"], "hidden": bool(one.get("hidden"))} for one in guides]


@on_page
async def _save_guides(context: dict[str, Any], guides: list[dict[str, Any]]) -> None:
    try:
        await run.io_bound(context["library"].set_game_guides, context["game_id"], guides)
    except Exception as exc:  # noqa: BLE001
        ui.notify(t("console.workbench.save_failed"), caption=why(exc), type="negative")
        return
    await context["rebuild"]()


def _guide_act(context: dict[str, Any], guide: dict[str, Any]) -> Callable[[], None]:
    """Hide or unhide one VPS lists, or remove one of the person's own."""
    held = [one for one in context["game"].get("guides") or [] if one.get("url")]

    async def act() -> None:
        if guide.get("hidden") or guide.get("origin") == "vps":
            wanted = [{**one, "hidden": not one.get("hidden")} if one is guide else one
                      for one in held]
        else:
            wanted = [one for one in held if one is not guide]
        await _save_guides(context, _as_sent(wanted))

    def draw() -> None:
        if guide.get("hidden"):
            panel.action(t("console.workbench.unhide"), act, icon=verbs.UNHIDE, inline=True,
                         hint=t("console.workbench.unhide.help"))()
            return
        mine = guide.get("origin") != "vps"
        with ui.element("div").classes("console-row-action"):
            ui.button(icon=verbs.REMOVE if mine else verbs.HIDE, on_click=act) \
                .props("flat dense round size=sm") \
                .tooltip(t("word.remove") if mine else t("console.workbench.hide"))

    return draw


async def guide_moved(state: dict[str, Any], moved: Any) -> None:
    """Put one shown guide where it was dropped, in the Guides drawn last. The hidden ones
    keep their order after the shown."""
    context = state.get("guide_move")
    if not context:
        return
    shown, hidden = _guides(context)
    try:
        source, target = int(moved["from"]), int(moved["to"])
    except (KeyError, TypeError, ValueError):
        return
    if not (0 <= source < len(shown) and 0 <= target < len(shown)) or source == target:
        return
    shown.insert(target, shown.pop(source))
    await _save_guides(context, _as_sent(shown + hidden))


async def _add_guide(context: dict[str, Any]) -> None:
    from common.games.info_file import GUIDE_KINDS, GUIDE_TUTORIAL

    held: dict[str, Any] = {"kind": GUIDE_TUTORIAL}

    def draw_address() -> None:
        held["address"] = frame.field(placeholder="https://")

    def draw_title() -> None:
        held["title"] = frame.field()

    async def add() -> None:
        said = str(held["address"].value or "").strip()
        if not said.lower().startswith(("http://", "https://")):
            held["address"].props["error"] = True
            held["address"].props["error-message"] = t("console.workbench.guide_needs_address")
            return
        box.close()
        kept = [one for one in context["game"].get("guides") or [] if one.get("url")]
        await _save_guides(context, [*_as_sent(kept),
                                     {"url": said, "kind": held["kind"],
                                      "title": str(held["title"].value or "").strip()}])

    with frame.opened(t("console.workbench.guide_dialog",
                        name=str(context["game"].get("name") or ""))) as box:
        panel.facts(ui, [
            (t("console.workbench.guide_address"), draw_address),
            (t("console.workbench.guide_title"), draw_title),
            (t("word.kind"), panel.select({one: _guide_kind(one) for one in GUIDE_KINDS},
                                          GUIDE_TUTORIAL,
                                          lambda event: held.update(kind=event.value)))])
        with frame.footer():
            frame.cancel(box.close)
            go = frame.answer(t("word.add"), add, icon=verbs.ADD)
    frame.focus(box, held["address"])
    frame.enter_presses(go)
    box.open()


def guide_words(guide: dict[str, Any]) -> tuple[str, str, str]:
    """(name, address, the line under the name)."""
    source = str(guide.get("source") or "")
    makers = ", ".join(name for name in guide.get("authors") or [] if name != source)
    return (str(guide.get("title") or "") or _guide_kind(str(guide.get("kind") or "")),
            str(guide.get("url") or ""),
            " \u00b7 ".join(part for part in (source, makers) if part))


def _guide_row(name: str, address: str, said: str, *, arrange: bool = False,
               act: Callable[[], None] | None = None) -> None:
    with ui.row().classes("items-center gap-2 w-full no-wrap console-member-row"):
        if arrange:
            ui.icon("drag_indicator").classes("console-drag-handle") \
                .props("tabindex=0 role=button") \
                .tooltip(t("console.workbench.drag_hint"))
        with ui.column().classes("gap-0 grow min-w-0"):
            panel.link_out(name, to=address)()
            if said:
                ui.label(said).classes("console-member-table")
        if act is not None:
            act()


def _table_entries(table: dict[str, Any],
                   context: dict[str, Any] | None = None,
                   match: Sequence[tuple[Any, Any]] = (),
                   links: Sequence[dict[str, Any]] = (),
                   findings: Sequence[tuple[Any, Any]] = ()) -> list[tuple[Any, Any]]:
    """One table's own facts.

    The rom is the one it resolves to with any alias followed, which is the one that
    has to exist - the declared name is shown beside it only when they differ, because
    that is the case somebody has to reason about.
    """
    pinmame = (table.get("dependencies") or {}).get("pinmame") or {}
    declared = str(pinmame.get("declared") or "")
    effective = str(pinmame.get("effective") or "")
    rom = effective or declared or "-"
    if declared and effective and declared != effective:
        rom = t("console.workbench.effective_declared",
                effective=(effective), declared=(declared))

    # Grouped by what a fact is about, one vocabulary shared with the views and the
    # grid. Each group carries the actions that work on it.
    features = table.get("features") or {}

    entries: list[tuple[Any, Any]] = [*findings]
    entries += match

    # What this file is. "Filename" rather than the group's own word, which named the
    # filename here and the on-disk state under Status - one word, two facts, both on
    # screen at once.
    reference = table.get("reference") or {}
    if game_tables.is_keyed(table):
        # Nothing read a file, so there is no version, author or hash to show and a
        # row of dashes would say we looked. What it has is the ID and whose it is.
        entries += [
            (HEADING, game_tables.KNOWN_AS),
            (t("word.id"), table.get("key") or "-"),
            (t("word.program"), table.get("app_name") or "-"),
            panel.note(t("console.workbench.keyed_hint")),
        ]
    elif reference:
        # Where it is comes first, because that is the fact that makes this entry
        # different from every other one on the page.
        where = str(reference.get("resolved") or reference.get("path") or "")
        entries += [
            (HEADING, game_tables.ELSEWHERE),
            (t("word.path"), panel.path_value(where) if where else "-"),
            (t("word.now"), panel.state(
                game_tables.word_for(game_tables.REACH_WORDS,
                                     not reference.get("reachable")),
                "on" if reference.get("reachable") else "warn")),
        ]
        if not reference.get("reachable"):
            # The distinction that matters: nothing here has been lost, so the thing
            # to do is make the location reachable, not forget the entry.
            entries.append(panel.note(
                t("console.workbench.file_offline")))
        entries += [
            (t("word.version"), table.get("version") or "-"),
            (t("word.author"), ", ".join(table.get("authors") or []) or "-"),
        ]
    else:
        entries += [
            (HEADING, game_tables.FILE),
            (t("console.workbench.filename"), table.get("filename") or "-"),
            (t("word.version"), table.get("version") or "-"),
            (t("word.author"), ", ".join(table.get("authors") or []) or "-"),
            (t("console.workbench.hash"), table.get("file_hash") or "-"),
            *_made_from(table, context),
        ]
    entries += _outside(links)

    # Its own group. These say what the table implements, which is not the same
    # question as what plays it - the group they shared could not be named honestly.
    if features:
        # The chips span the row: the heading already says Features, and a row
        # labelled for its own group is the File/Filename collision again.
        entries += [(HEADING, game_tables.FEATURES),
                    (FULL, lambda: _feature_chips(features))]
    if context is not None:
        entries += _table_marks(context, table)

    # Can it run, and how. The dependencies are shown as evidence, never managed
    # here: a finding jumps to where it is fixed.
    entries += [(HEADING, game_tables.LAUNCH)]
    present = bool(table.get("available"))
    entries += [(t("console.workbench.run"), _launch_state(table.get("launchable")))]
    # Only where there is a file of this game's to be on disk or not. Where it is is
    # already answered above for a reference, in words that fit it - and "Missing" is
    # what a deleted file says, which is not what an unmounted share is. An entry with
    # no file at all has nothing this row could report.
    if not game_tables.is_referenced(table) and not game_tables.is_keyed(table):
        entries.append(
            (game_tables.FILE,
             _state(game_tables.word_for(game_tables.FILE_WORDS, not present),
                    "on" if present else "bad")))
    if not game_tables.is_keyed(table):
        entries.append((t("console.workbench.rom"), _rom_state(pinmame, rom, context=context)))
    if context is not None:
        entries.append(_hidden_row(context, table))
        entries.append(_launcher_report(context, table))
        entries += [(FULL, _play_action(context, table))]
    return entries


def _made_from(table: dict[str, Any],
               context: dict[str, Any] | None) -> list[tuple[Any, Any]]:
    """The file a patch made this table from: the way to that table while it is on disk,
    Replaced where another file has its name, and Missing where nothing does."""
    base = (table.get("source") or {}).get("base") or {}
    if not base.get("file"):
        return []
    tables = (context or {}).get("tables") or []
    held = next((one for one in tables if base.get("available")
                 and str(one.get("id") or "") == str(base.get("table_id") or "")), None)
    if context is not None and held is not None:
        table_id = str(held["id"])
        return [(t("console.workbench.made_from"), panel.link(
            game_tables.name_among(held, tables), to=_table_address(context, table_id),
            on_click=partial(_go_to_table, context, table_id)))]
    if base.get("available"):
        return [(t("console.workbench.made_from"), str(base["file"]))]
    named = any(one.get("available") and one.get("filename") == base["file"]
                and str(one.get("id") or "") != str(base.get("table_id") or "")
                for one in tables if one is not table)
    word, why = ((t("console.workbench.replaced"), t("console.workbench.name_reused"))
                 if named else (game_tables.word_for(game_tables.FILE_WORDS, True), ""))

    def gone() -> None:
        with ui.row().classes("items-center gap-2 no-wrap min-w-0"):
            ui.label(str(base["file"])).classes("truncate min-w-0")
            chip = ui.label(word) \
                .classes("console-member-chip console-tier console-tier--warn")
            if why:
                chip.tooltip(why)

    return [(t("console.workbench.made_from"), gone)]


_state = panel.state


def _assets_label(context: dict[str, Any]) -> str:
    """Counts what is here, not what could be: a denominator over sixteen registry
    kinds would call every ordinary game mostly empty."""
    game = context["game"]
    chosen = next((item for item in context["tables"]
                   if item.get("id") == context["lens"]), None)
    kept = _kept_kinds(context, "asset")
    resolved = _only_kept((chosen or {}).get("assets") or {}, kept)
    have = sum(1 for state in resolved.values()
               if state.get("resolution") != "none")
    # Skipping what the table already answered, exactly as the body does. The folder
    # reports a backglass this table resolves too, so counting both said four where
    # two rows were drawn - a header disagreeing with the list under it.
    have += sum(1 for kind, state in _only_kept(game.get("assets") or {}, kept).items()
                if kind not in resolved and state.get("present"))
    return t("console.workbench.assets_2", have=(have)) if have else t("console.workbench.assets")


async def _assets_block(context: dict[str, Any]) -> None:
    """Every asset this game holds, and whose each one is.

    Two levels in one list, because somebody asking what a table has does not care
    which of them the filesystem answers at. The five VPX resolves by naming rule are
    the table's and carry a tier; the rest belong to the folder and carry presence.
    The tiers are `media_ownership`'s - the question is the same one, which file wins.
    """
    holder = ui.column().classes("gap-0 console-form")

    turn = [0]
    one_at_a_time = asyncio.Lock()

    async def draw() -> None:
        # Each pick redraws on a task of its own, and a draw awaits between clearing the
        # dock and filling it. Only the newest pick draws, so two cards never stack.
        turn[0] += 1
        mine = turn[0]
        async with one_at_a_time:
            if mine != turn[0]:
                return
            picked = context["slot"]["kind"]
            holder.clear()
            with holder:
                _rows(ui, _asset_entries(
                    context, lambda kind: panel.Pick(partial(_pick_slot, context, kind, draw),
                                                     kind == picked)))
            await _asset_dock(context, picked)

    await draw()


async def _asset_dock(context: dict[str, Any], picked: str) -> None:
    """The picked asset's card, the file panel's own, without the file's settings."""
    dock = context.get("dock")
    if dock is None:
        return
    kind = str(picked or "")
    library, game_id = context["library"], context["game_id"]
    files = await offload.io(library.files_of, "asset", game_id)
    found = _same_file(files, {"kind": kind, "table": context["lens"]}) if kind else None
    dock.clear()
    with dock:
        if found is None:
            with ui.column().classes("console-dock-empty items-center gap-1"):
                ui.label(t("console.workbench.file_panel_empty")).classes("console-empty-title")
                ui.label(t("console.workbench.file_hint")).classes("console-help")
            return
        detail = await _asset_detail_of(library, game_id, found)
        await _asset_file_block({**context, "row": found, "kind": kind, "detail": detail,
                                 "served": _served(found, files, context["tables"]),
                                 "link_view": "assets"})


def _asset_entries(context: dict[str, Any],
                   pick: Callable[[str], panel.Pick] | None = None) -> list[tuple[Any, ...]]:
    """The Assets block's rows, as `_assets_block` draws them.

    Kinds the library does not collect are left out entirely. A row saying an EM table
    has no ROM is not a fact about that table, it is the list answering a question this
    library never asked. `pick` makes a kind's row pickable.
    """
    game = context["game"]
    chosen = next((item for item in context["tables"]
                   if item.get("id") == context["lens"]), None)
    kept = _kept_kinds(context, "asset")
    resolved = _only_kept((chosen or {}).get("assets") or {}, kept)
    folder = _only_kept(game.get("assets") or {}, kept)

    entries: list[tuple[Any, ...]] = []

    def row(kind: str, value: Any) -> None:
        entries.append((_asset_name(kind), value, *((pick(kind),) if pick else ())))

    if chosen is not None:
        entries += [(HEADING, t("console.workbench.table_4"))]
        for kind, state in sorted(resolved.items()):
            row(kind, _resolved_row(context, chosen, kind, state))
            if kind == "script" and state.get("resolution") != "none":
                digest = str(chosen.get("vbs_hash") or "")
                # The hash travels with the asset rather than sitting in a group of
                # identifiers. Only where there is a sidecar to have one.
                if digest:
                    entries.append((t("console.workbench.script_hash"), digest))
        pinmame = (chosen.get("dependencies") or {}).get("pinmame") or {}
        if _collects("rom", kept) and (pinmame.get("effective") or pinmame.get("declared")):
            # A declared dependency, not a file: no file panel to open, so no pick.
            entries.append((_asset_name("rom"), _rom_row(context, pinmame)))

    entries += [(HEADING, t("console.workbench.game_folder"))]
    for kind, state in sorted(folder.items()):
        # Already answered above, and more precisely: the table's own lookup says
        # which file wins, where the folder can only say one is somewhere in it.
        if kind in resolved:
            continue
        present = bool(state.get("present"))
        chip = _present_row(present)
        row(kind, chip if present else _with_add(context, kind, chip))
    return entries


def _only_kept(states: dict[str, Any], kept: set[str] | None) -> dict[str, Any]:
    """Drop what the library does not collect. `table` is never in the toggles and so
    is never dropped - the .vpx is the library rather than an accessory to it."""
    return {kind: state for kind, state in states.items() if _collects(kind, kept)}


def _collects(kind: str, kept: set[str] | None) -> bool:
    return kept is None or kind in kept or kind in _ALWAYS_KEPT


def _asset_name(kind: str) -> str:
    """A kind's own word for itself. `asset_registry` cases the acronyms once."""
    try:
        return asset_registry.spec_for(kind).label
    except KeyError:
        return humanize(kind)


def _resolved_row(context: dict[str, Any], table: dict[str, Any], kind: str,
                  state: dict[str, Any]) -> Any:
    """Whose file this is, the file itself, and the one act that changes it."""
    external = state.get("resolution") != "none"
    name = str(state.get("file") or "")

    def draw() -> None:
        with ui.element("div").classes("console-fact-edit"):
            # The script takes no tier. Its absence is not a gap - a table running the
            # script inside its own .vpx is the ordinary table - and "Missing" here
            # would call every one of them broken. `SCRIPT_WORDS` asks the question
            # that has no wrong answer: which script runs.
            if kind == "script":
                word = game_tables.word_for(game_tables.SCRIPT_WORDS, external)
                why = (t("console.workbench.script_sidecar") if external
                       else t("console.workbench.script_embedded"))
                ui.label(word).classes("console-tier console-tier--off").tooltip(why)
            else:
                tier = media_ownership.for_resolution(state.get("resolution"))
                ui.label(t(tier.noun)).classes(f"console-tier {tier.css}") \
                    .tooltip(t(tier.why))
            if name:
                ui.label(name).classes("console-slot-file truncate").tooltip(name)
            if kind == "script":
                _script_actions(context, table, external)
            elif not external:
                _add_action(context, kind)

    return draw


def _present_row(present: bool) -> Any:
    """A folder-level kind, which is either there or not. No tier: nothing resolves it
    per table, and a tier would imply it could."""
    return _state(t("word.present") if present else t("console.workbench.missing"),
            "on" if present else "off")


def _script_actions(context: dict[str, Any], table: dict[str, Any],
                    external: bool) -> None:
    """Extract a sidecar, or drop one. The script is managed here and Launch only
    reports it."""
    if external and game_tables.runs_its_own_script(table):
        ui.button(t("word.delete"),
            icon=verbs.DELETE, on_click=lambda: _drop_script(context, table)) \
            .props("flat dense no-caps size=sm") \
            .classes("console-action console-action--inline console-action--danger")
    else:
        ui.button(t("console.workbench.extract"), icon=verbs.EXTRACT,
                on_click=lambda: _extract_script(context, table)) \
            .props("flat dense no-caps size=sm") \
            .classes("console-action console-action--inline")


def _launch_state(launchable: bool | None) -> Any:
    """The rollup, above the dependencies it is built from.

    Its inputs stay on screen underneath: a bare "Blocked" with no reason is a state
    somebody has to go hunting behind, and the row that explains it is the next one.
    """
    if launchable is None:
        return _state(game_tables.LAUNCH_UNKNOWN, "unknown")
    return _state(game_tables.word_for(game_tables.LAUNCH_WORDS, not launchable),
                  "on" if launchable else "bad")


def _played_when(stamp: str | None) -> str:
    """A date, not a timestamp. Nobody reads a play record to the second."""
    return when.ago(stamp) if when.parsed(stamp) else t("word.never")


def _played_for(seconds: int) -> str:
    """Play time in the largest unit that is still true, because the number is read at
    a glance and 41,400 seconds is not a length anybody pictures."""
    if seconds < 60:
        return t("word.none") if not seconds \
            else t("console.workbench.sec", count=seconds)
    minutes = seconds // 60
    if minutes < 90:
        return t("console.workbench.min", count=minutes)
    hours, rest = divmod(minutes, 60)
    return (t("console.workbench.hr_min", hours=(hours), rest=(rest)) if rest
            else t("console.workbench.hr", count=hours))


def _play_rows(record: dict[str, Any]) -> list[tuple[Any, Any]]:
    """What has been done with this."""
    return [
        (t("word.last_played"), _played_when(record.get("last_played"))),
        (t("console.workbench.times_played"),
                str(int(record.get("play_count") or 0) or t("word.never"))),
        (t("console.workbench.play_time"),
                _played_for(int(record.get("play_time_seconds") or 0))),
    ]


def _tag_picker(held: list[str], library: Library,
                on_change: Callable[[list[str]], Any],
                derived: Sequence[str] = ()) -> Callable[[], None]:
    """The tags on this game, and the ones the library already knows.

    The same control a multi-valued filter axis uses - chips for what is set, and the
    text input once the list outgrows a glance, because a list longer than a screen is
    typed into rather than scrolled. Typing filters the known
    ones, so a tag somebody already used is the easy thing to pick; a new one is added
    on Enter, and `add-unique` is what makes a repeat impossible.

    Case is not folded. Two spellings are two tags until somebody merges them, and
    folding here would hide the duplicate instead of letting it be found.
    """
    def draw() -> None:
        with ui.column().classes("gap-1 w-full min-w-0"):
            if derived:
                _derived_chips(derived, library.tag_looks())
            control = tag_chips.Picker(library.tags(), value=held,
                                       looks=library.tag_looks(), adds=True,
                                       look=dropdown.OUTLINED) \
                .props('hide-dropdown-icon popup-content-class="console-picker-popup"') \
                .classes("w-full min-w-0")
        control.on_value_change(lambda: on_change(list(control.value or [])))

    return draw


def _derived_chips(tags: Sequence[str], looks: dict[str, dict[str, Any]]) -> None:
    with ui.element("span").classes(tag_chips.BOX):
        for tag in tags:
            sources = (looks.get(tag) or {}).get("sources") or [{}]
            panel.tag_link(
                tag, tag_chips.color_of(tag, looks), mark=community.ICON,
                to=community.address(str(sources[0].get("extension") or ""),
                                     str(sources[0].get("list") or "")),
                hint=t("console.tags.from_source",
                       source=", ".join(tag_source(one) for one in sources if one)))()


IPDB_URL = "https://www.ipdb.org/machine.cgi?id={id}"


# What the catalog calls these against what a person does. Only where the two differ:
# `Manufacturer` needs no translating and a map that repeats it is a map nobody trusts.
DETAIL_WORDS = {
    "Title": t("word.name"),
    "IPDBId": "IPDB",
    "guides": t("console.workbench.guides"),
    "Themes": t("console.workbench.theme"),
}


def _details_differ(context: dict[str, Any],
                    differs: list[dict[str, Any]]) -> Callable[[], None]:
    """The game's details against the entry's, where they have come apart.

    Adopting is one act over all of them rather than a choice per field. They are one
    machine's facts, and taking this one's year beside that one's maker would describe
    no machine at all.
    """
    async def adopt() -> None:
        await _write(context, context["library"].adopt_vps_details,
                     context["game_id"])

    def draw() -> None:
        # The block lays its children out in a row, so the stack goes in a column of
        # its own - the same shape the fault list beside an icon uses.
        with ui.element("div").classes("console-attention w-full"), \
                ui.column().classes("gap-1 min-w-0 grow"):
            ui.label(t("console.workbench.spreadsheet_differs")) \
                .classes("console-attention-line")
            for item in differs:
                said = str(item.get("field") or "")
                with ui.row().classes("items-baseline gap-2 w-full no-wrap"):
                    ui.label(DETAIL_WORDS.get(said, said)).classes("console-diff-field")
                    ui.label(str(item.get("ours") or "-")).classes("console-diff-was")
                    ui.icon("arrow_forward").classes("console-diff-arrow")
                    ui.label(str(item.get("theirs") or "-")).classes("console-help truncate")
            ui.button(t("console.workbench.use_spreadsheet"),
                icon=verbs.ACCEPT, on_click=adopt) \
                .props("flat dense no-caps size=sm").classes("console-action")

    return draw


def _change_match(pick: Callable[[], Any], *, matched: bool) -> Callable[[], None]:
    """The one act a Match group offers, named for whether there is a match to change."""
    said = t("console.workbench.change_match") if matched \
        else t("console.workbench.match_vps")
    hint = t("console.workbench.change_match.help") if matched \
        else t("console.workbench.match_vps.help")

    def draw() -> None:
        with ui.element("div").classes("console-slot-actions"):
            panel.action(said, pick, icon=verbs.MATCH, hint=hint)()

    return draw


@on_page
async def _pick_a_match(context: dict[str, Any]) -> None:
    """Ask which catalog entry this game is, and write the answer.

    The picker itself is `console.vps_match`, because the grid offers the same act over
    a selection and two copies of it would drift. What stays here is the write: this
    section owns the game in front of it and knows how to redraw itself afterwards.
    """
    picked = await vps_match.ask(context["library"], context["game"])
    if picked is vps_match.CANCELLED:
        return
    library = context["library"]
    try:
        if picked == vps_match.CLEARED:
            await run.io_bound(library.declare_no_match, context["game_id"])
            await context["rebuild"]()
            return
        await run.io_bound(library.set_game_overrides, context["game_id"],
                           {"alt_vps_id": str(picked)})
        differs = await run.io_bound(library.vps_details, context["game_id"])
        if differs:
            wanted = await _confirm_details(differs)
            if wanted:
                await run.io_bound(library.adopt_vps_details, context["game_id"], wanted)
    except Exception as exc:
        ui.notify(t("console.workbench.save_failed"), caption=why(exc), type="negative")
    await context["rebuild"]()


async def _confirm_details(differs: list[dict[str, Any]]) -> list[str]:
    """Ask which of the new entry's details to take, and answer with their names.

    Everything is ticked to start, so confirming without reading takes the whole entry -
    which is what somebody who has just said "this is that machine" means.
    """
    chosen = {str(item.get("field") or ""): True for item in differs}

    with frame.opened(t("console.workbench.new_entry_question"), wide=True,
                      persistent=True) as box:
        for new in (False, True):
            rows = [one for one in differs if bool(one.get("new")) is new]
            if not rows:
                continue
            panel.facts(ui, [(panel.HEADING, t("console.workbench.details_new") if new
                              else t("console.workbench.details_changed"))])
            with ui.column().classes("w-full gap-0 px-3"):
                for item in rows:
                    _detail_choice(item, chosen)
        with frame.footer():
            frame.cancel(lambda: box.submit(False))
            frame.answer(t("console.workbench.use_selected"), lambda: box.submit(True),
                         icon=verbs.ACCEPT)

    if not await box:
        return []
    return [field for field, take in chosen.items() if take]


def _detail_choice(item: dict[str, Any], chosen: dict[str, bool]) -> None:
    """One field, with what it would become - and what it is now, where there is one."""
    field = str(item.get("field") or "")
    with ui.row().classes("items-baseline gap-2 w-full no-wrap"):
        box = ui.checkbox(value=True).props("dense")
        box.on_value_change(lambda _, key=field, b=box: chosen.__setitem__(key,
                                                                          bool(b.value)))
        ui.label(DETAIL_WORDS.get(field, field)).classes("console-diff-field")
        if not item.get("new"):
            ui.label(str(item.get("ours") or "-")).classes("console-diff-was")
            ui.icon("arrow_forward").classes("console-diff-arrow")
        ui.label(str(item.get("theirs") or "-")).classes("console-help truncate")


def _rom_state(pinmame: dict[str, Any], rom: str,
               context: dict[str, Any] | None = None) -> Any:
    """The rom, and whether it is actually there.

    The chain resolves aliases and audits the install, so the name alone is half an
    answer: what anybody wants of a rom is whether it will run.

    A missing one carries the way *to* the fix rather than the fix: Launch reports and
    Assets manages, so a finding jumps to where the act lives.
    """
    installed = pinmame.get("installed")
    if not pinmame.get("effective") or installed is None:
        return rom
    chip = _state(t("word.installed") if installed
            else t("console.workbench.not_installed"),
                  "on" if installed else "warn", beside=rom)
    if installed or context is None:
        return chip

    def draw() -> None:
        chip()
        ui.button(t("console.workbench.assets"), icon=verbs.DRILL,
                  on_click=lambda: _choose(context, "assets")) \
            .props("flat dense no-caps size=sm") \
            .classes("console-action console-action--inline") \
            .tooltip(t("console.workbench.rom_tip"))

    return draw


def _rom_row(context: dict[str, Any], pinmame: dict[str, Any]) -> Any:
    rom = str(pinmame.get("effective") or pinmame.get("declared") or "-")
    chip = _rom_state(pinmame, rom)
    if pinmame.get("installed") is not False:
        return chip
    return _with_add(context, "rom", chip)


def _with_add(context: dict[str, Any], kind: str, chip: Callable[[], Any]) -> Any:
    def draw() -> None:
        with ui.element("div").classes("console-fact-edit"):
            chip()
            _add_action(context, kind)

    return draw


def _add_action(context: dict[str, Any], kind: str) -> None:
    opens = _add_opener(context, kind)
    if opens is not None:
        panel.action(t("word.add"), opens, icon=verbs.ADD, inline=True,
                     hint=t("console.workbench.add_missing.help"))()


def _add_opener(context: dict[str, Any], kind: str) -> Callable[[], Any] | None:
    label = _asset_name(kind)
    done = context["rebuild"]
    if kind == "readme":
        return partial(mediasource.open_notes_sources, context, label, done)
    if kind in file_acts.WHOLE_FOLDER or kind == "rom":
        return partial(mediasource.open_folder_sources, context, kind, label, done)
    if kind in file_acts.PLACEABLE:
        return partial(mediasource.open_asset_sources, context, kind, label, done)
    return None


async def _findings(context: dict[str, Any],
                    tables: Sequence[dict[str, Any]]) -> list[tuple[Any, Any]]:
    """What is wrong with these tables, before anything that is merely true about them:
    one alert per finding, ending in the act that fixes it where the panel has one.

    Only real faults. Hidden and not-default are choices somebody made, not problems,
    and listing them here would teach the block to be ignored.
    """
    releases: dict[str, dict[str, Any]] = {}
    entry_url = unread = ""
    if any(table.get("update_available") for table in tables):
        vps_id = str(context["game"].get("vps_id") or "")
        listed, unread = await _read_releases(context, vps_id)
        releases = {str(one.get("vps_file_id") or ""): one for one in listed}
        if vps_id and not unread:
            try:
                entry = await offload.io(context["library"].vps_entry, vps_id)
            except Exception as exc:
                logger.warning("console: could not read VPS for %s", vps_id, exc_info=True)
                unread = why(exc)
            else:
                entry_url = str((entry or {}).get("url") or "")
    named = len(context["tables"]) > 1
    entries: list[tuple[Any, Any]] = []
    for table in tables:
        said = game_tables.name_among(table, context["tables"]) if named else ""
        entries += [(FULL, _alert(line, act, said))
                    for line, act in _faults(context, table, releases, entry_url, unread)]
    return entries


def _faults(context: dict[str, Any], table: dict[str, Any],
            releases: dict[str, dict[str, Any]], entry_url: str,
            unread: str = "") -> list[tuple[str, Callable[[], None] | None]]:
    pinmame = (table.get("dependencies") or {}).get("pinmame") or {}
    faults: list[tuple[str, Callable[[], None] | None]] = []
    if not table.get("available"):
        # Three ways a thing can be unavailable and they are not the same fault. A file
        # that is gone is a deletion; a file somewhere else is a location that is away,
        # and nothing here is lost; something with no file at all has nothing to play
        # it. The same sentence for all three would send somebody to the wrong fix.
        if game_tables.is_referenced(table):
            faults.append((t("console.workbench.place_unreachable"), None))
        elif game_tables.is_keyed(table):
            faults.append((t("console.workbench.unplayable"), None))
        else:
            faults.append((t("console.workbench.file_absent"),
                           panel.action(t("word.forget"),
                                        partial(_forget_table, context, table),
                                        icon=verbs.FORGET,
                                        hint=t("console.workbench.forget_table.help"))))
    base = (table.get("source") or {}).get("base") or {}
    if table.get("available") and base.get("file") and not base.get("available"):
        faults.append((t("console.workbench.source_gone"), None))
    if pinmame.get("effective") and pinmame.get("installed") is False:
        opens = _add_opener(context, "rom")
        faults.append((t("console.workbench.rom_missing", rom=pinmame["effective"]),
                       panel.action(t("word.add"), opens, icon=verbs.ADD,
                                    hint=t("console.workbench.add_missing.help"))
                       if opens else None))
    if table.get("update_available"):
        source = table.get("source") or {}
        theirs = str(source.get("version") or "")
        release = releases.get(str(source.get("vps_file_id") or "")) or {}
        to = str(release.get("url") or "") or entry_url
        act = (panel.link_out(t("console.workbench.get_version", version=theirs), to=to)
               if to else _state(t("console.workbench.vps_failed"), "unknown",
                                 hint=unread) if unread else None)
        faults.append((t("console.workbench.newer_on_vps", theirs=theirs,
                         ours=str(table.get("version") or "")), act))
    return faults


def _alert(line: str, act: Callable[[], None] | None, said: str = "") -> Callable[[], None]:
    """One finding, and the table it is about where the panel holds more than one."""
    def draw() -> None:
        with ui.element("div").classes("console-attention"):
            ui.icon("error_outline").classes("console-attention-icon")
            with ui.column().classes("gap-0 min-w-0 grow"):
                ui.label(line).classes("console-attention-line")
                if said:
                    ui.label(said).classes("console-member-table truncate max-w-full") \
                        .tooltip(said)
            if act is not None:
                act()

    return draw


def _hidden_row(context: dict[str, Any], table: dict[str, Any]) -> tuple[Any, Any]:
    """Whether the frontend offers this table."""
    table_id = str(table.get("id") or "")

    @on_page
    async def hide(event: Any) -> None:
        hidden = bool(event.value)
        try:
            answer = await run.io_bound(context["library"].set_table_hidden,
                                        context["game_id"], table_id, hidden)
        except Exception as exc:
            ui.notify(t("console.workbench.save_failed"), caption=why(exc), type="negative")
            return
        ui.notify(game_tables.hidden_said(str(context["game"].get("name") or ""), table,
                                          answer, hidden=hidden), type="positive")
        await context["rebuild"]()

    # On is hidden, the direction the grid column and its filter read the same flag.
    return (t("word.hidden"),
            lambda: _switch(bool(table.get("hidden")), hide,
                            hint=game_tables.hidden_hint(table, context["tables"])))


def _switch(value: bool, on_change: Callable[[Any], Any], *,
            disabled: bool = False, hint: str = "") -> None:
    """The panel's switch, drawn where it is called rather than handed back."""
    panel.switch(value, on_change, disabled=disabled, hint=hint)()


def _play_action(context: dict[str, Any], table: dict[str, Any]) -> Callable[[], None]:
    """Play this one, not the game's default - the panel is about this entry."""
    filename = game_tables.native_key(table)

    @on_page
    async def go() -> None:
        try:
            await run.io_bound(context["library"].launch, context["game_id"], filename)
        except Exception as exc:
            ui.notify(t("console.workbench.launch_failed"), caption=why(exc), type="negative")

    def draw() -> None:
        with ui.row().classes("items-center gap-2"):
            button = ui.button(t("console.workbench.play_table"), icon="play_arrow",
                    on_click=go) \
                .props("flat dense no-caps size=sm").classes("console-action")
            if not table.get("available"):
                button.disable()
                button.tooltip(t("console.workbench.vpx_absent"))

    return draw


def launcher_rows(context: dict[str, Any], table: dict[str, Any]) -> list[tuple[Any, Any]]:
    """Which launcher plays this table and what it does after. Neither has a discovered
    value - each falls back to what applies everywhere - so empty is the revert."""
    overrides = table.get("overrides") or {}

    async def toggle(event: Any) -> None:
        await _save_overrides(context, {"delete_nvram_on_close": bool(event.value)},
                              table=True)

    def nvram() -> None:
        _switch(bool(overrides.get("delete_nvram_on_close")), toggle,
                hint=t("console.workbench.nvram_note"))

    return [
        (t("console.workbench.launcher"), _launcher_pick(context, table)),
        *_launcher_notes(context, table),
        (t("console.workbench.nvram_clear"), nvram),
    ]


def _launcher_report(context: dict[str, Any], table: dict[str, Any]) -> tuple[Any, Any]:
    """The launcher in one line, and a way to its settings."""
    name = str(table.get("launcher_name") or "")
    own = int(table.get("launcher_settings_here") or 0)
    from_game = int(table.get("launcher_settings_from_folder") or 0)
    configurable = bool(table.get("launcher_app_configurable"))
    said = (t("console.workbench.launcher_own", name=name, count=own)
            if name and configurable and own
            else t("console.workbench.launcher_from_game", name=name, count=from_game,
                   scope=t(CAME_FROM["folder"]))
            if name and configurable and from_game
            else name or "-")
    to = "/console?" + deeplink.query({**context["state"], "section": "table_settings"})
    return (t("console.workbench.launcher"),
            panel.link(said, to=to, on_click=partial(_choose, context, "table_settings")))


def _launcher_notes(context: dict[str, Any], table: dict[str, Any]) -> list[tuple[Any, Any]]:
    """What the picker cannot say itself: that there is nothing to pick, or that the
    program playing this table does without what the table's own app knows about it."""
    listing = context.get("launchers") or {}
    held = listing.get("launchers") or []
    if not held:
        return [panel.note(t("console.workbench.launcher_hint"))]
    runs = next((one for one in held if one["launcher_id"] == table.get("launcher")), None)
    own: dict[str, Any] = next((one for one in listing.get("apps") or []
                if one.get("id") == table.get("app")), {})
    if runs is None or runs.get("app") == table.get("app") or not own.get("has_config"):
        return []
    return [panel.note(t("console.workbench.runs_with_other",
                         app=runs.get("app_name") or "", own=own.get("name") or ""))]


def _launcher_pick(context: dict[str, Any], table: dict[str, Any]) -> Callable[[], None]:
    """Which launcher plays this table, chosen from the ones this install has.

    A picker, not a path. A free-text field asks somebody to type a binary that nothing
    validates, and every other table would have to be told about it separately.

    It shows the launcher that plays the table. One the table chose carries a dot and a
    Clear, and clearing is how it goes back to the default.
    """
    table_id = str(table.get("id") or "")
    listing = context.get("launchers") or {}
    held = listing.get("launchers") or []
    known = {one["launcher_id"]: one for one in held}
    named = str((listing.get("mappings") or {}).get(table_id) or "")
    named = named if named in known else ""
    offer = launchers_page.launcher_offer(held, str(table.get("app") or ""), named)
    current = named or str(table.get("launcher") or "")

    def draw() -> None:
        field = panel.MarkedSelect(
            {one["id"]: one["name"] for one in offer},
            value=current if any(one["id"] == current for one in offer) else None,
            marks={one["id"]: one["mark"] for one in offer},
            heading=t("console.workbench.other_programs"),
            heading_at=next((one["id"] for one in offer if one["other"]), None)) \
            .classes("w-full min-w-0")
        if named:
            field.props("clearable")
            off = not known[named].get("enabled")
            with field.add_slot("prepend"):
                ui.element("span").classes(
                    "console-mark console-mark--full console-named-mark"
                    + (" console-named-mark--off" if off else "")).tooltip(
                    t("console.workbench.named_off", name=known[named]["display_name"],
                      fallback=str(table.get("launcher_name") or "")) if off
                    else t("console.workbench.chosen_here"))
        if not held:
            field.disable()
            field.tooltip(t("console.workbench.no_launcher"))

        @on_page
        async def changed() -> None:
            try:
                await run.io_bound(context["library"].assign_launcher,
                                   table_id, str(field.value or ""))
            except Exception as exc:
                ui.notify(t("console.workbench.launcher_failed"),
                          caption=why(exc), type="negative")
                return
            await (context.get("rebuild") or context["saved"])()

        field.on_value_change(changed)

    return draw


def _launchers_for_panel(library: Library) -> dict[str, Any]:
    """This install's launchers with the default marked, beside what each table names
    and what each app has. Runs off the event loop.

    Empty where the read fails: the panel is about a table, and a launcher list that
    would not load is a disabled picker with a reason rather than a panel that does not
    draw.
    """
    try:
        found = library.launchers()
    except Exception:
        logger.exception("Could not read the launchers for the table panel")
        return {}
    defaults = set((found.get("defaults") or {}).values())
    return {**found, "launchers": [{**one, "is_default": one["launcher_id"] in defaults}
                                   for one in (found.get("launchers") or [])]}


# Named for the thing, not for the .info key. PinMAME is left out: it is not a script
# flourish like the rest, and the ROM row above already answers for it in detail.
def _feature_chips(features: dict[str, Any]) -> None:
    """What the table's script was seen to use, named where there is room for names -
    the grid draws the same three states as marks."""
    with ui.element("div").classes("console-chips"):
        for key, label in table_features.LABELS.items():
            state = table_features.state_of(features.get(key))
            ui.label(label).classes(f"console-tier {state.chip}").tooltip(state.noun)


@on_page
async def _script_act(context: dict[str, Any], call: Any, table_id: str,
                      done: str, failed: str) -> None:
    """Run one script act and redraw. The panel is showing which script runs, so it is
    exactly what the act changes."""
    try:
        await run.io_bound(call, context["game_id"], table_id)
    except Exception as exc:
        ui.notify(failed, caption=why(exc), type="negative")
        return
    ui.notify(done, type="positive")
    await context["rebuild"]()


async def _extract_script(context: dict[str, Any], table: dict[str, Any]) -> None:
    """Not confirmed: it writes a new file and takes nothing away, and the way back is
    the Delete beside it."""
    await _script_act(context, context["library"].extract_script,
                      table.get("id") or "", t("console.workbench.extract_done", count=1),
                      t("console.workbench.extract_failed"))


@on_page
async def _drop_script(context: dict[str, Any], table: dict[str, Any]) -> None:
    """Confirmed: whatever the sidecar held goes with it, and a patched table quietly
    becomes an unpatched one."""
    every = game_tables.shares_its_script(table)
    if not await confirm.ask(
            t("console.workbench.delete_question", count=1),
            detail=t("console.game_tables.script_detail" if every
                     else "console.workbench.delete_detail"),
            lines=[f"{Path(table.get('filename') or '').stem}.vbs"]):
        return
    await _script_act(context, context["library"].delete_script,
                      table.get("id") or "",
                      t("console.game_tables.script_deleted" if every
                        else "console.workbench.delete_done", count=1),
                      t("console.workbench.delete_failed"))


@on_page
async def _forget_table(context: dict[str, Any], table: dict[str, Any]) -> None:
    """Drop a gone table's record, once the user says it is not coming back.

    Confirmed because it is the only destructive thing on this surface, and the dialog
    names the file rather than the id - the id is ours, the filename is what the user
    recognizes. The API refuses the request outright if the .vpx is back, so a stale
    panel cannot delete a table that returned while it was open.
    """
    detail = ("console.workbench.forget_keyed" if game_tables.is_keyed(table)
              else "console.workbench.forget_reference" if game_tables.is_referenced(table)
              else "console.workbench.forget_missing")
    made = game_tables.made_from_it_line(
        [game_tables.name_among(one, context["tables"])
         for one in game_tables.made_from_it(table, context["tables"])])
    if not await confirm.ask(
            t("console.workbench.forget_table", count=1), detail=t(detail),
            lines=[game_tables.name_among(table, context["tables"]), *([made] if made else [])],
            confirm=t("word.forget"), icon=verbs.FORGET):
        return
    try:
        await run.io_bound(context["library"].forget_table,
                           context["game_id"], table.get("id") or "")
    except Exception as exc:
        ui.notify(t("console.workbench.forget_failed"), caption=why(exc), type="negative")
        return
    ui.notify(t("console.workbench.table_forgotten", count=1), type="positive")
    await _table_gone(context, table)


async def _table_gone(context: dict[str, Any], table: dict[str, Any]) -> None:
    """Put the panel and the grid right once `table` is no longer the game's."""
    if table.get("id") and table.get("id") == context.get("lens"):
        left = await offload.io(context["library"].tables_for, context["game_id"])
        after = next((str(one.get("id") or "") for one in left if one.get("default")), "")
        if await _open_in_tables(context, after):
            return
    await _table_list_changed(context)


# How long a table that has just been added is marked as new in its game's block.
_ARRIVED_S = 5.0


def _add_table(context: dict[str, Any]) -> None:
    mediasource.open_table_sources(context, _after_an_add(context))


def _after_an_add(context: dict[str, Any]) -> Callable[[], Awaitable[None]]:
    """What follows a table joining this game, remembering what it held before so what
    arrived can be told from what was there."""
    held = {str(one.get("id") or "") for one in context["tables"]}
    was = next((one for one in context["tables"] if one.get("default")), None)
    return partial(_table_added, context, held, was)


async def after_a_row_drop(library: Library, state: dict[str, Any], game_id: str,
                           redraw: Callable[[], None]) -> Callable[[], Awaitable[None]]:
    """What follows a table dropped on a game's row: what follows one dropped on its
    panel, with the page put right in place of the panel where it shows another game."""
    game = next((one for one in library.games if str(one.get("id")) == game_id), {})
    tables = await offload.io(library.tables_for, game_id)

    async def put_right() -> None:
        shown = state.get("panel_rebuild")
        if state.get("game") == game_id and callable(shown):
            await shown()
            return
        refresh = state.get("refresh_game")
        if state.get("view") in ("games", "tables") and callable(refresh):
            await refresh(game_id)
            return
        redraw()

    context = {"library": library, "game": game, "game_id": game_id, "tables": tables,
               "state": state, "rebuild": put_right}
    return _after_an_add(context)


@on_page
async def _table_added(context: dict[str, Any], held: set[str],
                       was: dict[str, Any] | None) -> None:
    try:
        tables = await offload.io(context["library"].tables_for, context["game_id"])
    except Exception:  # noqa: BLE001 - the redraw below reads it again and says why
        tables = []
    new = next((one for one in tables if str(one.get("id") or "") not in held), None)
    if new is None:
        await _table_list_changed(context)
        return
    context["state"]["arrived_table"] = (str(new.get("id") or ""), time.monotonic())
    _say_added(context, new, was, tables)
    if not await _open_in_tables(context, str(new.get("id") or "")):
        await _table_list_changed(context)


def _say_added(context: dict[str, Any], new: dict[str, Any], was: dict[str, Any] | None,
               tables: list[dict[str, Any]]) -> None:
    """Name what arrived, and where the automatic default moved to it, offer the one it
    moved from back, locked."""
    name = game_tables.name_among(new, tables)
    game = str(context["game"].get("name") or "")
    plays = next((one for one in tables if one.get("default")), None)
    if was is None or plays is None or plays.get("id") != new.get("id"):
        ui.notify(t("console.game_tables.added", table=name, game=game), type="positive")
        return
    state, game_id, library = context["state"], context["game_id"], context["library"]
    view = state.get("view")
    kept = game_tables.name_among(was, tables)

    async def keep() -> None:
        await offload.io(library.set_default_table, game_id, str(was.get("id") or ""))
        redraw = state.get("panel_rebuild")
        if state.get("game") == game_id and state.get("view") == view and callable(redraw):
            await redraw()
            return
        refresh = state.get("refresh_game")
        if callable(refresh):
            await refresh(game_id)

    undo.offer(t("console.game_tables.result_added", table=name, game=game), keep,
               label=t("console.game_tables.keep", table=kept),
               done=t("console.game_tables.locked_to", table=kept))


async def _open_in_tables(context: dict[str, Any], table_id: str) -> bool:
    """Under Tables, put the grid right and open `table_id` there, or nothing where it
    is "". False under any other view, which a rebuild answers instead."""
    state = context["state"]
    opens = state.get("open_table")
    if state.get("view") != "tables" or not callable(opens):
        return False
    refresh = state.get("refresh_game")
    if callable(refresh):
        await refresh(context["game_id"])
    await opens(table_id)
    return True


async def _table_list_changed(context: dict[str, Any]) -> None:
    """Redraw the panel, and put the grid behind it right too.

    A name at the call site; `rebuild` does both.
    """
    await context["rebuild"]()


@on_page
async def _contain_table(context: dict[str, Any], table: dict[str, Any]) -> None:
    """Copy a referenced file into the game folder, so the entry stops depending on
    somewhere else being there.

    Confirmed because it writes a file and because what it costs - the disk - is the
    thing somebody is choosing to spend. Named for what it is *for*, not for the
    mechanism: nobody wants "convert to contained", they want the table to keep working
    when the share is away.
    """
    reference = table.get("reference") or {}
    if not await confirm.ask(
            t("console.workbench.copy_question"),
            detail=t("console.workbench.copy_detail"),
            lines=[reference.get("resolved") or reference.get("path") or ""],
            confirm=t("console.workbench.copy"), icon=verbs.COPY):
        return
    try:
        await run.io_bound(context["library"].contain_table,
                           context["game_id"], table.get("id") or "")
    except Exception as exc:  # noqa: BLE001
        ui.notify(t("console.workbench.copy_failed"), caption=why(exc), type="negative")
        return
    ui.notify(t("console.workbench.copied"), type="positive")
    await _table_list_changed(context)


def _tables_block(context: dict[str, Any], held: bool = True) -> None:
    """This game's tables, and which one it offers first.

    A block inside Game Details rather than a rail entry of its own: most games hold one
    table, so "Tables (1)" would be a place you went to read a single row, and the rail
    holds places. This is the shape instead - a sub-table, a related collection with its
    own columns.

    Version and author, and a filename only for what separates two rows that match on
    both.
    """
    tables = context["tables"]
    showing = str(context.get("lens") or "")
    # Only where there is a choice to describe. A count beside one row says nothing.
    said = t("console.workbench.tables_2", count=(len(tables))) if len(tables) > 1 \
        else t("console.workbench.table_3")
    with ui.row().classes("items-center gap-2 w-full no-wrap console-heading-row"):
        ui.label(said if tables else t("console.workbench.tables")) \
            .classes("console-card-title console-fact-heading grow")
    if not tables:
        ui.label(t("console.workbench.no_tables")).classes("console-help")
    arrived, at = context["state"].get("arrived_table") or ("", 0.0)
    if time.monotonic() - at > _ARRIVED_S:
        arrived = ""
    usual = game_tables.usual_launcher(tables)
    apart = game_tables.told_apart(tables)
    for table in tables:
        since = str(table.get("absent_since") or "")
        here = str(table.get("id") or "") == showing
        with ui.column().classes("gap-0 w-full console-member-row") as row:
            if arrived and table.get("id") == arrived:
                row.classes(add="console-member-row--new")
            # Chips gathered before anything is drawn: they wrap under the name rather
            # than competing with it for the line, and an empty run must draw no row.
            chips: list[tuple[str, str, str]] = []
            if since:
                # Stated, not judged: how long it has been gone is what tells a
                # deletion from a share that was late mounting, and that call is
                # the user's.
                chips.append((game_tables.word_for(game_tables.FILE_WORDS, True),
                              "console-tier console-tier--warn",
                              t("console.workbench.absent_since", value=when.local(since))))
            if table.get("hidden"):
                chips.append((game_tables.HIDDEN_WORDS[0], "console-chip-warn",
                              game_tables.hidden_hint(table, tables)))
            launcher = str(table.get("launcher_name") or "")
            if launcher and str(table.get("launcher") or "") != usual:
                chips.append((launcher, "console-tier console-tier--off", ""))

            with ui.row().classes("items-start gap-2 w-full no-wrap"):
                # On every row, and leading. `docs/conventions.md`: show varying state
                # on every row rather than let a reader take meaning from absence -
                # which is what a chip on the default alone asked them to do. A game
                # has exactly one default, so the control that says so is a radio.
                _default_mark(context, table, several=len(tables) > 1)
                # The name and what qualifies it on one line, wrapping only when the
                # line runs out - and wrapping onto the name's own left edge rather
                # than the radio's, because they belong to the name. One unwrapped row
                # spent the name's width on the chips and left a file called "VP..."
                # to tell two builds apart.
                with ui.row().classes("items-center gap-2 grow min-w-0 "
                                      "console-member-main"):
                    name = _said_name(table, game_tables.table_name(table)) \
                        .classes("console-member-name min-w-0")
                    differs = apart.get(str(table.get("id") or ""))
                    if differs:
                        ui.label(differs).classes("console-cell-quiet truncate min-w-0") \
                            .tooltip(str(table.get("filename") or ""))
                    # Which of them the panel beside this is about. Without it the block
                    # repeats the grid you are already looking at; with it, it is where
                    # you are - this game has two, you are on one, that one is default.
                    if here:
                        name.classes(add="console-member-name--here")
                    if since:
                        name.classes(add="opacity-60")
                    elif table.get("default") \
                            and (table.get("default_kind") or "") == game_tables.CHOSEN:
                        word, why = game_tables.DEFAULT_WORDS[game_tables.CHOSEN]
                        with ui.row().classes("items-center gap-1 no-wrap console-cell-quiet"):
                            ui.icon(verbs.LOCKED).classes("console-member-lock")
                            ui.label(word).tooltip(why)
                    for text, tone, why in chips:
                        chip = ui.label(text).classes(f"console-member-chip {tone}")
                        if why:
                            chip.tooltip(why)
                with ui.element("div").classes("console-row-action"):
                    if game_tables.is_referenced(table):
                        ui.button(icon=verbs.CONTAIN,
                                  on_click=lambda _, t=table: _contain_table(context, t)) \
                            .props("flat dense round size=sm") \
                            .tooltip(t("console.workbench.copy_game"))
                    # An entry the folder does not hold can always be forgotten: nothing
                    # on disk here will mint it again, which is the opposite of a table
                    # that is there - dropping that record only means the next scan
                    # re-adds it.
                    if game_tables.can_forget(table):
                        ui.button(icon=verbs.FORGET,
                                  on_click=lambda _, t=table: _forget_table(context, t)) \
                            .props("flat dense round size=sm color=warning") \
                            .tooltip(t("word.forget"))
                    if not since:
                        _lock_button(context, table, tables)
                        _release_button(context, table)
                        _launch_button(context, table)
            _release_line(table, held)
    # Drawn even where the list is empty: a folder with nothing in it yet is exactly
    # where one of these is added.
    with ui.row().classes("items-center gap-2 w-full console-slot-actions"):
        panel.action(t("console.workbench.add_table"), lambda: _add_table(context),
                     icon=verbs.ADD, hint=t("console.workbench.add_table.help"))()


def _release_line(table: dict[str, Any], held: bool = True) -> None:
    """Which build of the machine this file is, once somebody has said.

    Nothing at all until then, which is the honest reading of an absent record: no
    matcher has examined this and none exists, so a row that read "not matched" would
    be reporting a search that never happened.

    Drawn from what the row already carries. Reaching for the release list here puts a
    blocking API call inside a synchronous draw, and the rows after it never appear.
    """
    source = table.get("source") or {}
    if not source.get("vps_file_id"):
        return
    version = str(source.get("version") or "")
    made_by = ", ".join(str(name) for name in (source.get("authors") or [])[:3])
    told = " \u00b7 ".join(part for part in (version, made_by) if part)
    if not told and not held:
        return
    with ui.row().classes("items-center gap-2 w-full no-wrap console-member-table-line"):
        ui.label(told or t("console.workbench.delisted_table")) \
            .classes("console-help truncate")
    _based_on(source.get("mod_of"), "console-member-table-line")


def _based_on(mod: dict[str, Any] | None, classes: str = "") -> None:
    """What a table's release is a mod of, one level up: the way to that table where the
    library holds it, in whichever game, and Missing with the way to VPS where not."""
    line = game_tables.mod_line(mod)
    if not mod or not line:
        return
    with ui.row().classes(f"items-center gap-2 w-full no-wrap min-w-0 {classes}"):
        if mod.get("table_id"):
            panel.link(line, to="/console?" + deeplink.query(
                {"view": "tables", "game": str(mod.get("game_id") or ""),
                 "table": str(mod["table_id"])}))()
            return
        ui.label(line).classes("console-help truncate min-w-0")
        if not mod.get("vps_file_id"):
            return
        word, why = game_tables.GONE_WORDS
        ui.label(word).tooltip(why) \
            .classes("console-member-chip console-tier console-tier--off")
        if mod.get("url"):
            panel.out(to=str(mod["url"]), hint=t("console.vps_match.open_in_vps"))()


def _release_button(context: dict[str, Any], table: dict[str, Any]) -> None:
    """The way to say which build this file is.

    Shown whether or not one is recorded, because with nothing recorded there is
    otherwise no way in: the row says nothing about its release until somebody has
    answered, so the affordance cannot be the answer.
    """
    entry = str(context["game"].get("vps_id") or "")
    button = ui.button(icon="link",
                       on_click=lambda: _pick_a_release(context, table)) \
        .props("flat dense round size=sm")
    if entry:
        button.tooltip(t("console.workbench.release"))
        return
    # A release belongs to an entry, so there is nothing to choose among until the
    # game is matched. Said on the control rather than in a dialog that opens empty.
    button.disable()
    button.tooltip(t("console.workbench.releases_unmatched"))


async def _match_line(context: dict[str, Any], kind: str, matched_to: Any) -> str:
    """What the bound record is called. Resolved here because the catalog is already
    open on this side and an id is not something to put on screen."""
    said = str(matched_to or "")
    listed = file_acts.listed_as(kind, vps_kinds.MEDIA)
    if not said or listed is None:
        return ""
    library = context["library"]
    vps_id = str(context["game"].get("vps_id") or "")
    try:
        records = (await offload.io(library.vps_releases, vps_id, listed.listed_as)
                   if vps_id else [])
        held = bool(records) or bool(vps_id and await offload.io(library.vps_catalog_held))
    except Exception:
        logger.warning("console: could not read %s for %s", listed.listed_as, vps_id,
                       exc_info=True)
        return t("console.workbench.matched_file")
    for record in records:
        if str(record.get("vps_file_id") or "") == said:
            told = " · ".join(part for part in (
                str(record.get("version") or ""),
                ", ".join(str(name) for name in (record.get("authors") or [])[:2]),
            ) if part)
            return t("console.workbench.matched",
                    told=(told)) if told else t("console.workbench.matched_file")
    # Worth saying: it is why no update will ever be reported for this file.
    return (t("console.workbench.delisted_file") if held
            else t("console.workbench.matched_file"))


def _match_button(context: dict[str, Any], kind: str, label: str,
                  entry: dict[str, Any], redraw: Callable[[], None]) -> None:
    """The way to say which VPS record one file is. Only for media kinds VPSdb lists -
    a picker over a kind nothing publishes opens empty every time."""
    listed = file_acts.listed_as(kind, vps_kinds.MEDIA)
    if listed is None:
        return
    path = str(entry.get("path") or "")
    if not path:
        return
    bound = str(entry.get("matched_to") or "")
    button = ui.button(t("console.workbench.change_match_2") if bound
            else t("console.workbench.match"), icon=verbs.MATCH,
                       on_click=lambda: _pick_a_record(context, listed.listed_as,
                                                       label, path, bound, redraw)) \
        .props("flat dense no-caps size=sm").classes("console-action")
    if context["game"].get("vps_id"):
        button.tooltip(t("console.workbench.published_file"))
        return
    # The records belong to an entry, so there is nothing to choose among until the
    # game is matched. Said on the control rather than in a dialog that opens empty.
    button.disable()
    button.tooltip(t("console.workbench.files_unmatched"))


@on_page
async def _pick_a_record(context: dict[str, Any], listed_as: str, label: str,
                         path: str, bound: str,
                         redraw: Callable[[], None]) -> None:
    """Bind one file to a record VPSdb publishes, or take the binding back.

    The assets ledger's twin of `_pick_a_release`, unordered for the same reason: a
    scorer over this question is no better than chance.
    """
    picked = await ask_a_record(context, listed_as, label, path, bound)
    if picked is None:
        return
    await _write(context, context["library"].set_asset_source, context["game_id"], path,
                 str(picked))
    redraw()


async def ask_a_record(context: dict[str, Any], listed_as: str, label: str, path: str,
                       bound: str, place: str = "") -> Any:
    """The record the person picked, "" to take the binding back, or what leaving answers:
    nothing, or in a walk (`place` is its position) Skip and Stop."""
    records, empty, reason = await _listed_by_vps(
        context, t("console.workbench.kind_unlisted", kind=label), listed_as)

    with frame.opened(t("console.workbench.published", kind=label), wide=True,
                      persistent=True) as box:
        if place:
            ui.label(place).classes("console-help px-3")
        ui.label(path).classes("console-help px-3")
        with ui.column().classes("w-full gap-0 console-source-list console-pick-list px-3"):
            _in_place_of_list(empty, reason)
            for item in records:
                _record_row(item, box, bound)
        with frame.footer():
            if bound:
                frame.aside(t("word.clear"), lambda: box.submit(""), icon=verbs.CLEAR)
            frame.leave(box, bool(place))

    return await box


def _record_row(record: dict[str, Any], dialog: Any, bound: str) -> None:
    """One published file, by the two things a person can compare against their own."""
    said = str(record.get("vps_file_id") or "")
    meta = []
    made_by = ", ".join(str(name) for name in (record.get("authors") or [])[:3])
    if made_by:
        meta.append(made_by)
    if record.get("updated_at"):
        meta.append(when.ago(record["updated_at"]))
    name = str(record.get("version") or "") or t("console.workbench.no_version")
    if said == bound:
        name = f"{name}  ✓"
    candidates.choice(str(record.get("img_url") or ""), name,
                      " · ".join(meta), lambda: dialog.submit(said),
                      glyph="inventory_2", missing=vps_match.NO_PICTURE)


async def _listed_by_vps(context: dict[str, Any], none_listed: str,
                         *listed_as: str) -> tuple[list[dict[str, Any]], str, str]:
    """What VPS lists for the game, read off the loop, the line a picker shows in place
    of the list - `none_listed`, or why there is no list to show - and why a read
    failed. The two lines are empty while there is a list."""
    library = context["library"]
    vps_id = str(context["game"].get("vps_id") or "")
    try:
        found = (list(await offload.io(library.vps_releases, vps_id, *listed_as))
                 if vps_id else [])
        held = bool(found) or await offload.io(library.vps_catalog_held)
    except Exception as exc:
        logger.warning("console: could not read VPS for %s", vps_id, exc_info=True)
        return [], t("console.workbench.vps_failed"), why(exc)
    if found:
        return found, "", ""
    return [], none_listed if held else t("console.workbench.no_vps_data"), ""


def _in_place_of_list(line: str, reason: str) -> None:
    if line:
        panel.line(line, hint=reason)


@on_page
async def _pick_a_release(context: dict[str, Any], table: dict[str, Any]) -> None:
    """Bind this table to one of the entry's builds, or take the binding back.

    Ordered as VPSdb holds them and marked with nothing: a scorer over this exact
    question is no better than chance. What the panel does offer is the file's own
    version and authors, which is not a ranking - it is the user's own data, put where
    they can compare it against the list rather than remembering it.
    """
    library = context["library"]
    bound = str((table.get("source") or {}).get("vps_file_id") or "")
    releases, empty, reason = await _listed_by_vps(
        context, t("console.workbench.tables_unlisted"))

    with frame.opened(t("console.workbench.release_table"), wide=True,
                      persistent=True) as box:
        with ui.element("div").classes("px-3"):
            _yours(table)
        with ui.column().classes("w-full gap-0 console-source-list console-pick-list px-3"):
            _in_place_of_list(empty, reason)
            for item, under in in_lineage(releases):
                _release_row(item, box, bound, under)
        with frame.footer():
            if bound:
                frame.aside(t("word.clear"), lambda: box.submit(""), icon=verbs.CLEAR)
            frame.cancel(lambda: box.submit(None))

    picked = await box
    if picked is None:
        return
    await _write(context, library.set_table_source, context["game_id"],
                 str(table.get("id") or ""), str(picked))


def _yours(table: dict[str, Any]) -> None:
    """What this file says about itself, so the list is compared against something.

    A `.vpx` carries a version and its authors and VPS names releases by the same two,
    which is the only honest handle here - VPS records a filename on almost none of them.
    """
    said = str(table.get("version") or "")
    made_by = ", ".join(str(name) for name in (table.get("authors") or [])[:4])
    told = " \u00b7 ".join(part for part in (said, made_by) if part)
    if table.get("filename"):
        ui.label(str(table["filename"])).classes("console-slot-file")
    ui.label(t("console.workbench.file_says", told=(told)) if told
             else t("console.workbench.unversioned")) \
        .classes("console-help")


def _release_words(release: dict[str, Any]) -> tuple[str, str]:
    """A build's name and the line under it: its version, then format, makers and date."""
    meta = [str(release.get("format") or "")]
    made_by = ", ".join(str(name) for name in (release.get("authors") or [])[:3])
    if made_by:
        meta.append(made_by)
    if release.get("updated_at"):
        meta.append(when.ago(release["updated_at"]))
    name = str(release.get("version") or "") or t("console.workbench.no_version")
    return name, " \u00b7 ".join(part for part in meta if part)


def _release_row(release: dict[str, Any], dialog: Any, bound: str,
                 under: bool = False) -> None:
    """One build, with its picture."""
    said = str(release.get("vps_file_id") or "")
    name, meta = _release_words(release)
    if said == bound:
        name = f"{name}  \u2713"
    row = candidates.choice(str(release.get("img_url") or ""), name, meta,
                            lambda: dialog.submit(said), glyph=icons.TABLES,
                            more=_mod_words(release), missing=vps_match.NO_PICTURE)
    if under:
        row.classes("console-source-row--under")


def _mod_words(release: dict[str, Any]) -> tuple[str, ...]:
    """What a mod is a mod of, and VPS's note on it where that line does not carry it."""
    mod = release.get("mod_of")
    if not mod:
        return ()
    line = game_tables.mod_line(mod)
    note = str(release.get("comment") or "").strip()
    return (line, note) if note and mod.get("vps_file_id") else (line,)


def in_lineage(releases: list[dict[str, Any]]) -> list[tuple[dict[str, Any], bool]]:
    """`releases` with each mod straight after the one it is based on, and whether it
    sits under one. One step in however deep the chain; a mod of a release not in the
    list keeps its place, and a loop of links is placed where its first member is."""
    listed = {str(one.get("vps_file_id") or "") for one in releases} - {""}
    under: dict[str, list[dict[str, Any]]] = {}
    for one in releases:
        parent = str((one.get("mod_of") or {}).get("vps_file_id") or "")
        if parent in listed:
            under.setdefault(parent, []).append(one)
    placed: set[int] = set()
    ordered: list[tuple[dict[str, Any], bool]] = []

    def place(one: dict[str, Any], nested: bool) -> None:
        if id(one) in placed:
            return
        placed.add(id(one))
        ordered.append((one, nested))
        for mod in under.get(str(one.get("vps_file_id") or ""), []):
            place(mod, True)

    for one in releases:
        if str((one.get("mod_of") or {}).get("vps_file_id") or "") not in listed:
            place(one, False)
    for one in releases:
        place(one, False)
    return ordered


def _release_shown(release: dict[str, Any]) -> None:
    """The build a table is matched to, in the shape the picker offered it."""
    url = str(release.get("url") or "")

    def end() -> None:
        if url:
            panel.out(to=url, hint=t("console.workbench.open_release"))()

    name, meta = _release_words(release)
    candidates.choice(str(release.get("img_url") or ""), name, meta,
                      glyph=icons.TABLES, trailing=end, entry=True,
                      missing=vps_match.NO_PICTURE)


async def _read_releases(context: dict[str, Any],
                         vps_id: str) -> tuple[list[dict[str, Any]], str]:
    """The entry's builds, read off the loop, and why they could not be read. Empty
    where they were."""
    if not vps_id:
        return [], ""
    try:
        return list(await offload.io(context["library"].vps_releases, vps_id)), ""
    except Exception as exc:
        logger.warning("console: could not read VPS for %s", vps_id, exc_info=True)
        return [], why(exc)


def _launch_button(context: dict[str, Any], table: dict[str, Any]) -> None:
    """Play this one. The row names the table, so the act on it is unambiguous - which
    is what lets Game Details offer a launch without inventing a game-level one whose
    target would be implicit."""
    filename = game_tables.native_key(table)

    @on_page
    async def go() -> None:
        try:
            await run.io_bound(context["library"].launch, context["game_id"], filename)
        except Exception as exc:
            ui.notify(t("console.workbench.launch_failed"), caption=why(exc), type="negative")

    button = ui.button(icon="play_arrow", on_click=go) \
        .props("flat dense round size=sm").tooltip(t("console.workbench.play_table"))
    if not table.get("available"):
        button.disable()


def _default_mark(context: dict[str, Any], table: dict[str, Any], *,
                  several: bool) -> None:
    """Which table the game offers, and the way to change it. A table that cannot be the
    default is shown unset, with why."""
    chosen = bool(table.get("default"))
    mark = ui.icon("radio_button_checked" if chosen else "radio_button_unchecked") \
        .classes("console-default-mark")
    if chosen:
        mark.classes(add="console-default-mark--on")
        automatic = several and (table.get("default_kind") or "") == game_tables.DERIVED
        mark.tooltip(game_tables.DEFAULT_WORDS[game_tables.DERIVED][1] if automatic
                     else t("console.workbench.offered_table"))
        return
    if why := game_tables.why_not_default(table):
        mark.classes(add="opacity-30")
        mark.tooltip(why)
        return
    mark.classes(add="cursor-pointer")
    mark.tooltip(t("console.workbench.make_default"))
    mark.on("click", lambda t=table: _make_default(context, t))


def _lock_button(context: dict[str, Any], table: dict[str, Any],
                 tables: list[dict[str, Any]]) -> None:
    act = game_tables.lock_act(table, tables)
    if act is None:
        return
    lock, hint = act
    ui.button(icon=verbs.LOCK if lock else verbs.UNLOCK,
              on_click=lambda: _lock_default(context, table, lock=lock)) \
        .props("flat dense round size=sm").tooltip(hint)


@on_page
async def _lock_default(context: dict[str, Any], table: dict[str, Any], *,
                        lock: bool) -> None:
    try:
        after = await run.io_bound(context["library"].set_default_table, context["game_id"],
                                   str(table.get("id") or "") if lock else "")
    except Exception as exc:
        ui.notify(t("console.workbench.change_failed"), caption=why(exc), type="negative")
        return
    ui.notify(game_tables.lock_said(str(context["game"].get("name") or ""), table,
                                    (after or {}).get("tables") or [], lock=lock),
              type="positive")
    await context["rebuild"]()


@on_page
async def _make_default(context: dict[str, Any], table: dict[str, Any]) -> None:
    """Hand the game a different default. Everything downstream that follows the game
    rather than one table moves with it, which is the point of following."""
    try:
        await run.io_bound(context["library"].set_default_table,
                           context["game_id"], str(table.get("id") or ""))
    except Exception as exc:
        ui.notify(t("console.workbench.change_failed"), caption=why(exc), type="negative")
        return
    ui.notify(game_tables.now_plays(str(context["game"].get("name") or ""), table),
              type="positive")
    await context["rebuild"]()


def _rows(target: Any, entries: Sequence[tuple[Any, ...]]) -> None:
    """The panel's fact list, with this surface's labels cased on the way in.

    The pane writes them as prose - `Made by`, `Last played` - so the casing rule is
    applied here rather than inside the list, where it would also reach labels a
    registry has already settled and turn `RAR Tool Path` into `Rar Tool Path`.
    """
    panel.facts(target, [(entry[0] if entry[0] in (panel.HEADING, panel.FULL,
                                                   panel.ASIDE, panel.LEDE)
                          else field_label(str(entry[0])), *entry[1:])
                         for entry in entries])


# --- collections ------------------------------------------------------------------
# A collection's rail. Nothing here is shared with a game's: the two subjects have no
# section in common, because the rail is a function of (nav node, subject) rather than
# one list everything appears in.
#
def _collection(context: dict[str, Any]) -> dict[str, Any]:
    return context["collection"]


def _is_dynamic(row: dict[str, Any]) -> bool:
    """Whether this collection changes under its owner.

    Derived, never stored: it carries criteria or it does not. Named for what it does
    to the user rather than for how it was built, which is what makes the arrangement
    question answerable - only a static list has a membership stable enough to arrange.
    """
    return (row.get("type") or "") == "filter"


def _rules_drafted(context: dict[str, Any]) -> bool:
    """Whether an unsaved draft asks for anything."""
    return bool(context.get("unsaved") and collection_rules.filters_from(
        context["draft"].get("rules") or [], context["fields"]))


# --- Device sections --------------------------------------------------------
#
# Each is a thin adapter: the rows themselves are `console/devices.py`'s, because what a
# device is and what may be asked of it belongs with the device, not with the panel that
# draws it. The panel's job here is the rail and the frame.

def _device(context: dict[str, Any]) -> dict[str, Any]:
    return context.get("device") or {}


async def _device_details(context: dict[str, Any]) -> None:
    """Everything a device is, in groups, read down in one go.

    Descriptive, then operational, then what this install holds about it: what a thing
    *is* comes before what can be done to it, and the record we keep of it is nobody's
    first question.
    """
    with ui.column().classes("gap-0 console-form"):
        _rows(ui, await devices_page.detail_groups(context))


async def _device_software(context: dict[str, Any]) -> None:
    """What it is running, and whether there is a newer build to take."""
    with ui.column().classes("gap-0 console-form"):
        _rows(ui, await devices_page.software_rows(context))


async def _device_capabilities(context: dict[str, Any]) -> None:
    """What it can be asked for, as that install declares it."""
    with ui.column().classes("gap-0 console-form"):
        _rows(ui, devices_page.capability_rows(context))


async def _device_logs(context: dict[str, Any]) -> None:
    """What it has been writing down."""
    with ui.column().classes("gap-0 console-form"):
        _rows(ui, await devices_page.log_rows(context))


# The app's declared groups, as rail sections. Fixed rather than read at import: a
# section key has to be stable for `section=` in an address to mean one thing, and the
# groups an app declares are its own vocabulary rather than this file's.
CONFIG_GROUP_KEYS = ("displays", "input", "sound", "graphics", "plugins")


def _launcher_config_sections() -> tuple[Section, ...]:
    """One rail section per group the app declares, in the order it declares them.

    A group the launcher's app does not offer draws nothing and the rail leaves it out,
    which is how 10.8.0 - where the plugin architecture does not exist - shows fewer
    sections rather than empty ones.
    """
    return tuple(
        Section(f"launcher_{key}", _config_group_label(key), _config_group_block(key),
                subjects=frozenset({"launcher"}), shown=_config_group_shown(key))
        for key in CONFIG_GROUP_KEYS)


def _config_group_shown(key: str) -> Callable[[dict[str, Any]], bool]:
    def shown(context: dict[str, Any]) -> bool:
        if not _program_is_there(context):
            return False
        found = _group(context, key)
        return found is not None and bool(found.settings)
    return shown


def _program_is_there(context: dict[str, Any]) -> bool:
    """Whether the program this launcher names is on this machine, which is where its
    settings are read from. Details stays without it, to point it somewhere else."""
    return _program_state(context.get("launcher") or {}) == path_state.OK


def _program_state(launcher: dict[str, Any]) -> str:
    checks = launcher.get("checks") or {}
    return str((checks.get("bin_path") or {}).get("state") or "")


def _program_note(launcher: dict[str, Any]) -> str:
    """Why its program's own settings are not shown, or "" where they are or it has
    none to show."""
    state = _program_state(launcher)
    if not launcher.get("has_config") or state == path_state.OK:
        return ""
    if state == path_state.UNSET:
        return t("console.workbench.program_hint", app=launcher["app_name"])
    return t("console.workbench.app_missing", app=launcher["app_name"])


def _config_group_label(key: str) -> Callable[[dict[str, Any]], str]:
    def said(context: dict[str, Any]) -> str:
        found = _group(context, key)
        return found.label if found is not None else key.title()
    return said


def _group(context: dict[str, Any], key: str) -> Any:
    return next((g for g in context.get("config_groups") or [] if g.key == key), None)


def _config_group_block(key: str) -> Callable[[dict[str, Any]], Any]:
    async def draw(context: dict[str, Any]) -> None:
        found = _group(context, key)
        if found is None or not found.settings:
            return
        await _config_rows(context, found)
    return draw


# Where a value came from, in the words somebody would use. Never the wire's: a
# setting nobody has touched is not "unset", it is what the program does by default, and
# saying so takes no word at all - an unmarked row is the untouched one, so a mark always
# means somebody did something.
CAME_FROM = {
    "launcher": "console.workbench.all_tables",
    "folder": "console.workbench.this_game",
    "entry": "console.workbench.table",
}


def _config_mark(held: dict, scope: str, field: Any) -> Callable[[], None] | None:
    """The word beside a value, where it is an exception: a scope other than this one and
    All Tables. Set here is the dot's to say (`_marked`)."""
    came = held.get("scope") or ""
    if not held.get("set_here") and came not in ("", scope, "launcher"):
        return panel.state(t(CAME_FROM.get(came, "console.workbench.inherited")), "off")
    return None


Part = tuple[Callable[[], None], dict, Any]


def _varies(parts: Sequence[Part], tables: Sequence[dict[str, Any]], app_name: str,
            joiner: str = "", *, by_value: bool = False) -> Callable[[], None] | None:
    """Varies, where the tables a row is written to use different values for it, with
    each table's on hover: a pair's two parts joined by `joiner`. With `by_value` the
    hover counts the tables holding each value, which is what a long selection can be
    read from."""
    if not any(held.get("varies") for _, held, _ in parts):
        return None
    each = [held.get("each") or [] for _, held, _ in parts]
    said = [joiner.join(_said_value(field, used[index][1])
                        or t("console.workbench.app_default", app=app_name)
                        for used, (_, _, field) in zip(each, parts, strict=True))
            for index in range(len(each[0]))]
    if by_value:
        lines = [t("console.workbench.value_count", said=value, count=count)
                 for value, count in Counter(said).most_common()]
    else:
        lines = [t("console.workbench.part_said", label=_table_line(table, list(tables)),
                   said=value) for (table, _), value in zip(each[0], said, strict=True)]
    return panel.state(t("console.workbench.varies"), "off", hint="\n".join(lines))


def _marked(parts: Sequence[Part], app_name: str,
            redraws: list[Callable[[], None]] | None = None, *, joiner: str = "",
            on_leave: Callable[[], Any] | None = None,
            clear: Callable[[], Awaitable[None]] | None = None,
            playing: bool = False) -> Callable[[], None]:
    """One value, or a pair with `joiner` between them, as `(control, held, field)`. A
    value at the default is drawn quiet and unmarked. Where this scope sets any of them
    to something else, a dot comes before it, whose each is on hover, and `clear` after
    the control. Each draw adds to `redraws` what brings the dot, the hover and Reset up to
    each `held` without drawing the controls again. `on_leave` runs when focus leaves the
    line.

    Reset only where there is something to reset: on an untouched row it would be a
    control that does nothing, and a column of inert verbs teaches people to stop reading
    them.
    """
    def draw() -> None:
        with ui.row().classes("items-center gap-1 no-wrap console-field-line") as line:
            line.props["data-setting"] = parts[0][2].key
            with ui.row().classes("items-center gap-1 no-wrap console-field-row") as row:
                dot = ui.element("span").classes(
                    "console-mark console-mark--full console-named-mark")
                if len(parts) == 1:
                    parts[0][0]()
                else:
                    _pair(parts, joiner)
                path_tip = getattr(parts[0][0], "path_tip", None) if len(parts) == 1 else None
                whose = None
                if path_tip is None:
                    whose = ui.tooltip("")
                    whose.props('anchor="bottom left" self="top left"')
            end = ui.element("div").classes("console-row-action")
        if on_leave is not None:
            row.on("focusout", on_leave)

        def show() -> None:
            changed = [(held, field) for _, held, field in parts if _changed(held, field)]
            dot.set_visibility(bool(changed))
            off = any(not held.get("in_effect", True) for held, _ in changed)
            dot.classes(add="console-named-mark--off" if off else None,
                        remove=None if off else "console-named-mark--off")
            row.classes(add=None if changed else "console-field-row--default",
                        remove="console-field-row--default" if changed else None)
            said = _each_said(
                [(field, _whose_value(held, field, app_name)) for _, held, field in parts],
                len(parts))
            if path_tip is not None:
                path_tip.say(said)
            elif whose is not None:
                whose.text = said
            end.clear()
            if clear is not None and changed:
                with end:
                    panel.icon_action(t("word.reset"), clear, icon=verbs.RESET,
                                      enabled=not playing,
                                      hint=t(PLAYING_NOTE) if playing else _each_said(
                                          [(field, _clear_hint(held, field, app_name))
                                           for held, field in changed], len(parts)))()

        show()
        if redraws is not None:
            redraws.append(show)
    return draw


def _pair(parts: Sequence[Part], joiner: str) -> None:
    """Each part's control, named by its label for a screen reader, with `joiner` after
    every part but the last: where the pair wraps, the second control starts the line at
    the first one's edge instead of being pushed in by a joiner."""
    with ui.element("div").classes("console-field-pair"):
        for index, (control, _, field) in enumerate(parts):
            with ui.element("div").classes("console-field-part") as named:
                control()
                if joiner and index < len(parts) - 1:
                    ui.label(joiner).classes("console-cell-join").props("aria-hidden=true")
            named.props["role"] = "group"
            named.props["aria-label"] = field.label
            named.props["data-setting"] = field.key


def _each_said(said: Sequence[tuple[Any, str]], of: int) -> str:
    """What the parts of a row of `of` say: once where each of them says the same, else a
    line per part led by its name."""
    if len(said) == of and len({words for _, words in said}) == 1:
        return said[0][1]
    return "\n".join(t("console.workbench.part_said", label=field.label, said=words)
                     for field, words in said)


def _whose_value(held: dict, field: Any, app_name: str) -> str:
    whose = t(CAME_FROM.get(held.get("scope") or "", "console.workbench.inherited"))
    if held.get("set_here") and not held.get("in_effect", True):
        if said := _said_value(field, held.get("value") or ""):
            return t("console.workbench.override_value", whose=whose, value=said)
        return t("console.workbench.override", whose=whose)
    if held.get("set_here"):
        value, follows = _follows(held, field, app_name)
        if not _changed(held, field):
            return follows
        if value:
            return t("console.workbench.changed_from", value=value, whose=follows)
        return t("console.workbench.changed_link", whose=follows)
    if held.get("scope"):
        return whose
    if not held.get("value") and (said := getattr(field, "left_empty", "")):
        return str(said)
    return t("console.workbench.app_default", app=app_name)


def _same_value(field: Any, one: str, other: str) -> bool:
    if _said_value(field, one) == _said_value(field, other):
        return True
    try:
        return float(one) == float(other)
    except ValueError:
        return False


def _said_value(field: Any, value: str) -> str:
    """A value as somebody reads it rather than as it is stored. A switch is On or Off,
    never 1 or 0, and an enumerated setting is its own label."""
    if value == "":
        return getattr(field, "blank", "")
    if getattr(field, "type", "") == "bool":
        return t("word.off") if value in ("0", "false",
                t("console.workbench.false")) else t("word.on")
    for stored, label in getattr(field, "choices", ()) or ():
        if stored == value:
            return label
    return value


def _leaves(held: dict, field: Any) -> str:
    """The value that is in force once this scope stops naming one."""
    if held.get("fallback_scope"):
        return str(held.get("fallback") or "")
    return str(field.default or "")


def _follows(held: dict, field: Any, app_name: str) -> tuple[str, str]:
    """`_leaves` as somebody reads it, and whose it is."""
    where = held.get("fallback_scope") or ""
    whose = (t(CAME_FROM.get(where, "console.workbench.inherited")) if where
             else t("console.workbench.app_default", app=app_name))
    return _said_value(field, _leaves(held, field)), whose


def _changed(held: dict, field: Any) -> bool:
    """A value this scope sets that is not the one it would follow without it. One that
    something narrower answers over counts: it is the exception most worth seeing."""
    if not held.get("set_here"):
        return False
    if held.get("varies") or not held.get("in_effect", True):
        return True
    return not _same_value(field, str(held.get("value") or ""), _leaves(held, field))


def _clear_hint(held: dict, field: Any, app_name: str) -> str:
    """What resetting it will leave in force, and whose value that is."""
    value, whose = _follows(held, field, app_name)
    if value:
        return t("console.workbench.back_to", value=value, whose=whose)
    return t("console.workbench.back_link", whose=whose)


def _beside(mark_of: Callable[[], Callable[[], None] | None], held: dict, field: Any,
            redraws: list[Callable[[], None]] | None = None,
            more: Callable[..., Callable[[], None] | None] | None = None,
            beyond: Callable[[], None] | None = None,
            paired: Sequence[tuple[dict, Any]] = (),
            ) -> Callable[[], None]:
    """The mark, whatever `more` offers for somebody's own value, then `beyond` whoever's
    value it is. Drawn as a panel ASIDE, whose cell it hides while it holds none of them.
    `paired` is the rest of a pair's rows, `(held, field)` each, handed to `more` too.
    """
    def draw() -> None:
        cell = ui.context.slot.parent
        box = ui.row().classes("items-center gap-2 no-wrap")

        def fill() -> None:
            box.clear()
            mark = mark_of()
            own = any(one.get("set_here") for one in (held, *(said for said, _ in paired)))
            verb = more(held, field, *paired) if more is not None and own else None
            with box:
                if mark is not None:
                    mark()
                if verb is not None:
                    verb()
                if beyond is not None:
                    beyond()
            cell.set_visibility(mark is not None or verb is not None or beyond is not None)

        fill()
        if redraws is not None:
            redraws.append(fill)
    return draw


# Said once over the group rather than on every row. The program rewrites both layers
# when a table exits and its own in-game menu writes the same keys, so an edit made now
# is one of two writers and the last one wins.
PLAYING_NOTE = "console.workbench.playing_lock"
PLAYING_WHY = "console.workbench.playing_lock.help"

# A number writes on every keystroke, so its redraw waits until it loses focus: drawn
# between two keys, the second lands nowhere.
TYPED = ("int", "number")
REPORTED = "reported"


def _playing(library: Library) -> bool:
    try:
        return bool((library.play_state() or {}).get("launching"))
    except Exception:  # noqa: BLE001 - not knowing is not a reason to refuse to draw
        return False


async def _config_rows(context: dict[str, Any], group: Any) -> None:
    """One area of the program's own settings, at the launcher scope: the rows the app
    curates for it under their headings, then the way to the rest."""
    if not group.curated:
        await _every_row(context, group)
        return
    if vpx_input.applies(group):
        with ui.column().classes("gap-0 console-form"):
            panel.facts(ui, vpx_input.entries(context, group, await _config_values(context)))
        return
    values = await _config_values(context)
    _area_search(context, group, values)
    shown = curated_blocks(group, values)
    if vpx_displays.applies(group):
        entries = await vpx_displays.entries(
            context, group, shown, values,
            partial(_setting_entries, context, curated=True,
                    redraw_on=switches(group.curated)))
    else:
        entries = await _setting_entries(
            context, [(heading.label, heading.note, fields) for heading, fields in shown],
            curated=True, redraw_on=switches(group.curated),
            pairs=[pair for heading, _ in shown for pair in heading.pairs])
    if rest := len(group.settings) - len(curated_keys(group)):
        entries.append((FULL, panel.action(
            t("console.workbench.more_settings", count=rest),
            lambda: _open_all_settings(context, area=group.key), icon=verbs.DRILL,
            hint=t("console.workbench.more_settings.help"))))
    with ui.column().classes("gap-0 console-form"):
        panel.facts(ui, entries)


async def _every_row(context: dict[str, Any], group: Any) -> None:
    """An area the app curates nothing for, whole."""
    # A heading per source section. Labels are the program's and are not unique - five
    # plugins each call their switch `Enable`, and two of the five say nothing else
    # about themselves. The section is the only thing that tells them apart, and it is
    # what the program groups them by too.
    titled = len({_section_of(f.key) for f in group.settings}) > 1
    blocks = [(_section_label(section, group.label) if titled else "", "", list(fields))
              for section, fields in groupby(group.settings, lambda f: _section_of(f.key))]
    with ui.column().classes("gap-0 console-form"):
        panel.facts(ui, await _setting_entries(context, blocks))


def curated_blocks(group: Any, values: dict[str, Any]) -> list[tuple[Any, list[Any]]]:
    """Each curated heading with the rows it draws: all of them while its switch is on
    anywhere, the switch alone while it is off, and never a row its own switch hides."""
    by_key = {f.key: f for f in group.settings}

    def set_to(key: str, on: bool) -> bool:
        held = values.get(key) or {}
        return (key in by_key and not held.get("varies")
                and _is_on(by_key[key], held) == on)

    found = []
    for heading in group.curated:
        hidden = {key for one in getattr(heading, "switched", ())
                  if set_to(one.enabled_by, not getattr(one, "on", True)) for key in one.keys}
        fields = [by_key[key] for key in heading.keys if key in by_key and key not in hidden]
        if set_to(heading.enabled_by, False):
            fields = [by_key[heading.enabled_by]]
        if fields:
            found.append((heading, fields))
    return found


def switches(headings: Iterable[Any]) -> set[str]:
    """Every switch the headings draw rows by."""
    return {key for one in headings
            for key in (one.enabled_by, *(s.enabled_by for s in getattr(one, "switched", ())))
            if key}


def conflicts(groups: Sequence[Any], values: dict[str, Any]) -> dict[str, str]:
    """Each switch that is on while a rival of it is too, and that rival's name."""
    headings = [one for group in groups for one in getattr(group, "curated", ())
                if one.enabled_by]
    fields = {f.key: f for group in groups for f in group.settings}
    names = {one.enabled_by: one.label or apps.humanized(one.key) for one in headings}

    def on(key: str) -> bool:
        return key in fields and _is_on(fields[key], values.get(key) or {})

    return {one.enabled_by: names.get(rival, rival) for one in headings
            if on(one.enabled_by) for rival in getattr(one, "rivals", ()) if on(rival)}


def rival_switches(groups: Sequence[Any]) -> set[str]:
    return {key for group in groups for one in getattr(group, "curated", ())
            if getattr(one, "rivals", ()) for key in (one.enabled_by, *one.rivals)}


def curated_keys(group: Any) -> set[str]:
    held = {f.key for f in group.settings}
    return {key for heading in group.curated for key in heading.keys if key in held}


def _is_on(field: Any, held: dict[str, Any]) -> bool:
    value = str(held.get("value") or field.default or "").strip().lower()
    return value not in ("", "0", "false", "off", "no")


def _area_search(context: dict[str, Any], group: Any, values: dict[str, Any]) -> None:
    """Any setting, found from any area: what is typed here carries on in All Settings, and
    so does what differs from the default in this area."""
    app_name = str(context["launcher"].get("app_name") or "")
    with ui.row().classes("items-center gap-x-4 console-section-bar"):
        search = panel.search(t("console.app_settings.search_settings")) \
            .props("debounce=250")
        holder = ui.row().classes("items-center")

    def draw_changed(changed: int) -> None:
        holder.clear()
        with holder:
            panel.action(t("console.workbench.changed_filter_count", count=changed),
                         lambda: _open_all_settings(context, area=group.key, differs=True),
                         icon=verbs.FILTER, enabled=bool(changed),
                         hint=t("console.workbench.changed_filter.help" if changed
                                else "console.workbench.changed_filter.none",
                                app=app_name))()

    async def recount() -> None:
        if not holder.is_deleted:
            draw_changed(changed_count([group], await _config_values(context)))

    draw_changed(changed_count([group], values))
    context["recount_changed"] = recount

    def find(typed: Any) -> None:
        if said := str(typed or "").strip():
            _open_all_settings(context, query=said, focus=True)

    search.on_value_change(lambda e: find(e.value))


def _open_all_settings(context: dict[str, Any], **wanted: Any) -> None:
    """All Settings on what was asked for, and nothing an earlier visit narrowed it to."""
    context["state"]["all_settings"] = wanted
    _choose(context, "launcher_all")


async def _config_values(context: dict[str, Any]) -> dict[str, Any]:
    """Every value as it stands at the context's scope - the launcher's unless it names
    a table, or as its `config_read` reads them - read once per draw."""
    values: dict[str, Any] = context.setdefault("config_values", {})
    if not values and (read := context.get("config_read")) is not None:
        values.update(await run.io_bound(read) or {})
    elif not values:
        values.update(await run.io_bound(
            context["library"].launcher_config_values,
            context["launcher"]["launcher_id"], str(context.get("config_table") or ""),
            str(context.get("config_scope") or "launcher")) or {})
    return values


def _mark_for(held: dict, scope: str, field: Any,
              offered: bool) -> Callable[[], None] | None:
    """`_config_mark`, or why this scope holds a value it does not offer: Per Table at the
    launcher, and Ignored at a table where the program never reads it."""
    if offered:
        return _config_mark(held, scope, field)
    if held.get("set_here") and scope == "launcher":
        return panel.state(t("console.app_settings.per_table"), "off",
                           hint=t("console.app_settings.per_table.help"))
    if not held.get("set_here") or held.get("in_effect"):
        return None
    return panel.state(t("console.app_settings.ignored"), "warn",
                       hint=t("console.app_settings.all_tables_only"))


async def _setting_entries(context: dict[str, Any],
                           blocks: Sequence[tuple[str, str, Sequence[Any]]], *,
                           curated: bool = False, sub: bool = False,
                           redraw_on: Collection[str] = (),
                           pairs: Sequence[Any] = (),
                           ahead: Mapping[str, Sequence[tuple[Any, Any]]] | None = None,
                           ) -> list[tuple[Any, Any]]:
    """Settings as fact rows, block by block: its heading where it has one - a
    sub-heading with `sub` - the line under that, then its rows. A curated row's line is
    the app's help where it has one; the program's description otherwise. Two rows of a
    block that `pairs` names are one row, under the pair's label and note. `ahead` maps a
    setting's key to entries drawn above its row.

    A write marks every row again in place, so a control keeps its focus. The panel is
    redrawn instead where a setting in `redraw_on` was written, or where the write changed
    another setting's value or whose it is - drawn or not, since a table's first file of
    its own changes what it lists. For a number, that waits until it loses focus.

    The value shown is always the one the program will use, never what this scope
    happens to hold: you should not be looking at a number that is not in force.
    """
    library = context["library"]
    launcher = context["launcher"]
    values = await _config_values(context)
    scope = str(context.get("config_scope") or "launcher")
    table = str(context.get("config_table") or "")
    their_own = await _set_by_tables(context) if scope == "launcher" and not table else []
    if (more := context.get("config_more")) is not None:
        await more.ready(values)
    groups = context.get("config_groups") or []
    clashing = conflicts(groups, values)
    named = {f.key for _, _, fields in blocks for f in fields if getattr(f, "reported", ())}
    redraw_on = {*redraw_on, *rival_switches(groups), *named}
    seen = await offload.io(screens.connected) if named else []
    rows: dict[str, dict] = {}
    redraws: list[Callable[[], None]] = []
    shown = dict(values)
    pending = {"written": ""}
    reads = {"begun": 0, "shown": 0}
    in_turn = asyncio.Lock()

    async def settle() -> None:
        if written := pending["written"]:
            pending["written"] = ""
            await _keeping_place(ui.context.client, context["rebuild"], written)

    def written(values: dict[str, str]) -> Awaitable[Any]:
        if (write := context.get("config_write")) is not None:
            return config_applied(write, values)
        return run.io_bound(library.write_launcher_config, launcher["launcher_id"], values,
                            table=table, scope=scope)

    def clear(keys: Sequence[str]) -> Callable[[], Awaitable[None]]:
        @on_page
        async def wipe() -> None:
            try:
                async with in_turn:
                    wrote = await written({key: "" for key in keys
                                           if rows[key].get("set_here")})
            except Exception as exc:  # noqa: BLE001
                ui.notify(t("said.clear_failed"), caption=why(exc), type="negative")
                return
            if (done := context.get("config_done")) is not None:
                done(wrote or {})
            context.pop("config_values", None)
            await _keeping_place(ui.context.client, context["rebuild"], keys[0])
        return wipe

    def save(key: str, typed: bool) -> Callable[[Any], Awaitable[bool]]:
        @on_page
        async def write(value: Any) -> bool:
            try:
                async with in_turn:
                    wrote = await written({key: _as_text(value)})
            except Exception as exc:  # noqa: BLE001
                ui.notify(t("said.save_failed"), caption=why(exc), type="negative")
                return False
            if cut := (wrote or {}).get("cut"):
                no_longer_reads_game(cut, context.get("tables"))
            if (done := context.get("config_done")) is not None:
                done(wrote or {})
            context.pop("config_values", None)
            reads["begun"] += 1
            mine = reads["begun"]
            try:
                fresh = await _config_values(context)
            except Exception:  # noqa: BLE001
                fresh = {}
            cleared = bool(table and fresh and key in ((wrote or {}).get("cleared") or ()))
            stuck = cleared and _whose(fresh, key) not in ("", "launcher")
            if cleared and not stuck:
                ui.notify(t("console.app_settings.cleared"), type="positive")
            if fresh and typed and (stuck or key in redraw_on or _moved(shown, fresh, key)):
                pending["written"] = key
            elif not fresh or stuck or key in redraw_on or _moved(shown, fresh, key):
                asyncio.create_task(_keeping_place(ui.context.client, context["rebuild"], key))
                return True
            saved = context.get("saved")
            if callable(saved) and _whose(shown, key) != _whose(fresh, key):
                asyncio.create_task(saved())
            if more is not None:
                await more.ready(fresh)
            if mine < reads["shown"]:
                return True
            reads["shown"] = mine
            shown.update(fresh)
            for other, held in rows.items():
                held.clear()
                held.update(fresh.get(other) or {})
            for redraw in redraws:
                redraw()
            for follow in list(context.get("followers", ())):
                follow(fresh)
            if (recount := context.get("recount_changed")) is not None:
                await recount()
            return True
        return write

    playing = bool(context.get("playing"))
    app_name = str(launcher.get("app_name") or "")

    def offered(field: Any) -> bool:
        return scope in (getattr(field, "scopes", ()) or (scope,))

    def part(field: Any) -> Part:
        held = rows.setdefault(field.key, dict(values.get(field.key) or {}))
        option = _as_option(field)
        reported = getattr(field, "reported", ())
        return settings_page.control_for(
            option, settings_page.value_for(option, held.get("value")),
            save(field.key, option["type"] in TYPED), writable=not playing and offered(field),
            check=_unreported(held.get("value"), reported, app_name),
            suggestions={REPORTED: screens.reported(reported, seen)},
            varies=bool(held.get("varies")), browse=library.folders), held, field

    def marks(parts: Sequence[Part], joiner: str = "") -> Callable[[], None] | None:
        return _in_turn(_varies(parts, context.get("tables") or [], app_name, joiner,
                                by_value=bool(context.get("by_value"))),
                        *(None if held.get("varies")
                          else _mark_for(held, scope, field, offered(field))
                          for _, held, field in parts))

    entries: list[tuple[Any, Any]] = []
    if playing:
        entries.append(panel.note(t(PLAYING_NOTE), hint=t(PLAYING_WHY)))
    for title, lede, fields in blocks:
        if title and sub:
            entries.append((FULL, partial(_subheading, title)))
        elif title:
            entries.append((HEADING, title))
        if lede:
            entries.append(panel.lede(lede))
        in_block = {field.key: field for field in fields}
        rows_of = [(pair, [in_block[key] for key in pair.keys]) for pair in pairs
                   if all(key in in_block for key in pair.keys)]
        paired = {pair.keys[0]: (pair, both) for pair, both in rows_of}
        taken = {key for pair, _ in rows_of for key in pair.keys[1:]}
        for field in fields:
            if field.key in taken:
                continue
            entries.extend((ahead or {}).get(field.key, ()))
            pair, members = paired.get(field.key, (None, [field]))
            parts = [part(one) for one in members]
            keys = [one.key for one in members]
            owned = _tables_setting(their_own, keys)
            entries.append((pair.label if pair else field.label, _marked(
                parts, app_name, redraws, joiner=pair.joiner if pair else "",
                on_leave=settle if any(_as_option(one)["type"] in TYPED for one in members)
                else None, clear=clear(keys), playing=playing)))
            entries.append((panel.ASIDE, _beside(
                partial(marks, parts, pair.joiner if pair else ""), parts[0][1], field,
                redraws, more,
                _in_turn(*(_conflict(clashing[key]) for key in keys if key in clashing),
                         _tables_of_their_own(launcher, keys, owned) if owned else None),
                paired=[(held, one) for _, held, one in parts[1:]])))
            if pair:
                said = pair.note
            else:
                said = (getattr(field, "help", "") if curated else "") or field.description
            if said:
                entries.append(panel.note(said))
    return entries


def _whose(values: dict[str, Any], key: str) -> str:
    return str((values.get(key) or {}).get("scope") or "")


async def _keeping_place(client: Any, rebuild: Callable[[], Awaitable[Any]],
                         written: str) -> None:
    """`rebuild`, then focus the control that held focus, else `written`'s first, else the
    row now where the one that held it was. Nothing is focused where focus was outside the
    panel."""
    try:
        where = await client.run_javascript(_FOCUSED_SETTING)
    except Exception:  # noqa: BLE001 - a panel that cannot say where focus is still draws
        where = None
    await rebuild()
    if where is not None:
        places, row = ([where[0]], where[1]) if where else ([], -1)
        client.run_javascript(_REFOCUS_SETTING % json.dumps([[*places, [written, 0]], row]))


def no_longer_reads_game(cut: Sequence[dict[str, Any]],
                         tables: list[dict[str, Any]] | None) -> None:
    ui.notify(t("console.app_settings.detached", count=len(cut),
                tables="\n".join(_table_line(one, tables) for one in cut)), type="warning")


async def _set_by_tables(context: dict[str, Any]) -> list[frozenset[str]]:
    """What each of the launcher's tables sets for itself, one set per table that sets
    anything."""
    launcher_id = context["launcher"]["launcher_id"]
    try:
        rows = await offload.io(context["library"].load_tables)
    except Exception:  # noqa: BLE001 - a row that cannot say how many still draws
        return []
    return [frozenset(keys) for row in rows if row.get("launcher") == launcher_id
            if (keys := row.get("launcher_settings_keys"))]


def _tables_setting(their_own: Sequence[frozenset[str]], keys: Collection[str]) -> int:
    """How many tables set any of `keys` for themselves."""
    return sum(1 for held in their_own if not held.isdisjoint(keys))


def _unreported(value: Any, reported: Sequence[str], app_name: str) -> dict[str, str] | None:
    """The mark on a name the program has not reported using. None where it has reported
    nothing, which says nothing either way."""
    said = str(value or "")
    if not reported or not said or said in reported:
        return None
    return {"state": "missing",
            "reason": t("console.workbench.display_not_used", app=app_name)}


def _conflict(rival: str) -> Callable[[], None]:
    return panel.state(t("console.workbench.conflict"), "warn",
                       hint=t("console.workbench.conflict_hint", rival=rival))


def _in_turn(*draws: Callable[[], None] | None) -> Callable[[], None] | None:
    kept = [one for one in draws if one is not None]
    if not kept:
        return None

    def draw() -> None:
        for one in kept:
            one()
    return draw


def _tables_of_their_own(launcher: dict[str, Any], keys: Sequence[str],
                         count: int) -> Callable[[], None]:
    """The link to the Tables grid on the tables that answer over any of these
    settings."""
    return panel.link(t("console.workbench.override_count", count=count),
                      to="/console?" + deeplink.query({
                          "view": "tables", "launcher": launcher["launcher_id"],
                          "sets": ",".join(keys)}))


def _moved(before: dict[str, Any], after: dict[str, Any], written: str) -> bool:
    """Whether a setting other than the one written has a different value now, or has it
    from another scope."""
    def said(held: Any) -> tuple[Any, Any]:
        return (held or {}).get("value"), (held or {}).get("scope")
    return any(said(before.get(key)) != said(after.get(key))
               for key in before.keys() | after.keys() if key != written)


def _subheading(title: str) -> None:
    ui.label(title).classes("console-group")


def _section_of(qualified: str) -> str:
    """The part before the last dot. A section name has dots of its own -
    `Plugin.B2S.Enable` is `Enable` in `Plugin.B2S`."""
    return qualified.rsplit(".", 1)[0] if "." in qualified else ""


def _section_label(section: str, group_label: str) -> str:
    """What to call a source section on screen. Never its raw name: `[Plugin.B2S]` is
    the file's spelling, and what a reader wants is which of the two backglass plugins
    this is."""
    said = section.split(".", 1)[-1] if section.startswith("Plugin.") else section
    # Left as the program spells it. A section here is somebody's product name, and the
    # humanizer this file uses is built for snake_case fields - it lowercases the
    # capitals inside a name and gives back something worse than it was handed.
    said = said.replace("\\", " - ")
    return group_label if said.lower() == group_label.lower() else said


def setting_names(groups: Sequence[Any]) -> dict[str, str]:
    """What to call each of one program's settings away from its area, by key: its
    label, led by its plugin's or its window's name, or by the heading or section it
    sits under where another setting shares the label. A setting in a pair whose name
    another shares is led by the pair's name instead."""
    from console import app_settings

    fields = [(group, field) for group in groups for field in group.settings]
    shared = Counter(field.label for _group, field in fields)
    plugins = _plugin_names(groups)
    pairs = {key: str(pair.label) for pair in app_settings.named_pairs(groups)
             for key in pair.keys}
    labels = {field.key: field.label for _group, field in fields}

    def named(group: Any, field: Any) -> str:
        section = _section_of(field.key)
        if section.startswith(PLUGIN_SECTION):
            return plugin_row(section, field.label, plugins)
        if window := app_settings._window_of(field.key, group):
            return t("console.app_settings.window_row", window=window, label=field.label)
        if shared[field.label] < 2:
            return field.label
        heading = next((one.label for one in getattr(group, "curated", ())
                        if field.key in one.keys and one.label), "")
        return t("console.app_settings.heading_row",
                 heading=heading or _section_label(section, group.label), label=field.label)

    names = {field.key: named(group, field) for group, field in fields}
    read = Counter(name.casefold() for name in names.values())
    return {key: t("console.app_settings.heading_row", heading=pairs[key], label=labels[key])
            if key in pairs and read[name.casefold()] > 1 else name
            for key, name in names.items()}


def plugin_row(section: str, label: str, plugin_names: dict[str, str]) -> str:
    """A plugin's setting away from its heading, led by the plugin's name: it is all
    that tells one plugin's Enable from the next."""
    return t("console.app_settings.plugin_row",
             plugin=plugin_name(section[len(PLUGIN_SECTION):], plugin_names), label=label)


# --- All Settings -------------------------------------------------------------------

PLUGIN_SECTION = "Plugin."


def _all_settings_shown(context: dict[str, Any]) -> bool:
    return _program_is_there(context) and any(g.settings for g in _listed_groups(context))


def _listed_groups(context: dict[str, Any]) -> list[Any]:
    """The groups whose settings are rows. A summarized or read-only one is a table's
    alone."""
    return [g for g in context.get("config_groups") or []
            if not getattr(g, "summarized", False) and not getattr(g, "read_only", False)
            and not vpx_input.applies(g)]


async def _all_settings(context: dict[str, Any]) -> None:
    """Every setting the program keeps, in its own words, found by typing or narrowed
    to what differs from its default, or one area."""
    wanted: dict[str, Any] = context["state"].setdefault("all_settings", {})
    groups = _listed_groups(context)
    names = _plugin_names(groups)
    areas = {"": t("console.workbench.every_area"), **{g.key: g.label for g in groups}}
    if wanted.get("area") not in areas:
        wanted["area"] = ""

    app_name = str(context["launcher"].get("app_name") or "")
    changed = changed_count(groups, await _config_values(context))
    with ui.row().classes("items-center gap-x-4 gap-y-2 console-section-bar"):
        search = panel.search(t("console.app_settings.search_settings")) \
            .props("debounce=250")
        search.value = wanted.get("query") or ""
        if wanted.pop("focus", False):
            search.props("autofocus")
        area = dropdown.Select(areas, value=wanted["area"], look=dropdown.OUTLINED) \
            .classes("w-40")
        differs = ui.checkbox(t("console.workbench.changed_filter_count", count=changed),
                              value=bool(wanted.get("differs"))) \
            .props("dense").classes("whitespace-nowrap")
        differs.tooltip(t("console.workbench.changed_filter.help", app=app_name))
    results = ui.column().classes("gap-0 w-full")

    async def recount() -> None:
        if not differs.is_deleted:
            differs.set_text(t("console.workbench.changed_filter_count",
                               count=changed_count(groups, await _config_values(context))))

    context["recount_changed"] = recount

    async def draw() -> None:
        found = found_settings(groups, await _config_values(context), wanted)
        entries = await _setting_entries(
            context, [(section_title(section, names), "", fields) for section, fields in found],
            pairs=curated_pairs(groups))
        results.clear()
        with results, ui.column().classes("gap-0 console-form"):
            panel.facts(ui, entries if found else [panel.intro(
                t("console.workbench.settings_empty"))])

    async def narrow(key: str, value: Any) -> None:
        wanted[key] = value or ("" if key in ("query", "area") else False)
        await draw()

    search.on_value_change(lambda e: narrow("query", e.value))
    area.on_value_change(lambda e: narrow("area", e.value))
    differs.on_value_change(lambda e: narrow("differs", e.value))
    await draw()


def found_settings(groups: Sequence[Any], values: dict[str, Any],
                   wanted: dict[str, Any]) -> list[tuple[str, list[Any]]]:
    """What All Settings lists: each setting under its source section, the sections in
    the order the areas first reach them."""
    terms = str(wanted.get("query") or "").lower().split()

    def wanted_here(field: Any) -> bool:
        held = values.get(field.key) or {}
        return not ((wanted.get("differs") and not _changed(held, field))
                    or (terms and not _says_all(field, terms)))

    listed = [field for group in groups
              if not wanted.get("area") or group.key == wanted["area"]
              for field in group.settings]
    kept = {field.key for field in listed if wanted_here(field)}
    kept.update(key for pair in curated_pairs(groups) if not kept.isdisjoint(pair.keys)
                for key in pair.keys)
    found: dict[str, list[Any]] = {}
    for field in listed:
        if field.key in kept:
            found.setdefault(_section_of(field.key), []).append(field)
    return list(found.items())


def curated_pairs(groups: Sequence[Any]) -> list[Any]:
    return [pair for group in groups for heading in getattr(group, "curated", ())
            for pair in getattr(heading, "pairs", ())]


def _says_all(field: Any, terms: Sequence[str]) -> bool:
    said = " ".join((field.label, field.key, field.description,
                     getattr(field, "help", ""))).lower()
    return all(term in said for term in terms)


def changed_count(groups: Sequence[Any], values: dict[str, Any], area: str = "") -> int:
    """How many rows the Changed filter would list: a pair is one row."""
    keys = {field.key for group in groups if not area or group.key == area
            for field in group.settings
            if _changed(values.get(field.key) or {}, field)}
    rows = len(keys)
    for pair in curated_pairs(groups):
        if taken := keys.intersection(pair.keys):
            rows -= len(taken) - 1
    return rows


def _plugin_names(groups: Sequence[Any]) -> dict[str, str]:
    """A plugin's name where an area heads its rows with one, by plugin id."""
    return {h.key: h.label for g in groups for h in getattr(g, "curated", ())
            if h.keys and h.keys[0].startswith(f"{PLUGIN_SECTION}{h.key}.")}


def plugin_name(plugin: str, plugin_names: dict[str, str]) -> str:
    """A plugin's name: the one its area heads its rows with, else its id in words."""
    return plugin_names.get(plugin) or apps.humanized(plugin)


def section_title(section: str, plugin_names: dict[str, str]) -> str:
    """A source section as All Settings heads it: the program's name for it, in words."""
    if section.startswith(PLUGIN_SECTION):
        return t("console.workbench.plugin_section",
                 name=plugin_name(section[len(PLUGIN_SECTION):], plugin_names))
    return apps.humanized(section).replace("\\", " - ")


def _as_text(value: Any) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    return "" if value is None else str(value)


def _as_option(field: Any) -> dict[str, Any]:
    """A declared field as the control grammar reads it. `choices` is a mapping so the
    label goes on screen where the stored value would otherwise be."""
    option: dict[str, Any] = {"key": field.key, "type": field.type,
                              "label": field.label, "default": field.default,
                              "blank": getattr(field, "blank", "")}
    if named := getattr(field, "named", ()):
        option["named"] = {value: label for value, label in named}
    if path := getattr(field, "path", ""):
        option.update(path=path, suffixes=tuple(getattr(field, "suffixes", ())))
    if getattr(field, "reported", ()):
        option.update(suggest=REPORTED, clearable=False)
    if field.choices:
        blank = option["blank"]
        option["choices"] = {**({"": blank} if blank else {}),
                             **{value: label for value, label in field.choices}}
        option["type"] = "choice"
        said = getattr(field, "choice_help", None) or {}
        option["describes"] = {label: said[value] for value, label in field.choices
                               if said.get(value)}
    return option


@on_page
async def _agreed_to_switch_off(library: Any, launcher: dict[str, Any]) -> bool:
    try:
        found = await offload.io(library.launcher_fallback, launcher["launcher_id"])
    except Exception as exc:  # noqa: BLE001
        ui.notify(t("console.workbench.lookup_failed"), caption=why(exc), type="negative")
        return False
    if found.get("refused"):
        ui.notify(found["refused"], type="warning")
        return False
    count = int(found.get("tables") or 0)
    if not count:
        return True
    goes = list(found.get("fallbacks") or [])
    lines: list[str] = []
    if len(goes) == 1:
        detail = t("console.workbench.off_detail", count=count,
                   fallback=goes[0]["display_name"])
    else:
        detail = t("console.workbench.switched_off_split", count=count)
        lines = [t("console.workbench.launch_count", count=int(one["tables"]),
                   name=one["display_name"]) for one in goes]
    return await confirm.ask(
        t("console.workbench.off_question",
          name=launcher.get("display_name") or launcher["app_name"]),
        detail=detail, lines=lines, confirm=t("console.workbench.switch_off"),
        icon=verbs.SWITCH_OFF, danger=False)


# Every launcher's own fields follow its app's, and they are the commands.
COMMANDS_FROM = OWN_FIELDS[0].key


def _switched_off_goes_to(launcher: dict[str, Any], held: list[dict[str, Any]]) -> str:
    """The launcher its tables would use with this one off, or empty where none would."""
    found = next((one for one in held
                  if one.get("app") == launcher.get("app") and one.get("enabled")
                  and one.get("launcher_id") != launcher.get("launcher_id")), None)
    return str(found.get("display_name") or found.get("app_name") or "") if found else ""


def _why_not_the_default(launcher: dict[str, Any]) -> str:
    """Why the Default switch cannot make it the default, or "" where it can."""
    state = launchers_page.state_of(launcher)
    if state == launchers_page.STATE_NO_PROGRAM:
        return t("console.workbench.default_needs_program", name=launcher["display_name"])
    return "" if launcher.get("enabled") else t("console.workbench.default_needs_on")


async def _launcher_details(context: dict[str, Any]) -> None:
    """What this launcher is, and what it runs. Its own fields, which are few - the
    program's settings are the sections after this one."""
    library = context["library"]
    launcher = context["launcher"]
    rebuild = context["rebuild"]
    only_one = len(context.get("launchers") or []) <= 1
    is_default = context.get("defaults", {}).get(launcher["app"]) == launcher["launcher_id"]
    refused_default = _why_not_the_default(launcher)

    async def put(changes: dict[str, Any]) -> str:
        """Empty when it saved, else why it did not."""
        try:
            await run.io_bound(library.put_launcher, launcher["launcher_id"],
                               {**launcher, **changes})
        except Exception as exc:  # noqa: BLE001
            return why(exc)
        launcher.update(changes)
        for after in ("recheck_trouble", "refresh_launchers"):
            again = context["state"].get(after)
            if callable(again):
                await again()
        return ""

    @on_page
    async def write(**changes: Any) -> bool:
        refused = await put(changes)
        if refused:
            ui.notify(t("console.workbench.save_failed"), caption=refused, type="negative")
        return not refused

    async def rename(text: str) -> str:
        wanted = text.strip() or launcher["app_name"]
        if wanted == launcher["display_name"]:
            return ""
        refused = await put({"display_name": wanted})
        retitle = context.get("retitle")
        if not refused and callable(retitle):
            retitle(wanted)
        return refused

    @on_page
    async def flip(on: bool) -> None:
        if not on and not await _agreed_to_switch_off(library, launcher):
            await rebuild()
            return
        if await write(enabled=on):
            await rebuild()

    @on_page
    async def make_default(on: bool) -> None:
        if on and not is_default:
            try:
                await run.io_bound(library.make_launcher_default, launcher["launcher_id"])
            except Exception as exc:  # noqa: BLE001
                ui.notify(t("console.workbench.save_failed"), caption=why(exc), type="negative")
            again = context["state"].get("refresh_launchers")
            if callable(again):
                await again()
        await rebuild()

    def save_field(key: str) -> Callable[[Any], Any]:
        async def save(value: Any) -> bool:
            return await write(settings={**launcher["settings"], key: value})
        return save

    entries: list[tuple[Any, Any]] = [
        (HEADING, t("console.workbench.this_launcher")),
        (t("word.name"), panel.field(launcher["display_name"], rename,
                             placeholder=launcher["app_name"], refuses=True)),
        panel.note(t("console.workbench.name_note")),
        (t("word.runs"), launcher["app_name"]),
        (t("word.default"), panel.switch(
            is_default, lambda e: make_default(bool(e.value)),
            disabled=is_default or bool(refused_default),
            hint=t("console.workbench.default_another") if is_default else refused_default)),
        panel.note(t("console.workbench.default_help", app=launcher["app_name"])),
    ]
    entries.append((t("console.workbench.enabled"), panel.switch(
        launcher["enabled"], lambda e: flip(bool(e.value)), disabled=only_one,
        hint=t("console.workbench.only_launcher") if only_one else "")))
    if goes_to := _switched_off_goes_to(launcher, context.get("launchers") or []):
        entries.append(panel.note(
            t("console.workbench.off_note", default=goes_to)))

    entries.append((HEADING, t("word.program")))
    if note := _program_note(launcher):
        entries.append(panel.note(note))
    for field in launcher.get("fields") or []:
        if field["key"] == COMMANDS_FROM:
            entries.append((HEADING, t("console.workbench.commands")))
        entries.append((field["label"],
                        settings_page.control_for(
                            launchers_page.standing_option(field, launcher["app_name"]),
                            launcher["settings"].get(field["key"]),
                            save_field(field["key"]),
                            check=(launcher.get("checks") or {}).get(field["key"]),
                            browse=library.folders)))
        if field.get("description"):
            entries.append(panel.note(field["description"]))
        # Once, under the pair, rather than beside each of them.
        if field["key"] == "on_table_exit":
            commands_help.add_to(entries, tokens.TABLE)
    with ui.column().classes("gap-0 console-form"):
        _rows(ui, entries)


def _app_keeps_settings(context: dict[str, Any]) -> bool:
    """Whether there is a settings file to copy at all. `generic` keeps none."""
    return bool((context.get("launcher") or {}).get("has_config")) \
        and (bool(context.get("config_groups")) or _program_is_there(context))


async def _config_backups(context: dict[str, Any]) -> None:
    """The settings file this launcher writes, and the copies kept of it."""
    library, launcher = context["library"], context["launcher"]
    launcher_id = launcher["launcher_id"]
    try:
        found = await offload.io(library.launcher_config, launcher_id)
    except Exception:  # noqa: BLE001 - the copies are listed apart from the settings
        found = {}
    named = list((found.get("files") or {}).values())
    held = await backup_rows.listed(library, "launcher", launcher_id)
    playing = bool(context.get("playing"))
    entries: list[tuple[Any, Any]] = []
    if named:
        entries.append((t("word.file"), panel.path_value(named[0])))
    entries.append((t("console.section.backups"), backup_rows.row(
        library, "launcher", launcher_id, str(launcher.get("display_name") or launcher_id),
        held, context["rebuild"], hint=t(PLAYING_NOTE) if playing else "")))
    _rows(ui, entries)


async def _collection_details(context: dict[str, Any]) -> None:
    row = _collection(context)
    entries: list[tuple[Any, Any]] = [
        (HEADING, t("console.workbench.this_collection")),
        (t("word.name"), _text_control(context, row, "name")),
        (t("console.workbench.description"), _text_control(context, row, "description",
                lines=3)),
        (HEADING, t("console.workbench.frontend")),
        (t("console.workbench.in_menu"), _in_frontend_switch(context, row)),
        (t("console.workbench.open_on"), _open_on(context, row)),
        panel.note(t("console.workbench.open_on.help")),
        (t("console.workbench.page_by"), _page_by(context, row)),
        panel.note(t("console.workbench.page_by.help")),
        (FULL, partial(_image_slot, context, row)),
    ]
    with ui.column().classes("gap-0 console-form"):
        _rows(ui, entries)


def _text_control(context: dict[str, Any], row: dict[str, Any], field: str,
                  lines: int = 0) -> Callable[[], None]:
    """One editable field of a collection, and when it is written.

    Two rhythms, because the two fields cost different amounts to change. Free text
    settles as you stop typing. A name is this collection's identity - every route is
    keyed by it - so it is written when you leave the field, and `debounce=0` is what
    makes that safe: nicegui's model is only current if every keystroke reaches it, and
    reading it on blur without that gets whatever the last sync happened to hold.
    """
    @on_page
    async def save(value: str) -> None:
        if value == (row.get(field) or ""):
            return
        if field == "name" and not value.strip():
            ui.notify(t("said.needs_name"), type="warning")
            return
        if field == "name":
            await _rename(context, value)
            return
        await _patch(context, {field: value})

    def draw() -> None:
        control: ui.textarea | ui.input
        if lines:
            control = ui.textarea()
            control.value = row.get(field) or ""
            control.props(f"dense outlined rows={lines} debounce=800") \
                .classes("w-full min-w-0")
            control.on_value_change(lambda: save(control.value or ""))
            return
        control = ui.input()
        control.value = row.get(field) or ""
        control.props("dense outlined debounce=0").classes("w-full min-w-0")
        control.on("blur", lambda: save(control.value or ""))

    return draw


@on_page
async def _rename(context: dict[str, Any], wanted: str) -> None:
    # Imported here: console.collections imports console.games, which imports this module.
    from console.collections import renamed_to

    state = context["state"]
    try:
        new = await renamed_to(context["library"], state, _collection(context)["name"], wanted)
    except Exception as exc:
        ui.notify(t("console.workbench.save_failed"), caption=why(exc), type="negative")
        return
    state["collection"] = new
    reread = state.get("refresh_collections")
    if callable(reread):
        await reread(new)
        return
    deeplink.sync(state)
    await context["rebuild"]()


def _in_frontend_switch(context: dict[str, Any], row: dict[str, Any]) -> Callable[[], None]:
    shown = row.get("in_frontend") is not False

    async def changed(event: Any) -> None:
        if bool(event.value) != shown:
            await _patch(context, {"in_frontend": bool(event.value)})

    return panel.switch(shown, changed, hint=t("console.workbench.in_menu.help"))


@on_page
async def _write_open_on(context: dict[str, Any], value: str) -> None:
    try:
        await run.io_bound(context["library"].put_config, {"behavior": {
            "startup_collection": value}})
    except Exception as exc:
        ui.notify(t("console.workbench.save_failed"), caption=why(exc), type="negative")
        return
    await _written(context)


def _open_on(context: dict[str, Any], row: dict[str, Any], *,
             all_games: bool = False) -> Callable[[], None]:
    """What the frontend opens on, and how it moves. A collection offers the one act: to
    be it, or back to all games. The value is the setting Settings shows, written the
    same way. `all_games` is the row for the whole library, which is where the choices
    that are not a collection are made."""
    name = str(row.get("name") or "")
    behavior = (context.get("settings") or {}).get("behavior") or {}
    now = str(behavior.get("startup_collection") or "").strip()
    choices = panel.open_on_choices()

    if all_games:
        # What is set stays on the list while it is a collection, so the control never
        # shows a value it cannot name.
        options = choices if not now or now in choices else {**choices, now: now}

        @on_page
        async def chosen(event: Any) -> None:
            if str(event.value or "") != now:
                await _write_open_on(context, str(event.value or ""))

        return panel.select(options, now, chosen)

    here = bool(name) and now == name

    @on_page
    async def use() -> None:
        await _write_open_on(context, "" if here else name)

    def draw() -> None:
        with ui.row().classes("items-center gap-2 no-wrap min-w-0"):
            ui.label(choices.get(now) or now) \
                .classes("console-fact-value truncate min-w-0")
            panel.action(
                t("console.workbench.open_on.use_all" if here
                  else "console.workbench.open_on.use_this"), use, inline=True,
                icon=verbs.OPENS_ON,
                hint=t("console.workbench.open_on.use_all.help" if here
                       else "console.collections.opens_on.help"))()

    return draw


_PAGE_BY_GROUP = frozenset({"letter", "year", "rating"})


def _page_by(context: dict[str, Any], row: dict[str, Any]) -> Callable[[], None]:
    """Where the order has no groups the frontend moves by the count, so a stored group
    is shown as that."""
    stored = row.get("paging_group") or ""
    group = group_kind(row.get("order_by") or DEFAULT_ORDER_BY)
    choices = config_schema.option("behavior", "paging_group")
    said = ((context.get("settings") or {}).get("behavior") or {}).get("paging_group")
    current = str(said or (choices.default if choices else "") or "count")
    word = {key: t(f"config.behavior.paging_group.choice.{key}") for key in ("sort", "count")}
    options = {"": t("console.workbench.page_by.same", choice=word.get(current, ""))}
    if group in _PAGE_BY_GROUP:
        options["sort"] = word["sort"]
    options["count"] = word["count"]
    shown = stored if stored in options else "count"

    async def changed(event: Any) -> None:
        if event.value != shown:
            await _patch(context, {"paging_group": event.value})

    return panel.select(options, shown, changed)


def _image_slot(context: dict[str, Any], row: dict[str, Any]) -> None:
    """The collection's wheel, in the shape a media slot takes.

    Same card, same art region, same blank state, same row of actions - a picture in
    this app is presented one way, and a bespoke drop target here was a second.
    """
    name = row.get("name") or ""
    library = context["library"]
    present = bool(row.get("image"))
    stand_ins = [] if present else list(row.get("game_wheels") or [])
    label = t("console.workbench.wheel")

    async def clear() -> None:
        await run.io_bound(library.clear_collection_image, name)
        await _written(context)

    with ui.column().classes("w-full gap-1 console-slot p-2 mt-3"):
        ui.label(label).classes("console-card-title") \
            .tooltip(t("console.workbench.wheel.help"))
        with ui.element("div").classes("console-slot-art console-slot-art--wheel"):
            if present:
                ui.image(art.collection(name, version=row.get("image_version"),
                                        size=art.PANEL)) \
                    .classes("console-slot-image")
            elif stand_ins:
                with ui.element("div").classes("console-wheel-mosaic"):
                    for src in stand_ins:
                        ui.element("img").props(
                            f'src="{art.sized(src, art.CELL)}" loading="lazy"')
            else:
                with ui.column().classes("console-slot-blank items-center gap-1"):
                    ui.icon("image").classes("console-slot-blank-icon")
        if stand_ins:
            ui.label(t("console.workbench.slot_origin")) \
                .classes("text-xs console-label self-center")
        with ui.row().classes("items-center gap-2 w-full console-slot-actions"):
            ui.button(t("word.replace") if present else t("word.add"),
                      icon=verbs.REPLACE if present else verbs.ADD,
                      on_click=lambda: mediasource.open_image_sources(
                          library, name, label, lambda: _written(context))) \
                .props("flat dense no-caps size=sm").classes("console-action")
            if present:
                ui.button(t("word.remove"), icon=verbs.REMOVE, on_click=clear) \
                    .props("flat dense no-caps size=sm") \
                    .classes("console-action console-action--danger")


async def _written(context: dict[str, Any], name: str = "") -> None:
    """The grid read again and the panel redrawn. Refocusing the row is what redraws the
    panel, so nothing here rebuilds it as well."""
    reread = context["state"].get("refresh_collections")
    if callable(reread):
        await reread(name or _collection(context)["name"])
        return
    await context["rebuild"]()


async def _collection_redrawn(context: dict[str, Any], name: str) -> None:
    """The panel redrawn if it still shows `name`, and the grid's counts either way. Run
    again by an Undo, when the panel may have moved on."""
    state = context["state"]
    if state.get("collection") == name and state.get("view") == "collections":
        await _written(context)
        return
    reread = state.get("refresh_collections")
    if callable(reread) and state.get("view") == "collections":
        await reread()


def _games_label(context: dict[str, Any]) -> str:
    got = (context.get("membership") or {}).get("playable")
    return t("console.workbench.games") if got is None \
        else t("console.workbench.games_counted", count=got)


async def _collection_games(context: dict[str, Any]) -> None:
    row = _collection(context)
    held = (context.get("membership") or {}).get("members") or []
    if not held and not _is_dynamic(row) and not _drafting(context):
        _empty_fork(context)
        return
    def controls() -> None:
        _order_bar(context, row)
        _add_control(context, held)

    with ui.column().classes("gap-0 w-full min-w-0"):
        _rules_block(context, row)
        _games_list(context, row, controls)
    if context.get("unsaved"):
        _draft_bar(context)


def _empty_fork(context: dict[str, Any]) -> None:
    with ui.column().classes("gap-2 w-full min-w-0 py-2"):
        ui.label(t("console.workbench.empty")).classes("console-empty-title")
        _add_control(context, [])
        with ui.row().classes("items-center gap-2 no-wrap"):
            ui.label(t("word.or")).classes("console-help")
            _add_rule_button(context)
            ui.label(t("console.workbench.rule_hint")).classes("console-help")
        library = context["library"]
        lists = [(tag_source(one), tag) for tag, look in library.tag_looks().items()
                 for one in look.get("sources") or []]
        offered = [*collection_rules.templates(context["fields"]),
                   *collection_rules.tagged(lists, context["fields"])]
        if offered:
            with ui.row().classes("items-baseline gap-2 no-wrap"):
                ui.label(t("console.workbench.start_from")).classes("console-help shrink-0")
                with ui.row().classes("items-center gap-2 min-w-0"):
                    for one in offered:
                        panel.action(one.reads(),
                                     lambda _e=None, one=one: _start_from(context, one),
                                     icon=verbs.ADD, inline=True,
                                     hint=t("console.workbench.start_from.help"))()


def _start_from(context: dict[str, Any], template: collection_rules.Template) -> None:
    context["draft"]["rules"] = [dict(row) for row in template.rows]
    context["draft"]["order"] = dict(template.order)
    asyncio.create_task(context["rebuild"]())


# --- the rules ------------------------------------------------------------------


def _drafting(context: dict[str, Any]) -> bool:
    return "rules" in context["draft"]


def _stored_rules(context: dict[str, Any]) -> list[dict[str, Any]]:
    return collection_rules.rows_from(_collection(context).get("filters"),
                                      context["fields"])


def _rules_now(context: dict[str, Any]) -> list[dict[str, Any]]:
    """The rows on screen: the draft's while there is one, the stored rule's otherwise."""
    if _drafting(context):
        return list(context["draft"]["rules"])
    return _stored_rules(context)


def unsaved(drafts: dict[str, Any], collections: list[dict[str, Any]],
            known: list[collection_rules.Field]) -> set[str]:
    """The collections whose draft asks for something other than their stored rule."""
    stored = {str(one.get("name") or ""): one for one in collections}
    found = set()
    for name, draft in drafts.items():
        if "rules" not in draft or name not in stored:
            continue
        have = collection_rules.rows_from(stored[name].get("filters"), known)
        if (collection_rules.filters_from(draft["rules"], known)
                != collection_rules.filters_from(have, known)):
            found.add(name)
    return found


def _edit_rules(context: dict[str, Any], change: Callable[[list[dict[str, Any]]], None],
                *, redraw: bool = True) -> None:
    rows = [dict(one) for one in _rules_now(context)]
    change(rows)
    context["draft"]["rules"] = rows
    if redraw:
        asyncio.create_task(context["rebuild"]())


def _add_rule_button(context: dict[str, Any]) -> None:
    used = {str(one.get("field") or "") for one in _rules_now(context)}
    offered = [one for one in context["fields"] if one.name not in used and one.askable]
    button = ui.button(t("console.workbench.add_rule"), icon=verbs.ADD) \
        .props("flat dense no-caps size=sm").classes("console-action")
    if not offered:
        button.disable()
        return
    with button, ui.menu():
        for one in offered:
            ui.menu_item(one.label,
                         on_click=lambda _e=None, one=one: _edit_rules(
                             context, lambda rows: rows.append(
                                 collection_rules.row_on(one)))) \
                .classes("console-menu-item")


def _rules_block(context: dict[str, Any], row: dict[str, Any]) -> None:
    rows = _rules_now(context)
    smart = _is_dynamic(row)
    with ui.row().classes("items-center gap-1 no-wrap console-group"):
        ui.label(t("console.workbench.rules"))
        if smart:
            ui.icon(verbs.SMART).classes("console-heading-mark") \
                .tooltip(t("console.collections.smart.help"))
    if not rows and not smart:
        with ui.row().classes("items-center gap-2 w-full no-wrap py-1"):
            ui.label(t("console.workbench.hand_picked_rules")) \
                .classes("console-help min-w-0")
            _add_rule_button(context)
        return
    with ui.column().classes("gap-1 w-full min-w-0"):
        for index, one in enumerate(rows):
            _condition(context, index, one)
    with ui.row().classes("items-center gap-2 console-slot-actions"):
        _add_rule_button(context)
    added, taken = _by_hand(context)
    ui.label(collection_rules.sentence(rows, context["fields"], added, taken)) \
        .classes("console-help console-rule-sentence mt-1 mb-2")


def _by_hand(context: dict[str, Any]) -> tuple[int, int]:
    members = (context.get("membership") or {}).get("members") or []
    added = {one.get("game") for one in members if one.get("origin") == "named"}
    taken = {one.get("game") for one in members if one.get("origin") == "excluded"}
    return len(added), len(taken)


def _condition(context: dict[str, Any], index: int, row: dict[str, Any]) -> None:
    known = context["fields"]
    field = collection_rules.by_name(known).get(str(row.get("field") or ""))
    if field is None:
        return
    used = {str(one.get("field") or "") for at, one in enumerate(_rules_now(context))
            if at != index}

    def put(**changes: Any) -> Callable[[list[dict[str, Any]]], None]:
        def change(rows: list[dict[str, Any]]) -> None:
            rows[index] = {**rows[index], **changes}
        return change

    def moved_to(rows: list[dict[str, Any]]) -> None:
        rows[index] = collection_rules.row_on(collection_rules.by_name(known)[which.value])

    def gone(rows: list[dict[str, Any]]) -> None:
        del rows[index]

    with ui.element("div").classes("console-condition"):
        which = dropdown.Select({one.name: one.label for one in known
                                 if (one.name not in used and one.askable)
                                 or one.name == field.name},
                                value=field.name)
        which.on_value_change(lambda: _edit_rules(context, moved_to))
        if field.summary:
            which.tooltip(field.summary)
        asks = field.operators
        if len(asks) > 1:
            how = dropdown.Select({op: collection_rules.operator_word(op)
                                   for op in asks}, value=row.get("op"))
            how.on_value_change(lambda: _edit_rules(context, put(
                op=how.value, value=_kept_value(row, how.value))))
        else:
            ui.label(collection_rules.operator_word(asks[0])) \
                .classes("console-condition-op")
        with ui.element("div").classes("console-condition-value"):
            _condition_value(context, field, row, put)
        ui.button(icon=verbs.CANCEL, on_click=lambda: _edit_rules(context, gone)) \
            .props("flat dense round size=sm").classes("console-condition-remove") \
            .tooltip(t("console.workbench.remove_rule"))


def _kept_value(row: dict[str, Any], op: str) -> Any:
    """What a row keeps asking for when only how it asks changes."""
    before = row.get("op")
    kinds = ({collection_rules.AT_LEAST, collection_rules.EXACTLY},
             {collection_rules.BEFORE, collection_rules.AFTER},
             {collection_rules.ANY_OF, collection_rules.NONE_OF})
    if any(before in pair and op in pair for pair in kinds):
        return row.get("value")
    return None


def _condition_value(context: dict[str, Any], field: collection_rules.Field,
                     row: dict[str, Any],
                     put: Callable[..., Callable[[list[dict[str, Any]]], None]]) -> None:
    op, value = row.get("op"), row.get("value")
    if op in (collection_rules.YES, collection_rules.NO):
        return
    if op in (collection_rules.ANY_OF, collection_rules.NONE_OF, collection_rules.STARTS_WITH):
        _many_values(context, field, value, put)
        return
    if op in (collection_rules.AT_LEAST, collection_rules.EXACTLY):
        stars = dropdown.Select({one: t("console.stars.5", n=one) for one in field.values},
                                value=(value if value in field.values else None))
        stars.on_value_change(lambda: _edit_rules(context, put(value=stars.value)))
        return
    if op == collection_rules.BETWEEN:
        ends = value if isinstance(value, dict) else {}
        with ui.row().classes("items-center gap-2 no-wrap"):
            _year_box(context, ends.get("from"),
                      lambda year: put(value={**ends, "from": year}))
            ui.label(t("console.workbench.and")).classes("console-condition-op")
            _year_box(context, ends.get("to"),
                      lambda year: put(value={**ends, "to": year}))
        return
    _year_box(context, value, lambda year: put(value=year))


def _year_box(context: dict[str, Any], value: Any,
              change: Callable[[int | None], Callable[[list[dict[str, Any]]], None]],
              ) -> None:
    """A year, written when the box is left or Enter is pressed."""
    box = ui.number(value=value, format="%d", placeholder=t("word.year")) \
        .props("dense borderless debounce=0") \
        .classes("console-edit-field console-edit-narrow")

    def done() -> None:
        typed = box.value
        year = int(typed) if isinstance(typed, (int, float)) else None
        if year != value:
            _edit_rules(context, change(year))

    box.on("blur", done)
    box.on("keydown.enter", lambda: box.run_method("blur"))


def _many_values(context: dict[str, Any], field: collection_rules.Field, value: Any,
                 put: Callable[..., Callable[[list[dict[str, Any]]], None]]) -> None:
    """Written to the draft on every pick and redrawn once the list closes: a redraw
    closes a list that is open."""
    chosen = [str(one) for one in value or []]
    offered = [*field.values, *(one for one in chosen if one not in field.values)]
    control: dropdown.Select
    if field.name == "tags":
        control = tag_chips.Picker(offered, value=chosen,
                                   looks=context["library"].tag_looks(),
                                   counts=field.counts)
    else:
        control = panel.CountedSelect(offered, field.counts, value=chosen,
                                      typed=len(offered) > 8)
    control.props('popup-content-class="console-picker-popup"') \
        .classes("w-full min-w-0")
    held = {"open": False}

    def picked() -> None:
        _edit_rules(context, put(value=list(control.value or [])),
                    redraw=not held["open"])

    def shown() -> None:
        held["open"] = True

    def hidden() -> None:
        held["open"] = False
        asyncio.create_task(context["rebuild"]())

    control.on_value_change(picked)
    control.on("popup-show", shown)
    control.on("popup-hide", hidden)


@on_page
async def _save_rules(context: dict[str, Any]) -> None:
    """Write the rule and nothing else, then stop drafting."""
    row, library = _collection(context), context["library"]
    wanted = collection_rules.filters_from(context["draft"].get("rules") or [],
                                           context["fields"])
    if not wanted:
        if _is_dynamic(row):
            await _take_rules_away(context)
        else:
            await _cancel_rules(context)
        return
    order = context["draft"].get("order") or {}
    try:
        await run.io_bound(library.patch_collection, row["name"],
                           {"filters": wanted, **order})
    except Exception as exc:  # noqa: BLE001
        ui.notify(t("console.workbench.save_failed"), caption=why(exc), type="negative")
        return
    context["draft"].pop("rules", None)
    context["draft"].pop("order", None)
    await _written(context)


async def _cancel_rules(context: dict[str, Any]) -> None:
    context["draft"].pop("rules", None)
    await context["rebuild"]()


async def _keep_what_it_found(context: dict[str, Any]) -> None:
    # Imported here: console.collections imports console.games, which imports this module.
    from console.collections import keep_result

    await keep_result(context["library"], context["state"], [_collection(context)["name"]],
                      lambda name: _written(context, name or ""))


@on_page
async def _take_rules_away(context: dict[str, Any]) -> None:
    row = _collection(context)
    name = row["name"]
    added = _by_hand(context)[0]
    choices = {"found": t("console.workbench.keep_found", count=int(row.get("count") or 0)),
               "added": t("console.workbench.keep_added", count=added) if added
               else t("console.workbench.keep_none")}
    with frame.opened(t("console.workbench.take_rules_away", name=name)) as box:
        choice = ui.radio(choices, value="found").props("dense")
        with frame.footer():
            frame.cancel(lambda: box.submit(None))
            frame.answer(t("console.workbench.remove_rules"),
                         lambda: box.submit(choice.value), icon=verbs.REMOVE)
    answer = await box
    if answer == "found":
        await _keep_what_it_found(context)
        return
    if answer != "added":
        return
    try:
        await run.io_bound(context["library"].patch_collection, name,
                           {"clear_filters": True})
    except Exception as exc:  # noqa: BLE001
        ui.notify(t("console.workbench.save_failed"), caption=why(exc), type="negative")
        return
    context["draft"].pop("rules", None)
    ui.notify(t("console.workbench.converted", name=name), type="positive")
    await _written(context)


def _shown_games(lens: dict[str, Any] | None) -> set[str]:
    return {str(one.get("game") or "") for one in (lens or {}).get("members") or []
            if one.get("included") and not one.get("past_limit")}


def _draft_bar(context: dict[str, Any]) -> None:
    preview = context.get("preview") or {}
    now, then = _shown_games(context.get("membership")), _shown_games(preview)
    asks = collection_rules.filters_from(context["draft"].get("rules") or [],
                                         context["fields"])
    matched = int(preview.get("matched") or 0)
    said = [(t("console.workbench.games_match", count=matched) if matched
             else t("console.workbench.search_empty")) if asks
            else t("console.workbench.no_rules")]
    if then - now:
        said.append(t("console.workbench.join", count=len(then - now)))
    if now - then:
        said.append(t("console.workbench.leave", count=len(now - then)))
    with ui.row().classes("items-center gap-x-3 gap-y-1 w-full console-draft-bar"):
        with ui.row().classes("items-center gap-2 no-wrap min-w-0"):
            ui.label(game_tables.JOIN.join(said)).classes("console-draft-said")
            ui.label(game_tables.JOIN.strip()).classes("console-draft-said")
            ui.label(t("word.not_saved")).classes("console-draft-state") \
                .tooltip(t("console.workbench.not_saved_rules"))
        with ui.row().classes("items-center gap-2 no-wrap ml-auto"):
            panel.action(t("word.cancel"), lambda: _cancel_rules(context),
                         icon=verbs.CANCEL, hint=t("console.workbench.cancel_rules.help"))()
            ui.button(t("console.workbench.save_rules"), icon=verbs.SAVE,
                      on_click=lambda: _save_rules(context)) \
                .props("dense no-caps no-wrap unelevated size=sm")


# --- the order ------------------------------------------------------------------


def _order_bar(context: dict[str, Any], row: dict[str, Any]) -> None:
    row = _ordered(context, row)
    by, direction = row.get("order_by") or DEFAULT_ORDER_BY, row.get("direction")
    orders = _orders(context, row, by)
    if by not in orders:
        by, direction = DEFAULT_ORDER_BY, DEFAULT_DIRECTION
    ranking = _ranking(context, by)

    async def ordered(event: Any) -> None:
        if event.value == by:
            return
        changes: dict[str, Any] = {"order_by": event.value}
        if event.value in NATURAL_DIRECTION:
            changes["direction"] = NATURAL_DIRECTION[event.value]
        await _set_order(context, changes)

    async def turned(event: Any) -> None:
        if event.value != direction:
            await _set_order(context, {"order_by": by, "direction": event.value})

    with ui.row().classes("items-center gap-x-4 gap-y-1 w-full console-order-bar"):
        with ui.row().classes("items-center gap-2 no-wrap grow"):
            ui.label(t("console.workbench.order")).classes("console-order-label")
            dropdown.Select(orders, value=by, on_change=ordered)
            if by in DIRECTION_WORDS:
                words = DIRECTION_WORDS[by]
                dropdown.Select({way: t(words[way]) for way in ("asc", "desc")},
                                value=direction or NATURAL_DIRECTION[by],
                                on_change=turned)
            if ranking:
                ui.label(read_state(ranking) if ranking.get("offered")
                         else t("console.workbench.ranked_off")) \
                    .classes("console-order-label")
        with ui.row().classes("items-center gap-2 no-wrap ml-auto"):
            ui.label(t("console.workbench.show_limit")).classes("console-order-label")
            _limit_box(context, row)


def _orders(context: dict[str, Any], row: dict[str, Any], by: str) -> dict[str, str]:
    """The order menu. A stored ranked order is in it whether or not it is offered."""
    orders = {token: t(key) for token, key in SORT_LABELS.items()}
    if not _is_dynamic(row) and not _rules_drafted(context):
        orders = {MANUAL_ORDER: t("order.by.manual"), **orders}
    orders |= context["state"].get("ranked_orders") or {}
    ranking = _ranking(context, by)
    if ranking and by not in orders:
        orders[by] = community.ranked_label(ranking)
    return orders


def _ranking(context: dict[str, Any], by: str) -> dict[str, Any] | None:
    """The stored collection's ranked view, when `by` is the order it is stored in."""
    stored = _collection(context)
    return stored.get("ranking") if stored.get("order_by") == by else None


def _limit_box(context: dict[str, Any], row: dict[str, Any]) -> None:
    limit = row.get("limit")
    box = ui.number(value=limit, min=1, format="%d", placeholder=t("word.any")) \
        .props("dense borderless debounce=0") \
        .classes("console-edit-field console-edit-narrow")

    async def done() -> None:
        typed = box.value
        wanted = max(1, int(typed)) if isinstance(typed, (int, float)) else None
        if wanted == limit:
            return
        await _set_order(context, {"limit": wanted} if wanted else {"clear_limit": True})

    box.on("blur", done)
    box.on("keydown.enter", lambda: box.run_method("blur"))


def _ordered(context: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    """The collection as its order reads with a template's order drafted over it."""
    order = context["draft"].get("order")
    if order is None:
        return row
    merged = row | order
    if order.get("clear_limit"):
        merged.pop("limit", None)
    return merged


async def _set_order(context: dict[str, Any], changes: dict[str, Any]) -> None:
    order = context["draft"].get("order")
    if order is None:
        await _patch(context, changes)
        return
    if "limit" in changes:
        order.pop("clear_limit", None)
    if "clear_limit" in changes:
        order.pop("limit", None)
    order.update(changes)
    await context["rebuild"]()


@on_page
async def _patch(context: dict[str, Any], changes: dict[str, Any]) -> None:
    library = context["library"]
    try:
        await run.io_bound(library.patch_collection, _collection(context)["name"],
                           changes)
    except Exception as exc:
        ui.notify(t("console.workbench.save_failed"), caption=why(exc), type="negative")
        return
    await _written(context)


# --- what the collection holds ----------------------------------------------------


def _games_list(context: dict[str, Any], row: dict[str, Any],
                controls: Callable[[], None]) -> None:
    live = not context.get("unsaved")
    lens = context.get("membership") if live else context.get("preview")
    lens = lens or {}
    members = lens.get("members") or []
    name = _collection(context)["name"]
    find = (context["state"].setdefault("member_find", {}).get(name, "")
            .strip().lower()) if live else ""
    if find:
        members = [one for one in members if find in str(one.get("name") or "").lower()]
    kept = [one for one in members if (one.get("origin") or "") != "excluded"]
    excluded = [one for one in members if (one.get("origin") or "") == "excluded"]
    playable = sum(1 for one in kept if one.get("included") and not one.get("past_limit"))
    with ui.row().classes("items-center gap-2 w-full mt-2"):
        ui.label(t("console.workbench.games") if lens.get("error")
                 else _games_heading(playable, sum(1 for one in kept if _is_hidden(one)),
                                     len(excluded))) \
            .classes("console-card-title whitespace-nowrap")
        if live and int(row.get("count") or 0):
            with ui.element("span").classes("whitespace-nowrap"):
                panel.link(t("console.workbench.games_visible"), to="/console?"
                           + deeplink.query({"view": "games", "collection": name}))()
    controls()
    if lens.get("error"):
        panel.line(t("console.workbench.lookup_failed"), hint=str(lens["error"]),
                   classes="console-help text-warning")
        return
    if live and len((context.get("membership") or {}).get("members") or []) > 8:
        box = ui.input(placeholder=t("console.workbench.find_collection")) \
            .props("dense outlined clearable debounce=250") \
            .classes("w-full mb-2 mt-1")
        box.value = find

        async def look() -> None:
            context["state"]["member_find"][name] = box.value or ""
            await context["rebuild"]()

        box.on_value_change(look)
    # Only a list with no rules is arranged by hand, and only whole: a find draws a part
    # of it, and an order has to be the whole membership.
    arrange = live and not _is_dynamic(row) and not find and len(kept) > 1
    smart = _is_dynamic(row) if live else _rules_drafted(context)
    art_look = context["library"].thumbnail_look()
    with ui.column().classes("gap-0 w-full console-member-list") \
            .props('data-arrange="hub_member_moved"') as listed:
        listed._props[row_drag.LIST] = True
        if arrange:
            listed._props[row_drag.PLACED] = True
        if live and not _is_dynamic(row) and not find \
                and (row.get("order_by") or "") == MANUAL_ORDER:
            listed._props[row_drag.END] = True
        cut = False
        for member in kept:
            if member.get("past_limit") and not cut:
                cut = True
                ui.label(t("console.workbench.past_limit", limit=row.get("limit") or 0)) \
                    .classes("console-limit-line")
            _member_line(context, member, arrange=arrange, live=live, smart=smart,
                         look=art_look)
    # Grouped, not inline: a handful of rows somebody took out do not belong scattered
    # through forty they left in, and they are the ones most likely to be wanted back.
    if excluded:
        ui.label(t("console.workbench.removed_count", count=(len(excluded)))) \
            .classes("console-group mt-3")
        with ui.column().classes("gap-0 w-full"):
            for member in excluded:
                _member_line(context, member, live=live, smart=smart, look=art_look)
    if not live:
        return
    # `kept`, not `members`: the excluded rows are drawn in their own group below, so
    # the indices the browser reports are into this list. Sending `members` sends the
    # excluded ones too - a game both named and excluded appears twice, and the route
    # refuses the whole move.
    #
    # Read at the drop by the page's listener, `member_moved`.
    context["state"]["member_move"] = (context, kept) if arrange else None
    if arrange:
        ui.run_javascript(arranging.SCRIPT)
    # A write rebuilds the panel, so it is a new element starting at the top - and
    # changing a member's table sent a forty-row list back to the beginning. The
    # position is remembered per collection, because arriving at a different one
    # should start at the top rather than wherever the last one was left.
    ui.run_javascript(_KEEP_SCROLL % name.replace("'", "\\'"))


async def member_moved(state: dict[str, Any], moved: Any) -> None:
    """A drop in a collection's list, applied to the list drawn last."""
    held = state.get("member_move")
    if held:
        await _reorder(held[0], held[1], moved)


@on_page
async def _reorder(context: dict[str, Any], members: list[dict], moved: Any) -> None:
    """Put one game where it was dropped.

    Sent as the whole ordered list, which is what the route takes - atomic, and no
    index arithmetic on either side of the wire.
    """
    try:
        source, target = int(moved["from"]), int(moved["to"])
    except (KeyError, TypeError, ValueError):
        return
    order = [m["game"] for m in members]
    if not (0 <= source < len(order) and 0 <= target < len(order)) or source == target:
        return
    order.insert(target, order.pop(source))
    library = context["library"]
    try:
        await run.io_bound(library.set_collection_order,
                           _collection(context)["name"], order)
    except Exception as exc:
        ui.notify(t("console.workbench.move_failed"), caption=why(exc), type="negative")
        return
    await _written(context)


def _games_heading(playable: int, hidden: int, taken: int) -> str:
    if hidden and taken:
        return t("console.workbench.count_both", count=playable,
                 hidden=hidden, taken=taken)
    if hidden:
        return t("console.workbench.count_hidden", count=playable, hidden=hidden)
    if taken:
        return t("console.workbench.count_removed", count=playable, taken=taken)
    return t("console.workbench.count_games", count=playable)


def _is_hidden(member: dict[str, Any]) -> bool:
    return ((member.get("tables") or [{}])[0].get("origin") == "hidden"
            and member.get("origin") != "excluded")


def _locked_to(member: dict[str, Any]) -> str:
    return str(member.get("ref_table") or "") if member.get("origin") == "named" else ""


def _member_line(context: dict[str, Any], member: dict[str, Any], *,
                 arrange: bool = False, live: bool = True, smart: bool = False,
                 look: thumbnails.Look | None = None) -> None:
    origin = member.get("origin") or ""
    tables = member.get("tables") or []
    table = tables[0] if tables else {}
    gone = not tables or table.get("origin") == "missing"
    game = context.get("games_by_id", {}).get(str(member.get("game") or "")) or {}
    made = game_tables.made(game)
    line = ui.row().classes("items-center gap-2 w-full no-wrap console-member-row") \
        .props(f'data-origin="{origin}"')
    if member.get("past_limit"):
        line.classes(add="console-past-limit")
    # The handle and the action sit outside the two text lines so they center against
    # the row rather than against its first line, which read as pinned to the name.
    with line:
        if arrange:
            # Focusable, because the keyboard path grabs from here: without a tab stop
            # the arrangement is mouse-only, which is the same trap the hover-revealed
            # row action had.
            ui.icon("drag_indicator").classes("console-drag-handle") \
                .props('tabindex=0 role=button') \
                .tooltip(t("console.workbench.drag_hint"))
        with thumbnails.beside(member.get(thumbnails.FIELD), icons.GAMES, look=look), \
                ui.column().classes("gap-0 grow min-w-0"):
            with ui.row().classes("items-center gap-2 w-full no-wrap"):
                ui.label(member.get("name") or member.get("game") or "") \
                    .classes("console-member-name console-cell-identifier grow min-w-0 "
                             "truncate")
                if smart and origin == "named":
                    ui.label(t("console.workbench.held_manually_added")) \
                        .classes("console-member-chip console-tier console-tier--off") \
                        .tooltip(t("console.workbench.added_by_hand"))
                if gone and origin != "excluded":
                    word, why = game_tables.GONE_WORDS
                    ui.label(word).tooltip(why) \
                        .classes("console-member-chip console-chip-warn")
                elif _is_hidden(member):
                    ui.label(t("word.hidden")) \
                        .tooltip(t("console.workbench.hidden_row.help")) \
                        .classes("console-member-chip console-chip-warn")
            said = game_tables.table_name(table) if table.get("id") and not gone else ""
            missing = table.get("origin") == "missing"
            if made or said or missing:
                with ui.row().classes("items-center gap-1 w-full no-wrap min-w-0 "
                                      "console-member-table"):
                    if made:
                        ui.label(made).classes("console-cell-made whitespace-nowrap")
                    if made and (said or missing):
                        ui.label(game_tables.JOIN.strip()).classes("console-cell-join")
                    if said:
                        # The line already answers "which table does this use?", so it
                        # is also where that is changed. Removed rows are not in the
                        # collection and have nothing to point anywhere, and a preview
                        # is not stored yet.
                        _table_choice(context, member, table, said,
                                      editable=live and origin != "excluded")
                    elif missing:
                        ui.label(t("console.workbench.table_gone")) \
                            .classes("text-warning truncate min-w-0")
        if live:
            with ui.element("div").classes("console-row-action"):
                _member_action(context, member, origin)


def _table_choice(context: dict[str, Any], member: dict[str, Any],
                  table: dict[str, Any], said: str, *, editable: bool) -> None:
    """The table half of the row's second line, and the menu that changes which table
    this row plays."""
    with ui.row().classes("items-center gap-1 no-wrap grow min-w-0 "
                          "console-member-table-line") as line:
        if _locked_to(member):
            word, why = game_tables.LOCKED_WORDS
            ui.icon(verbs.LOCKED).classes("console-member-lock")
            ui.label(word).tooltip(why)
            ui.label(game_tables.JOIN.strip()).classes("console-cell-join")
        # The same line, and the same tooltip, as a game's Tables section: version and
        # author on screen, the filename a hover away. One formatter, so the two
        # surfaces cannot drift apart.
        _built_label(table, said).classes("grow min-w-0")
        if not editable:
            return
        ui.icon("expand_more").classes("console-member-table-caret")
        line.classes(add="cursor-pointer")
        # Anchored inside the element it belongs to. Built as a sibling it lands
        # wherever the parent row happens to start, which put an earlier menu 726px
        # from the control that opened it.
        with line, ui.menu().props('anchor="bottom left" self="top left"'):
            holder = ui.column().classes("gap-0 w-full items-stretch")
        # Filling only. The menu is a child of this line, so Quasar already opens and
        # closes it on a click here - calling `open()` as well reopened it in the same
        # gesture that closed it, which read as the menu refusing to shut.
        line.on("click", lambda: _fill_table_menu(context, member, table, holder))


@on_page
async def _fill_table_menu(context: dict[str, Any], member: dict[str, Any],
                           table: dict[str, Any], holder: Any) -> None:
    """This game's tables, read when asked for rather than with every row.

    One read per game and it is cached, but doing it while drawing forty rows would be
    forty requests on the loop - which `api.py` refuses outright.
    """
    game = str(member.get("game") or "")
    locked = _locked_to(member)
    following = table.get("origin") == "default"
    try:
        choices = await offload.io(context["library"].tables_for, game)
    except Exception as exc:
        ui.notify(t("console.workbench.tables_failed"), caption=why(exc),
                  type="negative")
        return
    others = [other for other in (context.get("membership") or {}).get("members") or []
              if other is not member and str(other.get("game") or "") == game]
    # Every table this collection already holds for this game - what its refs *resolve
    # to*, not just what they name. Asking only about named tables offers the file a
    # following ref already resolves to, so a one-table game is told it could add the
    # table it has, and "Also Add" and "Lock to" read as the same entry.
    # An excluded ref counts too: offering a table that is being kept out would add a
    # member the collection immediately drops again.
    spoken = {str(held.get("id") or "") for one in [member, *others]
              for held in one.get("tables") or []}
    # Tables another of this game's rows already plays. A pairing appears once (2.10),
    # so pointing this row at one of them cannot be stored - it is shown and refused
    # rather than hidden, because an entry that vanishes without a reason is the same
    # puzzle as a row that vanishes without one.
    taken: set[str] = set()
    default_taken = False
    for other in others:
        tables = other.get("tables") or []
        if tables and tables[0].get("origin") == "default":
            default_taken = True
        else:
            taken.update(str(held.get("id") or "") for held in tables)
    offers = next((one for one in choices if one.get("default")), None)
    blocked = t("console.workbench.already_collection")
    holder.clear()
    with holder:
        ui.item_label(t("console.workbench.plays_heading")).props("header") \
            .classes("console-menu-header")
        _table_menu_item(context, member, "", t("console.workbench.game_default"),
                         chosen=following, blocked=blocked if default_taken else "",
                         under=game_tables.table_name(offers) if offers else "")
        for one in choices:
            table_id = str(one.get("id") or "")
            _table_menu_item(context, member, table_id,
                             t("console.workbench.lock_to",
                               table=game_tables.table_name(one)),
                             chosen=table_id == locked,
                             blocked=blocked if table_id in taken else "")
        # The tournament case: a collection holding two versions of one game. Pointing
        # this row somewhere else cannot express it - that is one row, not two - so
        # adding is its own verb.
        spare = [one for one in choices if str(one.get("id") or "") not in spoken]
        if spare:
            ui.separator()
            ui.item_label(t("console.workbench.also_add")).props("header") \
                .classes("console-menu-header")
            for one in spare:
                _add_table_item(context, member, one)


async def _hold(context: dict[str, Any], member: dict[str, Any], table_id: str) -> None:
    """This row playing `table_id`, or its game's default where that is ""."""
    library, name = context["library"], _collection(context)["name"]
    game = str(member.get("game") or "")
    if member.get("origin") == "filter":
        await run.io_bound(library.add_to_collection, name, game, table_id)
        return
    await run.io_bound(library.set_member_table, name, game, table_id,
                       str(member.get("ref_table") or ""))


def _table_menu_item(context: dict[str, Any], member: dict[str, Any], table_id: str,
                     label: str, *, chosen: bool, blocked: str = "",
                     under: str = "") -> None:
    """One choice. The current one is ticked and inert - a menu that lets you pick what
    is already true reports a change that did not happen - and so is one the collection
    cannot hold, which says why instead of disappearing.

    `under` names what the game's default is today, so choosing it is not a blind pick.
    """
    @on_page
    async def pick() -> None:
        if chosen or blocked:
            return
        try:
            await _hold(context, member, table_id)
        except Exception as exc:
            ui.notify(t("console.workbench.change_failed"), caption=why(exc), type="negative")
            return
        await _written(context)

    marked = "console-menu-item"
    if chosen:
        marked += " console-menu-on"
    elif blocked:
        marked += " console-menu-blocked"
    item = ui.menu_item(on_click=pick).classes(marked)
    if blocked:
        # It stays open on a click it will not act on: closing would look like the
        # choice was taken.
        item.props("auto-close=false aria-disabled=true")
        with item:
            ui.tooltip(blocked).classes("console-menu-tip")
    with item, ui.row().classes("items-center gap-2 no-wrap w-full"):
        if table_id:
            ui.icon(verbs.LOCKED).classes("console-menu-mark")
        else:
            ui.element("span").classes("console-menu-mark")
        with ui.column().classes("gap-0 grow min-w-0"):
            ui.label(label).classes("console-menu-table-name")
            if under:
                ui.label(under).classes("console-menu-sub")
        if chosen:
            ui.icon("check").classes("console-menu-check")
        elif blocked:
            ui.icon("block").classes("console-menu-check console-menu-blocked-mark")


def _add_table_item(context: dict[str, Any], member: dict[str, Any],
                    table: dict[str, Any]) -> None:
    """A second row for this game, playing another of its tables.

    Landed next to the row it was asked from, not at the end: in a forty-row collection
    the end is off screen, and a new row you cannot see is indistinguishable from a
    click that did nothing.
    """
    library, name = context["library"], _collection(context)["name"]
    game = str(member.get("game") or "")
    playing = member.get("tables") or [{}]

    @on_page
    async def add() -> None:
        try:
            if member.get("origin") == "filter":
                # Found by the rule and not stored: stored as it plays now first, or
                # the game held by hand on the new table alone would replace this row.
                here = ("" if playing[0].get("origin") == "default"
                        else str(playing[0].get("id") or ""))
                await run.io_bound(library.add_to_collection, name, game, here)
                after = here
            else:
                after = str(member.get("ref_table") or "")
            await run.io_bound(library.add_to_collection, name, game,
                               str(table.get("id") or ""), after)
        except Exception as exc:
            ui.notify(t("said.add_failed"), caption=why(exc), type="negative")
            return
        await _written(context)

    with ui.menu_item(on_click=add).classes("console-menu-item"), \
            ui.row().classes("items-center gap-2 no-wrap w-full"):
        # A plus, not the lock the entries above wear: both groups name the same tables,
        # and the mark is what says this one adds rather than chooses.
        ui.icon("add").classes("console-menu-add")
        ui.label(game_tables.table_name(table)).classes("console-menu-table-name grow min-w-0")


def _member_action(context: dict[str, Any], member: dict[str, Any],
                   origin: str) -> None:
    """The one thing this row's state makes sense to do.

    Removing says the same word whichever way the row got here, because that is the
    one intent a reader has. Underneath it differs - a matched row has to be recorded
    as an exclusion or the rule finds it again - but the list says so by moving it
    into "Manually removed", which is better than a tooltip explaining it in advance.
    """
    library = context["library"]
    name = _collection(context)["name"]

    @on_page
    async def put_back() -> None:
        row = collection_adds.row_of(member)
        try:
            await run.io_bound(library.unexclude_from_collection, name, row.game, row.table)
        except Exception as exc:
            ui.notify(t("said.action_failed"), caption=why(exc), type="negative")
            return
        ui.notify(t("console.workbench.restore_into", name=name), type="positive")
        await _written(context)

    if origin == "excluded":
        ui.button(icon=verbs.REVERT, on_click=put_back) \
            .props("flat dense round size=sm").tooltip(t("console.workbench.put_back_2"))
    else:
        ui.button(icon=verbs.REMOVE, on_click=lambda: collection_adds.remove_row(
            library, name, member, then=partial(_collection_redrawn, context, name))) \
            .props("flat dense round size=sm").tooltip(t("console.workbench.remove_collection"))


def _add_control(context: dict[str, Any], members: list[dict]) -> None:
    """Add a game the rule did not find, or that there is no rule to find.

    A game, not a table: a member with no table named follows whichever table is the
    game's default, which is what somebody adding a game to a list almost always
    means. Holding it to one table is the unusual intent and is a second act.
    """
    state = context["state"]
    again = state.pop("add_again", None) == _collection(context)["name"]
    games = context["library"].games
    if not games:
        return
    # Typed into, not scrolled: this is a picker over the whole library, and a list
    # that long is searched. `use-input` with no debounce filters from the first
    # character; `new-value-mode` is left off so only a real game can be chosen.
    picker = panel.GamePicker(games, collection_adds.holds(members)[0],
                              label=t("console.workbench.add_games"),
                              art=context["library"].game_art()) \
        .props('input-debounce=0 hide-selected fill-input clearable') \
        .classes("w-full mt-2")
    (context["library"].thumbnail_look() or thumbnails.Look()).in_panel() \
        .apply_to_options(picker, "console-picker-popup")

    async def add() -> None:
        if not picker.value:
            return
        name = _collection(context)["name"]
        state["add_again"] = name
        done = await collection_adds.add(context["library"], name,
                                         [collection_adds.Row(str(picker.value))],
                                         then=partial(_collection_redrawn, context, name))
        if done is None:
            state.pop("add_again", None)

    picker.on_value_change(add)
    ui.run_javascript(_ADD_BOX % (picker.id, "true" if again else "false"))


def _tag_verbs(context: dict[str, Any]) -> list[panel.Verb]:
    return tageditor.acts(context["library"], [{**context["tag"], "tag": context["name"]}],
                          partial(_tag_changed, context))


def _collection_verbs(context: dict[str, Any]) -> list[panel.Verb]:
    # Imported here: console.collections imports console.games, which imports this module.
    from console.collections import acts

    state = context["state"]

    @on_page
    async def after(then: str | None) -> None:
        if then:
            state["collection"] = then
            await _written(context, then)
            return
        reread = state.get("refresh_collections")
        if callable(reread):
            await reread()
        deeplink.sync(state)
        await context["rebuild"]()

    row = _collection(context)
    return acts(context["library"], state, [row], after)


def _page_redraw(context: dict[str, Any]) -> Callable[[], None]:
    def redraw() -> None:
        reload_page = context["state"].get("rerender")
        if callable(reload_page):
            reload_page()
    return redraw


def _launcher_verbs(context: dict[str, Any]) -> list[panel.Verb]:
    return launchers_page.acts(context["library"], context["state"], [context["launcher"]],
                               len(context.get("launchers") or []), _page_redraw(context),
                               after=context["rebuild"],
                               playing=bool(context.get("playing")))


def _theme_verbs(context: dict[str, Any]) -> list[panel.Verb]:
    return themes_page.acts(context["library"], [context["theme"]],
                            partial(themes_page.changed, context))


def _backup_verbs(context: dict[str, Any]) -> list[panel.Verb]:
    async def refresh() -> None:
        again = context["state"].get("refresh_backups")
        if callable(again):
            await again()

    return backups_page.acts(context["library"], [context["backup"]], refresh)


def _player_verbs(context: dict[str, Any]) -> list[panel.Verb]:
    player = context["player"]
    return players_page.acts(context["library"], context["state"], [player],
                             _page_redraw(context),
                             accounts={str(player["id"]): context.get("accounts") or ()},
                             after=context["rebuild"])


def _device_verbs(context: dict[str, Any]) -> list[panel.Verb]:
    if context.get("library") is None:
        return []
    target = devices_page.Target(context["device"], devices_page.client_for(context),
                                 context.get("actions"), not devices_page.is_local(context))
    return devices_page.acts(context["library"], [target], _page_redraw(context))


def _game_verbs(context: dict[str, Any]) -> list[panel.Verb]:
    library, game_id, state = context["library"], context["game_id"], context["state"]
    name = str(context["game"].get("name") or "")
    offer = collection_adds.Offer(library, [collection_adds.Row(game_id)],
                                  collection_adds.GAMES, name,
                                  then=partial(_game_redrawn, context),
                                  narrowed=str(state.get("collection") or ""))

    async def refresh(ids: list[str]) -> None:
        again = state.get("refresh_games")
        if callable(again):
            await again(ids)
        else:
            await context["rebuild"]()

    async def rate(ids: list[str], value: int) -> bool:
        grid_rate = state.get("rate_games")
        if not callable(grid_rate):
            return False
        landed = await grid_rate(ids, value)
        if landed:
            await context["rebuild"]()
        return bool(landed)

    async def match(_games: list[dict[str, Any]]) -> None:
        await _pick_a_match(context)

    return game_acts.game_acts(
        library, [context["game"]], state, refresh,
        rate=rate if callable(state.get("rate_games")) else None, match=match,
        collections=game_acts.collections_of(offer, context["collections"]))


def _table_verbs(context: dict[str, Any]) -> list[panel.Verb]:
    library, game_id, table_id = context["library"], context["game_id"], context["lens"]
    table = next((one for one in context["tables"] if str(one.get("id")) == table_id), None)
    if table is None:
        return []

    async def after(game_ids: list[str], gone: bool) -> None:
        if gone:
            await _table_gone(context, table)
            return
        await context["rebuild"]()
        refresh = context["state"].get("refresh_game")
        if callable(refresh):
            for one in game_ids:
                await refresh(one)

    offer = collection_adds.Offer(
        library, [collection_adds.Row(game_id, table_id)], collection_adds.TABLES,
        game_tables.name_among(table, context["tables"]),
        then=partial(_game_redrawn, context))
    target = game_acts.Target(game_id, str(context["game"].get("name") or ""), table,
                              context["tables"])
    return game_acts.table_acts(library, [target], after, context["state"],
                                game_acts.collections_of(offer, context["collections"]))


def _file_after(context: dict[str, Any]) -> Callable[[list[str]], Awaitable[None]]:
    async def after(_game_ids: list[str]) -> None:
        await context["rebuild"]()
    return after


def _media_file_verbs(context: dict[str, Any]) -> list[panel.Verb]:
    one = file_acts.File(context["row"], context["game"])
    return file_acts.media_acts(context["library"], [one], context["state"],
                                _file_after(context))


def _asset_file_verbs(context: dict[str, Any]) -> list[panel.Verb]:
    one = file_acts.File(context["row"], context["game"])
    return file_acts.asset_acts(context["library"], [one], context["state"],
                                _file_after(context))


# What the panel header's menu offers, per subject: the same lists the grids' row menus
# draw. A subject with none has no menu.
def _selection_verbs(context: dict[str, Any]) -> list[panel.Verb]:
    """The grid's own bulk menu: the grid that holds the ticks names it."""
    verbs_of = context["state"].get("selection_verbs")
    return verbs_of() if callable(verbs_of) else []


SUBJECT_VERBS: dict[str, Callable[[dict[str, Any]], list[panel.Verb]]] = {
    "selection": _selection_verbs,
    "game_selection": _selection_verbs,
    "game": _game_verbs,
    "table": _table_verbs,
    "tag": _tag_verbs,
    "collection": _collection_verbs,
    "launcher": _launcher_verbs,
    "theme": _theme_verbs,
    "device": _device_verbs,
    "player": _player_verbs,
    "backup": _backup_verbs,
    "media_file": _media_file_verbs,
    "asset_file": _asset_file_verbs,
}


SECTIONS: tuple[Section, ...] = (
    # The game first, then the file: a table belongs to a game, and reading down is
    # reading from the thing that contains to the thing contained.
    Section("game_details", _game_label, _game_block),
    Section("table_details", lambda _: t("console.workbench.table_section"), _table_block,
            subjects=frozenset({"table"})),
    Section("table_settings", lambda _: t("console.workbench.table_settings"),
            _table_settings, subjects=frozenset({"table"})),
    Section("selection_marks", lambda _: t("console.workbench.details"),
            _selection_marks, subjects=frozenset({"selection"})),
    Section("game_selection_marks", lambda _: t("console.workbench.details"),
            _game_selection_marks, subjects=frozenset({"game_selection"})),
    Section("selection_settings", lambda _: t("console.workbench.table_settings"),
            _selection_settings, subjects=frozenset({"selection"})),
    Section("play", lambda _: game_tables.PLAY, _play_block),
    Section("collections", _collections_label, _collections_block),
    Section("media", _media_label, _media_block, dock=True),
    # Beside Media, not under Details: both answer "what does this game hold", one
    # for what a screen shows and one for what a launch needs.
    Section("assets", _assets_label, _assets_block, dock=True),
    Section("guides", _guides_label, _guides_block),
    # A launcher, in reading order: what it is and what it runs, then the program's own
    # settings grouped as the app declares them, then the copies kept of its file.
    Section("launcher_details", lambda _: t("console.workbench.details"), _launcher_details,
            subjects=frozenset({"launcher"})),
    *_launcher_config_sections(),
    Section("launcher_all", lambda _: t("console.workbench.all_settings"), _all_settings,
            subjects=frozenset({"launcher"}), shown=_all_settings_shown),
    Section("launcher_backups", lambda _: t("console.workbench.settings_file"),
            _config_backups, subjects=frozenset({"launcher"}), shown=_app_keeps_settings),
    Section("collection_details", lambda _: t("console.workbench.details"),
            _collection_details,
            subjects=frozenset({"collection"})),
    Section("collection_games", _games_label, _collection_games,
            subjects=frozenset({"collection"})),
    Section("all_games_details", lambda _: t("console.workbench.details"),
            _all_games_details, subjects=frozenset({"all_games"})),
    Section("media_file", lambda _: t("word.file"), _media_file_block,
            subjects=frozenset({"media_file"}), dock=_media_has_stage),
    Section("tag_details", lambda _: t("console.workbench.details"), _tag_details,
            subjects=frozenset({"tag"})),
    Section("tag_games", lambda context: t("console.tags.games_counted",
                                           count=int(context["tag"].get("games") or 0)),
            _tag_games, subjects=frozenset({"tag"})),
    Section("asset_file", lambda _: t("word.file"), _asset_file_block,
            subjects=frozenset({"asset_file"}), dock=_asset_has_stage),
    # A device, in reading order: what it is, what it is running, what it can be asked
    # for, what it has written down, and what it can be told to do. Its settings are not
    # here at all - they are a door in Details into that install's own Console, because a
    # build's settings belong to that build and rendering them from here meant fetching
    # its schema over HTTP.
    Section("device_details", lambda _: t("console.workbench.details"), _device_details,
            subjects=frozenset({"device"})),
    Section("device_software", lambda _: t("word.software"), _device_software,
            subjects=frozenset({"device"}),
            shown=lambda context: not devices_page.is_phone(context)),
    Section("device_capabilities", lambda _: t("console.workbench.capabilities"),
            _device_capabilities,
            subjects=frozenset({"device"})),
    Section("device_logs", lambda _: t("console.workbench.logs"), _device_logs,
            subjects=frozenset({"device"}),
            shown=lambda context: devices_page.serves(context, "logs")),
    Section("theme_details", lambda _: t("console.themes.theme"), themes_page.details,
            subjects=frozenset({"theme"})),
    Section("theme_settings", lambda _: t("console.themes.settings"),
            themes_page.settings_section, subjects=frozenset({"theme"}),
            shown=lambda context: bool(context["theme"].get("configurable"))),
    # A player: who they are, then an account per running extension offering one, which
    # the panel puts between these two, then what they have played.
    Section("player_details", lambda _: t("console.workbench.details"),
            players_page.details, subjects=frozenset({"player"})),
    Section("player_plays", lambda _: t("console.players.plays"), players_page.plays,
            subjects=frozenset({"player"}),
            shown=lambda context: players_page.has_plays(context["player"])),
    # A copy, then what a backup holds.
    Section("backup_details", lambda _: t("console.workbench.details"), backups_page.details,
            subjects=frozenset({"backup"})),
    Section("backup_contents", lambda _: t("console.backups.contents"), backups_page.contents,
            subjects=frozenset({"backup"}), shown=backups_page.has_contents),
)
