"""Discovery's front page, drawn from what `GET /discovery/home` answers: what VPS added
lately, the games the library holds that lack a kind VPS lists, the games VPS lists that it
has none of, whose work it holds, and the views it has saved.

A tile opens its game in the pane, an author's name opens the author's page, and See All
opens a grid on a named view of the same question. The search box and the counts on Your
Views need the whole catalog, which loads after the page is drawn; the shelves do not wait
for it.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from functools import partial
from typing import Any

from nicegui import ui

from common import icons
from common.failures import why
from common.i18n import t
from common.media.media_specs import media_label_map
from common.online import vps_find, vps_home
from manager.kit import (
    busy,
    candidates,
    deeplink,
    dropdown,
    game_tables,
    panel,
    remembered,
    verbs,
    views,
    when,
)
from manager.library import discovery_ask, discovery_marks, discovery_pictures, discovery_releases

logger = logging.getLogger("vpinfe.manager.library.discovery_home")

ADDRESS = "/manager?" + deeplink.query({"view": "discovery"})
WINDOW_KEY = "discovery_window"

WINDOWS = {days: word for word, days in discovery_ask.SINCE_DAYS}
DEFAULT_DAYS = 7

_CHIP_WORDS = {vps_home.ALL: "manager.discovery.chip.all",
               vps_home.YOURS: "manager.discovery.chip.yours"}


def window_days(value: Any) -> int:
    return value if value in WINDOWS else DEFAULT_DAYS


def remembered_days() -> int:
    return window_days(remembered.get(WINDOW_KEY))


def _fits(cell: Any, values: list[Any]) -> bool:
    """Whether a cell is one of the values picked, or for a list cell holds any of them."""
    if isinstance(cell, (list, tuple, set)):
        return any(one in values for one in cell)
    return cell in values


def view_count(view: views.View, rows: list[dict[str, Any]], *, compared: bool) -> int | None:
    """How many rows a view shows, where its filters are plain value lists; None where it
    holds a filter this does not read, or reads a column that is empty until the library is
    compared, since a count that may be wrong is worse than none."""
    if view.filters and not compared:
        return None
    shown = rows
    for field, model in view.filters.items():
        values = model.get("values") if isinstance(model, dict) else None
        if not isinstance(values, list):
            return None
        shown = [one for one in shown if _fits(one.get(field), values)]
    return len(shown)


def new_filters(days: int, chip: str, kept: list[str], *, counted: bool) -> dict[str, Any]:
    """The Releases filters that open on what a chip of the New shelf counts: added in the
    window, of a kind the shelf shows - the chip's own, or every kept kind it has a place
    for - and in the library for Your Games."""
    question: dict[str, Any] = {"since": days}
    if chip == vps_home.YOURS:
        question["owned"] = "yes"
    filters = discovery_releases.arrival_filters(question, counted=counted)
    filters["kind"] = {"values": [chip] if chip not in (vps_home.ALL, vps_home.YOURS)
                       else [one for one in kept if one not in vps_home.NOT_SHOWN]}
    return filters


def version_line(release: dict[str, Any]) -> str:
    """A release's version, and the one it held before VPS changed it where it was re-dated."""
    version, was = release.get("version") or "", release.get("was") or ""
    if version and was:
        return t("manager.discovery.version_was", version=version, was=was)
    return version


def _kind_words(listing: str) -> tuple[str, str]:
    """A kind by its VPS key: one release of it, and several."""
    # Imported here: `discovery` draws this page.
    from manager.library.discovery import KIND_MANY, KINDS
    one = next((t(word) for listed, _field, word in KINDS if listed == listing), listing)
    return one, t(KIND_MANY[listing]) if listing in KIND_MANY else one


# What a tab of games lacking a media kind with no VPS kind of its own is called, in the plural.
_MEDIA_GAPS = {
    "playfield": "manager.discovery.gap.playfield",
    "playfield_fss": "manager.discovery.gap.playfield_fss",
    "playfield_video": "manager.discovery.gap.playfield_video",
    "scoreview": "manager.discovery.gap.scoreview",
    "scoreview_video": "manager.discovery.gap.scoreview_video",
    "real_dmd": "manager.discovery.gap.real_dmd",
    "real_dmd_color": "manager.discovery.gap.real_dmd_color",
    "cab": "manager.discovery.gap.cab",
    "flyer": "manager.discovery.gap.flyer",
    "audio": "manager.discovery.gap.audio",
}


def _gap_words(kind: str) -> str:
    """What a game lacks, in the plural a tab names it with: a VPS kind, which holds the
    media kind filed with it, or a media kind with none."""
    if kind in vps_home.GAP_KINDS:
        return _kind_words(kind)[1]
    return t(_MEDIA_GAPS[kind]) if kind in _MEDIA_GAPS else media_label_map().get(kind, kind)


def fill(body: Any, home: dict[str, Any], *, library: Any, scope: str,
         view_presets: dict[str, Any],
         catalog: Callable[[], Awaitable[tuple[list[dict[str, Any]], list[dict[str, Any]]]]],
         reread: Callable[[int], Awaitable[dict[str, Any]]],
         on_select: Callable[[Any], Any],
         see_new: Callable[[int, str], Any],
         see_missing: Callable[[list[str]], Any],
         open_view: Callable[[str], Any],
         open_subject: Callable[[dict[str, str]], Any],
         marking: discovery_marks.Marking) -> None:
    """Draw Home into `body` from `home`, the answer for the remembered window.

    `catalog()` gives the people and the Browse rows once the catalog is in memory; `reread`
    answers for another window. `see_new(days, chip)` and `see_missing(game_ids)` open the
    grid on the shelf's question, `open_view(id)` on a saved view, and `open_subject` an
    author's page. `marking` is the menu a tile opens on a right click or a long press, and
    what says a release is Wanted."""
    shown: dict[str, Any] = {"home": home, "chip": vps_home.ALL, "lack": "", "rows": None,
                             "people": [], "asked": home["days"]}
    with body:
        with ui.row().classes("w-full items-center gap-2 px-3 pb-1 shrink-0"):
            ui.space()
            with panel.bar_end(), ui.element("div").classes("manager-suggest-anchor"):
                search = panel.search(t("manager.discovery.search"))
                discovery_ask.Suggest(search, lambda text: vps_find.find(
                    text, shown["people"], shown["rows"] or []), lambda group, one: choose(
                        group, one))
        shelf_box = ui.column().classes("w-full gap-2")
        with shelf_box:
            with ui.row().classes("manager-heading-row w-full items-center gap-2 px-3"):
                ui.label(t("manager.discovery.new_in")).classes("manager-fact-heading shrink-0")
                window = dropdown.Select(
                    {days: t(word) for days, word in WINDOWS.items()},
                    value=home["days"], look=dropdown.OUTLINED,
                    on_change=lambda event: pick_window(event.value)).classes("w-40")
                ui.space()
                see_all_slot = ui.row().classes("items-center")
            tiles_box = ui.column().classes("w-full gap-2")
        wanted_box = ui.column().classes("w-full gap-2")
        lacking_box = ui.column().classes("w-full gap-2")
        dont_have_box = ui.column().classes("w-full gap-2")
        authors_box = ui.column().classes("w-full gap-2")
        views_box = ui.column().classes("w-full gap-2")

    async def choose(group: str, one: dict[str, Any]) -> None:
        if group == vps_find.GAME:
            await on_select({"id": str(one["id"])})
        else:
            open_subject({"type": group, "name": str(one["name"])})

    def menu_on(card: Any, shelf: str, item: dict[str, Any], listing: str) -> None:
        """The tile's right click and long press."""
        word = media_label_map().get(listing) or (_kind_words(listing)[0] if listing else "")
        with card:
            menu = ui.context_menu()
        panel.verb_menu(menu, marking.title(shelf, item), [
            *(discovery_pictures.take_verb(library, item, refresh)
              if shelf == discovery_marks.MISSING else []),
            *marking.verbs(shelf, item, listing, word)])

    def tile(parent: Any, release: dict[str, Any]) -> None:
        with parent, ui.element("div").classes("manager-shelf-tile") as card:
            card.props("tabindex=0 role=button")
            card.on("click", lambda _e, one=release: on_select({"id": one["vps_id"]}))
            card.on("keydown.enter", lambda _e, one=release: on_select({"id": one["vps_id"]}))
            candidates.thumb(release["img_url"], icons.TABLES, t("manager.discovery.no_picture"))
            with ui.column().classes("gap-0 min-w-0"):
                ui.label(_kind_words(release["listing"])[0]).classes("text-xs manager-label")
                ui.label(release["game"]).classes("manager-shelf-name")
                ui.label(" · ".join(one for one in (
                    ", ".join(release["authors"][:2]), when.ago(release["added"])) if one)) \
                    .classes("text-xs manager-help truncate")
                if version_line(release):
                    ui.label(version_line(release)).classes("text-xs manager-help truncate")
                if release["mod"]:
                    ui.label(t("manager.discovery.mod")).classes("text-xs manager-help")
                if release["held"]:
                    ui.label(t("manager.discovery.have")).classes("text-xs manager-label")
            if marking.wanted_release(release["id"]):
                ui.icon(verbs.WANTED, size="18px").classes("manager-cell-mark").tooltip(
                    t("manager.discovery.mark.wanted.help"))
            menu_on(card, discovery_marks.NEW, release, release["listing"])

    def chip_words() -> dict[str, str]:
        out = {}
        for chip, shelf in shown["home"]["new"].items():
            if shelf["count"] or chip == vps_home.ALL:
                word = t(_CHIP_WORDS[chip]) if chip in _CHIP_WORDS else _kind_words(chip)[1]
                out[chip] = t("manager.discovery.counted", name=word, count=shelf["count"])
        return out

    def draw_shelf() -> None:
        tiles_box.clear()
        see_all_slot.clear()
        everything = shown["home"]["new"]
        words = chip_words()
        if shown["chip"] not in words:
            shown["chip"] = vps_home.ALL
        if not everything[vps_home.ALL]["count"]:
            return
        with see_all_slot:
            panel.link(t("manager.discovery.see_all"), to=ADDRESS,
                       on_click=lambda: see_new(shown["home"]["days"], shown["chip"]))()
        with tiles_box:
            with ui.row().classes("w-full items-center gap-1 px-3"):
                panel.segmented(words, shown["chip"], lambda event: pick_chip(event.value))
            row = ui.row().classes("manager-shelf w-full px-3")
            for one in everything[shown["chip"]]["releases"]:
                tile(row, one)

    async def refresh() -> None:
        """Read the shelves again for the window on show and draw them where they stand, so a
        tab or chip picked stays picked."""
        try:
            shown["home"] = await reread(shown["home"]["days"])
        except Exception as exc:  # noqa: BLE001 - the shelves stay as they were
            with tiles_box:
                ui.notify(t("manager.discovery.read_failed"), caption=why(exc), type="negative")
            return
        draw_shelf()
        draw_wanted()
        draw_lacking()
        draw_dont_have()
        draw_authors()

    async def pick_window(days: int) -> None:
        """Read the shelf for another window. The window is remembered once the read has
        answered; a read that fails leaves the shelf and the window as they were, and the
        answer to an earlier pick that arrives after a later one is dropped."""
        shown["asked"] = days
        if days == shown["home"]["days"]:
            return
        try:
            fresh = await reread(days)
        except Exception as exc:  # noqa: BLE001 - the shelf stays as it was
            if shown["asked"] == days:
                window.set_value(shown["home"]["days"])
                with tiles_box:
                    ui.notify(t("manager.discovery.read_failed"), caption=why(exc),
                              type="negative")
            return
        if shown["asked"] != days:
            return
        remembered.put(WINDOW_KEY, days)
        shown["home"] = fresh
        draw_shelf()
        draw_wanted()
        draw_dont_have()
        draw_authors()

    def pick_chip(chip: str) -> None:
        shown["chip"] = chip
        draw_shelf()

    def lacking_tabs() -> dict[str, int]:
        return {listing: gap["count"] for listing, gap in shown["home"]["missing"].items()
                if gap["count"]}

    def draw_lacking() -> None:
        lacking_box.clear()
        tabs = lacking_tabs()
        if not tabs:
            return
        listing = shown["lack"] if shown["lack"] in tabs else next(iter(tabs))
        with lacking_box:
            with ui.row().classes("manager-heading-row w-full items-center gap-2 px-3"):
                ui.label(t("manager.discovery.missing_from")).classes(
                    "manager-fact-heading shrink-0")
                panel.segmented({tab: t("manager.discovery.counted",
                                        name=_gap_words(tab), count=count)
                                 for tab, count in tabs.items()}, listing,
                                lambda event: pick_lack(event.value))
                ui.space()
                if ids := shown["home"]["missing"][listing].get("game_ids"):
                    panel.link(t("manager.discovery.see_all"), to=ADDRESS,
                               on_click=lambda: see_missing(ids))()
            row = ui.row().classes("manager-shelf w-full px-3")
            for game in shown["home"]["missing"][listing]["games"]:
                with row, ui.element("div").classes("manager-shelf-tile") as card:
                    card.props("tabindex=0 role=button")
                    card.on("click", lambda _e, game=game: on_select({"id": game["vps_id"]}))
                    card.on("keydown.enter",
                            lambda _e, game=game: on_select({"id": game["vps_id"]}))
                    candidates.thumb(game.get("picture") or game["img_url"], icons.TABLES,
                                     t("manager.discovery.no_picture"))
                    with ui.column().classes("gap-0 min-w-0 grow"):
                        ui.label(game["name"]).classes("manager-shelf-name")
                        if game["vps"]:
                            ui.label(t("manager.discovery.lacking.on_vps",
                                       count=game["vps"])).classes("text-xs manager-help")
                        if game["source"]:
                            ui.label(t("manager.discovery.lacking.from_source",
                                       count=game["source"])).classes("text-xs manager-help")
                    discovery_pictures.take_button(library, game, refresh)
                    menu_on(card, discovery_marks.MISSING, game, listing)

    def pick_lack(listing: str) -> None:
        shown["lack"] = listing
        draw_lacking()

    def draw_dont_have() -> None:
        dont_have_box.clear()
        lacked = shown["home"]["dont_have"]
        if not lacked["games"]:
            return
        with dont_have_box:
            with ui.row().classes("manager-heading-row w-full items-center gap-2 px-3"):
                ui.label(t("manager.discovery.dont_have")).classes(
                    "manager-fact-heading shrink-0")
                ui.label(t("manager.discovery.dont_have.order")).classes(
                    "text-xs manager-help")
            row = ui.row().classes("manager-shelf w-full px-3")
            for game in lacked["games"]:
                dont_have_tile(row, game)

    def dont_have_tile(parent: Any, game: dict[str, Any]) -> None:
        with parent, ui.element("div").classes("manager-shelf-tile") as card:
            card.props("tabindex=0 role=button")
            card.on("click", lambda _e, one=game: on_select({"id": one["vps_id"]}))
            card.on("keydown.enter", lambda _e, one=game: on_select({"id": one["vps_id"]}))
            candidates.thumb(game["img_url"], icons.TABLES, t("manager.discovery.no_picture"))
            with ui.column().classes("gap-0 min-w-0"):
                ui.label(t("word.game")).classes("text-xs manager-label")
                ui.label(game["game"]).classes("manager-shelf-name")
                if made := game_tables.made(game):
                    ui.label(made).classes("text-xs manager-help truncate")
                ui.label(t("manager.discovery.dont_have.authors", count=game["authors"])) \
                    .classes("text-xs manager-help")
            if marking.wanted_game(game["vps_id"]):
                ui.icon(verbs.WANTED, size="18px").classes("manager-cell-mark").tooltip(
                    t("manager.discovery.mark.wanted.help"))
            menu_on(card, discovery_marks.DONT_HAVE, game, "")

    def draw_wanted() -> None:
        wanted_box.clear()
        wanted = shown["home"]["wanted"]
        if not wanted["items"]:
            return
        with wanted_box:
            with ui.row().classes("manager-heading-row w-full px-3"):
                ui.label(t("manager.discovery.mark.wanted")).classes("manager-fact-heading")
            row = ui.row().classes("manager-shelf w-full px-3")
            for item in wanted["items"]:
                wanted_tile(row, item)

    def wanted_tile(parent: Any, item: dict[str, Any]) -> None:
        with parent, ui.element("div").classes("manager-shelf-tile") as card:
            card.props("tabindex=0 role=button")
            card.on("click", lambda _e, one=item: on_select({"id": one["vps_id"]}))
            card.on("keydown.enter", lambda _e, one=item: on_select({"id": one["vps_id"]}))
            candidates.thumb(item["img_url"], icons.TABLES, t("manager.discovery.no_picture"))
            with ui.column().classes("gap-0 min-w-0"):
                if item["listing"]:
                    ui.label(_kind_words(item["listing"])[0]).classes("text-xs manager-label")
                ui.label(item["game"]).classes("manager-shelf-name")
                if item["authors"]:
                    ui.label(", ".join(item["authors"][:2])).classes(
                        "text-xs manager-help truncate")
                if item["version"]:
                    ui.label(item["version"]).classes("text-xs manager-help truncate")
            menu_on(card, discovery_marks.WANT, item, item["listing"])

    def draw_authors() -> None:
        authors_box.clear()
        collected = shown["home"]["authors"]
        if not collected:
            return
        with authors_box:
            with ui.row().classes("manager-heading-row w-full px-3"):
                ui.label(t("manager.discovery.authors")).classes("manager-fact-heading")
            with ui.row().classes("manager-shelf w-full px-3"):
                for one in collected:
                    with ui.element("div").classes("manager-shelf-tile manager-shelf-tile--plain"):
                        author = {"type": vps_find.AUTHOR, "name": one["name"]}
                        panel.link(one["name"], to="/manager?" + deeplink.query(
                            {"view": "discovery", "subject": author}),
                            on_click=partial(open_subject, author),
                            classes="manager-shelf-name")()
                        ui.label(t("manager.discovery.authors.held", count=one["held"])) \
                            .classes("text-xs manager-help")
                        if one["new"]:
                            ui.label(t("manager.discovery.authors.new", count=one["new"])) \
                                .classes("text-xs manager-label")

    def draw_views() -> None:
        views_box.clear()
        custom, _active = views.stored(library, scope)
        listed = views.builtins(view_presets) + custom
        compared = bool(shown["home"]["counted"])
        with views_box:
            with ui.row().classes("manager-heading-row w-full px-3"):
                ui.label(t("manager.discovery.views")).classes("manager-fact-heading")
            with ui.row().classes("manager-shelf w-full px-3"):
                for one in listed:
                    count = None if shown["rows"] is None \
                        else view_count(one, shown["rows"], compared=compared)
                    with ui.element("div").classes("manager-shelf-tile manager-shelf-tile--plain") \
                            as card:
                        card.props("tabindex=0 role=button")
                        card.on("click", lambda _e, one=one: open_view(one.id))
                        card.on("keydown.enter", lambda _e, one=one: open_view(one.id))
                        ui.label(one.name).classes("manager-shelf-name")
                        if count is not None:
                            ui.label(t("manager.discovery.views.count", count=count)) \
                                .classes("text-xs manager-help")

    async def learn() -> None:
        try:
            shown["people"], shown["rows"] = await catalog()
        except Exception:  # noqa: BLE001 - the shelves stand without search and counts
            logger.warning("manager: could not read the catalog for Discovery's search",
                           exc_info=True)
            return
        draw_views()

    draw_shelf()
    draw_wanted()
    draw_lacking()
    draw_dont_have()
    draw_authors()
    draw_views()
    busy.start(views_box, learn)
