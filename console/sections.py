"""Strawman sections, built to be argued with.

Overview and Extensions exist here to show how the shell holds together, not as
finished pages. Where a page could use real library data it does -
a mock number proves nothing, and the checks below are the validator registry in
embryo: each one is a name, a sentence a person can read, and a predicate.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from nicegui import run, ui

from common.media_specs import media_label_map
from console.data import Library

# name, one-line description, predicate over (game, media entries).
#
# Deliberately shaped the way a real registry would be, so that promoting this is a
# matter of moving it and adding config rather than a rewrite. The description is not
# decoration: it is what the row's finding says, and writing it forces the check to be
# about something a person can act on.
CHECKS: tuple[tuple[str, str, str, Callable[[dict, dict, dict], bool]], ...] = (
    ("rom_missing", "Declared ROM is not installed",
     "The table will not boot; PinMAME has nothing to load.",
     lambda g, m, x: bool(x.get("rom_missing"))),
    ("no_playfield", "No playfield image",
     "The frontend has nothing to show for this game on the playfield screen.",
     lambda g, m, x: not m.get("playfield", {}).get("present")),
    ("no_backglass", "No backglass image",
     "A second screen will sit empty while this game is selected.",
     lambda g, m, x: not m.get("backglass", {}).get("present")),
    ("borrowed_wheel", "Wheel is standing in for something else",
     "A fallback is being used, so the wheel looks fine and is still missing.",
     lambda g, m, x: str(m.get("wheel", {}).get("via") or "").startswith("fallback:")),
    ("no_media", "No media at all",
     "Nothing resolved for any kind. Usually a folder that was never populated.",
     lambda g, m, x: not any(e.get("present") for e in m.values())),
    ("no_year", "No year recorded",
     "Sorting and filtering by year will place this game arbitrarily.",
     lambda g, m, x: not g.get("year")),
)


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


def findings(library: Library) -> dict[str, list[dict[str, Any]]]:
    """Run every check over the library. Keyed by check, so a section can show counts."""
    out: dict[str, list[dict[str, Any]]] = {key: [] for key, _, _, _ in CHECKS}
    extra = rollups(library)
    for game in library.games:
        entries = library.media.get(game["id"], {})
        facts = extra.get(game["id"], {})
        for key, _, _, predicate in CHECKS:
            try:
                if predicate(game, entries, facts):
                    out[key].append(game)
            except Exception:
                # A check that throws is a broken check, not a broken library. It
                # reports nothing rather than taking the page down with it.
                continue
    return out


def _card(title: str):
    card = ui.element("div").classes("console-card")
    with card:
        ui.label(title).classes("console-card-title")
    return card


def _bar(fraction: float) -> None:
    with ui.element("div").classes("console-bar w-full"):
        ui.element("div").style(f"width:{max(0.0, min(1.0, fraction)) * 100:.0f}%")


# --- Overview --------------------------------------------------------------------

def overview(library: Library, registry: list[dict], discovery: dict,
             go: Callable[[str], None]) -> None:
    found = findings(library)
    total_slots = sum(len(entries) for entries in library.media.values())
    present = sum(1 for entries in library.media.values()
                  for entry in entries.values() if entry.get("present"))
    open_findings = sum(len(games) for games in found.values())

    with ui.row().classes("w-full gap-4 no-wrap"):
        with _card("Library"):
            ui.label(str(len(library.games))).classes("console-kpi")
            ui.label("games").classes("text-xs opacity-60")
        with _card("Media coverage"):
            ui.label(f"{(present / total_slots * 100 if total_slots else 0):.0f}%") \
                .classes("console-kpi")
            _bar(present / total_slots if total_slots else 0)
            ui.label(f"{present} of {total_slots} slots").classes("text-xs opacity-60")
        with _card("Needs attention"):
            ui.label(str(open_findings)).classes("console-kpi")
            ui.label("findings across the library").classes("text-xs opacity-60")
        with _card("Devices"):
            ui.label(str(len(registry))).classes("console-kpi")
            ui.label("known to this install").classes("text-xs opacity-60")
        with _card("This build"):
            ui.label(str(discovery.get("vpinfe_version") or "?")).classes("console-kpi")
            ui.label("no update endpoint yet").classes("text-xs opacity-60")

    ui.label("Coverage by kind").classes("console-group mt-4")
    with ui.element("div").classes("console-card w-full"):
        # A filter says which games lack a topper. Nothing in a grid says "you have no
        # toppers at all" without filtering twenty kinds one at a time, which is the
        # one thing a rollup does that a lens cannot.
        kept = library.kept_kinds()["media"]
        counts = [(kind, sum(1 for entries in library.media.values()
                             if entries.get(kind, {}).get("present")))
                  for kind in library.kinds() if kind in kept]
        for kind, held in sorted(counts, key=lambda item: item[1]):
            with ui.row().classes("items-center gap-3 w-full no-wrap py-1"):
                ui.label(media_label_map().get(kind, kind)) \
                    .classes("console-setting w-40 shrink-0")
                with ui.element("div").classes("grow min-w-0"):
                    _bar(held / len(library.games) if library.games else 0)
                ui.label(f"{held} of {len(library.games)}") \
                    .classes("text-xs opacity-60 shrink-0")

    ui.label("What needs attention").classes("console-group mt-4")
    with ui.element("div").classes("console-card w-full"):
        for key, name, description, _ in CHECKS:
            games = found[key]
            with ui.row().classes("items-center gap-3 w-full no-wrap py-1"):
                ui.icon("error" if games else "check_circle", size="18px") \
                    .classes("text-warning" if games else "text-positive")
                with ui.column().classes("gap-0 grow min-w-0"):
                    ui.label(name).classes("console-setting")
                    # The sentence is the finding. Without it a count is a puzzle.
                    ui.label(description).classes("console-help")
                ui.label(f"{len(games)}").classes("text-sm opacity-70 shrink-0")
                ui.button("Show", on_click=lambda k=key: go("games")) \
                    .props("flat dense no-caps size=sm").classes("shrink-0") \
                    .set_enabled(bool(games))

    metadata(library.metadata_state(), _metadata_action(library))
    table_scripts(library)


# --- The library's own metadata ---------------------------------------------------
#
# Both operations rewrite a file in every game folder, so both ask first and both say
# what they cost. The upgrade keeps a copy; the restore spends one.


_ASKS = {
    "upgrade": ("Bring every game onto the current format?",
                "Each game's metadata file is copied beside itself first, so this can "
                "be put back. Nothing about your games changes - only the shape of the "
                "file they are described in.",
                "Upgrade", False),
    "restore": ("Put back the saved metadata?",
                "Every game with a saved copy goes back to it. Anything written since "
                "the copy was taken goes with it - a rating you set afterwards is in "
                "the current file, not the old one.",
                "Restore", True),
}


def _metadata_action(library: Library) -> Callable[[str], Any]:
    """Ask, start the job, and say it is under way.

    Under way rather than done: both of these rewrite a file per game and run as a job,
    which the drawer already reports on. Waiting here would be a spinner in front of a
    progress line that is already on screen.
    """
    from console import confirm
    from console.api import ApiClient

    async def start(which: str) -> None:
        title, detail, word, danger = _ASKS[which]
        if not await confirm.ask(title, detail=detail, confirm=word, danger=danger):
            return
        client = ApiClient()
        call = client.upgrade_info if which == "upgrade" else client.restore_info
        try:
            await run.io_bound(call)
        except Exception as exc:
            ui.notify(str(exc), type="negative")
            return
        ui.notify(f"{word} under way", type="positive")
        # The counts this card is drawn from are now stale. Asked again off the loop,
        # for the same reason they were read there in the first place.
        await run.io_bound(library.read_metadata_state)

    return start


# --- The library's own metadata, drawn ---------------------------------------------
#
# Every game folder carries a `.info`: its id, its catalog match, your rating and how
# often you have played it. It is where the library actually lives, and the grid is a
# view of it. Three things can be true of one that are worth acting on, and they are not
# the same thing as a game being short of a rom or a wheel image - which is why this is
# its own card rather than another row in the one above.


def _stamp(said: str) -> str:
    """`20260909T110917Z` as something a person reads, or "" for nothing."""
    if len(said) < 8:
        return ""
    return f"{said[0:4]}-{said[4:6]}-{said[6:8]}"


def _metadata_row(good: bool, name: str, said: str,
                  action: tuple[str, Callable[[], Any]] | None = None) -> None:
    with ui.row().classes("items-center gap-3 w-full no-wrap py-1"):
        ui.icon("check_circle" if good else "error", size="18px") \
            .classes("text-positive" if good else "text-warning")
        with ui.column().classes("gap-0 grow min-w-0"):
            ui.label(name).classes("console-setting")
            ui.label(said).classes("console-help")
        if action is not None:
            label, run = action
            ui.button(label, on_click=run) \
                .props("flat dense no-caps size=sm").classes("shrink-0")


def metadata(state: dict[str, Any], on_start: Callable[[str], Any]) -> None:
    """What the library's metadata files need, and the two ways to act on it.

    Drawn whole rather than only when something is wrong, the same as the card above it:
    a section that comes and goes cannot be looked for, and "everything is current" is
    worth being able to check rather than infer from an absence.
    """
    pending = int(state.get("pending_upgrade") or 0)
    unreadable = list(state.get("unreadable") or [])
    newer = int(state.get("newer_than_us") or 0)
    restorable = int(state.get("restorable") or 0)

    ui.label("Library metadata").classes("console-group mt-4")
    with ui.element("div").classes("console-card w-full"):
        _metadata_row(
            not pending, "Format",
            "Every game is on the current format" if not pending
            else f"{pending} were written by an older build and can be brought forward",
            None if not pending else ("Upgrade", lambda: on_start("upgrade")))

        # No action: the fix is on disk, in a file this cannot repair without guessing
        # what it was meant to say. Naming the folders is the whole of the help.
        _metadata_row(
            not unreadable, "Readable",
            "Every folder's metadata could be read" if not unreadable
            else f"{len(unreadable)} could not be read, so those games are not in your "
                 f"library: {', '.join(str(one.get('name') or '?') for one in unreadable[:4])}"
                 + (" and more" if len(unreadable) > 4 else ""))

        # Only when it is true. A row saying "nothing here was written by a newer build"
        # is a sentence about a thing that has never happened to most installs.
        if newer:
            _metadata_row(
                False, "Newer than this build",
                f"{newer} were written by a later version of VPinFE. This build reads "
                "what it understands and leaves the rest alone.")

        # A fact with an action rather than a warning: having backups is not a problem,
        # and a permanent amber row saying so would be one more thing to ignore.
        if restorable:
            when = _stamp(str(state.get("newest_backup") or ""))
            _metadata_row(
                True, "Backups",
                f"{restorable} games have a saved copy"
                + (f" from {when}" if when else "") + ", taken before an upgrade",
                ("Restore", lambda: on_start("restore")))


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
        return False, "The index could not be reached, so nothing has been checked"
    offered = list(found.get("offered") or [])
    checked = int(found.get("checked") or 0)
    already = int(found.get("already") or 0)
    if offered:
        shown = ", ".join(offered[:3]) + (" and more" if len(offered) > 3 else "")
        return False, f"{len(offered)} of {checked} can take a published fix: {shown}"
    running = f", and {already} already run one" if already else ""
    return True, f"Nothing published matches your tables ({checked} checked{running})"


def table_scripts(library: Library) -> None:
    """What the published index has for this library, once somebody asks.

    Asked rather than read on every draw. It is a request to somebody else's server, and
    a page that waited on it would be slow for a question most visits are not asking.
    """
    from console import confirm
    from console.api import ApiClient

    ui.label("Table scripts").classes("console-group mt-4")
    card = ui.element("div").classes("console-card w-full")

    def draw() -> None:
        card.clear()
        found = library.script_patches()
        with card:
            if not found:
                _metadata_row(
                    True, "Script fixes",
                    "The community publishes script fixes that let a table run under "
                    "Standalone. Nothing has been asked yet.",
                    ("Check", check))
                return
            good, said = _scripts_said(found)
            _metadata_row(good, "Script fixes", said,
                          ("Fetch", fetch) if found.get("offered") else ("Check", check))

    async def check() -> None:
        await run.io_bound(library.read_script_patches)
        draw()

    async def fetch() -> None:
        offered = list(library.script_patches().get("offered") or [])
        if not await confirm.ask(
                f"Fetch fixes for {len(offered)} table(s)?",
                detail="Each one lands as a .vbs beside the table it is for, and VPX "
                       "runs it instead of the script the table ships with. A table "
                       "that already has one is left alone.",
                confirm="Fetch", danger=False):
            return
        try:
            await run.io_bound(ApiClient().apply_script_patches)
        except Exception as exc:
            ui.notify(str(exc), type="negative")
            return
        ui.notify("Fetching under way", type="positive")
        await run.io_bound(library.read_script_patches)
        draw()

    draw()


# --- Extensions ------------------------------------------------------------------

def extensions(registry: list[dict]) -> None:
    ui.label("An extension runs where its feature lives. Where it runs is a "
             "property of the extension, not a setting.").classes("console-help mb-3")
    with ui.element("div").classes("console-card w-full"):
        ui.label("Nothing installed").classes("console-setting")
        ui.label("Install one from a repository, or drop a package here. The list will "
                 "show what it declares and which devices it reached.") \
            .classes("console-help")
