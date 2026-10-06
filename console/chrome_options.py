"""The flags the browser opens a window with, on the Browser settings page.

Three settings decide them - the options to add, the built-in ones to leave out and the
switch that turns the built-in ones on - and none of them says what the browser is then
run with. This is that reading, kept true as each of the three is saved.
"""
from __future__ import annotations

import json
import logging
import shlex
from collections.abc import Callable, Mapping
from typing import Any

from nicegui import ui

from common import device_client
from common.i18n import t
from common.values import is_truthy
from console import about, panel

logger = logging.getLogger("vpinfe.console.chrome_options")

SECTION = "chromium"
ADD = "options"
LEAVE_OUT = "options_exclude"
DEFAULTS = "defaults"
KEYS = (ADD, LEAVE_OUT, DEFAULTS)


def effective(held: Mapping[str, Any]) -> list[str]:
    """What a window is started with, given the three settings as they stand.

    A line that will not parse - an unbalanced quote - adds nothing, which is what the
    frontend does with it when it opens a window.
    """
    client = device_client.local()

    def parsed(key: str) -> list[str]:
        try:
            return client.parse_browser_options(str(held.get(key) or ""))
        except ValueError:
            return []

    return [*client.browser_options(include_default_options=is_truthy(held.get(DEFAULTS),
                                                                      default=True),
                                    exclude_options=parsed(LEAVE_OUT)),
            *parsed(ADD)]


def _entries(raw: Any, names: list[str]) -> list[str]:
    """What is left out, as the picker lists it: a known option by its name, which is how
    VPinFE matches it, and anything else as written."""
    out: list[str] = []
    try:
        listed = shlex.split(str(raw or ""))
    except ValueError:
        listed = str(raw or "").split()
    for entry in listed:
        entry = entry.split("=")[0] if entry.split("=")[0] in names else entry
        if entry not in out:
            out.append(entry)
    return out


def leave_out(option: dict, value: Any, save: Callable[[Any], Any], *,
              section: Mapping[str, Any], writable: bool = True,
              rerender: Callable[[], None] | None = None,
              suggestions: dict[str, Any] | None = None,
              on_control: Callable[[Any], Any] | None = None) -> Callable[[], None]:
    """VPinFE's own options to pick from, typed into to find one.

    A stored entry that is not one of them stays in the list, marked, so it can be seen
    and taken out - dropping it silently would change what a window starts with.
    """
    names = device_client.local().browser_default_option_names()
    held = _entries(value, names)
    options = {name: name for name in names}
    options.update({entry: t("console.settings.chrome_unknown", option=entry)
                    for entry in held if entry not in options})
    on = is_truthy(section.get(DEFAULTS), default=True)

    def changed(event: Any) -> Any:
        return save("\n".join(event.value or []))

    return panel.multi_select(options, held, changed, disabled=not writable or not on,
                              typed=True, placeholder=t("console.settings.chrome_leave_out.none"),
                              on_control=on_control)


class Preview:
    """The effective flags as one block, redrawn after each save of a setting behind them."""

    def __init__(self, values: Mapping[str, Any]) -> None:
        self.held: dict[str, Any] = dict(values.get(SECTION) or {})
        self.box: Any = None
        self.picker: Any = None
        self.writable = True

    def after(self, key: str, save: Callable[[Any], Any]) -> Callable[[Any], Any]:
        async def saved(value: Any) -> bool:
            done = bool(await save(value))
            if done:
                self.held[key] = value
                self.draw_inside()
                if key == DEFAULTS:
                    self.grey()
            return done

        return saved

    def leave_out(self, option: dict, value: Any, save: Callable[[Any], Any], *,
                  section: Mapping[str, Any], writable: bool) -> Callable[[], None]:
        """The picker, kept hold of so the switch above it can grey it out as it is set."""
        self.writable = writable

        def keep(control: Any) -> None:
            self.picker = control

        return leave_out(option, value, save, section=section, writable=writable,
                         on_control=keep)

    def grey(self) -> None:
        if self.picker is None or not self.writable:
            return
        if is_truthy(self.held.get(DEFAULTS), default=True):
            self.picker.enable()
        else:
            self.picker.disable()

    def row(self) -> tuple[str, Callable[[], None]]:
        def draw() -> None:
            self.box = ui.column().classes("gap-1 w-full min-w-0")
            self.draw_inside()

        return t("console.settings.chrome_effective"), draw

    def draw_inside(self) -> None:
        if self.box is None:
            return
        self.box.clear()
        text = "\n".join(effective(self.held))
        with self.box:
            ui.textarea(value=text).props("outlined readonly autogrow") \
                .classes("w-full console-log")
            with ui.row().classes("items-center gap-2 w-full no-wrap"):
                with ui.element("div").classes("shrink-0"):
                    panel.action(t("word.copy"),
                                 lambda event: about.copied(bool(event.args), text),
                                 icon="content_copy",
                                 hint=t("console.settings.chrome_copy.help"),
                                 js=about.COPY_JS % json.dumps(text))()
                ui.label(t("console.settings.chrome_effective.help")) \
                    .classes("console-help grow min-w-0")
