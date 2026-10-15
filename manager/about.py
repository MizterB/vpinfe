
"""What this install and this machine are.

The facts a person is asked for when they report something: version, build, OS, browser,
and where this install keeps its files. Metrics answers what the machine is *doing*;
this answers what it *is*, and the two are on separate pages because one changes every
two seconds and the other does not change at all.

**The page exists for its copy button.** Reading fourteen fields off a screen and typing
them into an issue is where a report goes wrong, so the whole set travels as one block
of text, assembled by the install rather than by whoever is looking at it.

The copy happens in the browser at the moment of the click. A browser only allows one
while it still believes a person just asked, and this Manager is server-rendered - a
click that goes to the server and comes back has spent that permission on the way.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from nicegui import ui

from common.failures import why
from common.i18n import t
from manager import busy, clipboard, offload, panel, verbs
from manager import whats_new as whats_new_page
from manager.data import Library

logger = logging.getLogger("vpinfe.manager.about")


def build(library: Library, state: dict[str, Any], redraw: Callable[[], None]) -> None:
    """Read once when the page opens. None of it changes while VPinFE runs."""
    held: dict[str, Any] = {"text": ""}

    with ui.column().classes("w-full gap-3") as body:
        pass

    async def load(refresh: bool = False) -> None:
        try:
            found = await offload.io(library.about, refresh)
        except Exception as exc:  # noqa: BLE001 - this page says why, never 500s
            body.clear()
            with body:
                panel.facts(ui, [panel.intro(t("manager.about.read_failed"),
                                             hint=why(exc))])
            return
        held["text"] = str(found.get("text") or "")
        _draw(body, found.get("groups") or [], held, load)

    busy.fill(body, load)


def _draw(body: Any, groups: list[dict[str, Any]], held: dict[str, Any],
          reload: Callable[..., Any]) -> None:
    body.clear()
    with body:
        with ui.row().classes("items-center gap-2 w-full no-wrap"):
            ui.label(t("manager.about.copy_note")) \
                .classes("manager-help grow min-w-0")
            panel.action(t("word.copy"), lambda event: clipboard.copied(bool(event.args),
                    held["text"]),
                         icon="content_copy",
                         hint=t("manager.about.copy_hint"),
                         js=clipboard.COPY_JS % json.dumps(held["text"]))()
            panel.action(t("manager.about.whats_new"),
                         lambda: whats_new_page.open_whats_new(again=True),
                         icon=verbs.REVIEW, hint=t("manager.about.whats_new_hint"))()
            panel.action(t("manager.about.refresh"), lambda: reload(True), icon=verbs.REFRESH,
                         hint=t("word.reread"))()
        # One list for all of them, headings inside it, the way Settings next door
        # draws its sections: a list per group sizes a label column per group, and the
        # values then start at four different places down one page.
        entries: list[tuple[Any, Any]] = []
        for group in groups:
            entries.append((panel.HEADING, str(group.get("heading") or "")))
            entries += [(str(fact.get("label") or ""),
                         panel.path_value(str(fact["value"])) if fact.get("path")
                         and fact.get("value") else str(fact.get("value") or ""))
                        for fact in group.get("facts") or []]
        panel.facts(ui, entries)
