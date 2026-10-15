"""The release match: the line, its buttons and the record and release pickers."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from nicegui import run, ui

from common import icons
from common.failures import why
from common.i18n import t
from common.online import vps_kinds
from manager.kit import (
    candidates,
    deeplink,
    game_tables,
    offload,
    panel,
    table_features,
    verbs,
    when,
)
from manager.kit.on_page import on_page
from manager.library import file_acts, release_match, vps_match
from manager.workbench.core import _write

logger = logging.getLogger("vpinfe.manager.workbench.game_match")


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
    with ui.row().classes("items-center gap-2 w-full no-wrap manager-member-table-line"):
        ui.label(told or t("manager.workbench.delisted_table")) \
            .classes("manager-help truncate")
    _based_on(source.get("mod_of"), "manager-member-table-line")


def _based_on(mod: dict[str, Any] | None, classes: str = "") -> None:
    """What a table's release is a mod of, one level up: the way to that table where the
    library holds it, in whichever game, and Missing with the way to VPS where not."""
    line = game_tables.mod_line(mod)
    if not mod or not line:
        return
    with ui.row().classes(f"items-center gap-2 w-full no-wrap min-w-0 {classes}"):
        if mod.get("table_id"):
            panel.link(line, to="/manager?" + deeplink.query(
                {"view": "tables", "game": str(mod.get("game_id") or ""),
                 "table": str(mod["table_id"])}))()
            return
        ui.label(line).classes("manager-help truncate min-w-0")
        if not mod.get("vps_file_id"):
            return
        word, why = game_tables.GONE_WORDS
        ui.label(word).tooltip(why) \
            .classes("manager-member-chip manager-tier manager-tier--off")
        if mod.get("url"):
            panel.out(to=str(mod["url"]), hint=t("manager.vps_match.open_in_vps"))()


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
        button.tooltip(t("manager.workbench.release"))
        return
    # A release belongs to an entry, so there is nothing to choose among until the
    # game is matched. Said on the control rather than in a dialog that opens empty.
    button.disable()
    button.tooltip(t("manager.workbench.releases_unmatched"))


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
        logger.warning("manager: could not read %s for %s", listed.listed_as, vps_id,
                       exc_info=True)
        return t("manager.workbench.matched_file")
    for record in records:
        if str(record.get("vps_file_id") or "") == said:
            told = " · ".join(part for part in (
                str(record.get("version") or ""),
                ", ".join(str(name) for name in (record.get("authors") or [])[:2]),
            ) if part)
            return t("manager.workbench.matched",
                    told=(told)) if told else t("manager.workbench.matched_file")
    # Worth saying: it is why no update will ever be reported for this file.
    return (t("manager.workbench.delisted_file") if held
            else t("manager.workbench.matched_file"))


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
    button = ui.button(t("manager.workbench.change_match_2") if bound
            else t("manager.workbench.match"), icon=verbs.MATCH,
                       on_click=lambda: _pick_a_record(context, listed.listed_as,
                                                       label, path, bound, redraw)) \
        .props("flat dense no-caps size=sm").classes("manager-action")
    if context["game"].get("vps_id"):
        button.tooltip(t("manager.workbench.published_file"))
        return
    # The records belong to an entry, so there is nothing to choose among until the
    # game is matched. Said on the control rather than in a dialog that opens empty.
    button.disable()
    button.tooltip(t("manager.workbench.files_unmatched"))


@on_page
async def _pick_a_record(context: dict[str, Any], listed_as: str, label: str,
                         path: str, bound: str,
                         redraw: Callable[[], None]) -> None:
    """Bind one file to a record VPSdb publishes, or take the binding back.

    The assets ledger's twin of `_pick_a_release`.
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
        context, t("manager.workbench.kind_unlisted", kind=label), listed_as)
    name = Path(path).name or path
    return await release_match.ask(
        release_match.Yours(name=name, file=name, facts=label, glyph="inventory_2"),
        records, bound=bound, empty=empty, reason=reason, place=place, files=True)


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
        logger.warning("manager: could not read VPS for %s", vps_id, exc_info=True)
        return [], t("manager.workbench.vps_failed"), why(exc)
    if found:
        return found, "", ""
    return [], none_listed if held else t("manager.workbench.no_vps_data"), ""


@on_page
async def _pick_a_release(context: dict[str, Any], table: dict[str, Any]) -> None:
    """Bind this table to one of the entry's builds, or take the binding back."""
    library = context["library"]
    bound = str((table.get("source") or {}).get("vps_file_id") or "")
    releases, empty, reason = await _listed_by_vps(
        context, t("manager.workbench.tables_unlisted"))

    picked = await release_match.ask(
        _yours(table), releases, bound=bound,
        formats=[str(one) for one in table.get("vps_formats") or []],
        empty=empty, reason=reason)
    if picked is None:
        return
    await _write(context, library.set_table_source, context["game_id"],
                 str(table.get("id") or ""), str(picked))


def _yours(table: dict[str, Any]) -> release_match.Yours:
    """What this file says about itself, as a row of the list it is compared against.

    A `.vpx` carries a version and its authors and VPS names releases by the same two,
    which is the only honest handle here - VPS records a filename on almost none of them.
    """
    version = str(table.get("version") or "")
    authors = tuple(str(name) for name in (table.get("authors") or []))
    filename = str(table.get("filename") or "")
    told = game_tables.JOIN.join(part for part in (version, ", ".join(authors[:4])) if part)
    facts = [", ".join(str(one) for one in table.get("vps_formats") or [])]
    held = table.get("features") or {}
    facts += [label for key, label in table_features.LABELS.items() if held.get(key) is True]
    if table.get("release_date"):
        facts.append(t("manager.release_match.released", when=when.ago(table["release_date"])))
    return release_match.Yours(
        name=told or filename, file=filename, authors=authors,
        facts=game_tables.JOIN.join(part for part in facts if part), version=version)


def _release_words(release: dict[str, Any]) -> tuple[str, str]:
    """A build's name and the line under it: its version, then format, makers and date."""
    meta = [str(release.get("format") or "")]
    made_by = ", ".join(str(name) for name in (release.get("authors") or [])[:3])
    if made_by:
        meta.append(made_by)
    if release.get("updated_at"):
        meta.append(when.ago(release["updated_at"]))
    name = str(release.get("version") or "") or t("manager.workbench.no_version")
    return name, " \u00b7 ".join(part for part in meta if part)


def _release_shown(release: dict[str, Any]) -> None:
    """The build a table is matched to, in the shape the picker offered it."""
    url = str(release.get("url") or "")

    def end() -> None:
        if url:
            panel.out(to=url, hint=t("manager.workbench.open_release"))()

    name, meta = _release_words(release)
    candidates.choice(str(release.get("img_url") or ""), name, meta,
                      glyph=icons.TABLES, trailing=end, entry=True,
                      more=_mod_note(release), missing=vps_match.NO_PICTURE)


def _mod_note(release: dict[str, Any]) -> tuple[str, ...]:
    """The lines VPS's note adds under a mod's build row; none for any other release."""
    comment = str(release.get("comment") or "").strip()
    is_mod = release.get("mod_of") or "MOD" in (release.get("features") or [])
    return (comment,) if comment and is_mod else ()


async def _read_releases(context: dict[str, Any],
                         vps_id: str) -> tuple[list[dict[str, Any]], str]:
    """The entry's builds, read off the loop, and why they could not be read. Empty
    where they were."""
    if not vps_id:
        return [], ""
    try:
        return list(await offload.io(context["library"].vps_releases, vps_id)), ""
    except Exception as exc:
        logger.warning("manager: could not read VPS for %s", vps_id, exc_info=True)
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
            ui.notify(t("manager.workbench.launch_failed"), caption=why(exc), type="negative")

    button = ui.button(icon="play_arrow", on_click=go) \
        .props("flat dense round size=sm").tooltip(t("manager.workbench.play_table"))
    if not table.get("available"):
        button.disable()


def _default_mark(context: dict[str, Any], table: dict[str, Any], *,
                  several: bool) -> None:
    """Which table the game offers, and the way to change it. A table that cannot be the
    default is shown unset, with why."""
    chosen = bool(table.get("default"))
    mark = ui.icon("radio_button_checked" if chosen else "radio_button_unchecked") \
        .classes("manager-default-mark")
    if chosen:
        mark.classes(add="manager-default-mark--on")
        automatic = several and (table.get("default_kind") or "") == game_tables.DERIVED
        mark.tooltip(game_tables.DEFAULT_WORDS[game_tables.DERIVED][1] if automatic
                     else t("manager.workbench.offered_table"))
        return
    if why := game_tables.why_not_default(table):
        mark.classes(add="opacity-30")
        mark.tooltip(why)
        return
    mark.classes(add="cursor-pointer")
    mark.tooltip(t("manager.workbench.make_default"))
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
        ui.notify(t("manager.workbench.change_failed"), caption=why(exc), type="negative")
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
        ui.notify(t("manager.workbench.change_failed"), caption=why(exc), type="negative")
        return
    ui.notify(game_tables.now_plays(str(context["game"].get("name") or ""), table),
              type="positive")
    await context["rebuild"]()
