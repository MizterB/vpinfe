"""The frontend themes this install knows, and which one plays.

Cards rather than a grid. A theme is chosen by looking at it - the preview is the point,
and a row of text columns is the one shape that cannot show one.

Active first, then installed, then the rest, which is the order somebody scans in: what
am I running, what could I switch to without downloading, what else is there.

**Configure renders the theme's own schema, not ours.** A theme declares its options in
its own manifest and this install has no opinion about what they can be. What a person
chooses is kept *outside* the theme package - an update deletes the package, and values
written into it were reset by the next update every time.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from nicegui import run, ui

from console import confirm, panel

logger = logging.getLogger("vpinfe.console.themes")

# What a theme says it needs. Named here because a number is not an answer: "3" is a
# cabinet, and somebody choosing a theme is choosing against the screens they have.
SCREENS = {1: "Desktop", 2: "Two screens", 3: "Cabinet"}


def build(library, state: dict[str, Any], redraw: Callable[[], None]) -> None:
    body = ui.column().classes("w-full gap-3")
    ui.timer(0.01, lambda: _fill(library, state, redraw, body, refresh=False),
             once=True)


async def _fill(library, state: dict[str, Any], redraw: Callable[[], None], body,
                refresh: bool) -> None:
    try:
        found = await run.io_bound(library.themes, refresh)
    except Exception as exc:  # noqa: BLE001 - this page says why, never 500s
        body.clear()
        with body:
            panel.facts(ui, [panel.intro(f"Could not read the themes: {exc}")])
        return

    themes = list(found.get("themes") or [])
    body.clear()
    with body:
        with ui.row().classes("items-center gap-2 w-full no-wrap px-1 pt-1"):
            ui.label("What the frontend looks like. Installing one downloads it; "
                     "making one active takes effect when the frontend next starts.") \
                .classes("console-help grow min-w-0")
            ui.button("Check for updates", icon="refresh",
                      on_click=lambda: _fill(library, state, redraw, body,
                                             refresh=True)) \
                .props("flat dense no-caps size=sm")
        if not themes:
            panel.facts(ui, [panel.intro(
                "No theme sources are configured, so there is nothing to list.")])
            return
        for theme in themes:
            _card(library, state, redraw, body, theme)


def _card(library, state: dict[str, Any], redraw: Callable[[], None], body,
          theme: dict[str, Any]) -> None:
    classes = "console-card w-full console-theme-card"
    if theme["active"]:
        classes += " console-theme-card--active"
    with ui.element("div").classes(classes):
        with ui.row().classes("w-full gap-4 no-wrap items-start"):
            _preview(theme)
            with ui.column().classes("gap-1 grow min-w-0"):
                _heading(theme)
                if theme.get("description"):
                    ui.label(theme["description"]).classes("console-help")
                ui.label(_said(theme)).classes("console-help")
                _actions(library, state, redraw, body, theme)
        # Only where it says something new: what changed matters before you take it,
        # and reading it about the copy you already run is reading old news.
        if theme.get("change_log") and (not theme["installed"]
                                        or theme["update_available"]):
            with ui.element("div").classes("console-theme-changes"):
                ui.label(theme["change_log"]).classes("console-help")


def _preview(theme: dict[str, Any]) -> None:
    """The picture, at one size so a column of cards has one left edge."""
    with ui.element("div").classes("console-theme-preview shrink-0"):
        if theme.get("preview"):
            ui.image(theme["preview"]).classes("w-full")
        else:
            ui.icon("image_not_supported", size="40px").classes("opacity-40")


def _heading(theme: dict[str, Any]) -> None:
    with ui.row().classes("items-center gap-2 w-full no-wrap flex-wrap"):
        ui.label(theme["name"]).classes("console-setting")
        # One state chip, not four. A theme is exactly one of these, and drawing the
        # others as absent would put a badge on every card saying nothing.
        if theme["active"]:
            _chip("Active", "console-tier--on")
        elif theme["update_available"]:
            _chip(f"Update to {theme['version']}", "console-tier--warn")
        elif theme["installed"]:
            _chip("Installed", "console-tier--off")
        if theme.get("configurable"):
            _chip("Configurable", "console-tier--off")
        if theme.get("url"):
            ui.link("Source", theme["url"], new_tab=True).classes("console-help")


def _chip(text: str, tone: str) -> None:
    ui.label(text).classes(f"console-member-chip console-tier {tone}")


def _said(theme: dict[str, Any]) -> str:
    """The facts that fit on one line: who made it, which version, what it needs."""
    parts = []
    if theme.get("author"):
        parts.append(f"by {theme['author']}")
    version = theme.get("installed_version") or theme.get("version")
    if version and theme["update_available"]:
        parts.append(f"v{theme['installed_version']} → v{theme['version']}")
    elif version:
        parts.append(f"v{version}")
    screens = theme.get("screens")
    if isinstance(screens, int):
        parts.append(SCREENS.get(screens, f"{screens} screens"))
    return " · ".join(parts)


def _actions(library, state: dict[str, Any], redraw: Callable[[], None], body,
             theme: dict[str, Any]) -> None:
    key = theme["key"]

    async def again() -> None:
        await _fill(library, state, redraw, body, refresh=False)

    with ui.row().classes("items-center gap-2 no-wrap flex-wrap pt-1"):
        if not theme["installed"]:
            ui.button("Install", icon="download",
                      on_click=lambda: _install(library, key, again)) \
                .props("flat dense no-caps size=sm")
        elif theme["update_available"]:
            ui.button("Update", icon="system_update_alt",
                      on_click=lambda: _install(library, key, again)) \
                .props("flat dense no-caps size=sm color=primary")
        if theme["installed"] and not theme["active"]:
            ui.button("Make active", icon="check_circle",
                      on_click=lambda: _activate(library, theme, again)) \
                .props("flat dense no-caps size=sm")
        if theme.get("configurable"):
            ui.button("Configure", icon="tune",
                      on_click=lambda: _configure(library, theme)) \
                .props("flat dense no-caps size=sm")
        if theme["installed"] and not theme["active"]:
            # Not on the active one: removing it would leave the frontend with no theme
            # at all, and the way out of that is a config file.
            ui.button("Remove", icon="delete",
                      on_click=lambda: _remove(library, theme, again)) \
                .props("flat dense no-caps size=sm color=negative")


async def _install(library, key: str, again: Callable[[], Any]) -> None:
    ui.notify(f"Downloading {key}...", type="ongoing")
    try:
        await run.io_bound(library.install_theme, key)
    except Exception as exc:  # noqa: BLE001
        ui.notify(f"Could not install it: {exc}", type="negative")
        return
    ui.notify(f"{key} installed", type="positive")
    await again()


async def _activate(library, theme: dict[str, Any], again: Callable[[], Any]) -> None:
    """Asked first, and the question says when it happens.

    The Manager UI restarts VPinFE here. This does not: a setting and a restart are two
    acts, and taking the second without asking is how somebody loses what they were
    doing on another screen.
    """
    if not await confirm.ask(
            f"Make {theme['name']} the active theme?",
            detail="It takes effect the next time the frontend starts. Nothing "
                   "restarts now.",
            confirm="Make active", danger=False):
        return
    try:
        await run.io_bound(library.activate_theme, theme["key"])
    except Exception as exc:  # noqa: BLE001
        ui.notify(f"Could not make it active: {exc}", type="negative")
        return
    ui.notify(f"{theme['name']} plays when the frontend next starts", type="positive")
    await again()


async def _remove(library, theme: dict[str, Any], again: Callable[[], Any]) -> None:
    if not await confirm.ask(
            f"Remove {theme['name']}?",
            detail="Its files are deleted. It can be installed again from here, and "
                   "any settings you gave it go with it.",
            confirm="Remove"):
        return
    try:
        await run.io_bound(library.remove_theme, theme["key"])
    except Exception as exc:  # noqa: BLE001
        ui.notify(f"Could not remove it: {exc}", type="negative")
        return
    ui.notify(f"{theme['name']} removed", type="positive")
    await again()


async def _configure(library, theme: dict[str, Any]) -> None:
    """The theme's own options, drawn from what it declares.

    Its schema rather than ours: a theme can offer a control this install has never
    heard of, and the fallback for one is a text field rather than a refusal.
    """
    try:
        found = await run.io_bound(library.theme_options, theme["key"])
    except Exception as exc:  # noqa: BLE001
        ui.notify(f"Could not read its settings: {exc}", type="negative")
        return

    options = list(found.get("options") or [])
    values = dict(found.get("values") or {})
    if not options:
        ui.notify(f"{theme['name']} declares no settings.", type="warning")
        return

    controls: dict[str, Any] = {}
    with ui.dialog() as dialog, ui.card().classes("console-confirm console-theme-config"):
        ui.label(found.get("title") or f"{theme['name']} settings") \
            .classes("console-confirm-title")
        ui.label(found.get("description")
                 or "These belong to the theme and are saved into its own file.") \
            .classes("console-help")
        with ui.column().classes("w-full gap-3 console-theme-options"):
            for option in options:
                controls[option["key"]] = _option_control(option, values)
        with ui.row().classes("justify-end gap-2 w-full"):
            ui.button("Cancel", on_click=lambda: dialog.submit(False)) \
                .props("flat no-caps")
            ui.button("Save", on_click=lambda: dialog.submit(True)).props("no-caps")

    if not await dialog:
        return
    wanted = {key: _read_control(control) for key, control in controls.items()}
    try:
        await run.io_bound(library.save_theme_options, theme["key"], wanted)
    except Exception as exc:  # noqa: BLE001
        ui.notify(f"Could not save those settings: {exc}", type="negative")
        return
    ui.notify("Saved", type="positive")


def _option_control(option: dict[str, Any], values: dict[str, Any]) -> Any:
    """One control, from the type the theme declares.

    An unknown type gets a text field rather than nothing: a theme that declares
    something new should be editable by an install that has not heard of it, badly
    rather than not at all.
    """
    # The names the theme service normalizes to, not the ones they look like: it emits
    # "boolean", and a renderer checking for "bool" draws a switch as a text field.
    kind = str(option.get("type") or "text")
    current = values.get(option["key"], option.get("default"))
    with ui.column().classes("w-full gap-0"):
        ui.label(str(option.get("name") or option["key"])).classes("console-setting")
        if option.get("description"):
            ui.label(option["description"]).classes("console-help")
        if kind == "boolean":
            control = ui.switch(value=bool(current)).props("dense")
        elif kind == "number":
            control = ui.number(value=current, min=option.get("min"),
                                max=option.get("max"), step=option.get("step")) \
                .props("dense outlined").classes("w-full")
        elif kind == "select":
            control = ui.select(_choices(option), value=current) \
                .props("dense outlined").classes("w-full")
        elif kind in ("textarea", "json"):
            control = ui.textarea(value=_as_text(current)) \
                .props("dense outlined").classes("w-full")
        else:
            control = ui.input(value=_as_text(current)) \
                .props("dense outlined").classes("w-full")
        ui.label(_expected(option, kind)).classes("console-help")
    control.kind = kind
    return control


def _choices(option: dict[str, Any]) -> Any:
    found = option.get("options") or []
    if found and isinstance(found[0], dict):
        return {one.get("value"): str(one.get("label") or one.get("value"))
                for one in found}
    return [one for one in found]


def _as_text(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, indent=2)
    return "" if value is None else str(value)


def _read_control(control: Any) -> Any:
    """What the control holds, in the shape the theme asked for.

    A json field is parsed here so a mistake is reported while the dialog is open,
    rather than saved as a string that its code cannot read.
    """
    value = control.value
    if getattr(control, "kind", "") == "json":
        text = str(value or "").strip()
        if not text:
            return None
        return json.loads(text)
    return value


def _expected(option: dict[str, Any], kind: str) -> str:
    """What a valid answer looks like. The Manager UI says this under every option and
    it is the difference between a field and a guess."""
    if kind == "boolean":
        return "Expected: on or off."
    if kind == "number":
        low, high = option.get("min"), option.get("max")
        if low is not None and high is not None:
            return f"Expected: a number between {low} and {high}."
        return "Expected: a number."
    if kind == "select":
        return f"Expected: one of {len(option.get('options') or [])} choices."
    if kind == "textarea":
        return "Expected: text, over as many lines as you like."
    if kind == "json":
        return "Expected: JSON - an object, an array, or a single value."
    return "Expected: text."
