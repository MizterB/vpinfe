"""Launchers: which ways this install runs a table, and one of them open beside it.

A grid with a workbench, the shape Devices uses, and for the reason Devices uses it: one
launcher is deep. Its own seven fields are the least of it - an app declares its whole
settings surface, which for Visual Pinball is around twelve hundred keys in named groups,
and that is more inside one object than anything else in the Console holds. A section rail
is how the Console shows what is inside one thing, and without one the seven fields
somebody actually came to change sit at the top of a thousand-row scroll.

The grid answers the one question a list of launchers has: which of these can actually
run a table. It knows because each row carries what the disk made of the program it
names.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from typing import Any

from nicegui import run, ui

from common import install_identity, path_checks
from common.i18n import t
from console import confirm, grid, offload, panel, verbs, views
from console import dialog as frame
from console.data import Library

logger = logging.getLogger("vpinfe.console.launchers")

SCOPE = "console.launchers.columns"

# Said once over the list rather than under each row. What a launcher is for, in the
# words somebody would use before they know the word.

# Why a row is the default, where that is not obvious. Only on the one it applies to -
# a note on every row would say nothing.
DEFAULT_HINT = t("console.launchers.tables_name_no_launcher")

STATE_READY = "word.ready"
STATE_OFF = "console.launchers.switched_off"
STATE_BROKEN = "console.launchers.cannot_run"
STATE_NO_PROGRAM = "console.launchers.no_program"

_STATE_CHOICES = [{"value": one, "label": one}
                  for one in (t(STATE_READY), t(STATE_OFF), t(STATE_NO_PROGRAM),
                              t(STATE_BROKEN))]

COLUMNS: list[dict[str, Any]] = [
    grid.identifier("name", t("word.name"), 240, pinned="left"),
    grid.column("app", t("word.runs"), 180,
                help=t("console.launchers.program_behind_says_something.help")),
    grid.column("state", t("word.state"), 150, **grid.choice_filter(_STATE_CHOICES),
                help=t("console.launchers.ready_switched_program_cannot.help")),
    grid.column("default", t("word.default"), 110,
                help=t("console.launchers.tables_name_no_launcher.help")),
    grid.column("program", t("word.program"), 420,
                help=t("console.launchers.executable_launcher_runs.help")),
]

LAUNCHER_VIEWS: dict[str, list[str] | views.Preset] = {
    "console.view.overview": views.Preset(
        columns=("name", "app", "state", "default", "program"),
        help=t("console.view.launchers.help")),
}


def _broken(one: dict) -> Iterator[str]:
    """Every path this launcher names that the disk cannot answer for."""
    checks = one.get("checks") or {}
    labels = {field["key"]: field["label"] for field in one.get("fields") or []}
    for key, found in checks.items():
        state = str(found.get("state") or "")
        if state in ("", path_checks.OK, path_checks.UNSET):
            continue
        yield f"{labels.get(key, key)}: {found.get('reason') or state}"


def _names_no_program(one: dict) -> bool:
    checks = one.get("checks") or {}
    return any(field.get("path") == "exe"
               and (checks.get(field["key"]) or {}).get("state") == path_checks.UNSET
               for field in one.get("fields") or [])


def state_of(one: dict) -> str:
    """The worse fact wins. Switched off is a choice somebody made; a program that is
    not there is a launcher that cannot run, and it is the one to say when a row is
    both."""
    if next(iter(_broken(one)), ""):
        return STATE_BROKEN
    if _names_no_program(one):
        return STATE_NO_PROGRAM
    return STATE_READY if one.get("enabled") else STATE_OFF


def rows(held: list[dict], defaults: dict) -> list[dict[str, Any]]:
    return [{
        "id": one["launcher_id"],
        "name": one["display_name"],
        "app": one["app_name"],
        "state": t(state_of(one)),
        # Blank on every other row rather than "No": a column that says the same thing
        # everywhere but once is a column about the exception.
        "default": t("word.default") if defaults.get(one["app"]) ==
                one["launcher_id"] else "",
        "program": str((one.get("settings") or {}).get("bin_path") or ""),
    } for one in held]


def build(library: Library, state: dict[str, Any],
          on_select: Callable[[dict | None], Any],
          redraw: Callable[[], None]) -> None:
    """The grid. Read on every draw, because this page edits it and what the disk says
    can change without anybody editing anything."""
    body = ui.column().classes("w-full grow min-h-0 gap-0")
    # On a timer, because reading goes over HTTP and the draw it is part of runs on the
    # event loop, where the client refuses a call.
    ui.timer(0.01, lambda: _fill(library, state, on_select, redraw, body), once=True)


async def _fill(library: Library, state: dict[str, Any], on_select: Callable[[dict | None], Any],
                redraw: Callable[[], None], body: Any) -> None:
    try:
        found = await offload.io(library.launchers)
    except Exception as exc:  # noqa: BLE001 - this page says why, never 500s
        with body:
            panel.facts(ui, [panel.intro(t("console.launchers.could_not_read_launchers",
                    exc=(exc)))])
        return

    # Imported here: `workbench` imports this module, and `games` imports `workbench`,
    # so reaching for it at the top would close the loop.
    from console.games import view_control

    held = list(found.get("launchers") or [])
    apps_known = list(found.get("apps") or [])
    built = rows(held, dict(found.get("defaults") or {}))
    fields = [definition["field"] for definition in COLUMNS]

    with body:
        with ui.row().classes("w-full items-center gap-2 px-3 py-2 mb-2 shrink-0 "
                              "console-panel console-grid-bar"):
            bar = panel.grid_bar()
            wire_views, _picker, showing, describe = view_control(
                library, SCOPE, LAUNCHER_VIEWS, fields, COLUMNS, bar=bar)
            describe()
            with bar.top, panel.bar_end():
                search = panel.search(t("console.launchers.search_launchers"))
            with bar.bottom, panel.bar_end():
                ui.label(t("console.launchers.launcher", count=len(built))) \
                    .classes("text-xs console-label")
                panel.add_action(
                    [(t("console.launchers.add", value=(one['name'])),
                      (lambda a=one: _add(library, state, redraw, a)))
                     for one in apps_known],
                    empty=not built)

        if not built:
            panel.facts(ui, [panel.intro(
                t("console.launchers.no_launchers_yet_add"))])
            return

        by_id = {row["id"]: row for row in built}
        by_launcher = {one["launcher_id"]: one for one in held}
        grid.on_row_focus(SCOPE,
                          lambda event: on_select(by_id.get(grid.focused_row(event))))

        def fill(row: dict | None) -> None:
            launcher = by_launcher.get(str((row or {}).get("id") or ""))
            if launcher is None:
                menu.clear()
                return
            panel.verb_menu(menu, str(launcher["display_name"]),
                            acts(library, state, launcher, len(held), redraw))

        with ui.element("div").classes("w-full grow min-h-0 flex flex-col"):
            table = grid.build(COLUMNS, built, SCOPE, on_context=fill, view_of=showing)
            menu = ui.context_menu()
        search.on_value_change(
            lambda: table.run_grid_method("setGridOption", "quickFilterText",
                                          search.value or ""))
        # After the grid exists: the widgets sit above it and the behavior needs it.
        wire_views(table)


async def _add(library: Library, state: dict[str, Any], redraw: Callable[[], None],
               app: dict) -> None:
    """A new launcher for an app, with nothing filled in.

    Nothing copied from an existing one: Add is for a second program, and Duplicate is
    the action for a second way of running the same one.
    """
    from common.games import launchers as model

    made = model.mint_launcher_id()
    try:
        name = model.free_name(app["name"], await _names(library))
        await run.io_bound(library.put_launcher, made,
                           {"app": app["id"], "display_name": name,
                            "enabled": True, "settings": {}})
    except Exception as exc:  # noqa: BLE001
        ui.notify(t("said.could_not_add_it", exc=(exc)), type="negative")
        return
    state["launcher"] = made
    redraw()


async def duplicate(library: Library, state: dict[str, Any], redraw: Callable[[], None],
                     launcher: dict) -> None:
    """A copy, which is the case this feature exists for: change one thing - usually the
    configuration file - and you have a second way of running the same program.

    The copy does not claim to own an ini. It points at whatever the original did, and
    only a file VPinFE made is one VPinFE offers to delete.
    """
    from common.games import launchers as model

    made = model.mint_launcher_id()
    try:
        name = model.free_name(t("console.launchers.copy_of", name=launcher["display_name"]),
                               await _names(library))
        await run.io_bound(library.put_launcher, made,
                           {**launcher, "launcher_id": made, "owns_ini": False,
                            "display_name": name})
    except Exception as exc:  # noqa: BLE001
        ui.notify(t("console.launchers.could_not_duplicate", exc=(exc)), type="negative")
        return
    state["launcher"] = made
    redraw()


async def _names(library: Library) -> list[str]:
    found = await offload.io(library.launchers)
    return [str(one.get("display_name") or "") for one in found.get("launchers") or []]


def copy_targets(known: list[dict], install_id: str) -> list[dict]:
    return [one for one in known
            if str(one.get("kind") or "vpinfe") == "vpinfe"
            and install_identity.FRONTEND in (one.get("features") or ())
            and str(one.get("device_id") or "") != install_id]


async def copy_dialog(library: Library, state: dict[str, Any], launcher: dict) -> None:
    """Pick the devices, see what it will do, then do it.

    A copy with no ongoing link, which the dialog says rather than leaving somebody to
    find out: edit a cabinet's launcher afterwards and the two diverge.
    """
    try:
        known = await offload.io(library.devices)
    except Exception as exc:  # noqa: BLE001
        ui.notify(t("console.launchers.could_not_read_devices", exc=(exc)), type="negative")
        return
    reachable = copy_targets(known, str(state.get("install_id") or ""))
    if not reachable:
        ui.notify(t("console.launchers.no_other_frontend"), type="warning")
        return

    picked: set[str] = set()
    with frame.opened(t("console.launchers.copy_to_devices",
                        value=launcher["display_name"])) as box:
        ui.label(t("console.launchers.arrives_same_name_same")).classes("console-help px-3")
        with ui.column().classes("gap-1 px-3"):
            for one in reachable:
                name = str(one.get("display_name") or one.get("device_id"))
                ui.checkbox(name, on_change=lambda e, d=one: (
                    picked.add(str(d.get("device_id"))) if e.value
                    else picked.discard(str(d.get("device_id"))))) \
                    .props("dense")
            also = ui.checkbox(t("console.launchers.also_copy_tables_use")).props("dense")
        ui.label(t("console.launchers.one_way_copy_change")).classes("console-help px-3")
        with frame.footer():
            frame.cancel(lambda: box.submit(None))
            frame.answer(t("word.copy"), lambda: box.submit(True), icon=verbs.COPY)

    if not await box:
        return
    if not picked:
        ui.notify(t("console.launchers.no_devices_picked"), type="warning")
        return
    await _do_copy(library, launcher, [one for one in reachable
                                       if str(one.get("device_id")) in picked],
                   bool(also.value))


async def _do_copy(library: Library, launcher: dict, devices: list[dict],
                   with_mappings: bool) -> None:
    from common.games import launcher_copy

    mappings = {}
    if with_mappings:
        try:
            found = await offload.io(library.launchers)
            mappings = {table: to for table, to in (found.get("mappings") or {}).items()
                        if to == launcher["launcher_id"]}
        except Exception as exc:  # noqa: BLE001
            ui.notify(t("console.launchers.could_not_read_assignments", exc=(exc)), type="negative")
            return

    def client_for(device: Any) -> Any:
        from common import device_client

        return device_client.for_device(device)

    outcomes = await offload.io(launcher_copy.copy_to, devices, [launcher],
                                  mappings, client_for=client_for)
    said = launcher_copy.said(outcomes)
    ui.notify(said, type="positive" if all(one.ok for one in outcomes) else "warning")


def acts(library: Library, state: dict[str, Any], launcher: dict, count: int,
         redraw: Callable[[], None]) -> list[panel.Verb]:
    """What can be done to one launcher."""
    offered = [panel.Verb(t("console.workbench.duplicate"),
                          lambda: duplicate(library, state, redraw, launcher))]
    if state.get("can_manage_devices"):
        offered.append(panel.Verb(t("console.workbench.copy_devices"),
                                  lambda: copy_dialog(library, state, launcher)))
    offered.append(panel.Verb(
        t("word.remove"),
        None if count <= 1 else (lambda: remove(library, state, redraw, launcher)),
        danger=True, hint=t("console.workbench.launcher_install")))
    return offered


def removal_words(found: dict[str, Any]) -> tuple[str, list[str]]:
    """The confirm's detail and lines, from what switching the launcher off would do,
    which is what removing it does to its tables."""
    kept = t("console.launchers.remove_keeps_files")
    count = int(found.get("tables") or 0)
    goes = list(found.get("fallbacks") or [])
    if not count:
        return kept, []
    if len(goes) == 1:
        name = goes[0].get("display_name")
        said = (t("console.launchers.remove_moves_to", count=count, fallback=name) if name
                else t("console.launchers.remove_strands", count=count))
        return f"{said} {kept}", []
    return (f"{kept} {t('console.launchers.remove_split', count=count)}",
            [t("console.workbench.count_launch_with", count=int(one["tables"]),
               name=one["display_name"]) if one.get("display_name")
             else t("console.launchers.count_no_launcher", count=int(one["tables"]))
             for one in goes])


async def remove(library: Library, state: dict[str, Any], redraw: Callable[[], None],
                  launcher: dict) -> None:
    """Asked about first, because it is the destructive one and it takes assignments
    with it - a table pointing here goes back to the default."""
    try:
        found = await offload.io(library.launcher_fallback, launcher["launcher_id"])
    except Exception as exc:  # noqa: BLE001
        ui.notify(t("console.workbench.could_not_work", exc=(exc)), type="negative")
        return
    detail, lines = removal_words(found)
    if not await confirm.ask(
            t("console.launchers.remove", value=(launcher['display_name'])),
            detail=detail, lines=lines, confirm=t("word.remove"), icon=verbs.REMOVE):
        return
    try:
        await run.io_bound(library.delete_launcher, launcher["launcher_id"])
    except Exception as exc:  # noqa: BLE001
        ui.notify(t("said.could_not_remove_it", exc=(exc)), type="negative")
        return
    state["launcher"] = ""
    redraw()
