"""Discovery's Releases tab: one row for each release VPS lists that fits the question.

The question, its chips, the search and the saved views are the Games tab's; this tab asks
the same thing and lists the releases that answer it where the Games tab lists their games.
A row stands for a release and a press on it opens its game's pane.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from nicegui import ui

from common import icons
from common.i18n import t
from common.online import vps_find, vps_question
from manager.kit import grid as grid_module
from manager.kit import panel, thumbnails, verbs, views, when
from manager.kit.data import Library
from manager.kit.on_page import on_page
from manager.library import discovery_ask

SCOPE = "discovery_releases"

HAVE = "have"
MOD = "mod"

_ADDED_SAID: dict[str, Any] = {
    ":valueFormatter": "params => (params.data || {}).added_said || ''"}
_NEWEST =({"colId": "added", "sort": "desc", "sortIndex": 0},)
_SHOWN = "getElement(%d).api.getDisplayedRowCount()"


def columns(kind_words: Mapping[str, str]) -> list[dict[str, Any]]:
    """The grid's columns; `kind_words` is the VPS kinds the library collects, to the word
    each is called."""
    return [
        grid_module.identifier(
            "name", t("word.game"), 260, pinned="left", subtitle="said",
            picture=thumbnails.FIELD, glyph=icons.GAMES,
            help=t("manager.discovery.releases.name.help"),
            **{":getQuickFilterText":
               "params => [params.data.name, params.data.said, params.data.find, "
               "params.data.authors, params.data.version].filter(Boolean).join(' ')"}),
        grid_module.column(
            "kind", t("word.kind"), help=t("manager.discovery.releases.kind.help"),
            **grid_module.choice_filter([{"value": listing, "label": t(word)}
                                         for listing, word in kind_words.items()])),
        grid_module.column("version", t("word.version"),
                           help=t("manager.discovery.releases.version.help")),
        grid_module.column("authors", t("manager.discovery.ask.group.author"), 200,
                           help=t("manager.discovery.releases.authors.help")),
        grid_module.column(
            "added", t("manager.discovery.ask.added"),
            help=t("manager.discovery.releases.added.help"),
            **_ADDED_SAID),
        grid_module.column(
            "held", t("manager.view.have"), help=t("manager.discovery.releases.held.help"),
            **{":cellClass": "params => params.value ? 'manager-have' : ''",
               **grid_module.choice_filter([{"value": HAVE, "label": t("manager.view.have")}])}),
        grid_module.column("format", t("manager.discovery.ask.format_pick"),
                           help=t("manager.discovery.releases.format.help")),
        grid_module.column("features", t("manager.games.features"), 200,
                           help=t("manager.discovery.releases.features.help")),
        grid_module.column(
            "mod", t("manager.games.mod"), help=t("manager.discovery.releases.mod.help"),
            **grid_module.choice_filter([{"value": MOD, "label": t("manager.games.mod")}])),
    ]


_FIELDS = ("name", "kind", "version", "authors", "added", "held", "format", "features", "mod")
_SHOWN_FIELDS = ("name", "kind", "version", "authors", "added", "held")

VIEWS: dict[str, list[str] | views.Preset] = {
    "manager.view.everything": views.Preset(
        columns=_SHOWN_FIELDS, sort=_NEWEST,
        help=t("manager.view.releases_everything.help")),
}


def rows(found: Mapping[str, Sequence[tuple[str, Mapping[str, Any]]]],
         games: Mapping[str, Mapping[str, Any]], people: Sequence[Mapping[str, Any]],
         *, counted: bool) -> list[dict[str, Any]]:
    """One grid row for each release in `found` (`vps_question.games_found`'s answer).

    `games` is the Games tab's rows by id. A release is Have only once the library has been
    counted, since before that nothing is known to be held."""
    names = [str(one["name"]) for one in people]
    now = datetime.now(UTC)
    said_on: dict[Any, str] = {}
    out = []
    for game_id, fitting in found.items():
        game = games.get(game_id)
        if game is None:
            continue
        find = " ".join(filter(None, [game.get("game_type"), *(game.get("themes") or ())]))
        for listing, release in fitting:
            added = str(release.get("added") or "")
            said = _said(added, now, said_on)
            out.append({
                "id": f"{game_id}:{release['id']}",
                "game_id": game_id,
                "name": game["name"],
                "said": game["said"],
                "find": find,
                thumbnails.FIELD: game.get(thumbnails.FIELD) or "",
                "kind": listing,
                "version": release.get("version") or "",
                "authors": ", ".join(names[at] for at in release.get("by") or ()),
                "added": added,
                "added_said": said,
                "held": HAVE if counted and release.get("held") else "",
                "format": release.get("format") or "",
                "features": ", ".join(release.get("features") or ()),
                "mod": MOD if release.get("mod") else "",
            })
    return out


def _said(added: str, now: datetime, said_on: dict[Any, str]) -> str:
    """How long ago `added` was. Past the recent window the words are the local date, so
    stamps on one date share a call: `when.ago` reads the settings on each, which across
    every release is seconds."""
    at = when.parsed(added)
    key = added if at is None or now - at < when.RECENT else at.astimezone().date()
    if key not in said_on:
        said_on[key] = when.ago(added, now) if added else ""
    return said_on[key]


def summary(count: int) -> str:
    return t("manager.discovery.releases.summary", count=count)


async def fill(
        body: Any, *, library: Library, state: dict[str, Any], games: list[dict[str, Any]],
        people: list[dict[str, Any]], releases: dict[str, Any], kind_words: dict[str, str],
        counted: bool, compared: str, address: str,
        on_select: Callable[[Any], Any], reread: Callable[[], Awaitable[None]],
        count_again: Callable[[], Awaitable[None]],
        acts: Callable[[list[dict[str, Any]], Callable[[], Awaitable[None]], bool],
                       list[panel.Verb]]) -> None:
    """Draw the tab into `body`. `games`, `people` and `releases` are the Games tab's, and
    `reread` puts fresh ones in them where they stand."""
    # Imported here: `games` imports modules that import this one.
    from manager.library.games import view_control

    by_id = {row["id"]: row for row in games}
    vocabulary = vps_question.vocabulary(releases)
    grid_columns = grid_module.with_art(columns(kind_words), library.thumbnail_look())
    shown: dict[str, Any] = {"rows": {}, "count": 0, "selected": 0}
    # The grid resolves a ticked id against this list, so it is kept as the rows drawn.
    held: list[dict[str, Any]] = []

    async def narrow(question: dict[str, Any]) -> None:
        found = vps_question.games_found(question, people, games, releases)
        built = rows(found, by_id, people, counted=counted)
        held[:] = built
        shown["rows"] = {row["id"]: row for row in built}
        shown["count"] = len(built)
        draw_chips()
        table.run_grid_method("setGridOption", "rowData", built)
        count.text = counted_text()

    async def change(question: dict[str, Any]) -> None:
        asking.value = question
        await narrow(question)
        if asking.changed is not None:
            await asking.changed()

    asking = views.Asking(narrow, state.pop("arriving", None))

    @on_page
    async def choose(group: str, one: dict[str, Any]) -> None:
        if group == vps_find.GAME:
            await on_select(by_id.get(str(one["id"])))
        else:
            await change(discovery_ask.with_value(
                asking.value, discovery_ask.SUBJECT_KEY[group], str(one["name"])))

    with body:
        with ui.row().classes(
                "w-full items-center gap-2 px-3 py-2 mb-2 shrink-0 manager-panel manager-grid-bar"):
            bar = panel.grid_bar()
            wire_views, _picker, showing, describe = view_control(
                library, SCOPE, VIEWS, list(_FIELDS), grid_columns, bar=bar,
                art_in_lists=True, asking=asking)
            describe()
            with bar.top, panel.bar_end():
                with ui.element("div").classes("manager-suggest-anchor"):
                    search = panel.search(t("manager.discovery.search"))
                    discovery_ask.Suggest(
                        search, lambda text: vps_find.find(text, people, games), choose)
            with bar.bottom, panel.bar_end():
                count = ui.label(summary(0)).classes("text-xs manager-label")
                show_selection = panel.selection_menu(
                    t("manager.discovery.actions_selected"), lambda: picked(),
                    lambda chosen: acts(chosen, after,
                                        bool(grid_module.hidden_count(table))),
                    lambda: table.run_grid_method("deselectAll"))
                if compared:
                    ui.label(compared).classes("text-xs manager-label")
                panel.refresh(lambda: count_again(), t("manager.discovery.compare_again"))

        chips_row = ui.row().classes("w-full items-center gap-2 px-3 pb-2 shrink-0")

        def draw_chips() -> None:
            chips_row.clear()
            with chips_row:
                discovery_ask.chips(asking.value, kind_words, change)
                add, more = panel.menu_label_button(t("manager.discovery.ask.add"), verbs.FILTER)
                add.classes("manager-ask-add")
                more.on("before-show", lambda: discovery_ask.add_menu(
                    more, asking.value, kind_words, list(kind_words), people, vocabulary,
                    change, counted=counted))

        draw_chips()
        if not games:
            panel.facts(ui, [panel.intro(t("manager.discovery.empty"))])
        if not counted:
            with ui.row().classes("w-full items-center gap-2 px-3 pb-2 shrink-0"):
                ui.label(t("manager.discovery.not_compared")).classes("text-xs manager-label")
                panel.link(t("manager.discovery.compare_now"), to=address,
                           on_click=lambda: count_again())()

        def counted_text() -> str:
            if shown["selected"]:
                return grid_module.selection_said(
                    table, shown["selected"],
                    t("manager.discovery.selected", picked=shown["selected"],
                      shown=shown["count"]))
            return summary(shown["count"])

        def on_selected(chosen_rows: list[dict[str, Any]]) -> None:
            shown["selected"] = len(chosen_rows)
            show_selection(bool(chosen_rows))
            count.text = counted_text()

        def games_of(release_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
            """The games the releases are for, each once, in the order first met."""
            ids = dict.fromkeys(str(one.get("game_id")) for one in release_rows)
            return [by_id[game_id] for game_id in ids if game_id in by_id]

        def fill_menu(row: dict | None) -> None:
            one = shown["rows"].get(str((row or {}).get("id") or ""))
            if one is None:
                menu.clear()
                return
            on = grid_module.menu_rows(table, one)
            chosen = games_of(on)
            panel.verb_menu(menu, one["name"] if len(on) == 1
                            else t("manager.discovery.selected_n", count=len(chosen)),
                            panel.for_selection(
                                acts(chosen, after,
                                     len(on) > 1 and bool(grid_module.hidden_count(table))),
                                len(chosen)))

        async def on_header_context(col_id: str | None) -> None:
            await grid_module.header_menu(menu, table, grid_columns, col_id)

        with ui.element("div").classes("w-full grow min-h-0 flex flex-col"):
            table: ui.aggrid = grid_module.build(grid_columns, held, SCOPE,
                                                 on_select_rows=on_selected,
                                                 on_context=fill_menu,
                                                 on_header_context=on_header_context,
                                                 view_of=showing)
            menu: ui.context_menu = ui.context_menu()
        grid_module.on_row_focus(
            SCOPE, lambda event: on_select(
                by_id.get(str((shown["rows"].get(grid_module.focused_row(event)) or {})
                              .get("game_id") or ""))))
        search.on_value_change(
            lambda: table.run_grid_method("setGridOption", "quickFilterText",
                                          search.value or ""))
        table.on("modelUpdated", lambda: _counted_in_view())
        wire_views(table)

    def picked() -> list[dict[str, Any]]:
        return games_of([shown["rows"][str(r["id"])] for r in grid_module.selection(table)
                         if str(r.get("id")) in shown["rows"]])

    async def _counted_in_view() -> None:
        shown["count"] = int(await ui.run_javascript(_SHOWN % table.id) or 0)
        count.text = counted_text()

    @on_page
    async def after() -> None:
        """The rows read again from the library, the grid and the pane put right."""
        await reread()
        by_id.clear()
        by_id.update({row["id"]: row for row in games})
        vocabulary.update(vps_question.vocabulary(releases))
        await narrow(asking.value)
        chosen = state.get("entry")
        if chosen and state.get("workbench"):
            await on_select(by_id.get(chosen))

    state["redraw_discovery"] = after
    state["count_discovery"] = count_again
