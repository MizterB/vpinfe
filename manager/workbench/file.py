"""The file subject: media and asset files, the backglass facts and their actions."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from functools import partial
from pathlib import PurePosixPath
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlencode

from nicegui import run, ui

from common.config import path_state
from common.failures import why
from common.games import asset_registry
from common.games.asset_resolver import VPX_ASSET_KINDS
from common.i18n import t
from manager.kit import art, confirm, deeplink, media_ownership, offload, panel, verbs, when
from manager.kit.data import Library, config_groups
from manager.kit.on_page import on_page
from manager.library import backglass_view, file_acts, mediasource, mediaview, text_editor
from manager.library import record as recorder
from manager.workbench.all_settings import (
    PLAYING_NOTE,
    PLAYING_WHY,
    _config_values,
    _keeping_place,
    _playing,
    _program_state,
    _setting_entries,
    config_applied,
    curated_blocks,
    no_longer_reads_game,
    switches,
)
from manager.workbench.core import _asset_name, _outside_lines, _table_line
from manager.workbench.game_match import _match_line
from manager.workbench.game_media import _file_line, _on_disk, _slot, _slot_art
from manager.workbench.game_table import _alert, _drop_script, _state
from manager.workbench.launcher import _launchers_for_panel

logger = logging.getLogger("vpinfe.manager.workbench.file")


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


def _file_title(target: ui.column, row: dict[str, Any], game: dict[str, Any],
                table: dict[str, Any] | None) -> None:
    with target:
        name = str(row.get("named") or row.get("label") or row.get("kind") or "")
        ui.label(name).classes("text-base manager-workbench-title leading-tight truncate") \
            .tooltip(name)
        with ui.element("div").classes("text-xs manager-workbench-label "
                                       "manager-workbench-links"):
            panel.link(str(game.get("name") or ""), to="/manager?" + deeplink.query(
                {"view": "games", "game": game["id"]}))()
        orphan = file_acts.tier_of(row) == media_ownership.ORPHAN
        if table is None and not orphan:
            return
        with ui.element("div").classes("manager-workbench-table manager-workbench-links"):
            if table is not None:
                panel.link(_table_line(table), to="/manager?" + deeplink.query(
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
        return ui.element("div").classes("manager-stage")


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
        with _stage(context), ui.element("div").classes("manager-slot-art"):
            mediaview.preview("/api/v1/filesystem/file?" + urlencode(
                {"path": str(PurePosixPath(folder) / path)}), kind,
                str(row.get("label") or kind))
    with ui.column().classes("w-full gap-1 manager-slot p-2"):
        with ui.column().classes("w-full gap-0 manager-slot-facts"):
            with ui.row().classes("items-start gap-2 w-full no-wrap"):
                where = _on_disk(context, path)
                named = ui.label(path or str(row.get("file") or "")) \
                    .classes("manager-slot-file grow min-w-0")
                if where:
                    named.tooltip(where)
                    panel.copy_text(where)
                media_ownership.badge(tier)
            ui.label(t(media_ownership.tier_for(tier).why)).classes("manager-help")


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
        return t("manager.workbench.inert_asset")
    if (tier == media_ownership.GAME and not lens
            and len(context["served"]) < len(context["tables"])):
        return t("manager.workbench.shared_by_some")
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
            ui.label(t("manager.workbench.missing_table", kind=label)
                     if context["lens"]
                     else t("manager.workbench.missing_game", kind=label)) \
                .classes("manager-help")
            return
        with ui.row().classes("items-start gap-2 w-full no-wrap"):
            _file_line(context, kind, path, str(context.get("link_view") or ""), path)
            if tier not in media_ownership.SCOPES:
                media_ownership.badge(tier)
            if glass and not glass["damaged"]:
                _backglass_chips(glass)
        spec = _asset_spec(detail)
        if spec:
            spoken["spec"] = ui.label(spec).classes("manager-help")
        if glass and glass["damaged"]:
            _alert(t("manager.backglass.damaged"), None)()
        elif glass and facts:
            panel.facts(ui, _backglass_facts(context, glass))
        said = _asset_said(context, tier)
        if said:
            ui.label(said).classes("manager-help")
        origin = str(row.get("origin") or "")
        if origin and origin not in ("unknown", "user"):
            ui.label(t("manager.workbench.source",
                       source_name=media_ownership.source_name(origin))) \
                .classes("manager-help")
        _outside_lines(links)

    def acts() -> None:
        _asset_actions(context, kind, label, present, path, tier, detail)

    if context.get("link_view"):
        with ui.column().classes("w-full gap-1 manager-slot p-2"):
            with ui.column().classes("w-full gap-0 manager-slot-facts"):
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
            entries += [(panel.HEADING, t("manager.workbench.details")),
                        *((panel.READ, entry) for entry in about)]
        if "file_settings" in context:
            entries += await _file_settings_entries(context)
        return entries

    first = await form_entries()
    with ui.column().classes("w-full gap-0 manager-form") as form:
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
    with ui.element("div").classes("manager-slot-art manager-slot-art--text"):
        ui.label(head).classes("manager-file-text")
        _enlarge(lambda: _open_whole(context, path, label))


def _enlarge(act: Callable[[], Any]) -> None:
    ui.button(icon=verbs.ENLARGE, on_click=act).props("flat dense round size=sm") \
        .classes("manager-slot-zoom").tooltip(t("word.enlarge"))


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
    with ui.element("div").classes("manager-slot-art"):
        mediaview.preview(art.backglass(game_id, path, version=glass["version"],
                                        size=art.PANEL), "backglass", label)
        _enlarge(lambda: mediaview.open_image(
            art.backglass(game_id, path, version=glass["version"]), label))


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
        ui.label(t("manager.backglass.two_versions")) \
            .classes("manager-tier manager-tier--unknown") \
            .tooltip(t("manager.backglass.two_versions.hint"))
    if glass["still"]:
        ui.label(t("manager.backglass.still")).classes("manager-tier manager-tier--unknown") \
            .tooltip(t("manager.backglass.still.hint"))


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
        entries.append((t("manager.backglass.artwork"), glass["artwork"]))
    if glass["rom"]:
        roms = _backglass_roms(context)
        differs = any(rom.lower() != glass["rom"].lower() for rom in roms)
        entries.append((t("manager.backglass.rom"),
                        _state(t("manager.backglass.different"), "warn", beside=glass["rom"],
                               hint=t("manager.backglass.different.hint", rom=", ".join(roms)))
                        if differs else glass["rom"]))
    if glass["players"]:
        entries.append((t("manager.backglass.players"), str(glass["players"])))
    if glass["size"]:
        wide, high = glass["size"]
        shown = t("manager.workbench.width_by_height", width=wide, height=high)
        entries.append((t("manager.backglass.picture"), _hinted(
            shown, t("manager.backglass.picture.hint", grill=glass["grill"]))
            if glass["grill"] else shown))
    if glass["scoreview_art"]:
        wide, high = glass["scoreview_art"]
        entries.append((t("manager.backglass.score_art"),
                        t("manager.workbench.width_by_height", width=wide, height=high)))
    return entries


def _hinted(text: str, hint: str) -> Callable[[], None]:
    def draw() -> None:
        ui.label(text).classes("manager-fact-value truncate min-w-0").tooltip(hint)

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
        from manager.workbench import app_settings
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
        entries[:0] = [(panel.HEADING, t("manager.section.settings")), panel.intro(
            t("manager.workbench.writes_to_tables", count=len(shared)),
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
            ui.notify(t("manager.backglass.damaged"), type="warning")
        else:
            await fit()

    return panel.FULL, panel.action(
        t("manager.backglass.dmd_fit"), press, icon=verbs.FIT,
        hint=t("manager.backglass.dmd_fit.hint"), enabled=not inner.get("playing"))


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
    with ui.row().classes("items-center gap-2 w-full manager-slot-actions"):
        if not loose:
            ui.button(t("word.replace") if present else t("word.add"),
                      icon=verbs.REPLACE if present else verbs.ADD,
                      on_click=lambda: mediasource.open_asset_sources(
                          context, kind, label, context["rebuild"], path)) \
                .props("flat dense no-caps size=sm").classes("manager-action")
        if not (present and path):
            return
        if kind == "script" and table is not None and tier == media_ownership.TABLE:
            ui.button(t("word.delete"), icon=verbs.DELETE,
                      on_click=lambda: _drop_script(context, table)) \
                .props("flat dense no-caps size=sm") \
                .classes("manager-action manager-action--danger")
        else:
            ui.button(t("word.remove"), icon=verbs.REMOVE,
                      on_click=lambda: _remove_asset(context, kind, path, tier)) \
                .props("flat dense no-caps size=sm") \
                .classes("manager-action manager-action--danger")


def _folder_actions(context: dict[str, Any], kind: str, label: str, present: bool,
                    path: str, files: int) -> None:
    with ui.row().classes("items-center gap-2 w-full manager-slot-actions"):
        panel.action(t("word.replace") if present else t("word.add"),
                     lambda: mediasource.open_folder_sources(context, kind, label,
                                                             context["rebuild"], path),
                     icon=verbs.REPLACE if present else verbs.ADD,
                     hint=t("manager.workbench.folder_source.help"))()
        if present and path:
            ui.button(t("word.remove"), icon=verbs.REMOVE,
                      on_click=lambda: _remove_asset(context, kind, path, "", files=files)) \
                .props("flat dense no-caps size=sm") \
                .classes("manager-action manager-action--danger")


@on_page
async def _remove_asset(context: dict[str, Any], kind: str, path: str, tier: str,
                        files: int | None = None) -> None:
    detail = file_acts.asset_removal_detail(kind, tier, files)
    if not await confirm.ask(t("manager.workbench.remove_asset", name=PurePosixPath(path).name),
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
        parts.append(t("manager.workbench.files_in_folder", count=int(detail.get("files") or 0)))
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
        ui.notify(t("manager.workbench.read_failed"), caption=why(exc),
                  type="negative")
        return
    text_editor.show_whole(label, str(found.get("head") or ""))
