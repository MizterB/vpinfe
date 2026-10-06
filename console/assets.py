
"""The library seen by asset file rather than by game.

The Media lens's twin, and it exists for the same reason: a row is a file, so a gap is
countable and a bulk action can be handed one. What differs is what the files are for.
Media is what a game looks like; an asset is what it needs to play as intended, and a
matrix that mixes them is neither.

It is also the surface a recorded defect has been waiting for. The Games grid reports a
`.directb2s` from a folder scan, so a game whose only backglass is named for one table
reads "has one" while its sibling launches without a backglass. Here they are two rows.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from nicegui import ui

from common import icons
from common.i18n import t
from console import game_tables, grid, list_art, media_ownership, offload, panel, views
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


def rows(found: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The API's assets, flattened for a grid."""
    return [{**row,
             "scope": game_tables.scope_of(row),
             "used_by": row.get("serves"),
             "reason": _reason(row),
             "source": media_ownership.source_name(str(row.get("origin") or "")),
             "match": str(row.get("matched_to") or ""),
             "path": row.get("path") or ""}
            for row in found]


_FILE = "word.file"
_GAME = "word.game"
_SOURCE = "word.source"

COLUMNS: list[dict[str, Any]] = [
    grid.identifier("game", t("word.name"), 240, pinned="left", group=t(_FILE),
                subtitle=("said", "", "said_built"), picture=list_art.FIELD,
                glyph=icons.GAMES, built_tip=t("console.media_ownership.named_for"),
                help=t("console.assets.name.help")),
    grid.column("scope", t("console.assets.scope"), 100, group=t(_FILE),
                **grid.choice_filter(_SCOPE_CHOICES),
                help=t("console.assets.scope.help")),
    grid.column("label", t("word.kind"), 160, group=t(_FILE),
                help=t("console.assets.kind.help")),
    grid.column("used_by", t("word.used_by"), type="numericColumn", group=t(_FILE),
                help=t("console.assets.used_by.help")),
    grid.column("reason", t("word.unused_reason"), 150, group=t(_FILE),
                **grid.choice_filter(_REASON_CHOICES),
                help=t("console.assets.reason.help")),
    grid.column("path", t("word.path"), 300, group=t(_FILE),
                help=t("console.assets.path.help")),
    grid.column("source", t("word.source"), 165, group=t(_SOURCE),
                **grid.choice_filter(_SOURCE_CHOICES),
                help=t("console.assets.source.help")),
    grid.column("match", t("console.assets.match"), 140, group=t(_SOURCE),
                help=t("console.assets.match.help")),
    grid.column("manufacturer", t("word.manufacturer"), 150, group=t(_GAME),
                help=t("help.who_made_it")),
    grid.column("year", t("word.year"), group=t(_GAME),
            help=t("help.year_released")),
]

_ALL = [definition["field"] for definition in COLUMNS]

VIEWS: dict[str, list[str] | views.Preset] = {
    "console.view.have": views.Preset(
        columns=("game", "label", "reason", "used_by", "path"),
        sort=({"colId": "game", "sort": "asc", "sortIndex": 0},),
        filters={"reason": {"values": ["", ORPHAN, UNUSED]}},
        help=t("console.assets.have_view.help")),
    "console.view.missing": views.Preset(
        columns=("game", "label", "reason"),
        sort=({"colId": "game", "sort": "asc", "sortIndex": 0},),
        filters={"reason": {"values": [MISSING]}},
        help=t("console.assets.missing_view.help")),
    "console.view.orphans": views.Preset(
        columns=("game", "label", "reason", "path"),
        sort=({"colId": "game", "sort": "asc", "sortIndex": 0},),
        filters={"reason": {"values": [ORPHAN]}},
        help=t("console.assets.orphans_view.help")),
    "console.view.unused": views.Preset(
        columns=("game", "label", "reason", "used_by", "path"),
        sort=({"colId": "game", "sort": "asc", "sortIndex": 0},),
        filters={"reason": {"values": [UNUSED]}},
        help=t("console.assets.unused_view.help")),
    "console.view.sources": views.Preset(
        columns=("game", "label", "used_by", "path", "source", "match"),
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
    built = rows(found)
    columns = grid.with_art(COLUMNS, library.list_art_look())
    gaps = sum(1 for row in built if not row.get("present"))
    on_screen = {"rows": len(built)}

    def said() -> str:
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
            if rescan is not None:
                panel.refresh(rescan, t("console.assets.rescan"))

    by_id = {row["id"]: row for row in built}
    grid.on_row_focus(SCOPE,
                      lambda event: on_select(by_id.get(grid.focused_row(event))))

    async def on_header_context(col_id: str | None) -> None:
        await grid.header_menu(menu, table, columns, col_id)

    with ui.element("div").classes("w-full grow min-h-0 flex flex-col"):
        table = grid.build(columns, built, SCOPE,
                           on_header_context=on_header_context, view_of=showing)
        menu = ui.context_menu()
    search.on_value_change(
        lambda: table.run_grid_method("setGridOption", "quickFilterText",
                                      search.value or ""))

    async def counted() -> None:
        """Whatever narrowed the rows - a filter, the search, a view - lands here."""
        seen = await table.run_grid_method("getDisplayedRowCount")
        on_screen["rows"] = int(seen if isinstance(seen, int) else len(built))
        count.text = said()

    table.on("modelUpdated", counted)

    async def refresh_files(game_id: str) -> None:
        fresh = rows(await offload.io(library.files_of, "asset", game_id))
        grid.replace_rows(table, built, by_id, fresh, lambda row: row["game_id"] == game_id)

    state["refresh_files"] = refresh_files
    wire_views(table)
