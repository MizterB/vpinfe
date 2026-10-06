"""The flags the browser opens a window with, on the Browser settings page.

Three settings decide them - the options to add, the built-in ones to drop and the switch
that turns the built-in ones off - and none of them says what the browser is then run
with. This is that reading, kept true as each of the three is saved.
"""
from __future__ import annotations

import json
import logging
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
DROP = "options_exclude"
OFF = "disable_defaults"
KEYS = (ADD, DROP, OFF)


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

    return [*client.browser_options(include_default_options=not is_truthy(held.get(OFF)),
                                    exclude_options=parsed(DROP)),
            *parsed(ADD)]


class Preview:
    """The effective flags as one block, redrawn after each save of a setting behind them."""

    def __init__(self, values: Mapping[str, Any]) -> None:
        self.held: dict[str, Any] = dict(values.get(SECTION) or {})
        self.box: Any = None

    def after(self, key: str, save: Callable[[Any], Any]) -> Callable[[Any], Any]:
        async def saved(value: Any) -> bool:
            done = bool(await save(value))
            if done:
                self.held[key] = value
                self.draw_inside()
            return done

        return saved

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
