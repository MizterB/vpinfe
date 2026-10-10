"""Strawman sections, built to be argued with.

Overview exists here to show how the shell holds together, not as a finished page. Where
a page could use real library data it does - a mock number proves nothing, and the checks
below are the validator registry in embryo: each one is a name, a sentence a person can
read, and a predicate.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from nicegui import run, ui

from common.failures import why
from common.i18n import t
from common.media_specs import media_label_map
from console import dialog as frame
from console import (
    front,
    jobs_list,
    media_fill,
    needs,
    offload,
    panel,
    set_aside,
    verbs,
    when,
)
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

def kind_holdings(library: Library) -> list[tuple[str, int]]:
    """How many games hold each kind the library collects, fewest first.

    Only the kinds collected: a kind switched off is not a gap, and listing it would offer
    a bar for a file nobody wants."""
    held = {kind: 0 for kind in library.kinds() if kind in library.kept_kinds()["media"]}
    ids = {game["id"] for game in library.games}
    for game_id, entries in library.media.items():
        if game_id not in ids:
            continue
        for kind, entry in entries.items():
            if kind in held and entry.get("present"):
                held[kind] += 1
    return sorted(held.items(), key=lambda item: (item[1], item[0]))


def _local_name(registry: list[dict], discovery: dict) -> str:
    from console import devices

    local = discovery.get("install_id")
    entry = next((one for one in registry if one.get("device_id") == local), {})
    return devices.device_label(entry)


def _need_menu(menu: Any, need: needs.Need, fix: Callable[..., Any],
               acts: set_aside.Acts) -> None:
    """What a row offers beyond opening: the fix, for just the new ones where some joined,
    then setting the row aside."""
    menu.clear()
    with menu:
        if (mine := need.fix) is not None:
            panel.menu_entry(mine.label, lambda: fix(need), mark=lambda: ui.icon(mine.icon))
            if need.new and mine.key == needs.GET_MEDIA:
                panel.menu_entry(
                    t("console.needs.fix_new", fix=mine.label, count=len(need.new)),
                    lambda: fix(need, need.new), mark=lambda: ui.icon(mine.icon))
        panel.menu_entry(
            t("console.needs.skip_version") if need.key == needs.UPDATE
            else t("console.needs.dismiss"),
            lambda: acts.dismiss(need), under=needs.comes_back(need.key))
        panel.menu_entry(t("console.needs.stop_checking"), lambda: acts.stop(need.key))


def _need_row(need: needs.Need, state: dict[str, Any], fix: Callable[..., Any],
              acts: set_aside.Acts) -> None:
    """Icon in its tone, label, what joined since it was dismissed, count in its own unit,
    the fix, and the whole row opens what it counted. Its menu is the button at its end and
    a right click anywhere on it."""
    row = ui.element("div").classes(f"console-need console-need--{need.tone}") \
        .props("tabindex=0 role=link")
    row.on("click", lambda: state["open_on"](need.opens))
    row.on("keydown.enter", lambda: state["open_on"](need.opens))
    with row:
        ui.icon(need.icon).classes("console-need-icon")
        ui.label(need.label).classes("console-setting grow min-w-0").tooltip(need.tip)
        if need.new and not need.opens.then:
            # A row that opens a step has no grid to narrow.
            from console import games

            def only_new() -> Any:
                return state["open_on"](needs.Opens(
                    need.opens.view, need.opens.arriving,
                    {**need.opens.keys, games.NEW_KEY: need.new}, need.opens.then))

            with ui.element("div").on("click.stop", lambda: None) \
                    .on("keydown.enter.stop", lambda: None):
                chip = ui.label(t("console.needs.new", count=len(need.new))) \
                    .classes("console-member-chip console-chip-warn console-need-new") \
                    .props("tabindex=0 role=link") \
                    .tooltip(t("console.needs.new.tip"))
                chip.on("click", only_new)
                chip.on("keydown.enter", only_new)
        if said := need.counted():
            ui.label(said).classes("console-need-count shrink-0")
        if need.fix is not None:
            with ui.element("div").classes("console-need-fix").on("click.stop", lambda: None) \
                    .on("keydown.enter.stop", lambda: None):
                panel.icon_action(need.fix.label, lambda: fix(need), icon=need.fix.icon,
                                  hint=need.fix.tip)()
        if not needs.can_set_aside(need.key):
            return
        with ui.element("div").classes("console-need-more").on("click.stop", lambda: None) \
                .on("keydown.enter.stop", lambda: None):
            _button, menu = panel.menu_button(verbs.MORE, t("console.needs.row_menu"))
        _need_menu(menu, need, fix, acts)
        _need_menu(ui.context_menu(), need, fix, acts)


def _aside_line(one: needs.Aside, acts: set_aside.Acts) -> None:
    with ui.row().classes("console-aside-line items-center gap-3 w-full no-wrap"):
        ui.icon(one.icon).classes("console-need-icon console-need--muted")
        ui.label(one.label).classes("console-setting grow min-w-0")
        ui.label(one.chip).classes("console-member-chip console-chip-quiet") \
            .tooltip(one.tip)
        again = acts.check_again if one.stopped else acts.show_again
        panel.action(t("console.needs.check_again") if one.stopped
                     else t("console.needs.show_again"),
                     lambda: again(one.key), inline=True,
                     icon=verbs.REFRESH if one.stopped else verbs.UNHIDE,
                     hint=t("console.needs.check_again.help") if one.stopped
                     else t("console.needs.show_again.help"))()


def _needs_you(arranged: needs.Arranged, state: dict[str, Any], fix: Callable[..., Any],
               acts: set_aside.Acts) -> None:
    ui.label(t("console.needs.title")).classes("console-group")
    with ui.element("div").classes("console-card console-needs"):
        if not arranged.rows:
            with ui.row().classes("items-center gap-3 w-full no-wrap"):
                ui.icon("check_circle").classes("console-need-icon console-need--none")
                ui.label(t("console.needs.nothing")).classes("console-setting grow")
                panel.action(t("console.needs.choose_checks"),
                             lambda: state["open_on"](needs.Opens(
                                 "settings", keys={"settings_page": "library.audit"})),
                             icon=verbs.GO, hint=t("console.needs.choose_checks.help"))()
        for need in arranged.rows:
            _need_row(need, state, fix, acts)
    if arranged.aside:
        shown = panel.disclosure(t("console.needs.set_aside", count=len(arranged.aside))) \
            .classes("console-disclosure-rows")
        shown.value = bool(state.get(_ASIDE_OPEN))
        shown.on_value_change(lambda event: state.__setitem__(_ASIDE_OPEN, event.value))
        with shown, ui.element("div").classes("console-card console-needs w-full"):
            for one in arranged.aside:
                _aside_line(one, acts)


def _opens(row: Any, state: dict[str, Any], where: needs.Opens) -> None:
    """Make a row a link: it opens `where` on a click or Enter."""
    row.props("tabindex=0 role=link")
    row.on("click", lambda: state["open_on"](where))
    row.on("keydown.enter", lambda: state["open_on"](where))


def _figure(count: int, label: str, state: dict[str, Any], where: needs.Opens) -> None:
    figure = ui.element("div").classes("console-figure")
    _opens(figure, state, where)
    with figure:
        ui.label(f"{count:,}").classes("console-kpi")
        ui.label(label).classes("console-help")


def _kind_row(kind: str, held: int, total: int, state: dict[str, Any]) -> None:
    name = media_label_map().get(kind, kind)
    without = total - held
    row = ui.element("div").classes("console-need")
    if not without:
        row.classes("console-need--static")
    if without:
        _opens(row, state, needs.Opens("games", needs.blank(f"media_{kind}")))
    with row:
        ui.label(name).classes("console-setting w-40 shrink-0")
        with ui.element("div").classes("grow min-w-0"):
            _bar(held / total if total else 0)
        ui.label(t("console.sections.held_of_games", held=held, total=total)) \
            .classes("console-need-count shrink-0")
    row.tooltip(t("console.sections.kind_tip", held=held, total=total, kind=name,
                  without=without) if without
                else t("console.sections.kind_all", total=total, kind=name))


def _hide_kinds(library: Library, state: dict[str, Any], kinds: list[str]) -> Any:
    @on_page
    async def hide() -> None:
        try:
            await run.io_bound(library.hide_media_kinds, kinds)
        except Exception as exc:  # noqa: BLE001 - the reason belongs on screen
            ui.notify(t("console.sections.hide_failed"), caption=why(exc), type="negative")
            return
        await state["open_on"](needs.Opens("settings", keys={"settings_page": "library.media"}))

    return hide


_NAMED_KINDS = 2


def _library(library: Library, state: dict[str, Any]) -> None:
    held = kind_holdings(library)
    total = len(library.games)
    ui.label(t("console.sections.library")).classes("console-group")
    with ui.element("div").classes("console-card w-full"):
        with ui.element("div").classes("console-figures"):
            _figure(total, t("console.section.games"), state, needs.Opens("games"))
            _figure(len(library.table_rows()), t("console.section.tables"), state,
                    needs.Opens("tables"))
        present = [(kind, count) for kind, count in held if count]
        if present:
            ui.label(t("console.sections.games_with")).classes("console-fact-heading")
            for kind, count in present:
                _kind_row(kind, count, total, state)
        empty = [kind for kind, count in held if not count]
        if empty:
            names = [media_label_map().get(kind, kind) for kind in empty]
            shown = ", ".join(names[:_NAMED_KINDS])
            with ui.row().classes("items-center gap-3 w-full no-wrap"):
                folded = len(names) > _NAMED_KINDS
                panel.line(t("console.sections.none_have", count=len(empty),
                             kinds=t("console.sections.more", names=shown) if folded else shown),
                           hint=", ".join(names) if folded else "",
                           classes="console-help grow min-w-0")
                panel.action(t("console.sections.hide_kinds"),
                             _hide_kinds(library, state, empty), inline=True, icon=verbs.HIDE,
                             hint=t("console.sections.hide_kinds.help"))()


RECENT_JOBS = 5

# How a job went: its glyph and the tone it is drawn in.
_JOB_MARKS = {
    "running": (verbs.JOB_RUNNING, "accent"),
    "done": (verbs.DONE, "none"),
    jobs_list.WITH_ERRORS: (verbs.HAD_ERRORS, "warm"),
    "failed": (verbs.JOB_FAILED, "danger"),
    jobs_list.STOPPED: (verbs.STOP, "muted"),
}


def _latest_jobs(library: Library) -> list[dict[str, Any]] | None:
    """The last few jobs, newest first. None where they could not be read."""
    listed = library.front().get("listed")
    if listed is None:
        return None
    progress = {str(one.get("id") or ""): float(one.get("pct") or 0) for one in listed}
    return [{**one, "pct": progress.get(one["id"], 0.0)}
            for one in jobs_list.rows(listed, time.time())[:RECENT_JOBS]]


def _job_line(one: dict[str, Any], state: dict[str, Any]) -> None:
    icon, tone = _JOB_MARKS.get(one["outcome"], (verbs.DONE, "muted"))
    row = ui.element("div").classes("console-need")
    if tone != "none":
        row.classes(f"console-need--{tone}")
    _opens(row, state, needs.Opens("jobs", keys={"jobs_find": one["what"],
                                                  "jobs_outcome": ""}))
    with row:
        ui.icon(icon).classes("console-need-icon" + (" console-need--none" if tone == "none"
                                                      else ""))
        with ui.element("div").classes("grow min-w-0"):
            ui.label(one["what"]).classes("console-setting")
            if one["detail"]:
                ui.label(one["detail"]).classes("console-help console-job-detail")
            if one["outcome"] == "running":
                bar = ui.linear_progress(value=one["pct"] / 100, show_value=False).props("rounded")
                if not one["pct"]:
                    bar.props("indeterminate")
        ui.label(when.ago(datetime.fromtimestamp(one["started"], UTC).isoformat())) \
            .classes("console-need-count shrink-0")
    row.tooltip(t("console.sections.job_open", outcome=t(f"console.jobs.outcome.{one['outcome']}")))


def _recent_jobs(library: Library, state: dict[str, Any]) -> None:
    ui.label(t("console.sections.recent_jobs")).classes("console-group")

    def signature() -> tuple[Any, ...]:
        shown = _latest_jobs(library)
        return (int(time.time() // 60), None if shown is None else tuple(
            (one["id"], one["outcome"], one["detail"], int(one["pct"])) for one in shown))

    held = {"signature": signature()}

    @ui.refreshable
    def card() -> None:
        shown = _latest_jobs(library)
        if shown is None:
            ui.label(t("console.sections.jobs_unread")).classes("console-help px-2")
        elif not shown:
            ui.label(t("console.sections.no_jobs")).classes("console-help px-2")
        for one in shown or []:
            _job_line(one, state)
        if shown:
            with ui.row().classes("justify-end w-full"):
                panel.action(t("console.sections.all_jobs"),
                             lambda: state["open_on"](needs.Opens(
                                 "jobs", keys={"jobs_find": "", "jobs_outcome": ""})),
                             inline=True, icon=verbs.GO,
                             hint=t("console.sections.all_jobs.help"))()

    def tick() -> None:
        if (now := signature()) != held["signature"]:
            held["signature"] = now
            card.refresh()

    with ui.element("div").classes("console-card console-needs w-full"):
        card()
    ui.timer(front.POLL_S, tick)


_ASIDE_OPEN = "aside_open"


def _prune(library: Library, record: Mapping[str, list[str]]) -> None:
    """Write the dismissals back without the ids no row counts any more. Skipped where the
    record could not be read, which says nothing about what is in it."""
    if not library.dismissed_was_read():
        return
    changed = [(row, list(record.get(row, ()))) for row in list(library.dismissed())
               if list(record.get(row, ())) != library.dismissed()[row]]
    if not changed:
        return

    async def write() -> None:
        for row, ids in changed:
            try:
                await run.io_bound(library.set_dismissed, row, ids)
            except Exception:  # noqa: BLE001 - kept as it was; the next visit tries again
                return

    ui.timer(0.05, write, once=True)


def overview(library: Library, registry: list[dict], discovery: dict,
             go: Callable[[str], None], state: dict[str, Any]) -> None:
    arranged = needs.arrange(needs.collect(library, state), library.dismissed(),
                             library.stopped(), library.watched().get("unread") or (),
                             needs.blind(library))
    _prune(library, arranged.record)

    def placed(game_ids: tuple[str, ...]) -> None:
        for game_id in game_ids:
            library.forget_media(game_id)
        if state.get("view") == "overview":
            go("overview")

    def fix(need: needs.Need, only: tuple[str, ...] | None = None) -> Any:
        if need.fix is None:
            return None
        if need.fix.key == needs.GET_MEDIA:
            ids = need.ids if only is None else only
            return media_fill.confirm_kind(list(ids), need.fix.kind, state,
                                           lambda: placed(ids))
        from console import devices

        return devices.confirm_update(library, _local_name(registry, discovery),
                                      library.watched().get("update") or {})

    def drawn_again() -> None:
        if state.get("view") == "overview":
            go("overview")

    acts = set_aside.Acts(library, drawn_again)

    # The container the two columns answer to: this page's own width, not the window's,
    # which the workbench pane shares.
    with ui.element("div").classes("console-overview"):
        front.top(library, state, go)
        front.strip(library, go)
        with ui.element("div").classes("console-overview-columns"):
            with ui.element("div").classes("console-overview-main"):
                _needs_you(arranged, state, fix, acts)
                with ui.element("div").props(f"id={METADATA_ID}"):
                    metadata(library.metadata_state(),
                             _metadata_action(library, state, drawn_again), state.get(_LEFT))
                table_scripts(library)
            with ui.element("div").classes("console-overview-side"):
                _library(library, state)
                _recent_jobs(library, state)


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
