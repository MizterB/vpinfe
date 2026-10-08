"""Asking for a new name, for one row or for each of several in a walk."""

from __future__ import annotations

from typing import Any

from nicegui import ui

from common.i18n import t
from console import dialog as frame
from console import panel, verbs, walks


async def ask(current: str, *, title: str, label: str, hint: str = "", place: str = "",
              walking: bool = False) -> str | None:
    """The name wanted, `walks.SKIPPED` for no change, or `walks.STOPPED` to end a walk.

    `place` says where a walk has got to, and is empty outside one. `walking` splits Cancel
    into Skip and Stop, which are different intents in a run.
    """
    held: dict[str, Any] = {}

    def answer() -> str | None:
        said = " ".join(str(held["field"].value or "").split())
        return said if said and said != current else walks.SKIPPED

    with frame.opened(title) as box:
        if place:
            ui.label(place).classes("console-help px-3")
        if hint:
            ui.label(hint).classes("console-help px-3")
        panel.facts(ui, [(label, lambda: held.update(field=frame.field(current)))])
        with frame.footer():
            if walking:
                frame.quiet(t("word.stop"), lambda: box.submit(walks.STOPPED), icon=verbs.STOP)
                frame.quiet(t("word.skip"), lambda: box.submit(walks.SKIPPED), icon=verbs.SKIP)
            else:
                frame.cancel(lambda: box.submit(walks.SKIPPED))
            go = frame.answer(t("word.rename"), lambda: box.submit(answer()),
                              icon=verbs.RENAME)
    frame.focus(box, held["field"], select=True)
    frame.enter_presses(go)
    return await box
