"""What a kind's section lists: the releases VPS lists, the files the game holds and the
pictures a media source offers.

Each release ends in one glyph and acts at once; pressing its row does nothing else. The card
Full shows above the list is always drawn and revealed by CSS, so the toggle never rebuilds.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Any

from nicegui import run, ui

from common import timestamps
from common.failures import why
from common.games import opened_pages
from common.i18n import t
from common.media.media_specs import IMAGE_FAMILY
from common.online import vps_find, vps_kinds
from manager.kit import art, candidates, deeplink, game_tables, panel, verbs, when
from manager.kit.on_page import on_page
from manager.library import (
    discovery,
    discovery_ext,
    discovery_get,
    discovery_marks,
    discovery_pictures,
    import_dialog,
    mediasource,
    mediaview,
    release_match,
)
from manager.library.discovery_get import Offered, Pick
from manager.library.discovery_kinds import LONG_KIND, Kind, Scene, short_name

logger = logging.getLogger("vpinfe.manager.library.discovery_list")


@dataclass
class _View:
    """What a kind's list is showing: the filter, the release the Full card holds and the
    pictures the sources' pages gave. Kept in the page's state, so a redraw does not lose it."""

    text: str = ""
    pressed: str = ""
    shells: dict[str, ui.element] = field(default_factory=dict)
    looked: dict[str, str] = field(default_factory=dict)
    reading: bool = False


def _when(record: dict[str, Any]) -> str:
    stamp = when.parsed(record.get("updated_at"))
    return when.day(stamp.astimezone()) if stamp else ""


def _head(record: dict[str, Any]) -> str:
    return discovery.told(record) or t("manager.discovery.unnamed_file")


def _detail(record: dict[str, Any], *, features: bool) -> str:
    return game_tables.JOIN.join(part for part in (
        _when(record), discovery.site_of(record)[0],
        discovery.what_it_is(record, features=features)) if part)


def _record_of(kind: Kind, vps_file_id: str) -> dict[str, Any] | None:
    return next((one for one in kind.records
                 if vps_file_id and str(one.get("vps_file_id")) == vps_file_id), None)


def _last_opened(kind: Kind, scene: Scene) -> tuple[str, str]:
    """The release whose page was opened most recently for this game and is not held yet, with
    its words, or `("", "")`. Read when a file arrives, so a page opened a moment ago counts."""
    tied = {one["vps_file_id"] for one in kind.mine if one.get("vps_file_id")}
    for one in opened_pages.recent(scene.vps_id, kind.listed_as):
        record = _record_of(kind, str(one.get("vps_file_id") or ""))
        if record and str(record["vps_file_id"]) not in tied:
            return str(record["vps_file_id"]), _head(record)
    return "", ""


def _source_line() -> str:
    return t("manager.discovery.source_line", source=t("manager.discovery.local"))


def _enlarges(box: ui.element, show: Callable[[], None]) -> None:
    box.classes("manager-record-thumb").props("tabindex=0 role=button")
    box.props["aria-label"] = t("word.enlarge")
    box.on("click", show).on("keydown.enter", show).on("keydown.space.prevent", show)


def _art(src: str, family: str, glyph: str) -> None:
    """A picture or the first frame of a video, or the kind's glyph where there is none."""
    if src and family == "video":
        ui.html(f'<video src="{src}#t=0.1" preload="metadata" muted playsinline></video>')
    elif src and family == "image":
        ui.html(f'<img src="{src}" loading="lazy" alt="">')
    else:
        ui.icon(glyph).classes("manager-source-thumb-glyph")


def body(context: dict[str, Any], scene: Scene, kind: Kind) -> None:
    """The section of one kind: why VPS could not be read, its list, and the way to import a
    file."""
    holder = ui.column().classes("gap-1 w-full min-w-0 manager-kind-body")
    with holder:
        if kind.unread:
            panel.line(t("manager.discovery.files_failed"), hint=kind.unread)
        if kind.media:
            _tiles(context, scene, kind)
        if kind.records or kind.mine:
            _releases(context, scene, kind)
        _foot(context, scene, kind, holder)


def _ours(kind: Kind) -> tuple[tuple[str, ...], str]:
    """Our kinds a file dropped on this section is for, and which inventory holds them."""
    if kind.media:
        return discovery_get.media_ours(kind.listed_as, kind.media), vps_kinds.MEDIA
    return discovery_get.of_listing(kind.listed_as)


def _foot(context: dict[str, Any], scene: Scene, kind: Kind, holder: ui.element) -> None:
    """Import a File…, with the line that says a file may be dropped on the section where the
    kind is missing."""
    ours, held_in = _ours(kind)
    use_file = discovery_get.use_a_file(
        context, scene.game_id, holder, ours=ours, held_in=held_in,
        add_table=kind.listed_as == "tableFiles",
        match=import_dialog.ReleaseMatch(
            _chooser(context, kind, scene), picture_of=_picture_of(context, scene, kind))
        if kind.records else None,
        opened=lambda: _last_opened(kind, scene))
    dropbox = kind.missing and not kind.records and not kind.offers
    with ui.row().classes("items-center gap-2 w-full" + (" manager-dropbox" if dropbox else "")):
        if dropbox:
            ui.label(t("manager.discovery.drop_here")).classes("manager-help")
        use_file()


# ---------------------------------------------------------------------------------------
# Releases


def _unheld(kind: Kind) -> list[dict[str, Any]]:
    """The releases the game does not hold yet: those whose page was opened first, then the
    rest, each newest first. The held ones are drawn above the list."""
    tied = {one["vps_file_id"] for one in kind.mine if one.get("vps_file_id")}
    rows = [one for one in discovery.newest_first(kind.records)
            if str(one.get("vps_file_id") or "") not in tied]
    return sorted(rows, key=lambda one: str(one.get("vps_file_id") or "") not in kind.opened)


def _releases(context: dict[str, Any], scene: Scene, kind: Kind) -> None:
    rows = _unheld(kind)
    ids = [str(one.get("vps_file_id") or "") for one in rows]
    view = context["state"].setdefault("discovery_views", {}).setdefault(
        (scene.vps_id, kind.key), _View())
    if view.pressed not in ids:
        view.pressed = ids[0] if ids else ""
    features = kind.listed_as == "tableFiles"
    card = ui.column().classes("gap-0 w-full manager-card-compare")
    if len(rows) + len(kind.mine) > LONG_KIND:
        box = panel.search(t("manager.folder_picker.filter")).classes("w-full")
        box.value = view.text
        box.on_value_change(lambda event: filter_by(str(event.value or "")))

    def shown() -> list[dict[str, Any]]:
        text = view.text.strip().lower()
        if not text:
            return rows
        return [one for one in rows if text in " ".join((
            _head(one), _detail(one, features=features),
            str(one.get("comment") or ""))).lower()]

    def hosted_of(record: dict[str, Any]) -> Offered | None:
        return context.get("hosted", {}).get(str(record.get("vps_file_id") or ""))

    def picture_of(record: dict[str, Any]) -> str:
        return str(record.get("img_url") or view.looked.get(str(record.get("vps_file_id")), ""))

    @on_page
    async def show_pictures() -> None:
        if view.reading:
            return
        view.reading = True
        draw()
        offered = [one for one in (hosted_of(record) for record in shown()) if one]
        try:
            said = await asyncio.gather(*(discovery_ext.read_look(context, one, scene.game_id)
                                          for one in offered))
        finally:
            view.reading = False
        if card.is_deleted:
            return
        for one, found in zip(offered, said, strict=True):
            if found.get("pictures"):
                view.looked[str(one.row["vps_file_id"])] = str(found["pictures"][0])
        draw()

    def press(file_id: str) -> None:
        view.pressed = file_id
        shade(view)
        draw_card()

    def draw_card() -> None:
        card.clear()
        with card:
            _card(context, scene, kind, rows, view, features, press)

    def build() -> None:
        view.shells.clear()
        with ui.row().classes("items-center justify-end w-full"):
            if view.reading:
                ui.spinner(size="xs")
            elif any(hosted_of(one) for one in shown()) and not any(picture_of(one)
                                                                    for one in rows):
                panel.action(t("manager.discovery.show_pictures"), show_pictures,
                             icon=verbs.SHOW_PICTURES, inline=True,
                             hint=t("manager.discovery.show_pictures.help"))()
        with ui.column().classes("gap-0 w-full min-w-0 manager-rels"):
            for held in kind.mine:
                _have(context, scene, kind, held)
            for record in shown():
                _release(context, scene, kind, record, view, features, picture_of(record),
                         press)
        shade(view)

    part = panel.region(build)

    def draw() -> None:
        part.refill()

    def filter_by(value: str) -> None:
        view.text = value
        part.refill()

    part()
    draw_card()


def shade(view: _View) -> None:
    for file_id, shell in view.shells.items():
        if file_id == view.pressed:
            shell.classes(add="manager-rel--pressed")
        else:
            shell.classes(remove="manager-rel--pressed")


def _own_picture(context: dict[str, Any], scene: Scene, kind: Kind,
                 name: str) -> tuple[str, str] | None:
    """The media slot and version to draw the held file from, where it is a picture the game's
    media route serves: a rule sheet is a document by kind and may still be a picture by
    extension."""
    ours, held_in = discovery_get.of_listing(kind.listed_as)
    if not scene.game_id or held_in != vps_kinds.MEDIA:
        return None
    if Path(name).suffix.lower() not in IMAGE_FAMILY:
        return None
    slot = discovery_get.slot_of((kind.media,) if kind.media else ours, held_in, name)
    held = ((context["library"].media.get(scene.game_id) or {}).get(slot) or {})
    return (slot, str(held.get("version") or "")) if held.get("present") else None


def _have(context: dict[str, Any], scene: Scene, kind: Kind, held: dict[str, str]) -> None:
    """A file the game holds: the release it is tied to where VPS lists it, else its name. A
    picture is drawn from the file itself, in place of the release's."""
    record = _record_of(kind, str(held.get("vps_file_id") or ""))
    name = str(held.get("name") or "")
    own = _own_picture(context, scene, kind, name)
    with ui.element("div").classes("manager-rel manager-rel--have"):
        with ui.element("div").classes("manager-rel-pic") as pic:
            candidates.thumb(
                art.media(scene.game_id, own[0], version=own[1], size=art.CELL) if own
                else str(record.get("img_url") or "") if record else "",
                kind.glyph, t("manager.discovery.no_picture"))
        if own:
            _enlarges(pic, partial(mediaview.open_pages, [
                art.media(scene.game_id, own[0], version=own[1], size=art.PANEL)], kind.label))
        with ui.column().classes("gap-0 grow min-w-0"):
            ui.label(_head(record) if record else short_name(name, scene.title)) \
                .classes("truncate").tooltip(name)
            ui.label(_source_line()).classes("manager-help truncate")
        with ui.row().classes("items-center gap-1 no-wrap shrink-0"):
            if kind.records:
                panel.icon_action(
                    t("manager.discovery.match"), partial(_match_held, context, scene, kind, name),
                    icon=verbs.MATCH, hint=t("manager.discovery.match"))()
            if later := _newer(context, scene, held):
                ui.label(t("manager.discovery.update.row", version=later)).classes("manager-label")
            ui.label(t("manager.discovery.have")).classes("manager-have")


def _newer(context: dict[str, Any], scene: Scene, held: dict[str, str]) -> str:
    """The version VPS lists now for the release a held file is tied to, where that is later
    than when it was tied and the update has not been skipped or ignored."""
    file_id = str(held.get("vps_file_id") or "")
    if not file_id or not scene.game_id:
        return ""
    return next((str(move["now"]) for move in context["library"].update_moves(scene.game_id)
                 if move["release_id"] == file_id), "")


def _looked(context: dict[str, Any], scene: Scene, kind: Kind) -> dict[str, str]:
    """The pictures the pane has read from the source, by release."""
    view = context["state"].get("discovery_views", {}).get((scene.vps_id, kind.key))
    return view.looked if view else {}


def _picture_of(context: dict[str, Any], scene: Scene, kind: Kind) -> Callable[[str], str]:
    """The picture of a release: the one VPS lists, else the one read from the source."""
    def of(vps_file_id: str) -> str:
        record = _record_of(kind, vps_file_id) or {}
        return str(record.get("img_url") or _looked(context, scene, kind).get(vps_file_id, ""))

    return of


def _chooser(context: dict[str, Any], kind: Kind, scene: Scene,
             name: str = "") -> Callable[[str], Awaitable[tuple[str, str] | None]]:
    """The picker of a release, with the pictures the pane has read from the source and, where
    the file is the game's own, its name and picture."""
    async def choose(current: str) -> tuple[str, str] | None:
        looked = _looked(context, scene, kind)
        own = _own_picture(context, scene, kind, name) if name else None
        mine = art.media(scene.game_id, own[0], version=own[1], size=art.CELL) if own else ""
        # The release the file is tied to is that file, as it is on the held row.
        listed = [{**one, "img_url": (mine if current and one.get("vps_file_id") == current
                                      else "") or one.get("img_url")
                   or looked.get(str(one.get("vps_file_id")), "")} for one in kind.records]
        picked = await release_match.ask(
            release_match.Yours(scene.title, name, glyph=kind.glyph, picture=mine),
            listed, bound=current, files=True)
        if not isinstance(picked, str):
            return None
        record = _record_of(kind, picked)
        return (picked, _head(record)) if record else ("", "")

    return choose


@on_page
async def _match_held(context: dict[str, Any], scene: Scene, kind: Kind, name: str) -> None:
    """Tie a file the game holds to the release the person says it is."""
    library, state = context["library"], context["state"]
    held = next((one for one in kind.mine if one.get("name") == name), {})
    chosen = await _chooser(context, kind, scene, name)(str(held.get("vps_file_id") or ""))
    if chosen is None or not scene.game_id:
        return
    try:
        if kind.listed_as == "tableFiles":
            for one in await run.io_bound(library.tables_for, scene.game_id) or ():
                if one.get("filename") == name:
                    await run.io_bound(library.set_table_source, scene.game_id, str(one["id"]),
                                       chosen[0])
        else:
            await run.io_bound(library.set_asset_source, scene.game_id, name, chosen[0])
    except Exception as exc:  # noqa: BLE001 - the file stays; only the tie failed
        logger.warning("manager: could not tie %s to %s", name, chosen[0], exc_info=True)
        ui.notify(t("manager.discovery.tie_failed"), caption=why(exc), type="warning")
        return
    await discovery_get.settle(state, scene.vps_id)


def _release(context: dict[str, Any], scene: Scene, kind: Kind, record: dict[str, Any],
             view: _View, features: bool, picture: str, press: Callable[[str], None]) -> None:
    file_id = str(record.get("vps_file_id") or "")
    wired = False
    with ui.column().classes("gap-0 w-full min-w-0") as shell:
        view.shells[file_id] = shell
        with ui.element("div").classes("manager-rel manager-rel--press") as row:
            with ui.element("div").classes("manager-rel-pic") as pic:
                candidates.thumb(picture, kind.glyph, t("manager.discovery.no_picture"))
            if picture:
                _enlarges(pic, partial(mediaview.open_pages, [picture], kind.label))
            with ui.column().classes("gap-0 grow min-w-0"):
                ui.label(_head(record)).classes("truncate")
                ui.label(_detail(record, features=features)).classes("manager-help truncate")
            discovery_marks.release_mark_glyph(context, file_id)
            _end(context, scene, kind, record, lambda: opened())
        discovery_marks.release_marks(context, row, str(context["discovery"]["name"]),
                                      kind.label, record)
        row.on("click", lambda _event=None: press(file_id))
        noted = ui.column().classes("gap-0 w-full")

        def opened() -> None:
            """Say under the release when its page was opened, and make the row take a file
            dropped on it as that release."""
            nonlocal wired
            at = kind.opened.get(file_id)
            noted.clear()
            if at is None:
                return
            with noted:
                ui.label(t("manager.discovery.opened", when=when.ago(at.get("at"), inline=True))) \
                    .classes("manager-help manager-rel-opened")
            if not wired:
                wired = True
                ours, held_in = _ours(kind)
                discovery_get.use_a_file(
                    context, scene.game_id, shell, ours=ours, held_in=held_in,
                    add_table=kind.listed_as == "tableFiles",
                    match=import_dialog.ReleaseMatch(
                        _chooser(context, kind, scene), vps_file_id=file_id,
                        label=_head(record), picture_of=_picture_of(context, scene, kind)))

        opened()


def _end(context: dict[str, Any], scene: Scene, kind: Kind, record: dict[str, Any],
         opened: Callable[[], None]) -> None:
    """A release's end: the way to its page, then its download glyph, or what its download is
    doing."""
    file_id = str(record.get("vps_file_id") or "")
    offered: Offered | None = context.get("hosted", {}).get(file_id)
    site, page = discovery.site_of(record)
    with ui.row().classes("items-center gap-1 no-wrap shrink-0"):
        if page:
            _way_out(scene, kind, file_id, site, page, discovery.page_is_broken(record), opened)
        if offered is not None:
            _download(context, scene, offered)


def _way_out(scene: Scene, kind: Kind, file_id: str, site: str, page: str, broken: bool,
             opened: Callable[[], None]) -> None:
    async def note() -> None:
        await run.io_bound(opened_pages.note, scene.vps_id, kind.listed_as, file_id, page)
        kind.opened[file_id] = {"vps_file_id": file_id, "at": timestamps.utc_now_iso()}
        opened()

    panel.out(to=page, on_click=note,
              hint=t("manager.discovery.link_broken") if broken
              else t("manager.discovery.open_on", site=site))()


def _download(context: dict[str, Any], scene: Scene, offered: Offered) -> None:
    """The download glyph of a file a source gets, or the file's state while it is on its way."""
    tray, pick = scene.tray, offered.pick
    said = t("manager.discovery.download_from", site=offered.name)

    def rest() -> None:
        panel.icon_action(
            said, partial(discovery_get.get, context, tray, scene.game_id, [pick]),
            icon=verbs.FROM_ONLINE, hint=said)()

    discovery_get.end(
        tray, pick, rest, discovery_get.try_again(context, tray, scene.game_id, pick),
        act=discovery_ext.acts_for(context, tray, lambda: scene.game_id, scene.listed, pick.key))


# ---------------------------------------------------------------------------------------
# Full: yours beside the release pressed


def _card(context: dict[str, Any], scene: Scene, kind: Kind, rows: list[dict[str, Any]],
          view: _View, features: bool, press: Callable[[str], None]) -> None:
    ids = [str(one.get("vps_file_id") or "") for one in rows]
    index = ids.index(view.pressed) if view.pressed in ids else 0
    with ui.element("div").classes("manager-card-pair"):
        with ui.column().classes("gap-1 manager-card"):
            ui.label(t("manager.workbench.yours")).classes("manager-help")
            if kind.mine:
                held = kind.mine[0]
                tied = _record_of(kind, str(held.get("vps_file_id") or ""))
                name = str(held.get("name") or "")
                ui.label(_head(tied) if tied else short_name(name, scene.title)) \
                    .classes("truncate").tooltip(name)
                ui.label(_source_line()).classes("manager-help")
                ui.label(t("manager.discovery.have")).classes("manager-have")
            else:
                panel.state(t("manager.view.missing"), "off")()
        if not rows:
            return
        record = rows[index]
        with ui.column().classes("gap-1 manager-card"):
            with ui.row().classes("items-center gap-1 no-wrap w-full"):
                ui.label(t("manager.discovery.card_of", n=index + 1, count=len(rows))) \
                    .classes("manager-help grow")
                panel.icon_action(
                    t("word.previous"), lambda: press(ids[(index - 1) % len(ids)]),
                    icon=verbs.EARLIER, hint=t("word.previous"), enabled=len(ids) > 1)()
                panel.icon_action(
                    t("word.next"), lambda: press(ids[(index + 1) % len(ids)]),
                    icon=verbs.LATER, hint=t("word.next"), enabled=len(ids) > 1)()
                offered = context.get("hosted", {}).get(ids[index])
                if offered is not None:
                    _download(context, scene, offered)
            src = str(record.get("img_url") or view.looked.get(ids[index]) or "")
            if src:
                with ui.element("div").classes("manager-tile-art"):
                    _art(src, "image", kind.glyph)
            ui.label(_head(record)).classes("truncate")
            ui.label(_detail(record, features=features)).classes("manager-help")
            _authors(context, record)


def _authors(context: dict[str, Any], record: dict[str, Any]) -> None:
    """Every author of the release, each a link to that author's page where the page can open
    one, and the names alone where a release has more than the two its head says."""
    names = [str(name) for name in (record.get("authors") or [])]
    state = context["state"]
    open_author = state.get("open_author")
    if open_author is not None and names:
        async def go(name: str) -> None:
            # The author's page is the list, which Full puts behind the pane.
            state.get("leave_full", lambda: None)()
            await open_author(name)

        with ui.row().classes("items-center gap-x-3 gap-y-0"):
            for name in names:
                panel.link(name, to="/manager?" + deeplink.query(
                    {"view": "discovery", "subject": {"type": vps_find.AUTHOR, "name": name}}),
                    on_click=partial(go, name))()
    elif len(names) > 2:
        ui.label(", ".join(names)).classes("manager-help")


# ---------------------------------------------------------------------------------------
# Pictures


def _size_name(pick: Pick) -> str:
    if pick.size in mediasource.SIZE_NAMES:
        return t(mediasource.SIZE_NAMES[pick.size])
    return pick.size


def _caption(scene: Scene, pick: Pick) -> str:
    source = str((scene.sources.get(pick.source) or {}).get("name") or pick.source)
    size = _size_name(pick)
    return t("manager.discovery.tile_caption", size=size, source=source) if size else source


def _tiles(context: dict[str, Any], scene: Scene, kind: Kind) -> None:
    tray = scene.tray
    with ui.element("div").classes("manager-media-tiles"):
        if kind.held:
            version = str(kind.slot.get("version") or "")
            src = art.media(scene.game_id, kind.media, version=version, size=art.PANEL)
            with ui.column().classes("gap-1 manager-tile manager-tile--yours"):
                with ui.element("div").classes("manager-tile-art") as plate:
                    _art(src, kind.held_family, kind.glyph)
                _enlarges(plate, partial(
                    mediaview.open_viewer, art.media(scene.game_id, kind.media, version=version),
                    kind.media, kind.label))
                with ui.row().classes("items-center gap-2 no-wrap"):
                    ui.label(t("manager.discovery.have")).classes("manager-have")
                    ui.label(_source_line()).classes("manager-help truncate")
        for offer in kind.offers:
            pick = discovery_get.pick_of(offer)
            src = str(offer.get("url") or "")
            with ui.column().classes("gap-1 manager-tile"):
                with ui.element("div").classes("manager-tile-art") as plate:
                    _art(src, kind.family, kind.glyph)
                _enlarges(plate, partial(mediaview.open_viewer, src, pick.kind, kind.label))
                with ui.row().classes("items-center gap-1 no-wrap w-full"):
                    ui.label(_caption(scene, pick)).classes("manager-help truncate grow")
                    discovery_get.end(
                        tray, pick, partial(_get_picture, context, scene, kind, pick),
                        discovery_get.try_again(context, tray, scene.game_id, pick))
                if discovery_pictures.newer(kind, offer):
                    discovery_pictures.set_aside(context, scene, kind)


def _get_picture(context: dict[str, Any], scene: Scene, kind: Kind, pick: Pick) -> None:
    said = t("manager.discovery.download_pic", kind=kind.label)
    panel.icon_action(
        said, partial(discovery_get.get, context, scene.tray, scene.game_id, [pick]),
        icon=verbs.FROM_ONLINE, hint=said)()
