"""A table's Settings section: which launcher plays it, then what the program that
launcher runs does differently for this table.

The program's rows are the table's differences and nothing else. Every setting, at this
table, is one step further: Show Every Setting.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from functools import partial
from types import SimpleNamespace
from typing import Any

from nicegui import ui

from common.i18n import t
from console import dialog as frame
from console import offload, panel, verbs, workbench
from console.data import config_groups

SCOPE_ENTRY = "entry"


def title_for(game_name: str, table_name: str, launcher_name: str,
              folder_tables: int) -> str:
    """Named for the table being edited. The game names it, and the table is added where
    the game has more than one."""
    subject = (t("console.app_settings.game_and_table", game=game_name, table=table_name)
               if folder_tables > 1 and table_name else game_name)
    return t("console.app_settings.settings", table=subject, launcher_name=launcher_name)


def shared_note(found: dict, folder_tables: int) -> tuple[Any, Any] | None:
    """Where this table's file is also its game's, what a value set for it reaches."""
    if folder_tables <= 1 or not found.get("shared_with_game"):
        return None
    return panel.intro(t("console.app_settings.shared_with_game", count=folder_tables - 1))


async def section(context: dict[str, Any]) -> None:
    table = next((one for one in context["tables"] if one.get("id") == context["lens"]),
                 None)
    entries = ([(panel.HEADING, t("console.workbench.launcher_2")),
                *workbench.launcher_rows(context, table),
                *await _program_entries(context, table)]
               if table is not None else [])
    with ui.column().classes("gap-0 console-form"):
        if table is None:
            ui.label(t("console.workbench.no_table_selected")).classes("console-help")
            return
        panel.facts(ui, entries)


def _runs(context: dict[str, Any], table: dict[str, Any]) -> dict[str, Any] | None:
    held = (context.get("launchers") or {}).get("launchers") or []
    return next((one for one in held if one["launcher_id"] == table.get("launcher")), None)


async def _program_entries(context: dict[str, Any],
                           table: dict[str, Any]) -> list[tuple[Any, Any]]:
    launcher = _runs(context, table)
    if launcher is None or not launcher.get("has_config"):
        return []
    library = context["library"]
    entries: list[tuple[Any, Any]] = [(panel.HEADING, t(
        "console.app_settings.for_this_table", app=launcher.get("app_name") or ""))]
    if note := workbench._program_note(launcher):
        return [*entries, panel.intro(note)]
    table_id = str(table.get("id") or "")
    try:
        found = await offload.io(library.launcher_config, launcher["launcher_id"],
                                 table_id, SCOPE_ENTRY)
    except Exception as exc:  # noqa: BLE001 - this says why, never 500s
        return [*entries, panel.intro(t("said.could_not_read_the_settings", exc=exc))]

    groups = config_groups(found)
    values = dict(found.get("values") or {})
    if shared := shared_note(found, len(context.get("tables") or []) or 1):
        entries.append(shared)
    blocks = differences(groups, values)
    camera = _camera(groups, values)
    if not blocks and not camera:
        entries.append(panel.intro(t("console.app_settings.same_as_all_tables")))
    inner: dict[str, Any] = {
        "library": library, "launcher": launcher, "config_groups": groups,
        "config_values": values, "config_scope": SCOPE_ENTRY, "config_table": table_id,
        "playing": await offload.io(workbench._playing, library),
        "state": context["state"], "rebuild": context["rebuild"],
    }
    entries += await workbench._setting_entries(
        inner, [(label, "", fields) for label, fields in blocks], curated=True, sub=True)
    entries += camera
    entries.append((panel.FULL, panel.action(
        t("console.app_settings.show_every_setting"),
        partial(_every_setting, context, table, inner), icon=verbs.DRILL)))
    return entries


def differences(groups: Sequence[Any], values: dict[str, Any]) -> list[tuple[str, list[Any]]]:
    """What this table's file sets and what reaches it from its game's, by area: the rows
    an area curates first, in its order, then the rest in the program's. A plugin's rows
    lead with the plugin's name, which is all that tells five Enables apart, and a row
    whose label another setting in its area shares leads with its window's."""
    names = workbench._plugin_names(groups)
    found = []
    for group in groups:
        if group.summarized:
            continue
        order = {key: at for at, key in
                 enumerate(key for heading in group.curated for key in heading.keys)}
        fields = sorted((field for field in group.settings
                         if _differs(values.get(field.key) or {})),
                        key=lambda field: order.get(field.key, len(order)))
        if fields:
            found.append((group.label, [_named(field, group, names) for field in fields]))
    return found


def _differs(held: dict[str, Any]) -> bool:
    return bool(held.get("set_here")) or held.get("scope") == "folder"


def _named(field: Any, group: Any, names: dict[str, str]) -> Any:
    section = workbench._section_of(field.key)
    if section.startswith(workbench.PLUGIN_SECTION):
        plugin = section[len(workbench.PLUGIN_SECTION):]
        label = t("console.app_settings.plugin_row", plugin=names.get(plugin, plugin),
                  label=field.label)
    elif (sum(one.label == field.label for one in group.settings) > 1
          and (window := _window_of(field.key, group))):
        label = t("console.app_settings.window_row", window=window, label=field.label)
    else:
        return field
    return SimpleNamespace(**{**vars(field), "label": label})


def _window_of(key: str, group: Any) -> str:
    """The curated heading a setting is drawn under, or the one whose keys its own
    continues: `BackglassFSWidth` goes with the heading of `BackglassOutput` and
    `BackglassDisplay`."""
    held = next((heading for heading in group.curated if key in heading.keys), None)
    if held is not None:
        return str(held.label)
    name = key.rsplit(".", 1)[-1]
    for heading in group.curated:
        names = [one.rsplit(".", 1)[-1] for one in heading.keys]
        stem = os.path.commonprefix(names)
        if (len(names) > 1 and stem and name.startswith(stem)
                and {workbench._section_of(one) for one in heading.keys}
                == {workbench._section_of(key)}):
            return str(heading.label)
    return ""


def _camera(groups: Sequence[Any], values: dict[str, Any]) -> list[tuple[Any, Any]]:
    """The camera as one row, where this table has one saved or its game gives it one."""
    group = next((one for one in groups if one.summarized), None)
    held = [values.get(field.key) or {} for field in (group.settings if group else ())]
    if group is None or not any(_differs(one) for one in held):
        return []
    own = any(one.get("set_here") for one in held)
    return [(panel.FULL, partial(workbench._subheading, group.label)),
            (t("console.app_settings.camera"),
             t("console.workbench.saved_for_this_table" if own
               else "console.app_settings.saved_for_this_game"))]


async def _every_setting(context: dict[str, Any], table: dict[str, Any],
                         inner: dict[str, Any]) -> None:
    """All Settings, at this table, over the panel. The panel is drawn again on the way
    out, since anything here may have changed what it lists."""
    count = len(context.get("tables") or []) or 1
    title = title_for(str((context.get("game") or {}).get("name") or ""),
                      workbench._table_line(table),
                      str(inner["launcher"].get("display_name") or ""), count)
    every: dict[str, Any] = {**inner, "state": {"all_settings": {}}}
    every.pop("config_values", None)

    with frame.opened(title, full=True) as dialog:
        body = ui.column().classes("w-full grow min-h-0 gap-0 overflow-auto")

        async def redraw() -> None:
            every.pop("config_values", None)
            body.clear()
            with body:
                await workbench._all_settings(every)

        every["rebuild"] = redraw
        await redraw()
        with frame.footer():
            frame.answer(t("word.done"), dialog.close, icon=verbs.DONE)

    dialog.on("hide", lambda: context["rebuild"]())
    dialog.open()
