"""Discovery: every game the catalog lists, against what the library holds.

One row per catalog entry. A kind VPS lists for the entry reads Have where the library
holds one and Missing where it does not; a kind VPS does not list is blank, and so is
every cell while the library has never been counted. A game that is not in the library
is Missing on every kind its entry lists.

The side pane is `discovery_pane`: a Game section and a section per kind the entry lists.
Kinds the library does not keep are not drawn.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Collection
from typing import Any

from nicegui import ui

from common import icons
from common.failures import why
from common.i18n import t
from common.online import sites, vps_find, vps_formats, vps_kinds, vps_question
from manager.kit import (
    busy,
    confirm,
    deeplink,
    game_tables,
    offload,
    panel,
    thumbnails,
    verbs,
    views,
    when,
)
from manager.kit import grid as grid_module
from manager.kit.data import Library
from manager.kit.on_page import on_page
from manager.library import (
    discovery_ask,
    discovery_get,
    discovery_releases,
    import_dialog,
)

logger = logging.getLogger("vpinfe.manager.library.discovery")

SCOPE = "discovery"
GAMES_ADDRESS = "/manager?" + deeplink.query({"view": "games"})
OWN_ADDRESS = "/manager?" + deeplink.query({"view": "discovery"})

BROWSE = "browse"
RELEASES = "releases"

HAVE = "have"
MISSING = "missing"
BLANK = "blank"
YES = "yes"
NO = "no"

# VPS's own key for the kind, the field the row carries it in, and the word it is called.
KINDS: tuple[tuple[str, str, str], ...] = (
    ("tableFiles", "kind_table", "word.table"),
    ("b2sFiles", "kind_backglass", "asset.kind.backglass.label"),
    ("romFiles", "kind_rom", "asset.kind.rom.label"),
    ("pupPackFiles", "kind_pup_pack", "asset.kind.pup_pack.label"),
    ("altColorFiles", "kind_color", "manager.discovery.color_kind"),
    ("altSoundFiles", "kind_altsound", "asset.kind.altsound.label"),
    ("povFiles", "kind_pov", "asset.kind.pov.label"),
    ("ruleFiles", "kind_rules", "guide.kind.rule_sheet.label"),
    ("wheelArtFiles", "kind_wheel", "media.kind.wheel.label"),
    ("topperFiles", "kind_topper", "media.kind.topper.label"),
)

_POLLS = 600
_POLL_S = 1.0


def _cell_class() -> str:
    return (f"params => params.value === '{HAVE}' ? 'manager-have'"
            f" : params.value === '{MISSING}' ? 'manager-lack' : ''")


def _yes_no() -> list[dict[str, Any]]:
    return [{"value": YES, "label": t("word.yes")}, {"value": NO, "label": t("word.no")}]


def _kind_column(listed_as: str, field: str, word: str) -> dict[str, Any]:
    label = t(word)
    options: dict[str, Any] = {
        ":cellClass": _cell_class(),
        **grid_module.choice_filter([{"value": HAVE, "label": t("manager.view.have")},
                                     {"value": MISSING, "label": t("manager.view.missing")}])}
    return grid_module.column(field, label,
                              help=t("manager.discovery.kind.help", kind=label), **options)


CATALOG_FACET_CEILING = 300

COLUMNS = [
    grid_module.identifier("name", t("word.game"), 260, pinned="left",
                           subtitle="said", picture=thumbnails.FIELD, glyph=icons.GAMES,
                           help=t("manager.discovery.name.help"),
                           **{":getQuickFilterText":
                              "params => [params.data.name, params.data.said, "
                              "params.data.game_type, ...(params.data.themes || [])]"
                              ".filter(Boolean).join(' ')"}),
    grid_module.column("in_library", t("manager.discovery.in_library"),
                       help=t("manager.discovery.in_library.help"),
                       **grid_module.choice_filter(_yes_no())),
    *(_kind_column(*kind) for kind in KINDS),
    grid_module.column("gap", t("manager.discovery.gaps"),
                       help=t("manager.discovery.gaps.help"),
                       **{":cellClass": _cell_class(),
                          **grid_module.choice_filter(
                              [{"value": MISSING, "label": t("manager.view.missing")}])}),
    grid_module.column("manufacturer", t("word.manufacturer"), help=t("help.who_made_it")),
    grid_module.year_column("year", t("word.year"), help=t("help.year_released")),
    grid_module.column("game_type", t("manager.games.type"),
                       help=t("manager.games.type.help")),
    grid_module.list_column("themes", t("manager.games.game_themes"), 200,
                            help=t("manager.games.themes.help")),
]

_KIND_FIELDS = [field for _listed, field, _word in KINDS]
# The game's own facts are on the Game cell's second line and in the pane. They stay in the
# column picker for sorting and filtering, and no view turns them on.
_PICKED = ("manufacturer", "year", "game_type", "themes")
_ALL = [definition["field"] for definition in COLUMNS]
_BY_NAME = ({"colId": "name", "sort": "asc", "sortIndex": 0},)

VIEWS: dict[str, list[str] | views.Preset] = {
    "manager.view.everything": views.Preset(
        columns=tuple(field for field in _ALL if field not in _PICKED), sort=_BY_NAME,
        help=t("manager.view.discovery_everything.help")),
    "manager.view.not_held": views.Preset(
        columns=("name", "in_library", *_KIND_FIELDS), sort=_BY_NAME,
        filters={"in_library": {"values": [NO]}},
        help=t("manager.view.not_held.help")),
    "manager.view.with_gaps": views.Preset(
        columns=("name", *_KIND_FIELDS, "gap"), sort=_BY_NAME,
        filters={"in_library": {"values": [YES]}, "gap": {"values": [MISSING]}},
        help=t("manager.view.with_gaps.help")),
}


def _state(listed: bool, counted: bool, in_library: bool, held: bool) -> str:
    if not listed or not counted:
        return ""
    return HAVE if in_library and held else MISSING


def rows(found: dict[str, Any], kept: Collection[str] | None = None) -> list[dict[str, Any]]:
    """One grid row per named catalog entry. `found` is what `GET /library/discovery` answers.

    `kept` is the VPS kinds the library collects; a kind outside it is blank on every row
    and counts toward no gap. None keeps them all."""
    counted = bool(found.get("counted"))
    out = []
    for entry in found.get("rows") or []:
        if not (entry.get("name") or "").strip():
            continue
        listed = set(entry.get("listed") or [])
        held = set(entry.get("held") or [])
        in_library = bool(entry.get("in_library"))
        row: dict[str, Any] = {
            "id": entry["vps_id"],
            "name": entry.get("name") or "",
            "manufacturer": entry.get("manufacturer") or "",
            "year": game_tables.year_of(entry.get("year")),
            "game_type": entry.get("type") or "",
            thumbnails.FIELD: entry.get("img_url") or "",
            "themes": list(entry.get("themes") or []),
            "url": entry.get("url") or "",
            "in_library": "" if not counted else (YES if in_library else NO),
            "is_in_library": in_library and counted,
            "listed": sorted(listed),
        }
        states = []
        for listed_as, field, _word in KINDS:
            row[field] = _state(listed_as in listed and (kept is None or listed_as in kept),
                                counted, in_library, listed_as in held)
            states.append(row[field])
        row["said"] = game_tables.made(row)
        row["gap"] = MISSING if MISSING in states else ""
        out.append(row)
    return out


def releases_of(found: dict[str, Any], kept: list[str]) -> dict[str, Any]:
    """Each game's releases by VPS id, of the kinds the library collects."""
    out = {}
    for entry in found.get("rows") or []:
        mine = {kind: one for kind, one in (entry.get("releases") or {}).items() if kind in kept}
        if mine:
            out[str(entry["vps_id"])] = mine
    return out


def row_of(library: Library, vps_id: str) -> dict[str, Any] | None:
    found = rows(library.catalog(), kept_listings(library))
    return next((one for one in found if one["id"] == vps_id), None)


def summary(shown: list[dict[str, Any]], counted: bool) -> str:
    if not counted:
        return t("manager.discovery.summary", count=len(shown))
    return t("manager.discovery.summary_compared", count=len(shown),
             held=sum(1 for one in shown if one["is_in_library"]))


def unmatched_games(library: Library) -> int:
    return sum(1 for game in library.game_rows() if game.get("vps_unmatched"))


def tab_of(state: dict[str, Any]) -> str:
    """The tab chosen, and Browse where the address named a subject."""
    if state.get("subject"):
        return BROWSE
    return RELEASES if state.get("discovery_tab") == RELEASES else BROWSE


def build(library: Library, state: dict[str, Any], on_select: Callable[[Any], Any],
          rerender: Callable[[], None]) -> None:
    tab = tab_of(state)

    def switch(event: Any) -> None:
        state["discovery_tab"] = event.value
        state["subject"] = None
        deeplink.sync(state)
        rerender()

    with ui.row().classes("w-full items-center px-3 pt-2 pb-1 shrink-0"):
        panel.segmented({BROWSE: t("manager.discovery.tab.games"),
                         RELEASES: t("manager.discovery.tab.releases")}, tab, switch)
    body = ui.column().classes("w-full grow min-h-0 gap-0")
    fill = _fill_releases if tab == RELEASES else _fill
    busy.fill(body, lambda: fill(library, body, state, on_select, rerender))


async def _fill_releases(library: Library, body: Any, state: dict[str, Any],
                         on_select: Callable[[Any], Any], rerender: Callable[[], None]) -> None:
    try:
        found = await _read(library)
    except Exception as exc:  # noqa: BLE001 - this page says why, never 500s
        with body:
            panel.facts(ui, [panel.intro(t("manager.discovery.read_failed"), hint=why(exc))])
        return
    kept_now = kept_listings(library)
    built = rows(found, kept_now)
    people = list(found.get("people") or [])
    releases = releases_of(found, kept_now)

    async def reread() -> None:
        if not library.has_catalog():
            await offload.io(library.load_catalog)
        again = library.catalog()
        built[:] = rows(again, kept_listings(library))
        people[:] = again.get("people") or []
        releases.clear()
        releases.update(releases_of(again, kept_listings(library)))

    @on_page
    async def count_again() -> None:
        if not await recount(library, state):
            return
        library.forget_catalog()
        rerender()

    async def open_author(name: str) -> None:
        known = vps_question.person_named(name, people)
        state["subject"] = {"type": vps_find.AUTHOR, "name": str(known["name"]) if known else name}
        state["arriving"] = None
        deeplink.sync(state)
        rerender()

    state["open_author"] = open_author
    await discovery_releases.fill(
        body, library=library, state=state, games=built, people=people, releases=releases,
        kind_words={listed_as: word for listed_as, _field, word in KINDS if listed_as in kept_now},
        counted=bool(found.get("counted")), compared=_counted_text(found), address=OWN_ADDRESS,
        on_select=on_select, reread=reread, count_again=count_again,
        acts=lambda chosen, after, check: acts(library, chosen, after, check=check))


async def _read(library: Library) -> dict[str, Any]:
    if library.has_catalog():
        return library.catalog()
    return await offload.io(library.load_catalog)


def _unmatched_line(count: int, show: Callable[[], Awaitable[Any]] | None) -> None:
    with ui.row().classes("w-full items-center gap-2 px-3 pb-2 shrink-0"):
        text = t("manager.discovery.unmatched", count=count)
        if show is None:
            ui.label(text).classes("text-xs manager-label")
        else:
            panel.link(text, to=GAMES_ADDRESS, on_click=show)()


def _never_counted_line(count_now: Callable[[], Awaitable[Any]]) -> None:
    with ui.row().classes("w-full items-center gap-2 px-3 pb-2 shrink-0"):
        ui.label(t("manager.discovery.not_compared")).classes("text-xs manager-label")
        panel.link(t("manager.discovery.compare_now"), to=OWN_ADDRESS, on_click=count_now)()


def grid_columns(library: Library, built: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The columns the grid declares: a kind column only for a kind the library collects."""
    off = {field for listed_as, field, _word in KINDS if not kept(library, listed_as)}
    return grid_module.with_art(
        grid_module.with_derived_facets([one for one in COLUMNS if one["field"] not in off],
                                        built, CATALOG_FACET_CEILING),
        library.thumbnail_look())


async def _fill(library: Library, body: Any, state: dict[str, Any],
                on_select: Callable[[Any], Any], rerender: Callable[[], None]) -> None:
    # Imported here: `games` imports modules that import this one.
    from manager.library.games import view_control

    try:
        found = await _read(library)
    except Exception as exc:  # noqa: BLE001 - this page says why, never 500s
        with body:
            panel.facts(ui, [panel.intro(t("manager.discovery.read_failed"), hint=why(exc))])
        return
    counted = bool(found.get("counted"))
    built = rows(found, kept_listings(library))
    people = list(found.get("people") or [])
    kept_now = kept_listings(library)
    releases = releases_of(found, kept_now)
    kind_words = {listed_as: word for listed_as, _field, word in KINDS if listed_as in kept_now}

    async def go_to(subject: dict[str, str] | None, question: dict[str, Any] | None = None) -> None:
        """Open a subject's page, or leave it - for the grid, with `question` asked."""
        if subject and subject["type"] == vps_find.AUTHOR:
            known = vps_question.person_named(subject["name"], people)
            subject = {**subject, "name": str(known["name"]) if known else subject["name"]}
        state["subject"] = subject
        state["arriving"] = question
        deeplink.sync(state)
        rerender()

    state["open_author"] = lambda name: go_to({"type": vps_find.AUTHOR, "name": name})
    if state.get("subject"):
        subject = state["subject"]
        known = vps_question.person_named(subject["name"], people) \
            if subject["type"] == vps_find.AUTHOR else None
        renamed = known is not None and known["name"] != subject["name"]
        if known is not None and renamed:
            state["subject"] = subject = {**subject, "name": str(known["name"])}

        @on_page
        async def redraw_subject() -> None:
            rerender()

        state["redraw_discovery"] = redraw_subject
        state.pop("count_discovery", None)
        with body:
            if renamed:
                deeplink.sync(state)
            discovery_ask.page(
                subject=subject, state=state, people=people, rows=built,
                releases=releases, kinds=kind_words, address=OWN_ADDRESS, open_game=on_select,
                leave=lambda: go_to(None), see_all=lambda question: go_to(None, question))
        return
    columns = grid_columns(library, built)
    by_id = {row["id"]: row for row in built}
    on_screen: dict[str, Any] = {"ids": [row["id"] for row in built], "selected": 0}
    unmatched = await offload.io(unmatched_games, library)
    show_unmatched = state.get("show_unmatched")
    fits: dict[str, Any] = {"games": None}
    vocabulary = vps_question.vocabulary(releases)

    def narrowed() -> list[dict[str, Any]]:
        return built if fits["games"] is None else [
            row for row in built if row["id"] in fits["games"]]

    async def narrow(question: dict[str, Any]) -> None:
        fits["games"] = (vps_question.games_fitting(question, people, built, releases)
                         if question else None)
        draw_chips()
        table.run_grid_method("setGridOption", "rowData", narrowed())

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
            await go_to({"type": group, "name": str(one["name"])})

    with body:
        with ui.row().classes(
                "w-full items-center gap-2 px-3 py-2 mb-2 shrink-0 manager-panel manager-grid-bar"):
            bar = panel.grid_bar()
            wire_views, _picker, showing, describe = view_control(
                library, SCOPE, VIEWS, [one["field"] for one in columns], columns, bar=bar,
                art_in_lists=True, asking=asking)
            describe()
            with bar.top, panel.bar_end():
                with ui.element("div").classes("manager-suggest-anchor"):
                    search = panel.search(t("manager.discovery.search"))
                    discovery_ask.Suggest(
                        search, lambda text: vps_find.find(text, people, built), choose)
            with bar.bottom, panel.bar_end():
                count = ui.label(summary(built, counted)).classes("text-xs manager-label")
                show_selection = panel.selection_menu(
                    t("manager.discovery.actions_selected"), lambda: picked(),
                    lambda chosen: acts(library, chosen, after,
                                        check=bool(grid_module.hidden_count(table))),
                    lambda: table.run_grid_method("deselectAll"))
                ui.label(_counted_text(found)).classes("text-xs manager-label")
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
        if not built:
            panel.facts(ui, [panel.intro(t("manager.discovery.empty"))])
        if unmatched:
            _unmatched_line(unmatched, show_unmatched if callable(show_unmatched) else None)
        if not counted:
            _never_counted_line(lambda: count_again())

        def counted_text() -> str:
            if on_screen["selected"]:
                return grid_module.selection_said(
                    table, on_screen["selected"],
                    t("manager.discovery.selected", picked=on_screen["selected"],
                      shown=len(on_screen["ids"])))
            return summary([by_id[one] for one in on_screen["ids"] if one in by_id], counted)

        def on_selected(chosen_rows: list[dict[str, Any]]) -> None:
            on_screen["selected"] = len(chosen_rows)
            show_selection(bool(chosen_rows))
            count.text = counted_text()

        def fill_menu(row: dict | None) -> None:
            one = by_id.get(str((row or {}).get("id") or ""))
            if one is None:
                menu.clear()
                return
            on = grid_module.menu_rows(table, one)
            panel.verb_menu(menu, one["name"] if len(on) == 1
                            else t("manager.discovery.selected_n", count=len(on)),
                            panel.for_selection(
                                acts(library, on, after,
                                     check=len(on) > 1 and bool(grid_module.hidden_count(table))),
                                len(on)))

        async def on_header_context(col_id: str | None) -> None:
            await grid_module.header_menu(menu, table, columns, col_id)

        with ui.element("div").classes("w-full grow min-h-0 flex flex-col"):
            table: ui.aggrid = grid_module.build(columns, built, SCOPE,
                                                 on_select_rows=on_selected,
                                                 on_context=fill_menu,
                                                 on_header_context=on_header_context,
                                                 view_of=showing)
            menu: ui.context_menu = ui.context_menu()
        grid_module.on_row_focus(
            SCOPE, lambda event: on_select(by_id.get(grid_module.focused_row(event))))
        search.on_value_change(
            lambda: table.run_grid_method("setGridOption", "quickFilterText",
                                          search.value or ""))
        table.on("modelUpdated", lambda: _counted_in_view())
        wire_views(table)

    def picked() -> list[dict[str, Any]]:
        return [by_id[str(r["id"])] for r in grid_module.selection(table)
                if str(r.get("id")) in by_id]

    async def _counted_in_view() -> None:
        drawn = await ui.run_javascript(_SHOWN % table.id) or []
        on_screen["ids"] = [str(one) for one in drawn]
        count.text = counted_text()

    @on_page
    async def after() -> None:
        """The rows read again from the library, the grid and the pane put right."""
        if not library.has_catalog():
            await offload.io(library.load_catalog)
        again = library.catalog()
        fresh = rows(again, kept_listings(library))
        built[:] = fresh
        by_id.clear()
        by_id.update({row["id"]: row for row in fresh})
        people[:] = again.get("people") or []
        releases.clear()
        releases.update(releases_of(again, kept_listings(library)))
        vocabulary.update(vps_question.vocabulary(releases))
        await narrow(asking.value)
        chosen = state.get("entry")
        if chosen and state.get("workbench"):
            await on_select(by_id.get(chosen))

    @on_page
    async def settled(entry_id: str) -> bool:
        """One entry's row read again and put right where it stands, and the open pane with
        it where that is the entry. False where the pane has to be drawn again."""
        if not library.has_catalog():
            await offload.io(library.load_catalog)
        row = next((one for one in rows(library.catalog(), kept_listings(library))
                    if one["id"] == entry_id), None)
        if row is None or entry_id not in by_id:
            return False
        if state.get("entry") == entry_id:
            pane = state.get("settle_pane_discovery")
            if not state.get("workbench") or not callable(pane) or not await pane(row):
                return False
        grid_module.transact(table, built, {"update": [row]}, by_id)
        count.text = counted_text()
        return True

    @on_page
    async def count_again() -> None:
        """Count the library against the catalog, and read the answer when it is in."""
        if not await recount(library, state):
            return
        library.forget_catalog()
        rerender()

    state["redraw_discovery"] = after
    state["settle_discovery"] = settled
    state["count_discovery"] = count_again


_SHOWN = """(() => {
  const ids = [];
  getElement(%d).api.forEachNodeAfterFilterAndSort(node => ids.push(node.data.id));
  return ids;
})()"""


def _counted_text(found: dict[str, Any]) -> str:
    if not found.get("counted"):
        return ""
    return t("manager.discovery.compared", when=when.ago(found["counted"], inline=True))


@on_page
async def recount(library: Library, state: dict[str, Any]) -> bool:
    """Start the count and wait for it. False where it failed, which is said on screen."""
    try:
        job = await offload.io(library.recount_catalog)
    except Exception as exc:  # noqa: BLE001
        ui.notify(t("manager.discovery.compare_failed"), caption=why(exc), type="negative")
        return False
    watch = state.get("watch_jobs")
    if callable(watch):
        watch()
    for _ in range(_POLLS):
        await asyncio.sleep(_POLL_S)
        try:
            found = await offload.io(library.job, str(job.get("id") or ""))
        except Exception:  # noqa: BLE001 - the footer line still reports it
            return False
        if found.get("state") == "running":
            continue
        if found.get("state") == "failed":
            ui.notify(t("manager.discovery.compare_failed"),
                      caption=str(found.get("error") or ""), type="negative")
            return False
        return True
    return False


def acts(library: Library, rows_on: list[dict[str, Any]],
         after: Callable[[], Awaitable[None]], *, check: bool = False) -> list[panel.Verb]:
    """What can be done to the entries a menu is open on. `check` is where the selection
    holds rows a search, a filter or a view leaves out, which `add` asks about first.

    Add waits for a count: before one, every entry reads as not in the library."""
    absent = [one for one in rows_on if one["in_library"] == NO]
    uncounted = any(not one["in_library"] for one in rows_on)
    hint = "" if absent else t(
        "manager.discovery.compare_first" if uncounted else "manager.discovery.already_in")
    return [panel.Verb(
        t("manager.discovery.add"),
        (lambda: add(library, absent, after, check=check)) if absent else None,
        hint=hint, icon=verbs.ADD)]


def pane_acts(library: Library, row: dict[str, Any], game_id: str,
              after: Callable[[], Awaitable[None]]) -> list[panel.Verb]:
    """The pane's own menu: `acts` for the entry, then the two places it can be opened.

    Open in Games is dimmed with its reason while no game holds the entry, which is also
    every entry before the first comparison."""
    out = acts(library, [row], after)
    opened = t("manager.discovery.to_games")
    if game_id:
        out.append(panel.Verb(
            opened, to="/manager?" + deeplink.query({"view": "games", "game": game_id})))
    else:
        hint = {"": t("manager.discovery.compare_first"),
                NO: t("manager.discovery.absent")}.get(row["in_library"], "")
        out.append(panel.Verb(opened, hint=hint))
    if row["url"]:
        out.append(panel.Verb(t("manager.discovery.picture_open"), to=row["url"]))
    return out


@on_page
async def add(library: Library, entries: list[dict[str, Any]],
              after: Callable[[], Awaitable[None]], *, check: bool = False) -> None:
    """Make a game with no tables from each entry, in the place new games go."""
    if len(entries) > 1 or check:
        if not await confirm.ask(
                t("manager.discovery.add_many", count=len(entries)),
                detail=t("manager.discovery.add_detail"),
                lines=[one["name"] for one in entries], confirm=t("manager.discovery.add"),
                icon=verbs.ADD, danger=False):
            return
    where = await import_dialog.ask_where(library)
    if where is None:
        return
    made = 0
    for entry in entries:
        try:
            await offload.io(library.add_game_from_vps, entry["id"], where)
        except Exception as exc:  # noqa: BLE001 - one refusal does not end the rest
            logger.warning("manager: could not add %s", entry["id"], exc_info=True)
            ui.notify(t("manager.discovery.add_failed", name=entry["name"]),
                      caption=why(exc), type="negative")
            continue
        made += 1
    if made:
        ui.notify(t("manager.discovery.added", count=made), type="positive")
        await after()


_TYPE_WORDS = {"SS": "manager.discovery.type.ss", "EM": "manager.discovery.type.em",
               "PM": "manager.discovery.type.pm"}


def type_word(code: str) -> str:
    """VPS's two letters spelled out, or as given for a code this does not know."""
    key = _TYPE_WORDS.get(code.strip().upper())
    return t(key) if key else code


def kept_ours(library: Library, listed_as: str) -> set[str]:
    """Which of our kinds behind a VPS kind this library collects. The table has no switch."""
    kind = vps_kinds.BY_LISTING.get(listed_as)
    if kind is None:
        return {listed_as}
    return set(kind.ours) & library.kept_kinds()[kind.held_in]


def kept(library: Library, listed_as: str) -> bool:
    return bool(kept_ours(library, listed_as))


def kept_listings(library: Library) -> list[str]:
    """The VPS kinds this library collects, in the order the grid draws them."""
    return [listed_as for listed_as, _field, _word in KINDS if kept(library, listed_as)]


async def owner_state(context: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
    """The game that holds this entry, and what it holds of it. ("", None) where none does
    or it cannot be read, which the pane answers from the row's own counts.

    Read once per drawing of the pane, whichever section asks first: both sections draw
    from the same answer."""
    if "owner" not in context:
        context["owner"] = asyncio.ensure_future(
            _read_owner(context["library"], context["discovery"]))
    return await context["owner"]


async def _read_owner(library: Library,
                      row: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
    if not row["is_in_library"]:
        return "", None
    try:
        owned, _other = await offload.io(library.owned, [row["id"]])
        game_id = str((owned.get(row["id"]) or {}).get("game_id") or "")
        if not game_id:
            return "", None
        return game_id, await offload.io(library.vps_held, game_id)
    except Exception:  # noqa: BLE001 - the pane still draws from the row
        logger.warning("manager: could not read what %s holds", row["id"], exc_info=True)
        return "", None


def _kind_state(held: dict[str, Any], listed_as: str) -> dict[str, Any]:
    return next((one for one in held.get("kinds") or [] if one.get("kind") == listed_as), {})


def held_of(held: dict[str, Any] | None, listed_as: str) -> list[dict[str, str]]:
    """The files the owning game holds of one VPS kind, each with the record it is tied to."""
    if held is None:
        return []
    if listed_as == "tableFiles":
        return list(held.get("tables") or [])
    return list(_kind_state(held, listed_as).get("files") or [])


def standing(library: Library, row: dict[str, Any],
             held: dict[str, Any] | None) -> dict[str, str]:
    """Have or Missing for each kept kind VPS lists. Empty where the library says nothing:
    the game is not in it, or it has never been counted."""
    if not row["is_in_library"]:
        return {}
    said: dict[str, str] = {}
    for listed_as, field, _word in KINDS:
        if listed_as not in row["listed"] or not kept(library, listed_as):
            continue
        if held is None:
            answer = row[field]
        else:
            has = held_of(held, listed_as) or _kind_state(held, listed_as).get("held")
            answer = HAVE if has else MISSING
        if answer:
            said[listed_as] = answer
    return said


def newest_first(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(records, key=lambda one: str(one.get("updated_at") or ""), reverse=True)


def what_it_is(record: dict[str, Any], *, features: bool) -> str:
    """That the file is a mod and of what, its features, and a format other than VPX."""
    facts = game_tables.release_facts(record, features=features)
    kept = str(record.get("format") or "").strip().upper()
    if kept and kept != "VPX":
        facts.append(vps_formats.name(kept))
    return game_tables.JOIN.join(facts)


def site_of(record: dict[str, Any]) -> tuple[str, str]:
    """The site the file's page is on, and the page: the first link VPS has not marked
    broken, or the first it has where all are. `("", "")` for a file with no link."""
    page = str(record.get("url") or "")
    return (sites.site_name(page), page) if page else ("", "")


def page_is_broken(record: dict[str, Any]) -> bool:
    """Whether VPS marks the page `site_of` gives as no longer working."""
    page = str(record.get("url") or "")
    return any(one.get("broken") for one in (record.get("urls") or []) if one.get("url") == page)


def told(record: dict[str, Any]) -> str:
    return " · ".join(part for part in (
        str(record.get("version") or ""),
        ", ".join(str(name) for name in (record.get("authors") or [])[:2])) if part)


# The VPS kinds that are art rather than files: they sit among the media, with the files
# a source holds of the same kind.
MEDIA_LISTINGS = {"wheelArtFiles": "wheel", "topperFiles": "topper", "ruleFiles": "rule_sheet"}


def media_bands(listed: list[tuple[str, str, str]],
                offers: Collection[str]) -> list[tuple[str, tuple[str, str, str]]]:
    """Each media kind with something to show, wheel and topper first, with the VPS kind
    behind it where VPS lists one."""
    bands: dict[str, tuple[str, str, str]] = {}
    for kind in listed:
        if kind[0] in MEDIA_LISTINGS:
            bands[MEDIA_LISTINGS[kind[0]]] = kind
    for media_kind in offers:
        bands.setdefault(media_kind, ("", "", f"media.kind.{media_kind}.label"))
    return sorted(bands.items(), key=lambda one: discovery_get.media_order(one[0]))


async def media_present(library: Library, game_id: str) -> dict[str, Any] | None:
    """What media the game has, by kind. None where the game is not in the library or it
    cannot be read, which marks nothing Missing."""
    if not game_id:
        return None
    try:
        return await offload.io(library.media_for, game_id, None)
    except Exception:  # noqa: BLE001 - the kinds still draw, unmarked
        logger.warning("manager: could not read the media %s has", game_id, exc_info=True)
        return None


def holds(held: dict[str, Any] | None, listed_as: str) -> bool:
    """Whether the owning game holds anything of one VPS kind."""
    if held is None:
        return False
    return bool(held_of(held, listed_as) or _kind_state(held, listed_as).get("held"))
