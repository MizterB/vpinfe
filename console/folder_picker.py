"""Browsing this machine to fill a path field with a folder, a program or a file.

`list_entries` is `library.folders`, taken as a parameter rather than imported: this
draws for any field that wants a path, and none of them is the library client.

New folder is offered for a folder, whenever the callable that lists is a method of an
object that can also make one - `library.folders` and the API client's are, a bare
function is not and so draws without it.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from nicegui import ui

from common import path_state
from common.failures import why
from common.i18n import t
from console import dialog as frame
from console import offload, panel, verbs
from console.on_page import on_page

_TITLE = {"dir": "console.folder_picker.title_folder",
         "exe": "console.folder_picker.title_program",
         "file": "console.folder_picker.title_file"}
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


def _enclosing(path: str) -> str:
    """The folder that holds `path`, as text, or "" at the top of it."""
    trimmed = path.rstrip("\\/")
    cut = max(trimmed.rfind("/"), trimmed.rfind("\\"))
    if cut < 0:
        return ""
    head = trimmed[:cut]
    return trimmed[:cut + 1] if not head or head.endswith(":") else head


def _typed_path(text: str, here: str) -> str:
    """What was typed or pasted as a path: quotes dropped, as Windows' Copy as path adds
    them, and a bare name taken as inside the folder you are in."""
    said = text.strip()
    if len(said) > 1 and said[0] == said[-1] and said[0] in "\"'":
        said = said[1:-1].strip()
    if said and not re.search(r"[\\/]", said) and not said.startswith("~") \
            and not re.match(r"^[A-Za-z]:", said):
        sep = "\\" if "\\" in here and "/" not in here else "/"
        said = here.rstrip("\\/") + sep + said
    return said


# Focus selects the whole path. Escape restores it once something else is typed; before
# that the dialog gets the key and closes.
_FOCUS_JS = ("() => { const input = document.getElementById(%s);"
             " setTimeout(() => input && input.select(), 0); }")
_ESCAPE_JS = ("(event) => { if (event.key !== 'Escape') return;"
              " const input = document.getElementById(%s);"
              " if (!input || input.dataset.shown === undefined"
              " || input.value === input.dataset.shown) return;"
              " event.stopPropagation(); input.value = input.dataset.shown;"
              " input.dispatchEvent(new Event('input')); window.consolePathEnd(%s); }")
# The field is drawn again on arriving, so Enter would leave the keyboard on nothing.
_REFOCUS_JS = ("setTimeout(() => { const input = document.getElementById(%s);"
               " if (input) input.focus(); }, 80);")
_SHOWN_JS = ("setTimeout(() => { const input = document.getElementById(%s);"
             " if (input) input.dataset.shown = %s; }, 60);")


@on_page
async def pick_path(list_entries: Callable[..., dict], start: str = "", *,
                    kind: str = "dir", suffixes: tuple[str, ...] = (),
                    nearest: bool = False) -> str | None:
    """The chosen path, or None where the dialog was cancelled.

    A `start` that cannot be listed opens at the kind's own start, saying why, instead
    of failing to open at all - the field it came from may hold a path from a mount that
    has since gone away, or one inside a private folder.

    With `nearest`, a `start` that is not there opens at the closest folder above it that
    is, saying nothing.
    """
    refused: Exception | None = None
    here: Any = None
    try:
        here = await offload.io(list_entries, start, kind, suffixes)
    except Exception as exc:  # noqa: BLE001 - a stale saved path is not a reason to refuse
        refused = exc
        above = _enclosing(start) if nearest else ""
        while above and here is None:
            try:
                here = await offload.io(list_entries, above, kind, suffixes)
                refused = None
            except Exception:  # noqa: BLE001 - keep climbing
                above = _enclosing(above)
    if here is None:
        here = await offload.io(list_entries, "", kind, suffixes)

    picked = start if kind != "dir" and any(
        f["path"] == start for f in here.get("files") or []) else ""
    state: dict[str, Any] = {"here": here, "selected": picked, "naming": None, "shown": ""}
    choose: dict[str, Any] = {}
    field: dict[str, Any] = {}
    make_folder: Callable[[str, str], dict] | None = getattr(
        getattr(list_entries, "__self__", None), "make_folder", None) if kind == "dir" else None

    with frame.opened(t(_TITLE[kind]), wide=True) as box:
        if refused is not None:
            with ui.element("div").classes("console-attention w-full"):
                ui.icon("error_outline").classes("console-attention-icon")
                with ui.column().classes("gap-0 min-w-0"):
                    ui.label(why(refused)).classes("console-attention-line")
                    ui.label(start).classes("console-help truncate")
        with ui.column().classes("console-picker-head gap-2"):
            path_row = ui.row().classes("items-center gap-2 w-full no-wrap")
            with ui.row().classes("items-center gap-x-4 w-full no-wrap"):
                term = ui.input(placeholder=t("console.folder_picker.filter_folders"
                                              if kind == "dir"
                                              else "console.folder_picker.filter")) \
                    .props("dense outlined clearable clear-icon=close").classes("grow")
                shown = ui.checkbox(t("console.folder_picker.show_hidden"), value=False) \
                    .props("dense").classes("whitespace-nowrap")
        with ui.column().classes("console-picker-well gap-0"):
            listing_col = ui.column().classes("w-full gap-1 console-folder-list")
            ui.label(t("console.folder_picker.private_note")).classes(
                "console-help console-picker-note")

        def _choice() -> str:
            """What Choose would give: the folder you are in, or the file chosen in it."""
            return state["selected"] if kind != "dir" and state["selected"] \
                else state["here"]["path"]

        def _sync_field() -> None:
            """Show `_choice()` in the field, as what is shown and not as something typed."""
            control = field.get("control")
            if control is None or control.is_deleted:
                return
            state["shown"] = _choice()
            control.value = state["shown"]
            ui.run_javascript(_SHOWN_JS % (json.dumps(panel.native_id(control)),
                                           json.dumps(state["shown"])))
            panel.path_ends(control)

        def draw_path() -> None:
            path_row.clear()
            here_now = state["here"]
            places = {one["path"]: one for one in here_now.get("roots") or []}
            state["shown"] = _choice()
            seen: dict[str, Any] = {"was": object()}
            with path_row:
                up = panel.icon_only(verbs.UP, lambda: _go(here_now["parent"]),
                                     hint=t("console.folder_picker.up"))
                if not here_now["parent"]:
                    up.disable()
                control = panel.path_box(state["shown"], name=t("word.path"))
                field["control"] = control
                with control.add_slot("prepend"):
                    ui.icon(_ROW_ICON[kind] if kind != "dir" and state["selected"]
                            else _icon_for(places.get(here_now["path"], {}).get("name", ""),
                                           here_now["path"])).classes("console-path-mark")
                with control.add_slot("append"):
                    mark = ui.element("div").classes("console-value-state")
                    panel.copy_path(control)
                    caret = panel.icon_only(verbs.PLACES, lambda: None,
                                            hint=t("console.folder_picker.places"))
                    caret.props["aria-label"] = t("console.folder_picker.places")
                    with caret, ui.menu().props('anchor="bottom right" self="top right"'):
                        _places_menu(places)
                panel.path_input(control)
                native = json.dumps(panel.native_id(control))
                control.on("focus", js_handler=_FOCUS_JS % native)
                control.on("keyup", js_handler=_ESCAPE_JS % (native, native))
                control.on("keydown.enter", _enter)
                ui.run_javascript(_SHOWN_JS % (native, json.dumps(state["shown"])))

                def typing() -> bool:
                    return (control.value or "") != state["shown"]

                def typed() -> None:
                    if "button" in choose:
                        choose["button"].set_enabled(typing() or bool(state["selected"]))

                async def look() -> None:
                    said = control.value or ""
                    if said == seen["was"]:
                        return
                    seen["was"] = said
                    if not typing() or not said.strip():
                        mark.clear()
                        return
                    _, _, reason = await _resolve(said)
                    if control.is_deleted or (control.value or "") != said:
                        return
                    mark.clear()
                    with mark:
                        panel.value_state(path_state.MISSING if reason else path_state.OK,
                                          reason)(control)

                control.on_value_change(typed)
                # One timer comparing against what it last asked about, as `path_field`
                # does: a restarted one-shot per keystroke stops arriving.
                ui.timer(0.3, look)

        def _places_menu(places: dict[str, dict[str, Any]]) -> None:
            """One entry per place, the current one ticked."""
            def entry(place: dict[str, Any]) -> None:
                current = place["path"] == state["here"]["path"]
                icon = _icon_for(place["name"], place["path"])
                panel.menu_entry(
                    place["name"], None if current else _opens(place["path"]),
                    mark=lambda: ui.icon(icon).classes("console-menu-mark"),
                    trail=(lambda: ui.icon("check").classes("console-menu-check"))
                    if current else None,
                    classes="console-menu-on" if current else "")

            for place in places.values():
                entry(place)

        async def _resolve(text: str) -> tuple[dict[str, Any] | None, str, str]:
            """The listing that holds what was typed, the file in it that it names (empty
            for a folder), and why Enter cannot go there (empty when it can).

            The listing decides, as it does for a click: a file it does not offer, by
            kind, case or Show hidden, or a private folder, is refused here rather than
            accepted and then dropped.
            """
            where = _typed_path(text, state["here"]["path"])
            folder = await offload.io(path_state.look, where, path_state.DIR)
            is_folder = folder.state == path_state.OK
            probe = where
            if not is_folder:
                if kind == "dir":
                    return None, "", folder.reason
                found = await offload.io(path_state.look, where, kind)
                if found.state != path_state.OK:
                    return None, "", found.reason
                if kind == "file" and suffixes and not where.lower().endswith(
                        tuple(one.lower() for one in suffixes)):
                    return None, "", t("error.path.wrong_suffix", suffix=" or ".join(suffixes))
                probe = _enclosing(where)
            try:
                fresh = await offload.io(list_entries, probe, kind, suffixes, shown.value)
            except Exception as exc:  # noqa: BLE001
                return None, "", why(exc)
            name = _last_name(where).lower()
            files = fresh.get("files") or []
            entry = next((one for one in files if one["name"].lower() == name), None)
            if is_folder:
                if entry is not None and name.endswith(".app"):
                    return fresh, entry["path"], ""
                if re.search(r"\.app([\\/]|$)", where, re.IGNORECASE):
                    return None, "", t("error.path.not_listed")
                return fresh, "", ""
            if entry is None:
                return None, "", t("error.path.not_listed")
            return fresh, entry["path"], ""

        @on_page
        async def _typed(text: str) -> tuple[dict[str, Any], str] | None:
            """The listing of what was typed and the file in it that it names, or None
            where it cannot be gone to, saying why."""
            fresh, chosen, reason = await _resolve(text)
            if fresh is None:
                ui.notify(t("console.mediasource.folder_failed"), caption=reason,
                          type="negative")
                return None
            return fresh, chosen

        @on_page
        async def _enter() -> None:
            text = field["control"].value or ""
            if text == state["shown"] or not text.strip():
                _take()
                return
            got = await _typed(text)
            if got is not None:
                state["selected"] = got[1]
                _arrive(got[0])
                ui.run_javascript(_REFOCUS_JS % json.dumps(panel.native_id(field["control"])))

        def _take() -> None:
            if kind == "dir":
                box.submit(state["here"]["path"])
            elif state["selected"]:
                box.submit(state["selected"])

        @on_page
        async def _choose() -> None:
            text = field["control"].value or ""
            if text == state["shown"] or not text.strip():
                _take()
                return
            got = await _typed(text)
            if got is None:
                return
            fresh, chosen = got
            if kind == "dir":
                box.submit(fresh["path"])
            elif chosen:
                box.submit(chosen)
            else:
                _arrive(fresh)

        def select(path: str) -> None:
            state["selected"] = path
            draw_listing()
            _sync_field()
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
                ui.notify(t("console.folder_picker.make_failed"), caption=why(exc),
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
                ui.notify(t("console.mediasource.folder_failed"), caption=why(exc),
                          type="negative")
                return
            _arrive(fresh, keep_filter=keep_filter)

        def _opens(path: str) -> Callable[[], Any]:
            return lambda: _go(path)

        draw_path()
        draw_listing()
        term.on_value_change(draw_listing)
        shown.on_value_change(lambda: _go(state["here"]["path"], keep_filter=True))

        with frame.footer().classes("console-dialog-footer--ruled"):
            if make_folder is not None:
                frame.aside(t("console.folder_picker.new_folder"), _start_naming,
                            icon=verbs.NEW_FOLDER)
            frame.cancel(lambda: box.submit(None))
            if kind == "dir":
                frame.answer(t("console.folder_picker.accept"), _choose, icon=verbs.CHOOSE)
            else:
                choose["button"] = frame.answer(
                    t("console.folder_picker.choose"), _choose, icon=verbs.CHOOSE)
                if not state["selected"]:
                    choose["button"].disable()

    return await box
