
"""The library seen by asset file rather than by game.

The Media lens's twin, and it exists for the same reason: a row is a file, so a gap is
countable and a bulk action can be handed one. What differs is what the files are for.
Media is what a game looks like; an asset is what it needs to play as intended, and a
matrix that mixes them is neither.

It is also where the per-table kinds are told apart: a game whose only backglass is named
for one table has it on one row and not the other. The Games grid reports the folder's kinds
only.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Collection
from typing import Any

from nicegui import ui

from common import icons
from common.games import asset_lens
from common.i18n import t
from console import (
    file_acts,
    game_tables,
    grid,
    media_ownership,
    offload,
    panel,
    text_editor,
    thumbnails,
    views,
)
from console.games import view_control

logger = logging.getLogger("vpinfe.console.assets")

SCOPE = "console.assets.columns"

# What the wire's binding is called on screen. Three of the four are the words the media
# lens already uses for the same question - whose file is this - and `orphaned` is the
# one assets have and media does not: a file named for a table that is not there.
ORPHAN = media_ownership.tier_for(media_ownership.ORPHAN).noun
UNUSED = media_ownership.tier_for(media_ownership.UNUSED).noun
MISSING = media_ownership.tier_for(media_ownership.MISSING).noun

_REASON_CHOICES = ([{"value": "", "label": t("word.in_use")}]
                   + [{"value": word, "label": t(word)}
                      for word in (MISSING, ORPHAN, UNUSED)])

_SCOPE_CHOICES = [{"value": "game", "label": t("word.game")},
                  {"value": "table", "label": t("word.table")}]

_SOURCE_CHOICES = ([{"value": name, "label": name}
                    for name in media_ownership.source_names()]
                   + [{"value": "", "label": t("word.no_file")}])


def _kind_choices(library: Any) -> list[dict[str, Any]]:
    """The kinds a row can be about and the library collects, as a filter lists them.

    Fixed, like the reasons beside it: a kind with no file yet is still one to ask about,
    and a list built from the rows would leave out the very gap somebody came to find.
    """
    kept = library.kept_kinds()["asset"]
    return [{"value": asset_lens.label_of(kind), "label": asset_lens.label_of(kind)}
            for kind in asset_lens.KINDS if kind in kept]


def _with_kind_filter(columns: list[dict[str, Any]], library: Any) -> list[dict[str, Any]]:
    return [{**one, **grid.choice_filter(_kind_choices(library))}
            if one["field"] == "label" else one for one in columns]


def _reason(row: dict[str, Any]) -> str:
    """Why this file is not the one being used, blank while it is.

    An asset has a second way to be unused that media does not: VPX resolves a script
    and a point of view by table stem only, so one named for the folder is correctly
    named and inert. `serves` is what tells them apart, not the binding.
    """
    binding = str(row.get("binding") or "")
    if binding == "orphaned":
        return ORPHAN
    if not row.get("present"):
        return MISSING
    return UNUSED if row.get("serves") == 0 else ""


def rows(found: list[dict[str, Any]],
         unsaved: Collection[tuple[str, str]] = ()) -> list[dict[str, Any]]:
    """The API's assets, flattened for a grid; `unsaved` is the (game, path) of the files
    with text typed and not saved."""
    return [{**row,
             "year": game_tables.year_of(row.get("year")),
             "unsaved": (str(row.get("game_id") or ""), str(row.get("path") or "")) in unsaved,
             "scope": game_tables.scope_of(row),
             "used_by": row.get("serves"),
             "reason": _reason(row),
             "source": media_ownership.source_name(str(row.get("origin") or "")),
             "match": str(row.get("matched_to") or ""),
             "path": row.get("path") or "",
             grid.NO_MENU: not file_acts.asset_has_acts(row)}
            for row in found]


_ESCAPE = ("const esc = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;')"
           ".replace(/\"/g, '&quot;');")

_KIND = (
    "params => {" + _ESCAPE +
    f" const unsaved = esc({json.dumps(t('word.not_saved'))});"
    f" const why = esc({json.dumps(t('console.text_editor.not_saved.help'))});"
    " let said = esc(params.value == null ? '' : params.value);"
    " if ((params.data || {}).unsaved) said += ' <span class=\"console-member-chip"
    " console-cell-chip console-tier console-tier--warn\" title=\"' + why + '\">'"
    " + unsaved + '</span>';"
    " return said; }"
)

_FILE = "word.file"
_GAME = "word.game"
_SOURCE = "word.source"

COLUMNS: list[dict[str, Any]] = [
    grid.identifier("game", t("word.name"), 240, pinned="left", group=t(_FILE),
                subtitle=("said", "", "said_built"), picture=thumbnails.FIELD,
                glyph=icons.GAMES, built_tip=t("console.media_ownership.named_for"),
                help=t("console.assets.name.help")),
    grid.column("scope", t("console.assets.scope"), 100, group=t(_FILE),
                **grid.choice_filter(_SCOPE_CHOICES),
                help=t("console.assets.scope.help")),
    grid.column("label", t("word.kind"), 160, group=t(_FILE),
                **{":cellRenderer": _KIND},
                help=t("console.assets.kind.help")),
    grid.column("path", t("word.path"), 300, group=t(_FILE),
                help=t("console.assets.path.help")),
    grid.column("source", t("word.source"), 165, group=t(_SOURCE),
                **grid.choice_filter(_SOURCE_CHOICES),
                help=t("console.assets.source.help")),
    grid.column("used_by", t("word.used_by"), type="numericColumn", group=t(_FILE),
                help=t("console.assets.used_by.help")),
    grid.column("reason", t("word.unused_reason"), 150, group=t(_FILE),
                **grid.choice_filter(_REASON_CHOICES),
                help=t("console.assets.reason.help")),
    grid.column("match", t("console.assets.match"), 140, group=t(_SOURCE),
                help=t("console.assets.match.help")),
    grid.column("manufacturer", t("word.manufacturer"), 150, group=t(_GAME),
                help=t("help.who_made_it")),
    grid.year_column("year", t("word.year"), group=t(_GAME),
                     help=t("help.year_released")),
]

_ALL = [definition["field"] for definition in COLUMNS]

VIEWS: dict[str, list[str] | views.Preset] = {
    "console.view.have": views.Preset(
        columns=("game", "label", "path", "source", "used_by", "reason"),
        sort=({"colId": "game", "sort": "asc", "sortIndex": 0},),
        filters={"reason": {"values": ["", ORPHAN, UNUSED]}},
        help=t("console.assets.have_view.help")),
    "console.view.missing": views.Preset(
        columns=("game", "label", "reason"),
        sort=({"colId": "game", "sort": "asc", "sortIndex": 0},),
        filters={"reason": {"values": [MISSING]}},
        help=t("console.assets.missing_view.help")),
    "console.view.orphans": views.Preset(
        columns=("game", "label", "path", "reason"),
        sort=({"colId": "game", "sort": "asc", "sortIndex": 0},),
        filters={"reason": {"values": [ORPHAN]}},
        help=t("console.assets.orphans_view.help")),
    "console.view.unused": views.Preset(
        columns=("game", "label", "path", "used_by", "reason"),
        sort=({"colId": "game", "sort": "asc", "sortIndex": 0},),
        filters={"reason": {"values": [UNUSED]}},
        help=t("console.assets.unused_view.help")),
    "console.view.sources": views.Preset(
        columns=("game", "label", "path", "source", "used_by", "match"),
        sort=({"colId": "source", "sort": "asc", "sortIndex": 0},
              {"colId": "game", "sort": "asc", "sortIndex": 1}),
        filters={"reason": {"values": [""]}},
        help=t("console.assets.sources_view.help")),
    "console.view.everything": views.Preset(
        columns=tuple(_ALL),
        help=t("console.assets.everything_view.help")),
}


def build(found: list[dict[str, Any]], library: Any,
          on_select: Callable[[dict | None], Any],
          state: dict[str, Any] | None = None,
          rescan: Callable[[], Any] | None = None) -> None:
    """The asset lens: one row per file, and one per file that is not there."""
    state = state if state is not None else {}
    built = rows(found, text_editor.drafts_of(state))
    columns = _with_kind_filter(
        grid.with_art(grid.with_derived_facets(COLUMNS, built), library.thumbnail_look()), library)
    gaps = sum(1 for row in built if not row.get("present"))
    on_screen = {"rows": len(built)}

    selected: list[dict[str, Any]] = []

    def said(picked: int = 0) -> str:
        if picked:
            return grid.selection_said(table, picked, t(
                "console.assets.selected", picked=picked, shown=on_screen["rows"]))
        if on_screen["rows"] == len(built):
            return t("console.assets.assets_missing", count=(len(built)), gaps=(gaps))
        return t("console.assets.assets", shown=on_screen["rows"], count=len(built))

    with ui.row().classes("w-full items-center gap-2 px-3 py-2 mb-2 shrink-0 "
                                  "console-panel console-grid-bar"):
        bar = panel.grid_bar()
        wire_views, _picker, showing, describe = view_control(library, SCOPE, VIEWS,
                                                    _ALL, columns, bar=bar,
                                                    art_in_lists=True)
        describe()
        with bar.top, panel.bar_end():
            search = panel.search(t("console.assets.search_assets"))
        with bar.bottom, panel.bar_end():
            count = ui.label(said()).classes("text-xs console-label")
            show_selection = panel.selection_menu(
                t("console.assets.assets_menu"), lambda: grid.selection(table),
                lambda chosen: acts_on(chosen),
                lambda: table.run_grid_method("deselectAll"))
            if rescan is not None:
                panel.refresh(rescan, t("console.assets.rescan"))

    by_id = {row["id"]: row for row in built}

    async def changed(ids: list[str]) -> None:
        for game_id in ids:
            await refresh_files(game_id)

    def acts_on(chosen: list[dict[str, Any]]) -> list[panel.Verb]:
        return file_acts.asset_acts(library, file_acts.files_of(library, chosen), state,
                                    changed)

    def on_select_rows(picked: list[dict[str, Any]]) -> None:
        selected[:] = picked
        show_selection(bool(picked))
        count.text = said(len(picked))

    def on_context(row: dict | None) -> None:
        if not row:
            menu.clear()
            return
        on = grid.menu_rows(table, row)
        panel.verb_menu(
            menu, str(row["game"]) + " - " + str(row["label"]) if len(on) == 1
            else t("console.assets.files", count=len(on)),
            panel.for_selection(acts_on(on), len(on)))

    grid.on_row_focus(SCOPE,
                      lambda event: on_select(by_id.get(grid.focused_row(event))))

    async def on_header_context(col_id: str | None) -> None:
        await grid.header_menu(menu, table, columns, col_id)

    with ui.element("div").classes("w-full grow min-h-0 flex flex-col"):
        table = grid.build(columns, built, SCOPE, on_select_rows, on_context,
                           on_header_context=on_header_context, view_of=showing)
        menu = ui.context_menu()
    search.on_value_change(
        lambda: table.run_grid_method("setGridOption", "quickFilterText",
                                      search.value or ""))

    async def counted() -> None:
        """Whatever narrowed the rows - a filter, the search, a view - lands here."""
        seen = await table.run_grid_method("getDisplayedRowCount")
        on_screen["rows"] = int(seen if isinstance(seen, int) else len(built))
        count.text = said(len(selected))

    table.on("modelUpdated", counted)

    async def refresh_files(game_id: str) -> None:
        fresh = rows(await offload.io(library.files_of, "asset", game_id),
                     text_editor.drafts_of(state))
        grid.replace_rows(table, built, by_id, fresh, lambda row: row["game_id"] == game_id)

    state["refresh_files"] = refresh_files

    def mark_unsaved(drafted: set[tuple[str, str]]) -> None:
        changed = [{**row, "unsaved": not row["unsaved"]} for row in built
                   if row["unsaved"] != ((row["game_id"], row["path"]) in drafted)]
        if changed:
            grid.transact(table, built, {"update": changed}, by_id)

    state["mark_unsaved_files"] = mark_unsaved
    wire_views(table)
