"""Strawman sections, built to be argued with.

Overview exists here to show how the shell holds together, not as a finished page. Where
a page could use real library data it does - a mock number proves nothing, and the checks
below are the validator registry in embryo: each one is a name, a sentence a person can
read, and a predicate.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from typing import Any

from nicegui import run, ui

from common.failures import why
from common.i18n import t
from common.media_specs import media_label_map
from console import dialog as frame
from console import media_fill, needs, offload, panel, verbs
from console.data import Library
from console.on_page import on_page

# name, one-line description, predicate over (game, media entries).
#
# Deliberately shaped the way a real registry would be, so that promoting this is a
# matter of moving it and adding config rather than a rewrite. The description is not
# decoration: it is what the row's finding says, and writing it forces the check to be
# about something a person can act on.
CHECKS: tuple[tuple[str, str, str, Callable[[dict, dict, dict], bool]], ...] = (
    ("rom_missing", t("console.sections.rom_missing"),
     t("console.sections.rom_missing_why"),
     lambda g, m, x: bool(x.get("rom_missing"))),
    ("unmatched", t("console.sections.unmatched"),
     t("console.sections.unmatched_why"),
     lambda g, m, x: not g.get("vps_id")),
    ("no_playfield", t("console.sections.playfield_missing"),
     t("console.sections.playfield_empty"),
     lambda g, m, x: not m.get("playfield", {}).get("present")),
    ("no_backglass", t("console.sections.backglass_missing"),
     t("console.sections.screen_empty"),
     lambda g, m, x: not m.get("backglass", {}).get("present")),
    ("no_media", t("console.sections.media_none"),
     t("console.sections.nothing_found"),
     lambda g, m, x: not any(e.get("present") for kind, e in m.items()
                             if kind in x["collected"])),
    ("no_year", t("console.sections.year_missing"),
     t("console.sections.year_sort"),
     lambda g, m, x: not g.get("year")),
)

# The element Unreadable Folder scrolls to.
METADATA_ID = "console-library-metadata"

# The checks a source can answer, and the kind each one fetches.
FILLS = {"no_playfield": "playfield", "no_backglass": "backglass"}


def rollups(library: Library) -> dict[str, dict[str, Any]]:
    """Per-game facts a check needs that the game payload does not carry.

    Whether a rom is installed is resolved per table, because two builds of one machine
    can declare different ones. A game reads as missing a rom when any of its tables
    declares one that PinMAME's audit says is not there.

    `rom_installed` is three-valued and only `False` counts. `None` is "we could not
    tell" - the audit needs a configured VPX binary, and the name match alone cannot
    see a clone set's parent zip. Treating not-known as missing would report a whole
    library as broken on any machine without VPX.
    """
    out: dict[str, dict[str, Any]] = {}
    for row in library.table_rows():
        fact = out.setdefault(str(row.get("game_id") or ""), {"rom_missing": False})
        if row.get("rom_installed") is False:
            fact["rom_missing"] = True
    return out


def reported(library: Library) -> tuple:
    """The checks this library asks to hear about.

    The library's answer, not this install's: a gap is a fact about the files, so two
    installs reading one library report the same ones. An unreadable policy reports
    everything, which is the answer a fresh library gives anyway.
    """
    hidden = library.hidden_checks()
    return tuple(one for one in CHECKS if one[0] not in hidden)


def findings(library: Library) -> dict[str, list[dict[str, Any]]]:
    """Run the checks this library asks for. Keyed by check, so a section shows counts."""
    collected = library.kept_kinds()["media"]
    # A kind the library does not collect has no column to land on and is not a gap.
    asked = tuple(one for one in reported(library)
                  if one[0] not in FILLS or FILLS[one[0]] in collected)
    out: dict[str, list[dict[str, Any]]] = {key: [] for key, _, _, _ in asked}
    extra = rollups(library)
    for game in library.games:
        entries = library.media.get(game["id"], {})
        facts = {"collected": collected, **extra.get(game["id"], {})}
        for key, _, _, predicate in asked:
            try:
                if predicate(game, entries, facts):
                    out[key].append(game)
            except Exception:
                # A check that throws is a broken check, not a broken library. It
                # reports nothing rather than taking the page down with it.
                continue
    return out


def _bar(fraction: float) -> None:
    with ui.element("div").classes("console-bar w-full"):
        ui.element("div").style(f"width:{max(0.0, min(1.0, fraction)) * 100:.0f}%")


# --- Overview --------------------------------------------------------------------

def media_coverage(library: Library) -> tuple[int, int, list[tuple[str, int]]]:
    """Slots filled, slots in all, and how many games hold each kind, fewest first.

    Only the kinds the library collects, in all three: a kind switched off is not a gap,
    and counting its slots would hold the percentage down for a file nobody wants."""
    kept = library.kept_kinds()["media"]
    held = {kind: 0 for kind in library.kinds() if kind in kept}
    present = total = 0
    for entries in library.media.values():
        for kind, entry in entries.items():
            if kind not in kept:
                continue
            total += 1
            if entry.get("present"):
                present += 1
                held[kind] += 1
    return present, total, sorted(held.items(), key=lambda item: item[1])


def _local_name(registry: list[dict], discovery: dict) -> str:
    from console import devices

    local = discovery.get("install_id")
    entry = next((one for one in registry if one.get("device_id") == local), {})
    return devices.device_label(entry)


def _need_row(need: needs.Need, state: dict[str, Any], fix: Callable[[needs.Need], Any]) -> None:
    """Icon in its tone, label, count in its own unit, the fix, and the whole row opens
    what it counted."""
    row = ui.element("div").classes(f"console-need console-need--{need.tone}") \
        .props("tabindex=0 role=link")
    row.on("click", lambda: state["open_on"](need.opens))
    row.on("keydown.enter", lambda: state["open_on"](need.opens))
    with row:
        ui.icon(need.icon).classes("console-need-icon")
        ui.label(need.label).classes("console-setting grow min-w-0").tooltip(need.tip)
        if said := need.counted():
            ui.label(said).classes("console-need-count shrink-0")
        if need.fix is not None:
            with ui.element("div").classes("console-need-fix").on("click.stop", lambda: None):
                panel.icon_action(need.fix.label, lambda: fix(need), icon=need.fix.icon,
                                  hint=need.fix.tip)()


def _needs_you(rows: list[needs.Need], state: dict[str, Any],
               fix: Callable[[needs.Need], Any]) -> None:
    ui.label(t("console.needs.title")).classes("console-group")
    with ui.element("div").classes("console-card console-needs"):
        if not rows:
            with ui.row().classes("items-center gap-3 w-full no-wrap"):
                ui.icon("check_circle").classes("console-need-icon console-need--none")
                ui.label(t("console.needs.nothing")).classes("console-setting grow")
                panel.action(t("console.needs.choose_checks"),
                             lambda: state["open_on"](needs.Opens(
                                 "settings", keys={"settings_page": "library.audit"})),
                             icon=verbs.GO, hint=t("console.needs.choose_checks.help"))()
            return
        for need in rows:
            _need_row(need, state, fix)


def _coverage(library: Library) -> None:
    present, total_slots, counts = media_coverage(library)
    ui.label(t("console.sections.coverage_kind")).classes("console-group")
    with ui.element("div").classes("console-card w-full"):
        ui.label(f"{(present / total_slots * 100 if total_slots else 0):.0f}%") \
            .classes("console-kpi")
        _bar(present / total_slots if total_slots else 0)
        ui.label(t("console.sections.slots", present=present, total_slots=total_slots)) \
            .classes("text-xs opacity-60")
        # A filter says which games lack a topper. Nothing in a grid says "you have no
        # toppers at all" without filtering twenty kinds one at a time, which is the
        # one thing a rollup does that a lens cannot.
        for kind, held in counts:
            with ui.row().classes("items-center gap-3 w-full no-wrap py-1"):
                ui.label(media_label_map().get(kind, kind)) \
                    .classes("console-setting w-40 shrink-0")
                with ui.element("div").classes("grow min-w-0"):
                    _bar(held / len(library.games) if library.games else 0)
                ui.label(t("console.sections.held_of_games", held=held,
                           total=len(library.games))) \
                    .classes("text-xs opacity-60 shrink-0")


def overview(library: Library, registry: list[dict], discovery: dict,
             go: Callable[[str], None], state: dict[str, Any]) -> None:
    rows = needs.collect(library, state)

    def placed(game_ids: tuple[str, ...]) -> None:
        for game_id in game_ids:
            library.forget_media(game_id)
        if state.get("view") == "overview":
            go("overview")

    def fix(need: needs.Need) -> Any:
        if need.fix is None:
            return None
        if need.fix.key == needs.GET_MEDIA:
            return media_fill.confirm_kind(list(need.ids), need.fix.kind, state,
                                           lambda: placed(need.ids))
        from console import devices

        return devices.confirm_update(library, _local_name(registry, discovery),
                                      library.watched().get("update") or {})

    def drawn_again() -> None:
        if state.get("view") == "overview":
            go("overview")

    # The container the two columns answer to: this page's own width, not the window's,
    # which the workbench pane shares.
    with ui.element("div").classes("console-overview"), \
            ui.element("div").classes("console-overview-columns"):
        with ui.element("div").classes("console-overview-main"):
            _needs_you(rows, state, fix)
            with ui.element("div").props(f"id={METADATA_ID}"):
                metadata(library.metadata_state(), _metadata_action(library, state, drawn_again),
                         state.get(_LEFT))
            table_scripts(library)
        with ui.element("div").classes("console-overview-side"):
            _coverage(library)


# --- The library's own metadata ---------------------------------------------------
#
# The upgrade rewrites a file in every game folder, so it asks first and says what it
# costs. It keeps a copy of each, and the Backups page puts them back.


_ASKS = {
    "upgrade": (t("console.sections.upgrade_confirm"),
                t("console.sections.backup_note"),
                t("word.upgrade"), verbs.ACCEPT, False),
}


_POLL_S = 1.0
_POLLS = 3600
_LEFT = "metadata_left"


def _metadata_action(library: Library, state: dict[str, Any],
                     then: Callable[[], None]) -> Callable[[str], Any]:
    """Ask, start the job, say it is under way, and say what came of it once it ends."""
    from console import confirm
    from console.api import ApiClient

    @on_page
    async def start(which: str) -> None:
        title, detail, word, icon, danger = _ASKS[which]
        if not await confirm.ask(title, detail=detail, confirm=word, icon=icon, danger=danger):
            return
        client = ApiClient()
        try:
            job = await offload.io(client.upgrade_info)
        except Exception as exc:
            ui.notify(t("said.start_failed"), caption=why(exc), type="negative")
            return
        ui.notify(t("console.sections.way", word=(word)), type="positive")
        watch = state.get("watch_jobs")
        if callable(watch):
            watch()
        found = await _ended(client, str(job.get("id") or ""))
        if found is None:
            return
        # The counts this card is drawn from are now stale. Asked again off the loop,
        # for the same reason they were read there in the first place.
        await run.io_bound(library.read_metadata_state)
        left: list[tuple[str, str]] = []
        if found.get("state") == "failed":
            ui.notify(t("console.sections.upgrade_failed"),
                      caption=str(found.get("error") or ""), type="negative")
        else:
            said, left = upgrade_outcome(found.get("result") or {}, library.metadata_state())
            ui.notify(said, type="warning" if left else "positive")
        state.setdefault(_LEFT, {})[which] = left
        then()

    return start


async def _ended(client: Any, job_id: str) -> dict[str, Any] | None:
    """The job once it is no longer running, or None if it could not be asked."""
    for _ in range(_POLLS):
        await asyncio.sleep(_POLL_S)
        try:
            found = await offload.io(client.job, job_id)
        except Exception:  # noqa: BLE001 - the footer line still reports it
            return None
        if found.get("state") != "running":
            return found
    return None


def _failures(result: dict[str, Any]) -> list[tuple[str, str]]:
    return [(str(one[0]), str(one[1])) for one in result.get("failures") or ()]


def upgrade_outcome(result: dict[str, Any],
                    metadata: dict[str, Any]) -> tuple[str, list[tuple[str, str]]]:
    """What a finished upgrade says, and each folder it left that is still waiting for
    one, with why."""
    waiting = set(metadata.get("pending_games") or ())
    left = [one for one in _failures(result) if one[0] in waiting]
    done = int(result.get("upgraded") or 0)
    if left and done:
        return t("console.sections.upgraded_some", done=done, total=done + len(left)), left
    if left:
        return t("console.sections.upgrade_count_failed", count=len(left)), left
    return t("console.sections.upgraded", count=done), left


# --- The library's own metadata, drawn ---------------------------------------------
#
# Every game folder carries a `.info`: its id, its catalog match, your rating and how
# often you have played it. It is where the library actually lives, and the grid is a
# view of it. Three things can be true of one that are worth acting on, and they are not
# the same thing as a game being short of a rom or a wheel image - which is why this is
# its own card rather than another row in the one above.


def _first_of(names: list[str], most: int) -> str:
    listed = ", ".join(names[:most])
    return t("console.sections.more", names=listed) if len(names) > most else listed


def _folder_lines(rows: list[tuple[str, str]], most: int = 4) -> list[tuple[str, str]]:
    lines = rows[:most]
    if len(rows) > most:
        lines.append((t("said.and_more", count=len(rows) - most), ""))
    return lines


def _metadata_row(good: bool, name: str, said: str,
                  action: tuple[str, Callable[[], Any]] | None = None,
                  lines: list[tuple[str, str]] | None = None) -> None:
    with ui.row().classes("items-center gap-3 w-full no-wrap py-1"):
        ui.icon("check_circle" if good else "error", size="18px") \
            .classes("text-positive" if good else "text-warning")
        with ui.column().classes("gap-0 grow min-w-0"):
            ui.label(name).classes("console-setting")
            ui.label(said).classes("console-help")
            for text, hover in lines or []:
                panel.line(text, hint=hover)
        if action is not None:
            label, run = action
            ui.button(label, icon=verbs.GO, on_click=run) \
                .props("flat dense no-caps size=sm").classes("shrink-0")


def metadata(state: dict[str, Any], on_start: Callable[[str], Any],
             left: Mapping[str, list[tuple[str, str]]] | None = None) -> None:
    """What the library's metadata files need, and the way to act on it.

    Drawn whole rather than only when something is wrong, the same as the card above it:
    a section that comes and goes cannot be looked for, and "everything is current" is
    worth being able to check rather than infer from an absence.

    `left` is each folder the last Upgrade could not write, with why.
    """
    ui.label(t("console.sections.library_metadata")).classes("console-group mt-4")
    with ui.element("div").classes("console-card w-full"):
        _metadata_rows(state, on_start, left)


def _metadata_rows(state: dict[str, Any], on_start: Callable[[str], Any],
                   left: Mapping[str, list[tuple[str, str]]] | None = None) -> None:
    pending = int(state.get("pending_upgrade") or 0)
    unreadable = list(state.get("unreadable") or [])
    unwritten = [(str(row["folder"]), str(row.get("error") or ""))
                 for row in state.get("unwritten") or []]
    newer = int(state.get("newer_than_us") or 0)
    left = left or {}
    named = dict([*unwritten, *(left.get("upgrade") or [])])

    _metadata_row(
        not pending and not unwritten, t("console.sections.format"),
        " · ".join(said for said in (
            t("console.sections.written_older", count=pending) if pending else "",
            t("console.sections.could_not_write", count=len(unwritten))
            if unwritten else "") if said)
        or t("console.sections.format_current"),
        None if not pending else (t("word.upgrade"),
                lambda: on_start("upgrade")),
        lines=_folder_lines(sorted(named.items(), key=lambda row: row[0].lower())))

    # No action: the fix is on disk, in a file this cannot repair without guessing
    # what it was meant to say. Naming the folders, and why, is the whole of the help.
    _metadata_row(
        not unreadable, t("console.sections.readable"),
        t("console.sections.metadata_readable") if not unreadable
        else t("console.sections.unreadable_one") if len(unreadable) == 1
        else t("console.sections.unreadable_many", count=len(unreadable)),
        lines=_folder_lines([(str(row["folder"]), str(row.get("error") or ""))
                             for row in unreadable]))

    # Only when it is true. A row saying "nothing here was written by a newer build"
    # is a sentence about a thing that has never happened to most installs.
    if newer:
        _metadata_row(
            False, t("console.sections.newer_build"),
            t("console.sections.written_later", newer=(newer)))


def _line_said(state: Mapping[str, Any]) -> str:
    """What the Games page says about the library's metadata, or "" for nothing."""
    missing = len(state.get("unreadable") or ())
    pending = int(state.get("pending_upgrade") or 0)
    unwritten = len(state.get("unwritten") or ())
    return " · ".join(said for said in (
        t("console.sections.unlisted", count=missing) if missing else "",
        t("console.sections.older_format", count=pending) if pending else "",
        t("console.sections.not_written", count=unwritten) if unwritten else "") if said)


def metadata_line(library: Library, state: dict[str, Any]) -> None:
    """The line above the Games grid, drawn only while `_line_said` has something to
    say, with the metadata card's rows in a dialog behind it."""
    outer = ui.element("div").classes("w-full shrink-0")
    with outer:
        line = ui.element("div").classes("w-full")
    held: dict[str, Any] = {}

    def draw() -> None:
        line.clear()
        said = _line_said(library.metadata_state())
        if not said:
            return
        with line, ui.element("div").classes("console-attention mb-2"):
            ui.icon("error_outline").classes("console-attention-icon")
            ui.label(said).classes("console-attention-line grow")
            panel.action(t("console.sections.show"), show, icon=verbs.GO,
                         hint=t("console.sections.show_metadata.help"))()

    def fill() -> None:
        body = held.get("body")
        if body is None or body.is_deleted:
            return
        body.clear()
        with body:
            _metadata_rows(library.metadata_state(), act, state.get(_LEFT))

    def drawn_again() -> None:
        if outer.is_deleted:
            return
        draw()
        fill()

    act = _metadata_action(library, state, drawn_again)

    def show() -> None:
        box = held.get("box")
        if box is None or box.is_deleted:
            # In `outer` rather than beside the button, so a redraw of the line leaves
            # the dialog open.
            with outer, frame.opened(t("console.sections.library_metadata"),
                                     wide=True) as box:
                held["body"] = ui.column().classes("w-full gap-0 px-3")
                with frame.footer():
                    frame.cancel(box.close, t("word.close"))
            held["box"] = box
        fill()
        box.open()

    draw()


# --- The scripts the tables run ---------------------------------------------------
#
# Standalone runs the same tables the Windows build does, and a good many of them need a
# small script change to do it. The community keeps an index of those fixes, matched on
# the hash of the script a table actually runs rather than on its name - one table's
# script appears under a dozen filenames, and a fix is only correct for the bytes it was
# built against. A fix arrives as a `.vbs` sidecar, which the program runs in place of
# the script the table ships with.


def _scripts_said(found: dict[str, Any]) -> tuple[bool, str]:
    """Whether this is worth acting on, and the sentence for it."""
    if found.get("reachable") is False:
        # Not the same as nothing to do, and it must not read that way: the library was
        # never examined.
        return False, t("console.sections.index_unreachable")
    offered = list(found.get("offered") or [])
    checked = int(found.get("checked") or 0)
    already = int(found.get("already") or 0)
    if offered:
        return False, t("console.sections.fixable", count=len(offered),
                checked=(checked), shown=_first_of(offered, 3))
    running = t("console.sections.already_run", already=(already)) if already else ""
    return True, t("console.sections.no_matches", checked=(checked),
            running=(running))


def table_scripts(library: Library) -> None:
    """What the published index has for this library, once somebody asks.

    Asked rather than read on every draw. It is a request to somebody else's server, and
    a page that waited on it would be slow for a question most visits are not asking.
    """
    from console import confirm
    from console.api import ApiClient

    ui.label(t("console.sections.table_scripts")).classes("console-group mt-4")
    card = ui.element("div").classes("console-card w-full")

    def draw() -> None:
        card.clear()
        found = library.script_patches()
        with card:
            if not found:
                _metadata_row(
                    True, t("console.sections.script_fixes"),
                    t("console.sections.script_fixes_note"),
                    (t("console.sections.check"), check))
                return
            good, said = _scripts_said(found)
            _metadata_row(good, t("console.sections.script_fixes"), said,
                          (t("word.fetch"), fetch)
                          if found.get("offered")
                          else (t("console.sections.check"), check))

    async def check() -> None:
        await run.io_bound(library.read_script_patches)
        draw()

    @on_page
    async def fetch() -> None:
        offered = list(library.script_patches().get("offered") or [])
        if not await confirm.ask(
                t("console.sections.fetch_confirm", count=len(offered)),
                detail=t("console.sections.script_fixes_how"),
                confirm=t("word.fetch"), icon=verbs.FETCH, danger=False):
            return
        try:
            await run.io_bound(ApiClient().apply_script_patches)
        except Exception as exc:
            ui.notify(t("console.sections.fetch_failed"), caption=why(exc),
                      type="negative")
            return
        ui.notify(t("console.sections.fetching_way"), type="positive")
        await run.io_bound(library.read_script_patches)
        draw()

    draw()
