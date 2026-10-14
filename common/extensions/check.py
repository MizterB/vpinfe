"""`--check-extension <folder>`: load an extension as the host does and say what it declared.

One line for each thing declared, then one for each read: only functions that read are
called (settings, `rows()`, `status()`, a dialog's first `ask()`), so nothing is sent,
saved or run. An extension whose service is down is told so, not failed: that is not
a mistake in what it declared.
"""

from __future__ import annotations

import logging
import re
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from common import i18n

from . import serving
from .host import LOADED, Record, Registry
from .store import ExtensionStore


def check(folder: Path | str) -> tuple[list[str], bool]:
    """The report for the extension in `folder`, and whether it passed."""
    lines: list[str] = []
    # A failure is reported on its own line; the log of it would print the same twice.
    quiet = logging.root.manager.disable
    logging.disable(logging.ERROR)
    try:
        with tempfile.TemporaryDirectory() as scratch:
            registry = Registry(ExtensionStore(scratch))
            record = registry.load(Path(folder).resolve())
            try:
                if record.state != LOADED:
                    lines.append(f"fails      {_why(record)}")
                    return lines, False
                return lines, _report(record, lines)
            finally:
                registry.clear()
                i18n.disown(f"ext.{record.name}")
    finally:
        logging.disable(quiet)


def _why(record: Record) -> str:
    said = i18n.t_source(record.why, **record.why_values) if record.why else ""
    return " - ".join(part for part in (said, record.error) if part) or record.name


def _report(record: Record, lines: list[str]) -> bool:
    ui = record.context.ui if record.context is not None else None
    assert ui is not None and record.manifest is not None
    manifest = record.manifest
    lines.append(f"loads      {manifest.name} {manifest.version}")
    problems: list[str] = []

    for field in ui.settings_declared:
        default = f", default {field['default']!r}" if field["default"] else ""
        lines.append(f"settings   {field['key']} ({field['type']}{default})")
    for declared in record.declared_lists:
        lines.append(f"list       {declared['key']} in {declared['area']}: "
                     f"{len(declared['columns'])} columns, {len(declared['views'])} views, "
                     f"{len(declared['verbs'])} verbs")
    for declared in record.actions:
        dialog = ui.action_objects[declared["key"]]
        methods = [one for one in ("ask", "check", "act", "run", "progress")
                   if callable(getattr(dialog, one, None))]
        lines.append(f"dialog     {declared['key']}: {' '.join(methods)}")
    if ui.account_functions is not None:
        lines.append("account    a player can hold one")
    for router, scope in record.routers:
        lines.append(f"routes     its own, on {scope}"
                     f" ({len(getattr(router, 'routes', []))} routes)")

    for key in ui.list_functions:
        _read(lines, problems, record, f"list {key}", lambda key=key: _read_list(record, key))
    if ui.settings_declared:
        _read(lines, problems, record, "settings", lambda: _read_settings(record))
    for declared in record.actions:
        key = declared["key"]
        _read(lines, problems, record, f"dialog {key}",
              lambda key=key: _read_dialog(record, key))

    for key, why in _missing(record, ui):
        problems.append(f"missing    {key} - {why}")
    lines.extend(problems)
    return not problems


def _read(lines: list[str], problems: list[str], record: Record, what: str,
          read: Any) -> None:
    try:
        said, found = read()
    except serving.ExtensionError as exc:
        if exc.unreachable:
            lines.append(f"reads      {what}: could not reach its service - {exc.message}")
        else:
            problems.append(f"fails      {what}: {exc.message}")
        return
    except Exception as exc:  # noqa: BLE001 - a bad shape is a finding, not a crash
        problems.append(f"fails      {what}: {type(exc).__name__}: {exc}")
        return
    lines.append(f"reads      {what}: {said}")
    problems.extend(f"missing    {key} - shown by {what}" for key in _stray(record, found))


def _read_list(record: Record, key: str) -> tuple[str, Any]:
    rows = serving.list_rows(record, key)["rows"]
    about = serving.list_about(record, key)
    acts = ", ".join(one["key"] for one in about["acts"]) or "none"
    return f"{len(rows)} rows, acts: {acts}", [rows, about]


def _read_settings(record: Record) -> tuple[str, Any]:
    found = serving.settings_read(record)
    return f"{len(found['fields'])} fields", found


def _read_dialog(record: Record, key: str) -> tuple[str, Any]:
    step = serving.dialog_ask(record, key)
    return f"first step has {len(step.get('fields') or [])} fields", step


def _strings(found: Any) -> Iterator[str]:
    if isinstance(found, str):
        yield found
    elif isinstance(found, dict):
        for one in found.values():
            yield from _strings(one)
    elif isinstance(found, list):
        for one in found:
            yield from _strings(one)


def _stray(record: Record, found: Any) -> list[str]:
    """Words a read showed as their own key, which is how a lookup with no entry looks."""
    shape = re.compile(rf"^ext\.{re.escape(record.name)}\.[\w.]+$")
    return sorted({one for one in _strings(found) if shape.match(one)})


def _missing(record: Record, ui: Any) -> list[tuple[str, str]]:
    """Every word the declarations leave to `i18n/en.json` that it has no entry for."""
    manifest = record.manifest
    wanted: list[tuple[str, str]] = []
    if manifest is not None and not manifest.display_name:
        wanted.append(("name", "the extension's name"))
    if manifest is not None and not manifest.description:
        wanted.append(("description", "the extension's description"))
    for field in ui.settings_declared:
        wanted.append((f"settings.{field['key']}.label", "a setting's label"))
        wanted.extend((f"settings.{field['key']}.choice.{value}", "a choice's label")
                      for value, label in field["choices"] if not label)
    for declared in record.declared_lists:
        key = declared["key"]
        if not declared["title"]:
            wanted.append((f"list.{key}.title", "a list's title"))
        wanted.extend((f"list.{key}.column.{one['field']}.header", "a column's header")
                      for one in declared["columns"] if not one["header"])
        wanted.extend((f"list.{key}.view.{one['key']}.name", "a view's name")
                      for one in declared["views"] if not one["name"])
        for verb in declared["verbs"]:
            at = f"list.{key}.verb.{verb['key']}"
            if not verb["label"]:
                wanted.append((f"{at}.label", "a verb's label"))
            if verb["danger"]:
                wanted.append((f"{at}.confirm", "the question a danger verb asks"))
            if verb["needs"]:
                wanted.append((f"{at}.needs", "why a verb is not for a row"))
    wanted.extend((f"action.{one['key']}.label", "a dialog's label")
                  for one in record.actions if not one["label"])
    return [(f"ext.{record.name}.{suffix}", why) for suffix, why in wanted
            if not i18n.first_key(f"ext.{record.name}.{suffix}")]
