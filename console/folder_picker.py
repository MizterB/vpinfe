"""Browsing this machine to fill a path field with a folder, a program or a file.

`list_entries` is `library.folders`, taken as a parameter rather than imported: this
draws for any field that wants a path, and none of them is the library client.

New folder is offered for a folder, whenever the callable that lists is a method of an
object that can also make one - `library.folders` and the API client's are, a bare
function is not and so draws without it.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from nicegui import ui

from common.failures import why
from common.i18n import t
from console import dialog as frame
from console import offload, panel, verbs
from console.on_page import on_page

_TITLE = {"dir": "console.folder_picker.choose_a_folder",
         "exe": "console.folder_picker.choose_a_program",
         "file": "console.folder_picker.choose_a_file"}
_ROW_ICON = {"exe": "terminal", "file": "description"}
# `/`, a drive and the mount points: where browsing starts over, so they wear the drive's mark.
_DRIVE_PATH = re.compile(r"^(/|/Volumes|/media|/mnt|[A-Za-z]:\\?)$")


def _free_name(folders: list[dict[str, Any]]) -> str:
    """The first of New folder, New folder 2, ... that this folder does not hold."""
    taken = {one["name"].lower() for one in folders}
    name, count = t("console.folder_picker.new_folder"), 1
    while name.lower() in taken:
        count += 1
        name = t("console.folder_picker.new_folder_numbered", count=count)
    return name


def _icon_for(name: str, path: str) -> str:
    """Home by the name the listing gives it, which is the only thing that says so: the
    Console may be drawing for a machine whose home it cannot see."""
    if name == t("word.home"):
        return verbs.HOME
    return verbs.DRIVE if _DRIVE_PATH.match(path) else "folder"


def _last_name(path: str) -> str:
    return re.split(r"[\\/]", path.rstrip("\\/"))[-1] or path


@on_page
async def pick_path(list_entries: Callable[..., dict], start: str = "", *,
                    kind: str = "dir", suffixes: tuple[str, ...] = ()) -> str | None:
    """The chosen path, or None where the dialog was cancelled.

    A `start` that cannot be listed opens at the kind's own start, saying why, instead
    of failing to open at all - the field it came from may hold a path from a mount that
    has since gone away, or one inside a private folder.
    """
    refused: Exception | None = None
    try:
        here = await offload.io(list_entries, start, kind, suffixes)
    except Exception as exc:  # noqa: BLE001 - a stale saved path is not a reason to refuse
        refused = exc
        here = await offload.io(list_entries, "", kind, suffixes)

    picked = start if kind != "dir" and any(
        f["path"] == start for f in here.get("files") or []) else ""
    state: dict[str, Any] = {"here": here, "selected": picked, "naming": None}
    choose: dict[str, Any] = {}
    make_folder: Callable[[str, str], dict] | None = getattr(
        getattr(list_entries, "__self__", None), "make_folder", None) if kind == "dir" else None

    with frame.opened(t(_TITLE[kind]), wide=True) as box:
        if refused is not None:
            with ui.element("div").classes("console-attention w-full"):
                ui.icon("error_outline").classes("console-attention-icon")
                with ui.column().classes("gap-0 min-w-0"):
                    ui.label(why(refused)).classes("console-attention-line")
                    ui.label(start).classes("console-help truncate")
        path_row = ui.row().classes("items-center gap-2 w-full no-wrap px-3")
        with ui.row().classes("items-center gap-x-4 w-full no-wrap px-3"):
            term = ui.input(placeholder=t("console.folder_picker.filter_folders"
                                          if kind == "dir"
                                          else "console.folder_picker.filter")) \
                .props("dense outlined clearable clear-icon=close").classes("grow")
            shown = ui.checkbox(t("console.folder_picker.show_hidden"), value=False) \
                .props("dense").classes("whitespace-nowrap")
        listing_col = ui.column().classes("w-full gap-1 console-folder-list px-3")
        ui.label(t("console.folder_picker.private_never_shown")).classes("console-help px-3")

        def draw_path() -> None:
            path_row.clear()
            here_now = state["here"]
            places = {one["path"]: one for one in here_now.get("roots") or []}
            with path_row:
                up = panel.icon_only(verbs.UP, lambda: _go(here_now["parent"]),
                                     hint=t("console.folder_picker.up"))
                if not here_now["parent"]:
                    up.disable()
                _, menu = panel.path_face(
                    _icon_for(places.get(here_now["path"], {}).get("name", ""),
                              here_now["path"]),
                    here_now["path"], name=t("word.where"))
                with menu:
                    _where_menu(places)

        def _where_menu(places: dict[str, dict[str, Any]]) -> None:
            """The folder you are in, each folder above it, then where browsing starts over."""
            here_now = state["here"]

            def entry(name: str, path: str, *, current: bool = False, under: str = "") -> None:
                mark = _icon_for(places.get(path, {}).get("name", ""), path)
                panel.menu_entry(
                    name, None if current else _opens(path),
                    mark=lambda: ui.icon(mark).classes("console-menu-mark"),
                    trail=(lambda: ui.icon("check").classes("console-menu-check"))
                    if current else None,
                    classes="console-menu-on" if current else "", under=under)

            entry(places.get(here_now["path"], {}).get("name") or _last_name(here_now["path"]),
                  here_now["path"], current=True)
            for above in here_now.get("above") or []:
                entry(places.get(above["path"], {}).get("name") or above["name"],
                      above["path"])
            ui.separator()
            for place in here_now.get("roots") or []:
                entry(place["name"], place["path"],
                      under="" if place["path"].rstrip("\\") == place["name"]
                      else place["path"])

        def select(path: str) -> None:
            state["selected"] = path
            draw_listing()
            if "button" in choose:
                choose["button"].enable()

        def draw_listing() -> None:
            listing_col.clear()
            wanted = (term.value or "").strip().lower()
            folders = [f for f in state["here"]["folders"] if wanted in f["name"].lower()]
            files = [f for f in state["here"].get("files") or []
                    if wanted in f["name"].lower()]
            with listing_col:
                if state["naming"] is not None:
                    _naming_row()
                if not folders and not files and state["naming"] is None:
                    ui.label(t("console.folder_picker.no_folders" if kind == "dir"
                              else "console.folder_picker.nothing_here")) \
                        .classes("console-help")
                for folder in folders:
                    row = ui.row().classes(
                        "items-center gap-2 w-full no-wrap console-source-row "
                        "console-source-row--pick console-source-row--line")
                    with row:
                        ui.icon("folder").classes("shrink-0")
                        ui.label(folder["name"]).classes("console-source-name grow")
                    row.on("click", lambda p=folder["path"]: _go(p))
                for one in files:
                    classes = ("items-center gap-2 w-full no-wrap console-source-row "
                              "console-source-row--pick console-source-row--line")
                    if one["path"] == state["selected"]:
                        classes += " console-source-row--chosen"
                    row = ui.row().classes(classes)
                    with row:
                        ui.icon(_ROW_ICON[kind]).classes("shrink-0")
                        ui.label(one["name"]).classes("console-source-name grow")
                    row.on("click", lambda p=one["path"]: select(p))
                    row.on("dblclick", lambda p=one["path"]: box.submit(p))

        def _naming_row() -> None:
            """The row a folder is named in, where it will sit, selected for typing as
            Finder and Explorer leave it."""
            with ui.row().classes("items-center gap-2 w-full no-wrap console-source-row "
                                  "console-source-row--line console-source-row--chosen"):
                ui.icon("folder").classes("shrink-0")
                typed = ui.input(value=state["naming"]) \
                    .props("dense borderless debounce=0").classes("console-edit-field grow")
            typed.on("keydown.enter", lambda: _make(typed.value))
            # Stopped before the window sees it: Quasar closes the whole dialog on Escape.
            typed.on("keyup.escape.stop", _stop_naming)
            ui.run_javascript(
                "requestAnimationFrame(() => { const field = "
                f"document.getElementById('c{typed.id}'); const input = field && "
                "(field.matches('input') ? field : field.querySelector('input')); "
                "if (input) { input.focus(); input.select(); } })")

        def _start_naming() -> None:
            term.value = ""
            state["naming"] = _free_name(state["here"]["folders"])
            draw_listing()

        def _stop_naming() -> None:
            state["naming"] = None
            draw_listing()

        @on_page
        async def _make(name: str) -> None:
            if make_folder is None:
                return
            try:
                fresh = await offload.io(make_folder, state["here"]["path"], name)
            except Exception as exc:  # noqa: BLE001
                ui.notify(t("console.folder_picker.could_not_make_it"), caption=why(exc),
                          type="negative")
                return
            _arrive(fresh)

        def _arrive(fresh: dict[str, Any], *, keep_filter: bool = False) -> None:
            state["here"] = fresh
            if not any(f["path"] == state["selected"] for f in fresh.get("files") or []):
                state["selected"] = ""
            state["naming"] = None
            if not keep_filter:
                term.value = ""
            draw_path()
            draw_listing()
            if "button" in choose:
                choose["button"].set_enabled(bool(state["selected"]))

        @on_page
        async def _go(path: str, *, keep_filter: bool = False) -> None:
            try:
                fresh = await offload.io(list_entries, path, kind, suffixes, shown.value)
            except Exception as exc:  # noqa: BLE001
                ui.notify(t("console.mediasource.could_not_read_folder"), caption=why(exc),
                          type="negative")
                return
            _arrive(fresh, keep_filter=keep_filter)

        def _opens(path: str) -> Callable[[], Any]:
            return lambda: _go(path)

        draw_path()
        draw_listing()
        term.on_value_change(draw_listing)
        shown.on_value_change(lambda: _go(state["here"]["path"], keep_filter=True))

        with frame.footer():
            if make_folder is not None:
                frame.aside(t("console.folder_picker.new_folder"), _start_naming,
                            icon=verbs.NEW_FOLDER)
            frame.cancel(lambda: box.submit(None))
            if kind == "dir":
                frame.answer(t("console.folder_picker.choose_this_folder"),
                            lambda: box.submit(state["here"]["path"]), icon=verbs.CHOOSE)
            else:
                choose["button"] = frame.answer(
                    t("console.folder_picker.choose"),
                    lambda: box.submit(state["selected"]), icon=verbs.CHOOSE)
                if not state["selected"]:
                    choose["button"].disable()

    return await box
