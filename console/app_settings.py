
"""The program's own settings for one table, opened over the workbench.

One component, two ways in. The launcher's rail opens it fixed to that launcher and
shows every group; this opens it for a table, where the question is almost always one
setting and the scope arrives already correct. Somebody who has never seen this screen
should be able to change one setting for one table without touching the scope picker.

Scopes are named for what they do rather than for the files behind them. A person thinks
"the DMD off for this one table" or "hide the grill on everything"; a filename belongs in
a tooltip and in the log, nowhere else.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from nicegui import run, ui

from common.i18n import t
from console import confirm, offload, panel, verbs
from console import dialog as frame
from console.data import Library

# One definition of both: the launcher's rail and this dialog are the same surface at
# two scopes, and two spellings of "a table is playing" would drift.
from console.workbench import CAME_FROM, PLAYING_NOTE, PLAYING_WHY, _playing

logger = logging.getLogger("vpinfe.console.app_settings")

SCOPE_ENTRY = "entry"
SCOPE_FOLDER = "folder"
SCOPE_LAUNCHER = "launcher"


def scope_words(folder_tables: int) -> dict[str, str]:
    """What each scope is called: the words the mark beside a value uses, so where an
    edit goes and where a value came from are said the same way."""
    words = {scope: t(key) for scope, key in CAME_FROM.items()}
    if folder_tables > 1:
        words[SCOPE_FOLDER] = t("console.app_settings.folder_tables",
                                scope=words[SCOPE_FOLDER], folder_tables=folder_tables)
    return words


def title_for(game_name: str, table_name: str, launcher_name: str,
              folder_tables: int) -> str:
    """Named for the table being edited. The game names it, and the table is added where
    the game has more than one."""
    subject = (t("console.app_settings.game_and_table", game=game_name, table=table_name)
               if folder_tables > 1 and table_name else game_name)
    return t("console.app_settings.settings", table=subject, launcher_name=launcher_name)


def shared_note(found: dict, scope: str, folder_tables: int) -> tuple[Any, Any] | None:
    """Where this table's file is also its game's, what a value set for it reaches."""
    if scope != SCOPE_ENTRY or folder_tables <= 1 or not found.get("shared_with_game"):
        return None
    return panel.intro(t("console.app_settings.shared_with_game", count=folder_tables - 1))


async def open_for_table(library: Library, *, launcher_id: str, launcher_name: str,
                         table_id: str, game_name: str, table_name: str = "",
                         folder_tables: int = 1,
                         on_done: Callable | None = None) -> None:
    if not launcher_id:
        ui.notify(t("console.app_settings.table_no_launcher_configure"), type="warning")
        return

    state: dict[str, Any] = {"scope": SCOPE_ENTRY, "search": "",
                             "folder_tables": folder_tables}
    words = scope_words(folder_tables)

    with frame.opened(title_for(game_name, table_name, launcher_name, folder_tables),
                      full=True) as dialog:
        # The picker before the settings, because it says where an edit will go and
        # that has to be readable before anything is edited rather than after.
        with ui.row().classes("items-center gap-3 w-full no-wrap px-3 pb-2"):
            ui.label(t("console.app_settings.edits_go")).classes("console-label text-xs")
            scope = ui.select(words, value=state["scope"]) \
                .props("dense outlined options-dense").classes("w-64")
            search = panel.search(t("console.app_settings.search_settings"))

        body = ui.column().classes("w-full grow min-h-0 gap-0 overflow-auto")

        async def draw() -> None:
            body.clear()
            with body:
                await _fill(library, launcher_id, table_id, state, words, draw)

        scope.on_value_change(lambda: _pick(state, scope.value, draw))
        search.on_value_change(lambda: _find(state, search.value or "", draw))
        await draw()
        with frame.footer():
            frame.answer(t("word.done"), dialog.close, icon=verbs.DONE)

    dialog.on("hide", lambda: on_done() if callable(on_done) else None)
    dialog.open()


def _pick(state: dict[str, Any], chosen: Any, draw: Callable) -> Any:
    state["scope"] = str(chosen or SCOPE_ENTRY)
    return draw()


def _find(state: dict[str, Any], text: str, draw: Callable) -> Any:
    state["search"] = text.strip().lower()
    return draw()


async def _fill(library: Library, launcher_id: str, table_id: str, state: dict[str, Any],
                words: dict[str, str], draw: Callable) -> None:
    scope = state["scope"]
    try:
        found = await offload.io(library.launcher_config, launcher_id,
                                   table_id, scope)
    except Exception as exc:  # noqa: BLE001 - this says why, never 500s
        panel.facts(ui, [panel.intro(t("said.could_not_read_the_settings", exc=(exc)))])
        return

    groups = found.get("groups") or []
    values = found.get("values") or {}
    playing = await offload.io(_playing, library)
    entries: list[tuple[Any, Any]] = []
    if (shared := shared_note(found, scope, int(state.get("folder_tables") or 1))):
        entries.append(shared)
    if playing:
        entries.append(panel.intro(t(PLAYING_NOTE), hint=t(PLAYING_WHY)))
    app_name = str(found.get("app_name") or "")
    wanted = state["search"]
    shown = 0
    for group in groups:
        if group.get("summarized"):
            continue
        rows = [f for f in group["settings"]
                if not wanted or wanted in f["label"].lower()
                or wanted in f["key"].lower()]
        if not rows:
            continue
        shown += len(rows)
        entries.append((panel.HEADING, group["label"]))
        entries.extend(_group_rows(library, launcher_id, table_id, scope, rows, values,
                                   draw, app_name, playing))

    if not shown:
        entries.append(panel.intro(
            t("console.app_settings.nothing_matches", value=(state['search'])) if wanted
            else t("console.app_settings.no_settings_show", value=(words[scope]))))
    with ui.column().classes("gap-0 console-form"):
        panel.facts(ui, entries)


def _group_rows(library: Library, launcher_id: str, table_id: str, scope: str,
                rows: list[dict], values: dict, draw: Callable, app_name: str,
                playing: bool = False) -> list[tuple[Any, Any]]:
    """One group's settings, with where each value comes from and the way off it."""
    from console import workbench

    entries: list[tuple[Any, Any]] = []
    for field in rows:
        held = values.get(field["key"]) or {}
        entries.append((field["label"], workbench._marked(
            _control(library, launcher_id, table_id, scope, field, held, draw, playing),
            held, _Field(field), app_name)))
        aside = _aside(library, launcher_id, table_id, scope, field, held, draw,
                       app_name, playing)
        if aside is not None:
            entries.append((panel.ASIDE, aside))
        if field.get("description"):
            entries.append(panel.note(field["description"]))
    return entries


def _control(library: Library, launcher_id: str, table_id: str, scope: str, field: dict,
             held: dict, draw: Callable, playing: bool = False) -> Callable[[], None]:
    """The control always shows the effective value: you never look at a number that is
    not the one the program will use."""
    from console import settings as settings_page

    async def save(value: Any) -> bool:
        # Giving a table its own file takes it off the folder's, so what the folder is
        # currently giving it has to be shown before that happens rather than found
        # afterwards. Only on the write that creates the file.
        seed = False
        if scope == SCOPE_ENTRY and not held.get("set_here"):
            answer = await confirm_new_table_file(library, launcher_id, table_id)
            if answer is None:
                await draw()
                return False
            seed = answer
        try:
            wrote = await run.io_bound(library.write_launcher_config, launcher_id,
                                       {field["key"]: _as_text(value)},
                                       table=table_id, scope=scope, seed=seed)
        except Exception as exc:  # noqa: BLE001
            ui.notify(t("said.could_not_save_it", exc=(exc)), type="negative")
            await draw()
            return False
        if field["key"] in (wrote or {}).get("cleared", ()):
            ui.notify(t("console.app_settings.now_same_all_tables"), type="positive")
        await draw()
        return True

    option = dict(field)
    if field.get("choices"):
        option["choices"] = {value: label for value, label in field["choices"]}
        option["type"] = "choice"
    # `or`, not a default argument: a setting nobody has touched has an empty effective
    # value, and a closed set of answers has no option spelled "". The control shows what
    # the program will use, which for an untouched setting is its own default.
    return settings_page.control_for(
        option, settings_page.value_for(option, held.get("value")), save,
        writable=not playing and _offered_here(field, scope))


def _offered_here(field: dict, scope: str) -> bool:
    return scope in field.get("scopes", (scope,))


def _aside(library: Library, launcher_id: str, table_id: str, scope: str, field: dict,
           held: dict, draw: Callable, app_name: str,
           playing: bool = False) -> Callable[[], None] | None:
    from console import workbench

    mark = (workbench._config_mark(held, scope, _Field(field))
            if _offered_here(field, scope)
            else panel.state(t("console.app_settings.unused"), "warn",
                             hint=t("console.app_settings.all_tables_only")))
    if mark is None and not held.get("set_here"):
        return None

    async def wipe() -> None:
        try:
            await run.io_bound(library.write_launcher_config, launcher_id,
                               {field["key"]: ""}, table=table_id, scope=scope)
        except Exception as exc:  # noqa: BLE001
            ui.notify(t("said.could_not_clear_it", exc=(exc)), type="negative")
            return
        await draw()

    def drawn() -> None:
        with ui.row().classes("items-center gap-2 no-wrap"):
            if mark is not None:
                mark()
            if held.get("set_here"):
                panel.action(t("word.clear"), wipe, icon=verbs.CLEAR, inline=True,
                             enabled=not playing,
                             hint=(t(workbench.PLAYING_NOTE) if playing
                                   else workbench._clear_hint(held, _Field(field),
                                                              app_name)))()
    return drawn


class _Field:
    """A setting off the wire, read the way the workbench reads a field."""

    def __init__(self, field: dict) -> None:
        self.type = field.get("type", "")
        self.choices = tuple(tuple(pair) for pair in field.get("choices") or ())
        self.default = field.get("default", "")


def _as_text(value: Any) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    return "" if value is None else str(value)


async def confirm_new_table_file(library: Library, launcher_id: str,
                                 table_id: str) -> bool | None:
    """Asked before a table gets a file of its own, where a folder file is reaching it.

    Returns whether to carry the folder's settings across, or None if the write should
    not happen at all.

    The two do not stack: once a table has its own file, the folder's other keys stop
    reaching it and fall through to the launcher. Carrying them is the only answer
    offered, because the alternative changes what the table does without saying so - the
    question here is whether to go ahead, not which of two things to do.
    """
    try:
        reaching = await offload.io(library.folder_settings_reaching, launcher_id,
                                      table_id)
    except Exception:  # noqa: BLE001 - a confirm must not be the thing that breaks
        logger.exception("Could not read what the folder gives this table")
        return False
    if not reaching:
        return False
    count = len(reaching)
    said = await confirm.ask(
        t("console.app_settings.setting_currently_reach_table", count=count),
        detail=t("console.app_settings.giving_table_own_settings"),
        confirm=t("console.app_settings.keep_them"), icon=verbs.KEEP)
    return True if said else None
