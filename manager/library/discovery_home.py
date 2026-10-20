"""Discovery's front page, drawn from what `GET /discovery/home` answers: the games of the
library with a later version of something they hold, what VPS added lately, the games the
library holds that lack a kind VPS lists, the games VPS lists that it has none of, whose work
it holds, and the views it has saved.

A tile opens its game in the pane, an author's name opens the author's page, and See All
opens a grid on a named view of the same question. The counts on Your Views need the whole
catalog, which loads after the page is drawn; the shelves do not wait for it.
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
from common.media.media_specs import IMAGE_FAMILY, MEDIA_SPECS, media_label_map
from common.online import script_fixes, vps_find, vps_home
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
from manager.library import (
    discovery_ask,
    discovery_marks,
    discovery_marks_grid,
    discovery_pictures,
    discovery_releases,
)

logger = logging.getLogger("vpinfe.manager.library.discovery_home")

ADDRESS = "/manager?" + deeplink.query({"view": "discovery"})
WINDOW_KEY = "discovery_window"

WINDOWS = {days: word for word, days in discovery_ask.SINCE_DAYS}
DEFAULT_DAYS = 7

_CHIP_WORDS = {vps_home.ALL: "manager.discovery.chip.all",
               vps_home.YOURS: "manager.discovery.chip.yours"}


WINDOW_WIDTH = "w-36"
KINDS_WIDTH = "w-44"
GAPS_WIDTH = "w-56"


def _heading() -> ui.row:
    """A shelf's heading row: the heading on the page's edge, its controls and See All at the
    right end, in `_end`."""
    return ui.row().classes("manager-heading-row w-full items-center gap-2")


def _end() -> ui.row:
    """What sits at a heading row's right end, on the same indent as the tiles under it."""
    return ui.row().classes("items-center gap-2 no-wrap pr-3")


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
    from manager.library.discovery import KINDS
    from manager.library.discovery_ask import KIND_MANY
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


# What a move of a source other than the spreadsheet is called on a tile, by the kind of file.
_MOVE_WORDS = {script_fixes.KIND: "manager.discovery.update.script_fix"}

# How many moves a tile lists before it counts the rest.
MOVES_SHOWN = 2


def move_line(move: dict[str, Any]) -> str:
    """One line of a tile: what has a later version, and the version it moved from and to."""
    word = _MOVE_WORDS.get(move["kind"])
    kind = t(word) if word else _kind_words(move["kind"])[0]
    if move["then"] and move["now"]:
        return t("manager.discovery.update.moved", kind=kind, then=move["then"], now=move["now"])
    return t("manager.discovery.update.later", kind=kind, now=move["now"]) \
        if move["now"] else kind


def is_picture(move: dict[str, Any]) -> bool:
    """Whether a move is a picture a source has replaced."""
    return bool(move.get("md5"))


def pictures_line(moves: list[dict[str, Any]]) -> str:
    """The one line a game's replaced pictures share, naming them: "Wheel and Backglass
    pictures", or just the names where one is not a picture (a video, a sound)."""
    labels = media_label_map()
    kinds = [str(one["kind"]) for one in moves]
    names = [labels.get(kind, kind) for kind in kinds]
    named = t("manager.collection_rules.and_last", rest=t(
        "manager.collection_rules.list_join").join(names[:-1]), last=names[-1]) \
        if len(names) > 1 else names[0]
    images = {spec.kind for spec in MEDIA_SPECS if spec.family == IMAGE_FAMILY}
    return t("manager.discovery.update.pictures", kinds=named) \
        if all(kind in images for kind in kinds) else named


def tile_lines(moves: list[dict[str, Any]]) -> list[str]:
    """The lines of a tile: one for each move, with the replaced pictures together in one,
    after the rest."""
    pictures = [one for one in moves if is_picture(one)]
    return [*(move_line(one) for one in moves if not is_picture(one)),
            *([pictures_line(pictures)] if pictures else [])]


def fix_line(moves: list[dict[str, Any]]) -> str:
    """The line a script fix has on a tile, or "" where there is none."""
    return next((move_line(one) for one in moves if one["kind"] == script_fixes.KIND), "")


def shown_lines(moves: list[dict[str, Any]]) -> list[str]:
    """The lines of a tile in the order they are drawn: as `tile_lines` has them, except
    that a script fix is kept among the lines shown, since its Fetch is drawn on it."""
    lines = tile_lines(moves)
    fix = fix_line(moves)
    if fix in lines[MOVES_SHOWN:]:
        lines.remove(fix)
        lines.insert(MOVES_SHOWN - 1, fix)
    return lines


def fix_folders(item: dict[str, Any]) -> list[str]:
    """The folders of the game's script fixes, which the fetch is asked for."""
    return [move["file"] for move in item["moves"]
            if move["kind"] == script_fixes.KIND and move["file"]]


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
         see_updates: Callable[[list[str]], Any],
         see_dont_have: Callable[[], Any],
         see_picture: Callable[[str, str], Any],
         fix_scripts: Callable[[list[str]], Any],
         open_view: Callable[[str], Any],
         open_releases_view: Callable[[str], Any],
         open_marks: Callable[[str], Any],
         open_subject: Callable[[dict[str, str]], Any],
         marking: discovery_marks.Marking) -> None:
    """Draw Home into `body` from `home`, the answer for the remembered window.

    `catalog()` gives the people and the Browse rows once the catalog is in memory; `reread`
    answers for another window. `see_new(days, chip)`, `see_missing(game_ids)` and
    `see_updates(game_ids)` open the grid on the shelf's question, `see_dont_have()` Browse on
    the games the shelf draws from, `see_picture(vps_id, kind)`
    a game's pane on the section of that media kind, `open_view(id)` on a saved view of
    Browse, `open_releases_view(id)` on one of Releases, `open_marks(view)` the Marks grid on
    its Ignored or Wanted view, `open_subject` an author's page, and `fix_scripts(folders)`
    fetches the script fixes of those games. `marking` is the menu a tile opens on a right
    click or a long press, and what says a release is Wanted."""
    shown: dict[str, Any] = {"home": home, "chip": vps_home.ALL, "lack": "", "rows": None,
                             "people": [], "asked": home["days"]}
    with body:
        updates_box = ui.column().classes("w-full gap-2")
        shelf_box = ui.column().classes("w-full gap-2")
        with shelf_box:
            with _heading():
                ui.label(t("manager.discovery.new_shelf")).classes(
                    "manager-fact-heading shrink-0")
                ui.space()
                with _end():
                    window = dropdown.Select(
                        {days: t(word) for days, word in WINDOWS.items()},
                        value=home["days"], look=dropdown.OUTLINED,
                        on_change=lambda event: pick_window(event.value)).classes(WINDOW_WIDTH)
                    kinds_slot = ui.element("div").classes("contents")
                    see_all_slot = ui.element("div").classes("contents")
            tiles_box = ui.column().classes("w-full gap-2")
        wanted_box = ui.column().classes("w-full gap-2")
        lacking_box = ui.column().classes("w-full gap-2")
        dont_have_box = ui.column().classes("w-full gap-2")
        authors_box = ui.column().classes("w-full gap-2")
        views_box = ui.column().classes("w-full gap-2")

    def menu_on(card: Any, shelf: str, item: dict[str, Any], listing: str) -> None:
        """The tile's right click and long press."""
        word = media_label_map().get(listing) or (_kind_words(listing)[0] if listing else "")
        with card:
            menu = ui.context_menu()
        panel.verb_menu(menu, marking.title(shelf, item), [
            *(discovery_pictures.take_verb(library, item, refresh)
              if shelf == discovery_marks.MISSING else []),
            *marking.verbs(shelf, item, listing, word)])

    def update_menu(card: Any, item: dict[str, Any]) -> None:
        """The right click and long press of an Updates tile."""
        entries = marking.update_verbs(item, lambda listing: _kind_words(listing)[0])
        if folders := fix_folders(item):
            entries.append(panel.Verb(t("manager.discovery.update.fetch_fix"),
                                      lambda: fix_scripts(folders), icon=verbs.FETCH))
        if not entries:
            return
        with card:
            menu = ui.context_menu()
        panel.verb_menu(menu, marking.title(discovery_marks.UPDATE, item), entries)

    def open_tile(item: dict[str, Any]) -> Any:
        """The game's pane, on the first replaced picture's section where pictures are all
        the tile holds."""
        if all(is_picture(one) for one in item["moves"]):
            return see_picture(item["vps_id"], str(item["moves"][0]["kind"]))
        return on_select({"id": item["vps_id"]})

    def fetch_button(folders: list[str]) -> None:
        """Fetch on the script-fix line: the press stops here, not on the tile."""
        with ui.element("div").classes("shrink-0").on("click.stop", lambda: None) \
                .on("keydown.enter.stop", lambda: None):
            panel.icon_action(t("manager.discovery.update.fetch_fix"),
                              lambda: fix_scripts(folders), icon=verbs.FETCH,
                              hint=t("manager.discovery.update.fetch_fix"))()

    def update_tile(parent: Any, item: dict[str, Any]) -> None:
        with parent, ui.element("div").classes("manager-shelf-tile") as card:
            card.props("tabindex=0 role=button")
            # A game matched to no entry has no Discovery pane: it opens in the Games list.
            opens = (lambda one=item: open_tile(one)) if item["vps_id"] \
                else (lambda one=item: see_updates([one["game_id"]]))
            card.on("click", lambda _e: opens())
            card.on("keydown.enter", lambda _e: opens())
            candidates.thumb(item["img_url"], icons.TABLES, t("manager.discovery.no_picture"))
            with ui.column().classes("gap-0 min-w-0"):
                ui.label(item["game"]).classes("manager-shelf-name")
                lines = shown_lines(item["moves"])
                fix = fix_line(item["moves"])
                for line in lines[:MOVES_SHOWN]:
                    if line == fix and (folders := fix_folders(item)):
                        with ui.row().classes("items-center gap-1 no-wrap"):
                            ui.label(line).classes("text-xs manager-help truncate")
                            fetch_button(folders)
                    else:
                        ui.label(line).classes("text-xs manager-help truncate")
                if len(lines) > MOVES_SHOWN:
                    ui.label(t("manager.discovery.update.more",
                               count=len(lines) - MOVES_SHOWN)) \
                        .classes("text-xs manager-help")
            update_menu(card, item)

    def draw_updates() -> None:
        updates_box.clear()
        updates = shown["home"]["updates"]
        if not updates["count"]:
            return
        with updates_box:
            with _heading():
                ui.label(t("manager.discovery.updates")).classes("manager-fact-heading")
                ui.space()
                with _end():
                    panel.link(t("manager.discovery.see_all"), to=ADDRESS,
                               on_click=lambda: see_updates(updates["game_ids"]))()
            row = ui.row().classes("manager-shelf w-full px-3")
            for one in updates["games"]:
                update_tile(row, one)

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
        kinds_slot.clear()
        see_all_slot.clear()
        words = chip_words()
        if shown["chip"] not in words:
            shown["chip"] = vps_home.ALL
        if shown["home"]["new"][vps_home.ALL]["count"]:
            with kinds_slot:
                dropdown.Select(words, value=shown["chip"], look=dropdown.OUTLINED,
                                on_change=lambda event: pick_chip(event.value)
                                ).classes(KINDS_WIDTH)
            with see_all_slot:
                panel.link(t("manager.discovery.see_all"), to=ADDRESS,
                           on_click=lambda: see_new(shown["home"]["days"], shown["chip"]))()
        draw_tiles()

    def draw_tiles() -> None:
        """The tiles of the kind picked, drawn again without the dropdown that picked it."""
        tiles_box.clear()
        everything = shown["home"]["new"]
        if not everything[vps_home.ALL]["count"]:
            return
        with tiles_box:
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
        draw_updates()
        draw_shelf()
        draw_wanted()
        draw_dont_have()
        draw_authors()

    def pick_chip(chip: str) -> None:
        shown["chip"] = chip
        draw_tiles()

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
            with _heading():
                ui.label(t("manager.discovery.missing_from")).classes(
                    "manager-fact-heading shrink-0")
                ui.space()
                with _end():
                    dropdown.Select(
                        {tab: t("manager.discovery.counted", name=_gap_words(tab), count=count)
                         for tab, count in tabs.items()}, value=listing,
                        look=dropdown.OUTLINED, on_change=lambda event: pick_lack(event.value)
                    ).classes(GAPS_WIDTH)
                    lacking_see_all = ui.element("div").classes("contents")
            lacking_tiles = ui.row().classes("manager-shelf w-full px-3")
        shown["lacking_slots"] = (lacking_see_all, lacking_tiles)
        draw_gaps(listing)

    def draw_gaps(listing: str) -> None:
        """The See All and the tiles of one kind, drawn again without the dropdown that
        picked it."""
        see_all, row = shown["lacking_slots"]
        see_all.clear()
        row.clear()
        gap = shown["home"]["missing"][listing]
        with see_all:
            if ids := gap.get("game_ids"):
                panel.link(t("manager.discovery.see_all"), to=ADDRESS,
                           on_click=lambda: see_missing(ids))()
        for game in gap["games"]:
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
        draw_gaps(listing)

    def draw_dont_have() -> None:
        dont_have_box.clear()
        lacked = shown["home"]["dont_have"]
        if not lacked["games"]:
            return
        with dont_have_box:
            with _heading():
                ui.label(t("manager.discovery.dont_have")).classes(
                    "manager-fact-heading shrink-0").tooltip(t("manager.discovery.dont_have.help"))
                ui.label(t("manager.discovery.dont_have.order")).classes(
                    "text-xs manager-help")
                ui.space()
                with _end():
                    panel.link(t("manager.discovery.see_all"), to=ADDRESS,
                               on_click=see_dont_have)()
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
            with _heading():
                ui.label(t("manager.discovery.mark.wanted")).classes("manager-fact-heading")
                ui.space()
                with _end():
                    panel.link(t("manager.discovery.see_all"), to=ADDRESS,
                               on_click=lambda: open_marks(discovery_marks_grid.WANTED_VIEW))()
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
            with _heading():
                ui.label(t("manager.discovery.authors")).classes("manager-fact-heading")
            with ui.row().classes("manager-shelf w-full px-3"):
                for one in collected:
                    with ui.element("div").classes("manager-shelf-tile manager-shelf-tile--plain"):
                        author = {"type": vps_find.AUTHOR, "name": one["name"]}
                        panel.link(one["name"], to="/manager?" + deeplink.query(
                            {"view": "discovery", "subject": author}),
                            on_click=partial(open_subject, author),
                            classes="manager-shelf-name")()
                        with ui.row().classes("items-center gap-1 no-wrap"):
                            ui.label(t("manager.discovery.authors.held", count=one["held"])) \
                                .classes("text-xs manager-help")
                            if one["new"]:
                                ui.label("·").classes("text-xs manager-help")
                                ui.label(t("manager.discovery.authors.new", count=one["new"])) \
                                    .classes("text-xs manager-label")

    def draw_views() -> None:
        views_box.clear()
        browse, _active = views.stored(library, scope)
        saved, _active = views.stored(library, discovery_releases.SCOPE)
        compared = bool(shown["home"]["counted"])
        ignored = None if shown["rows"] is None else marking.ignored_count()
        with views_box:
            with _heading():
                ui.label(t("manager.discovery.views")).classes("manager-fact-heading")
            with ui.row().classes("manager-shelf w-full px-3"):
                for one in views.builtins(view_presets) + browse:
                    count = None if shown["rows"] is None \
                        else view_count(one, shown["rows"], compared=compared)
                    view_tile(t("manager.discovery.tab.browse"), one.name, count,
                              partial(open_view, one.id))
                for one in views.builtins(discovery_releases.VIEWS) + saved:
                    view_tile(t("manager.discovery.tab.releases"), one.name, None,
                              partial(open_releases_view, one.id))
                if ignored:
                    view_tile(t("manager.discovery.marks.place"),
                              t("manager.discovery.mark.ignored"), ignored,
                              lambda: open_marks(discovery_marks_grid.IGNORED_VIEW),
                              many="manager.discovery.marks.summary")

    def view_tile(place: str, name: str, count: int | None, opens: Callable[[], Any], *,
                  many: str = "manager.discovery.views.count") -> None:
        """A saved view: where it opens, its name and how many rows it shows where that is
        known."""
        with ui.element("div").classes("manager-shelf-tile manager-shelf-tile--plain") as card:
            card.props("tabindex=0 role=button")
            card.on("click", lambda _e: opens())
            card.on("keydown.enter", lambda _e: opens())
            ui.label(place).classes("text-xs manager-label")
            ui.label(name).classes("manager-shelf-name")
            if count is not None:
                ui.label(t(many, count=count)).classes("text-xs manager-help")

    async def learn() -> None:
        try:
            shown["people"], shown["rows"] = await catalog()
        except Exception:  # noqa: BLE001 - the shelves stand without search and counts
            logger.warning("manager: could not read the catalog for Discovery's search",
                           exc_info=True)
            return
        draw_views()

    draw_updates()
    draw_shelf()
    draw_wanted()
    draw_lacking()
    draw_dont_have()
    draw_authors()
    draw_views()
    busy.start(views_box, learn)
