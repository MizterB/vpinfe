"""Every setting this install has, what it is set to, and what may be changed.

`common/config_schema.py` declares what a setting is called, what it accepts and what it
means. This answers the three questions a settings page asks of that: describe it, read
it, write it - once, so the config file, the Console and anything reading over HTTP
describe the same install the same way.

Values are typed the way the store types them - a bool arrives as a bool, a list as a
list - because a caller that has to know which strings mean true holds half a schema of
its own.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from common import config_schema, events, install_presence, path_state, port_checks
from common.apps.contract import Field
from common.backups import folder as backups_folder
from common.failures import why
from common.i18n import t
from common.labels import humanize
from common.manufacturer_logos import resolve_logos_dir
from common.paths import CONFIG_DIR, get_ini_config

logger = logging.getLogger("vpinfe.common.config_service")

# Sections served over the API and refused a write. Empty; the refusal path below is
# what a caller-origin check would reuse.
READ_ONLY_SECTIONS: frozenset[str] = frozenset()


class UnknownSettingsError(ValueError):
    """Keys no schema knows. `keys` names every one of them."""

    def __init__(self, keys: list[str]) -> None:
        self.keys = sorted(keys)
        super().__init__(", ".join(self.keys))


class SettingsWriteError(RuntimeError):
    """The settings file could not be written. The values are already in the store."""


class ReadOnlySettingsError(ValueError):
    """Keys this install will not take over the wire. `keys` names every one."""

    def __init__(self, keys: list[str]) -> None:
        self.keys = sorted(keys)
        super().__init__(", ".join(self.keys))


class RefusedSettingsError(ValueError):
    """Values a setting cannot hold on this machine. `reasons` says why, keyed
    `section.key`."""

    def __init__(self, reasons: dict[str, str]) -> None:
        self.reasons = dict(reasons)
        super().__init__("; ".join(reasons.values()))


def _describe(option: config_schema.ConfigOption) -> dict[str, Any]:
    return {
        "section": option.section,
        "key": option.key,
        "type": option.type,
        "default": option.default,
        "label": option.label or option.key,
        "label_key": f"{option.keys}.label",
        "description": option.description,
        "choices": list(option.choices),
        "choice_labels": option.choice_labels,
        "writable": option.section not in READ_ONLY_SECTIONS,
        # So a caller knows which strings name something on disk without matching on the
        # key. Empty for everything that is only text.
        "path": option.path,
        # Which live list is worth offering beside this setting, where one is. Named
        # rather than filled in here: the values change while the install runs, so a
        # caller asks for them when it draws rather than reading a snapshot taken when
        # the schema was described.
        "suggest": option.suggest,
        # What to gather it under on a page. Answered here rather than decided by each
        # surface, so the grouping is the schema's answer and not one each one invents.
        "group": option.group,
        "group_label": option.group_label,
        "editor": option.editor,
        # How many rows a text field gets. A setting declared over three lines that
        # arrives without this renders as a one-line box - which is what a command list
        # did until it was served.
        "lines": option.lines,
        "default_is": option.default_is,
        "unit": option.unit,
        "cuts_off_console": option.cuts_off_console,
        "applies": option.applies,
        "blank": option.blank,
        "home": option.home,
    }


def _said(key: str, fallback: str) -> str:
    said = t(key)
    return fallback if said == key else said


def _describe_field(list_key: str, field: Field) -> dict[str, Any]:
    words = f"config.list.{list_key}.field.{field.key}"
    return {
        "key": field.key,
        "type": field.type,
        "default": field.default,
        "label": field.label or _said(f"{words}.label", humanize(field.key)),
        "description": field.description or _said(f"{words}.description", ""),
        "choices": [{"value": value, "label": label} for value, label in field.choices],
        "lines": field.lines,
        "minimum": field.minimum,
        "maximum": field.maximum,
        "path": field.path,
        "suffixes": list(field.suffixes),
    }


def _describe_list(spec: config_schema.ConfigList) -> dict[str, Any]:
    variant = spec.variant
    return {
        "key": spec.key,
        "label": _said(f"config.list.{spec.key}.label", humanize(spec.key)),
        "home": spec.home,
        "fields": [_describe_field(spec.key, field) for field in spec.fields],
        "variant": None if variant is None else {
            "field": variant.field,
            "kinds": [{"kind": kind,
                       "fields": [_describe_field(spec.key, field)
                                  for field in variant.fields(kind) or ()]}
                      for kind in variant.kinds()],
        },
    }


def settable(windows: Sequence[str]) -> tuple[config_schema.ConfigOption, ...]:
    """The schema's settings, with a screen for each of `windows` it does not declare
    placed after its own."""
    declared = config_schema.settable()
    held = {option.section for option in declared}
    added = tuple(option for option in map(config_schema.window_screen, dict.fromkeys(windows))
                  if option.section not in held)
    after = 1 + max((at for at, option in enumerate(declared)
                     if config_schema.window_name(option.section)), default=-1)
    return (*declared[:after], *added, *declared[after:])


def schema(windows: Sequence[str] = ()) -> dict[str, Any]:
    """What a settings page is built from. `windows` are the active theme's.

    Internal options are left out: they are runtime state that happens to live in the
    config file, and offering a last-played pointer as a setting invites someone to set
    it. `settable()` is the same predicate the config file's own docs use.
    """
    options = [_describe(option) for option in settable(windows)]
    sections = [{"name": name,
                 "writable": name not in READ_ONLY_SECTIONS,
                 "options": [o for o in options if o["section"] == name]}
                for name in dict.fromkeys(option["section"] for option in options)]
    return {"sections": sections, "count": len(options),
            "lists": [_describe_list(spec) for spec in config_schema.lists()]}


def blank_stands_for() -> dict[tuple[str, str], str]:
    """By (section, key), the path a blank path setting falls back to on this machine.

    Only a setting whose blank means a folder VPinFE picks for itself is here. A Tool or
    the browser left blank is discovered instead, and those answer through their own
    reports.
    """
    return {(backups_folder.SECTION, backups_folder.FOLDER): str(backups_folder.DEFAULT_DIR),
            ("media", "manufacturer_logos_dir"): str(resolve_logos_dir("", CONFIG_DIR))}


def path_states() -> dict[str, Any]:
    """Every path setting, checked against this machine's disk.

    All of them in one answer rather than one call per field: a settings page wants the
    whole column at once, and the alternative is six requests that each stat one file.
    `default` is the path a blank one stands for, so the page can show where it points.
    """
    store = get_ini_config()
    options = path_state.path_options()
    found = path_state.look_all(
        path_state.Ask(store.value(option.section, option.key), option.path)
        for option in options)
    stands_for = blank_stands_for()
    return {"checks": [{"section": option.section, "key": option.key, "path": option.path,
                        "state": one.state, "reason": one.reason,
                        "default": stands_for.get((option.section, option.key), "")}
                       for option, one in zip(options, found, strict=True)]}


def values(windows: Sequence[str] = ()) -> dict[str, Any]:
    """Current values, typed. A setting the file does not carry answers its default,
    because that is what the install is actually running on."""
    store = get_ini_config()
    found: dict[str, dict[str, Any]] = {}
    for option in settable(windows):
        found.setdefault(option.section, {})[option.key] = \
            store.value(option.section, option.key)
    return {"values": found}


def set_values(wanted: dict[str, dict[str, Any]] | None,
               windows: Sequence[str] = ()) -> dict[str, Any]:
    """A patch: only the sections and keys given are written.

    Every key is checked against the schema first and the whole request is refused if any
    of them is unknown. Half-applying a settings save leaves an install in a state nobody
    asked for and no screen reflects.
    """
    store = get_ini_config()
    served = set(settable(windows))
    staged: list[tuple[str, str, Any]] = []
    unknown: list[str] = []
    refused: list[str] = []

    for section, entries in (wanted or {}).items():
        for key, value in (entries or {}).items():
            # Any spelling this setting has ever had, including a section it has since
            # moved out of. A caller written against an older name keeps working, which
            # is the contract every other reader of the config already honours.
            here, name = config_schema.locate(section, key)
            option = config_schema.option(here, name)
            if option is None or option not in served:
                unknown.append(f"{section}.{key}")
            elif option.section in READ_ONLY_SECTIONS:
                refused.append(f"{option.section}.{option.key}")
            else:
                staged.append((option.section, option.key, value))

    if unknown:
        raise UnknownSettingsError(unknown)
    if refused:
        raise ReadOnlySettingsError(refused)
    if not staged:
        return values(windows)
    if reasons := port_checks.refused(wanted):
        raise RefusedSettingsError(reasons)

    changed: list[str] = []
    for section, key, value in staged:
        before = store.value(section, key)
        store.set_value(section, key, value)
        if store.value(section, key) != before:
            changed.append(f"{section}.{key}")
    try:
        store.save()
    except Exception as exc:
        logger.exception("Could not write the settings file")
        raise SettingsWriteError(why(exc)) from exc

    if any(section == "device" and key == "name" for section, key, _ in staged):
        # The registry holds a copy of what each install reported. This one just changed
        # what it reports, and every screen listing devices reads the copy.
        install_presence.record_self()
    if changed:
        events.emit(events.SETTINGS_CHANGED, keys=changed, ini_config=store)
    return values(windows)
