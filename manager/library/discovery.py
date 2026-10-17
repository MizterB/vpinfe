"""Discovery: every game the catalog lists, against what the library holds.

One row per catalog entry. A kind VPS lists for the entry reads Have where the library
holds one and Missing where it does not; a kind VPS does not list is blank, and so is
every cell while the library has never been counted. A game that is not in the library
is Missing on every kind its entry lists.

The side pane has a Game section (picture, standing, details) and a Files section (the
records VPS lists, grouped by what the library holds). Kinds the library does not keep
are not drawn in either.
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
from common.media.media_specs import media_family
from common.online import sites, vps_formats, vps_kinds
from manager.kit import (
    busy,
    candidates,
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
from manager.library import discovery_ext, discovery_get, import_dialog, mediasource, mediaview

logger = logging.getLogger("vpinfe.manager.library.discovery")

SCOPE = "discovery"
GAMES_ADDRESS = "/manager?" + deeplink.query({"view": "games"})
OWN_ADDRESS = "/manager?" + deeplink.query({"view": "discovery"})

HAVE = "have"
MISSING = "missing"
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


def build(library: Library, state: dict[str, Any], on_select: Callable[[Any], Any],
          rerender: Callable[[], None]) -> None:
    body = ui.column().classes("w-full grow min-h-0 gap-0")
    busy.fill(body, lambda: _fill(library, body, state, on_select, rerender))


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
    columns = grid_columns(library, built)
    by_id = {row["id"]: row for row in built}
    on_screen: dict[str, Any] = {"ids": [row["id"] for row in built], "selected": 0}
    unmatched = await offload.io(unmatched_games, library)
    show_unmatched = state.get("show_unmatched")

    with body:
        with ui.row().classes(
                "w-full items-center gap-2 px-3 py-2 mb-2 shrink-0 manager-panel manager-grid-bar"):
            bar = panel.grid_bar()
            wire_views, _picker, showing, describe = view_control(
                library, SCOPE, VIEWS, [one["field"] for one in columns], columns, bar=bar,
                art_in_lists=True)
            describe()
            with bar.top, panel.bar_end():
                search = panel.search(t("manager.discovery.search"))
            with bar.bottom, panel.bar_end():
                count = ui.label(summary(built, counted)).classes("text-xs manager-label")
                show_selection = panel.selection_menu(
                    t("manager.discovery.actions_selected"), lambda: picked(),
                    lambda chosen: acts(library, chosen, after,
                                        check=bool(grid_module.hidden_count(table))),
                    lambda: table.run_grid_method("deselectAll"))
                ui.label(_counted_text(found)).classes("text-xs manager-label")
                panel.refresh(lambda: count_again(), t("manager.discovery.compare_again"))

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
        fresh = rows(library.catalog(), kept_listings(library))
        built[:] = fresh
        by_id.clear()
        by_id.update({row["id"]: row for row in fresh})
        table.run_grid_method("setGridOption", "rowData", fresh)
        chosen = state.get("entry")
        if chosen and state.get("workbench"):
            await on_select(by_id.get(chosen))

    @on_page
    async def count_again() -> None:
        """Count the library against the catalog, and read the answer when it is in."""
        if not await recount(library, state):
            return
        library.forget_catalog()
        rerender()

    state["redraw_discovery"] = after
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


# A kind with more records than this shows this many, and the rest behind a row.
SHOWN_RECORDS = 5

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


def split_records(records: list[dict[str, Any]],
                  mine: set[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The newest few, and the rest. A record you hold is never in the rest: a check that
    cannot be seen says you hold nothing."""
    first = [one for index, one in enumerate(records)
             if index < SHOWN_RECORDS or str(one.get("vps_file_id") or "") in mine]
    return first, [one for one in records if one not in first]


def _picture(src: str, address: str, name: str) -> None:
    with ui.element("div").classes("manager-vps-picture") as plate:
        if src:
            ui.html(f'<img src="{src}" alt="" loading="lazy">')
        else:
            ui.label(t("manager.discovery.no_picture")).classes("manager-help")
        if address:
            # click.stop, or following the link would also enlarge the picture.
            with ui.element("div").classes("manager-vps-picture-open") \
                    .on("click.stop", js_handler="() => {}"):
                panel.link_out(t("manager.discovery.picture_open"), to=address)()
    if src:
        def enlarge() -> None:
            mediaview.open_image(src, name)

        plate.classes("manager-vps-picture--open").tooltip(t("word.enlarge"))
        plate.props("tabindex=0 role=button")
        plate.props["aria-label"] = t("word.enlarge")
        plate.on("click", enlarge).on("keydown.enter.self", enlarge) \
            .on("keydown.space.self.prevent", enlarge)


async def _count_again(state: dict[str, Any]) -> None:
    again = state.get("count_discovery")
    if callable(again):
        await again()


def _never_counted(state: dict[str, Any]) -> None:
    with ui.row().classes("items-center gap-2 w-full"):
        ui.label(t("manager.discovery.not_compared")).classes("manager-help")
        panel.link(t("manager.discovery.compare_now"), to=OWN_ADDRESS,
                   on_click=lambda: _count_again(state))()


async def game(context: dict[str, Any]) -> None:
    """The picture, whether the library has the game, and what VPS says it is."""
    row, library, state = context["discovery"], context["library"], context["state"]
    counted = bool(library.catalog().get("counted"))
    game_id, held = await owner_state(context)
    tray = discovery_get.tray_of(state, row["id"])
    listed = listed_kinds(context)
    follows = counted and bool(tray.offered) and bool(library.online_sources())
    if follows:
        version = await discovery_ext.version_of(library)
        await discovery_ext.refresh(context, tray, game_id, listed, draws_rows=False)

    def standing_line() -> None:
        if row["is_in_library"]:
            panel.state(t("manager.discovery.in_library"), "on")()
            if game_id:
                panel.link(t("manager.discovery.to_games"),
                           to="/manager?" + deeplink.query({"view": "games", "game": game_id}))()
        else:
            ui.label(t("manager.discovery.absent")).classes("grow")

    with ui.column().classes("gap-0 w-full min-w-0"):
        _picture(str(row[thumbnails.FIELD]), row["url"], row["name"])
        if not counted:
            _never_counted(state)
        else:
            discovery_get.status_row(
                tray, standing_line,
                discovery_ext.stopper(context, tray, lambda: game_id, listed))
            if follows:
                discovery_ext.watch(context, tray, game_id, listed, version, draws_rows=False)
            said = standing(library, row, held)
            if said:
                panel.line(t("manager.discovery.have_of",
                             have=sum(1 for one in said.values() if one == HAVE),
                             count=len(said)))
        panel.facts(ui, [
            (panel.HEADING, t("manager.workbench.details")),
            (t("word.manufacturer"), row["manufacturer"] or "-"),
            (t("word.year"), str(row["year"] or "-")),
            (t("manager.games.type"), type_word(row["game_type"]) or "-"),
            (t("manager.games.game_themes"), ", ".join(row["themes"]) or "-")])
        if counted:
            discovery_get.bar(context, tray, game_id, lambda: _add_this(context))


def listed_kinds(context: dict[str, Any]) -> list[str]:
    """VPS's keys for the kinds the entry lists and the library keeps."""
    row, library = context["discovery"], context["library"]
    return [kind[0] for kind in KINDS if kind[0] in row["listed"] and kept(library, kind[0])]


async def _add_this(context: dict[str, Any]) -> None:
    state = context["state"]
    await add(context["library"], [context["discovery"]], lambda: discovery_get.redraw(state))


def first_line(comment: Any) -> str:
    """The first line of VPS's comment that says anything."""
    for line in str(comment or "").splitlines():
        if line.strip():
            return line.strip()
    return ""


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


def other_links(record: dict[str, Any]) -> list[tuple[str, str, bool]]:
    """Each link besides the one the row leads with, as its site, address and whether VPS
    marks it broken. Two links on one site both stay: they are different pages."""
    page = str(record.get("url") or "")
    return [(sites.site_name(str(one.get("url") or "")), str(one["url"]), bool(one.get("broken")))
            for one in (record.get("urls") or []) if one.get("url") and one["url"] != page]


def _told(record: dict[str, Any]) -> str:
    return " · ".join(part for part in (
        str(record.get("version") or ""),
        ", ".join(str(name) for name in (record.get("authors") or [])[:2])) if part)


def _glyph(listed_as: str) -> str:
    return icons.TABLES if listed_as == "tableFiles" else ""


def _out(site: str, address: str, *, broken: bool = False, hint: str = "") -> None:
    """A link to `address` named for its site, struck through where VPS marks it dead."""
    draw = panel.link_out(site, to=address,
                          hint=t("manager.discovery.link_broken") if broken else hint)
    if not broken:
        draw()
        return
    with ui.element("span").classes("manager-link-broken"):
        draw()


def _thumb(src: str, label: str, pictures: list[str], glyph: str, *, family: str = "image",
           enlarge: Callable[[], None] | None = None) -> None:
    """The file's picture, which opens in the viewer, with the band's other pictures a
    press from it where it is one of them. A frame with nothing to open stays a frame, so
    the words line up."""
    with ui.element("div").classes("shrink-0") as box:
        candidates.thumb(src, glyph, t("manager.discovery.no_picture"), family)
    if not src:
        return
    if enlarge is None:
        if src not in pictures:
            return

        def enlarge() -> None:
            mediaview.open_pages(pictures, label, pictures.index(src) + 1)

    box.classes("manager-record-thumb").props("tabindex=0 role=button")
    box.props["aria-label"] = t("word.enlarge")
    box.on("click", enlarge).on("keydown.enter", enlarge).on("keydown.space.prevent", enlarge)


def _opens(head: ui.element, detail: ui.element, fill: Callable[[], None],
           lead: ui.element | None = None) -> None:
    """Make pressing `head` open `detail`, drawn by `fill` the first time. `lead` is the
    line of `head` that gives way to it."""
    drawn = False

    def toggle() -> None:
        nonlocal drawn
        if not drawn:
            drawn = True
            with detail:
                fill()
        opening = not detail.visible
        detail.set_visibility(opening)
        if lead is not None:
            lead.set_visibility(not opening)
        head.props["aria-expanded"] = "true" if opening else "false"
        head.update()

    head.props("tabindex=0 role=button aria-expanded=false")
    head.on("click", toggle).on("keydown.enter", toggle).on("keydown.space.prevent", toggle)


def _ways_out(page: str, broken: bool, entry_url: str, use_file: Callable[[], None]) -> None:
    with ui.row().classes("items-center gap-4"):
        if page:
            _out(t("manager.discovery.open_page"), page, broken=broken)
        if entry_url:
            panel.link_out(t("manager.discovery.vps_entry"), to=entry_url)()
        use_file()
    ui.label(t("manager.discovery.or_drop")).classes("manager-help")


def _detail(record: dict[str, Any], *, entry_url: str, features: bool,
            use_file: Callable[[], None], looked: Callable[[], None] | None = None) -> None:
    """What the row's lines cut short, and the ways out. `looked` draws what the page of
    the file a source offers says."""
    authors = [str(name) for name in (record.get("authors") or [])]
    if len(authors) > 2:
        ui.label(", ".join(authors)).classes("manager-help")
    unshown = [str(one) for one in (record.get("features") or []) if one != "MOD"]
    if not features and unshown:
        ui.label(", ".join(unshown)).classes("manager-help")
    comment = str(record.get("comment") or "").strip()
    if comment:
        ui.label(comment).classes("manager-help manager-record-comment")
    if looked is not None:
        looked()
    others = other_links(record)
    if others:
        with ui.row().classes("items-center gap-2"):
            ui.label(t("manager.discovery.also_on")).classes("manager-help")
            for site, address, broken in others:
                _out(site, address, broken=broken)
    _ways_out(site_of(record)[1], page_is_broken(record), entry_url, use_file)


def _record(context: dict[str, Any], record: dict[str, Any], *, mine: bool, features: bool,
            kind: tuple[str, str, str], pictures: list[str], entry_url: str,
            game_id: str, tray: discovery_get.Tray) -> None:
    listed_as, _field, word = kind
    offered = None if mine else context.get("hosted", {}).get(
        str(record.get("vps_file_id") or ""))
    told = _told(record)
    stamp = when.parsed(record.get("updated_at"))
    said = what_it_is(record, features=features)
    comment = first_line(record.get("comment"))
    site, page = site_of(record)
    ours, held_in = discovery_get.of_listing(listed_as)
    with ui.row().classes("items-start gap-2 w-full no-wrap manager-member-row "
                          "manager-record") as shell:
        if offered is not None:
            discovery_get.tick_cell(tray, offered.pick)
        else:
            discovery_get.mark(mine)
        if pictures:
            _thumb(str(record.get("img_url") or ""), t(word), pictures, _glyph(listed_as))
        with ui.column().classes("gap-0 grow min-w-0"):
            with ui.column().classes("gap-0 w-full min-w-0 manager-record-head") as head:
                ui.label(told or t("manager.discovery.unnamed_file")).classes("truncate")
                if said:
                    ui.label(said).classes("manager-help truncate")
                lead = ui.label(comment).classes("manager-help truncate") if comment else None
            detail = ui.column().classes("gap-1 w-full manager-record-detail")
            detail.set_visibility(False)
            use_file = discovery_get.use_a_file(
                context, game_id, shell, ours=ours, held_in=held_in,
                vps_file_id=str(record.get("vps_file_id") or ""),
                add_table=listed_as == "tableFiles")
            _opens(head, detail,
                   lambda: _detail(
                       record, entry_url=entry_url, features=features, use_file=use_file,
                       looked=None if offered is None else
                       lambda: discovery_ext.look(context, offered, game_id)), lead)

        def whose() -> None:
            ui.label(when.day(stamp.astimezone()) if stamp else "").classes(
                "manager-help manager-record-when")
            if page:
                _out(site, page, broken=page_is_broken(record),
                     hint=t("manager.discovery.page_hint", site=site))

        if offered is None:
            with ui.column().classes("gap-0 items-end shrink-0 manager-record-aside"):
                whose()
        else:
            discovery_get.aside(
                tray, offered.pick, whose,
                discovery_get.try_again(context, tray, game_id, offered.pick),
                act=discovery_ext.acts_for(context, tray, lambda: game_id,
                                           listed_kinds(context), offered.pick.key))


def _offer(context: dict[str, Any], offer: dict[str, Any], *, label: str,
           sources: dict[str, dict[str, Any]], tray: discovery_get.Tray, game_id: str,
           entry_url: str) -> None:
    """A file a source holds for this game, which a tick gets."""
    pick = discovery_get.pick_of(offer)
    src = str(offer.get("url") or "")
    source = sources.get(pick.source) or {}
    name = str(source.get("name") or pick.source)
    size = (t(mediasource.SIZE_NAMES[pick.size]) if pick.size in mediasource.SIZE_NAMES
            else pick.size)
    said = (t("manager.mediasource.source_and_size", source_name=name, size=size) if size
            else name)
    base = str(source.get("url") or "").rstrip("/")
    folder = f"{base}/tree/main/{context['discovery']['id']}" if base else ""
    family = media_family(pick.kind)

    def enlarge() -> None:
        mediaview.open_viewer(src, pick.kind, label)

    def whose() -> None:
        if folder:
            panel.link_out(name, to=folder, hint=t("manager.discovery.folder_hint", site=name))()

    with ui.row().classes("items-start gap-2 w-full no-wrap manager-member-row "
                          "manager-record") as shell:
        discovery_get.tick_cell(tray, pick)
        _thumb(src, label, [], "", family=family, enlarge=enlarge)
        with ui.column().classes("gap-0 grow min-w-0"):
            with ui.column().classes("gap-0 w-full min-w-0 manager-record-head") as head:
                ui.label(said).classes("truncate")
                ui.label(label).classes("manager-help truncate")
            detail = ui.column().classes("gap-1 w-full manager-record-detail")
            detail.set_visibility(False)
            use_file = discovery_get.use_a_file(
                context, game_id, shell, ours=(pick.kind,), held_in=vps_kinds.MEDIA)
            _opens(head, detail, lambda: _ways_out("", False, entry_url, use_file))
        discovery_get.aside(tray, pick, whose,
                            discovery_get.try_again(context, tray, game_id, pick))


def _held_row(name: str, *, framed: bool, glyph: str) -> None:
    """A file you hold that VPS does not list: its own name, and nowhere to go."""
    with ui.row().classes("items-center gap-2 w-full no-wrap manager-member-row "
                          "manager-record manager-record--held"):
        discovery_get.mark(True)
        if framed:
            candidates.thumb("", glyph)
        ui.label(name).classes("grow min-w-0 truncate")
        ui.element("span").classes("manager-record-out")


async def _kind(context: dict[str, Any], kind: tuple[str, str, str],
                held: dict[str, Any] | None, *, features: bool, missing: bool,
                tray: discovery_get.Tray, game_id: str,
                offers: list[dict[str, Any]] | None = None,
                sources: dict[str, dict[str, Any]] | None = None) -> None:
    """One band: the files a source holds for the game, then what VPS lists, newest first.
    `kind` has no VPS key where only a source holds files of it."""
    library, row = context["library"], context["discovery"]
    listed_as, _field, word = kind
    offers, sources = offers or [], sources or {}
    listed: list[dict[str, Any]] = []
    if listed_as:
        try:
            listed = await offload.io(library.vps_releases, row["id"], listed_as)
        except Exception as exc:  # noqa: BLE001 - the other kinds still draw
            logger.warning("manager: could not read %s for %s", listed_as, row["id"],
                           exc_info=True)
            panel.line(t("manager.discovery.files_failed"), hint=why(exc))
    records = newest_first(listed)
    listed_ids = {str(one.get("vps_file_id") or "") for one in records}
    mine = held_of(held, listed_as)
    tied = {one["vps_file_id"] for one in mine if one.get("vps_file_id") in listed_ids}
    loose = [one["name"] for one in mine if one.get("vps_file_id") not in tied]
    shown, rest = split_records(records, tied)
    hosted = context.get("hosted", {})
    newest = next((hosted[str(one.get("vps_file_id") or "")].pick for one in records
                   if str(one.get("vps_file_id") or "") in hosted
                   and str(one.get("vps_file_id")) not in tied
                   and not hosted[str(one.get("vps_file_id"))].level), None)
    if newest is not None:
        context.setdefault("newest", {})[listed_as] = newest
    features = features and listed_as == "tableFiles"
    pictures = list(dict.fromkeys(str(one["img_url"]) for one in records if one.get("img_url")))
    entry_url = str(row.get("url") or "")

    with ui.row().classes("items-baseline gap-2 w-full no-wrap manager-band"):
        ui.label(t(word)).classes("grow min-w-0")
        if missing:
            ui.label(t("manager.view.missing")).classes("manager-band-tag")
        ui.label(str(len(records) + len(offers))).classes("manager-band-count")
    with ui.column().classes("gap-0 w-full manager-plain-rows") as body:
        for name in loose:
            _held_row(name, framed=bool(pictures), glyph=_glyph(listed_as))
        for offer in offers:
            _offer(context, offer, label=t(word), sources=sources, tray=tray, game_id=game_id,
                   entry_url=entry_url)
        for record in shown:
            _record(context, record, mine=str(record.get("vps_file_id") or "") in tied,
                    features=features, kind=kind, pictures=pictures, entry_url=entry_url,
                    game_id=game_id, tray=tray)
        if rest:
            more = ui.row().classes("w-full manager-record manager-record-more")

            def expand() -> None:
                more.delete()
                with body:
                    for record in rest:
                        _record(context, record, mine=False, features=features, kind=kind,
                                pictures=pictures, entry_url=entry_url, game_id=game_id,
                                tray=tray)

            with more:
                discovery_get.mark()
                panel.action(t("manager.discovery.more", count=len(rest)), expand,
                             icon=verbs.SHOW_MORE, inline=True,
                             hint=t("manager.discovery.more_hint"))()


# The VPS kinds that are art rather than files: they sit among the media, with the files
# a source holds of the same kind.
MEDIA_LISTINGS = {"wheelArtFiles": "wheel", "topperFiles": "topper"}


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


async def _media_present(library: Library, game_id: str) -> dict[str, Any] | None:
    """What media the game has, by kind. None where the game is not in the library or it
    cannot be read, which marks nothing Missing."""
    if not game_id:
        return None
    try:
        return await offload.io(library.media_for, game_id, None)
    except Exception:  # noqa: BLE001 - the bands still draw, unmarked
        logger.warning("manager: could not read the media %s has", game_id, exc_info=True)
        return None


async def files(context: dict[str, Any]) -> None:
    """What can be got for the entry: the files VPS lists, then its media, a band per kind
    with the ones the game lacks first."""
    row, library, state = context["discovery"], context["library"], context["state"]
    counted = bool(library.catalog().get("counted"))
    listed = [kind for kind in KINDS if kind[0] in row["listed"] and kept(library, kind[0])]
    game_id, held = await owner_state(context)
    tray = discovery_get.tray_of(state, row["id"])
    listed_as = [kind[0] for kind in listed]
    version = await discovery_ext.version_of(library)
    discovery_ext.adopt(context, tray, await discovery_ext.ask(library, row, game_id, listed_as,
                                                               keep=tray.offered))
    context["newest"] = {}
    context["refresh_hosted"] = lambda: discovery_ext.refresh(context, tray, game_id, listed_as)
    offers, sources, failed = await discovery_get.offers_for(library, row["id"])
    present = await _media_present(library, game_id)
    if present is not None:
        tray.release({one.kind for one in tray.picks.values()
                      if not (present.get(one.kind) or {}).get("present")})
    bands = media_bands(listed, offers)
    said = standing(library, row, held)
    file_kinds = sorted((kind for kind in listed if kind[0] not in MEDIA_LISTINGS),
                        key=lambda kind: said.get(kind[0]) != MISSING)
    lacking = {kind for kind, _band in bands
               if present is not None and not (present.get(kind) or {}).get("present")}
    bands.sort(key=lambda one: one[0] not in lacking)
    with ui.column().classes("gap-0 w-full min-w-0 manager-vps-files"):
        if not file_kinds and not bands and failed is None:
            panel.line(t("manager.discovery.lists_nothing"))
            return
        if not counted:
            _never_counted(state)
        newest_link = None
        if file_kinds:
            with ui.row().classes("items-baseline gap-3 w-full no-wrap"):
                ui.label(t("manager.discovery.files")).classes("manager-fact-heading grow")
                newest_link = ui.row().classes("items-center")
        for kind in file_kinds:
            await _kind(context, kind, held, features=not said,
                        missing=said.get(kind[0]) == MISSING, tray=tray, game_id=game_id)
        if newest_link is not None and context["newest"]:
            with newest_link:
                panel.link(t("manager.discovery.tick_newest"), to=OWN_ADDRESS,
                           on_click=lambda: _tick_newest(context, tray),
                           hint=t("manager.discovery.tick_newest.help"))()
        if bands or failed is not None:
            ui.label(t("manager.discovery.media")).classes("manager-fact-heading")
        if failed is not None:
            panel.line(t("manager.discovery.media_failed"), hint=why(failed))
        for media_kind, kind in bands:
            await _kind(context, kind, held, features=False, missing=media_kind in lacking,
                        tray=tray, game_id=game_id, offers=offers.get(media_kind),
                        sources=sources)
        if counted:
            discovery_get.bar(context, tray, game_id, lambda: _add_this(context))
        if library.online_sources():
            discovery_ext.watch(context, tray, game_id, listed_as, version)


def _tick_newest(context: dict[str, Any], tray: discovery_get.Tray) -> None:
    """Tick the newest file of each kind that an extension's source can get and the library
    does not hold."""
    if tray.running:
        return
    for pick in context["newest"].values():
        if pick.key not in tray.picks and pick.key not in tray.moves:
            tray.set(pick, True)
            tray.repaint(pick.key)
