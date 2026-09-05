"""The programs that play a table, which files each one claims, and what configuring
one of them takes.

Visual Pinball is the only real one today, and writing it down is what makes the next one
an entry in a tuple rather than a search for every place ".vpx" was assumed.

An app is code and a launcher is user data: the app says what fields configuring it takes,
and a launcher holds the values. That split is why a second way of running Visual Pinball
costs a row rather than seven more settings named after it.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Field:
    """One thing configuring an app takes, and how to draw it.

    Deliberately the shape of `config_schema.ConfigOption` minus the section: an editor
    generated from these should look like every settings page, and `path` feeds the same
    check that tells a person their binary is not where they said.
    """

    key: str
    label: str
    type: str = "string"
    default: str = ""
    description: str = ""
    # "file", "dir" or "exe" where this names something on disk. Declared rather than
    # guessed from the key: `bin_path` and `ini_path` end the same way and want
    # different answers.
    path: str = ""


@dataclass(frozen=True)
class App:
    """One program that plays a table, the files it claims, and what a launcher of it
    holds. Suffixes are lowercase and include the dot."""

    id: str
    name: str
    suffixes: tuple[str, ...]
    fields: tuple[Field, ...] = ()


# What running Visual Pinball takes, in the order a person meets it: what to run, then
# what to run it with, then the two overrides. The names have shed the `vpx_` prefix -
# a field on a Visual Pinball launcher does not need to say which app it belongs to.
VPX_FIELDS: tuple[Field, ...] = (
    Field("bin_path", "Program", path="exe",
          description="The Visual Pinball executable this launcher runs."),
    Field("ini_path", "Configuration File", path="file",
          description="The VPinballX.ini this launcher reads. Leave empty for the one "
                      "Visual Pinball finds itself."),
    Field("launch_env", "Environment",
          description="Variables to set before launching, one NAME=value per line."),
    Field("log_delete_on_start", "Clear The Log On Launch", type="bool", default="false",
          description="Delete Visual Pinball's log before each table, so what is in it "
                      "is about the table that just ran."),
    Field("ini_override", "Override File", path="file",
          description="Launch every table with this ini instead of the usual one."),
    Field("table_ini_override_enabled", "Per-Table Override", type="bool",
          default="false",
          description="Let a table use its own ini file when one sits beside it."),
    Field("table_ini_override_mask", "Per-Table Override Pattern",
          description="How a table's own ini is named, relative to the table."),
)

APPS: tuple[App, ...] = (
    App("vpx", "Visual Pinball X", (".vpx",), VPX_FIELDS),
)

DEFAULT_APP = APPS[0]


def app_for(filename: str) -> App | None:
    """Which app claims this file, or None for something that is not a table."""
    lowered = str(filename or "").lower()
    return next((app for app in APPS
                 if any(lowered.endswith(suffix) for suffix in app.suffixes)), None)


def app_name(app_id: str | None) -> str:
    """What to call an app on screen. Ids are for the wire; "vpx" shown to a user is
    an identifier leaking through where "Visual Pinball X" is the name. An id nothing
    claims is returned as it came, because inventing a name for it would be worse."""
    wanted = str(app_id or "").strip()
    if not wanted:
        return "-"
    return next((app.name for app in APPS if app.id == wanted), wanted)


def table_suffixes() -> tuple[str, ...]:
    """Every extension that makes a file a table, for a folder listing to filter on."""
    return tuple(suffix for app in APPS for suffix in app.suffixes)


def strip_suffix(filename: str) -> str:
    """The name without the extension its app claims it by. Not Path.stem: "Foo (Bar
    1.2).vpx" keeps everything up to the extension we know, and only that."""
    app = app_for(filename)
    if app is None:
        return str(filename or "")
    lowered = str(filename).lower()
    suffix = next(s for s in app.suffixes if lowered.endswith(s))
    return str(filename)[: -len(suffix)]
