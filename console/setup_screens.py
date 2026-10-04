"""Setup's Screens step: which screen is which, and the DMD panel if there is one.

The picture and the panel rows are the ones Settings > Hardware > Displays draws, and each
change is written as it is made. The answer is VPinFE's own; Visual Pinball's half of it is
`fill`, which waits for the Visual Pinball step where no launcher exists yet.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

from nicegui import run, ui

from common.failures import why
from common.host import display_service
from common.i18n import t
from console import (
    busy,
    displays,
    dmd_panel,
    offload,
    panel,
    placement_panel,
    screens,
    vpx_displays,
)
from console.api import ApiClient
from console.data import Library
from console.on_page import on_page
from console.setup_vpx import Vpx

logger = logging.getLogger("vpinfe.console.setup_screens")


@dataclass
class Screens:
    """What the Screens step has been told, for the Visual Pinball half of it."""
    answered: bool = False
    # The DMD panel's kind. VPinFE stores it only for PIN2DMD, so the others are kept here.
    kind: str = ""


@dataclass(frozen=True)
class Seen:
    """What the step draws from: VPinFE's settings and this computer's screens."""
    values: dict[str, Any]
    schema: list[dict]
    monitors: list[Any]
    names: list[str]
    reading: placement_panel.Reading | None


async def _gather(library: Library) -> Seen:
    return Seen(
        values=await offload.io(library.config_values),
        schema=await offload.io(library.config_schema),
        monitors=await offload.io(screens.connected),
        names=list(await offload.io(display_service.get_display_names)),
        reading=await run.io_bound(placement_panel.read, os.environ))


@on_page
async def write(changes: dict[str, dict[str, Any]]) -> bool:
    try:
        await run.io_bound(ApiClient().put_config, changes)
    except Exception as exc:  # noqa: BLE001 - the reason belongs on the page
        ui.notify(t("console.settings.save_failed"), caption=why(exc), type="negative")
        return False
    return True


def _entries(state: Screens, library: Library, seen: Seen,
             rebuild: Any) -> list[tuple[Any, Any]]:
    """The picture without its heading, which the step's title already says, then the
    DMD panel, then where the windows go."""
    @on_page
    async def follow(before: Any, after: Any, here: Any) -> None:
        await vpx_displays.follow(library, before, after, here)
        try:
            await offload.io(placement_panel.resync)
        except OSError as exc:
            ui.notify(t("console.placement.update_failed"), caption=why(exc), type="warning")

    async def kept(kind: str) -> None:
        state.kind = kind
        await vpx_displays.follow_dmd(library, kind)

    picture = [one for one in displays.rows(seen.values, seen.schema, seen.monitors, seen.names,
                                            write, rebuild, follow=follow)
               if one[0] is not panel.HEADING]
    return [*picture,
            *dmd_panel.rows(seen.values, seen.schema, write, rebuild, kept, kind=state.kind),
            *placement_panel.rows(seen.reading, seen.values, seen.schema, write, rebuild)]


async def ask(state: Screens) -> dict[str, Any]:
    library = Library(ApiClient())
    try:
        first = await _gather(library)
    except Exception:
        logger.warning("Could not read the screens", exc_info=True)
        return {"title": t("console.setup.screens.title"),
                "notes": [t("said.settings_unreadable")]}

    def draw(_: dict[str, Any]) -> None:
        with ui.element("div").classes("w-full") as page:
            shown = ui.element("div").classes("w-full")

        def render(seen: Seen) -> None:
            shown.clear()
            with shown:
                panel.facts(ui, _entries(state, library, seen, again))

        async def redraw() -> None:
            render(await _gather(library))

        def again() -> None:
            with page:
                busy.fill(shown, redraw)

        render(first)

    return {"title": t("console.setup.screens.title"), "draw": draw}


async def answer(state: Screens, vpx: Vpx) -> None:
    """The step is answered. Visual Pinball's half is written now where there is a launcher,
    and by the Visual Pinball step (`fill`) where there is none yet."""
    state.answered = True
    if vpx.launcher is not None:
        await fill(state, vpx.launcher.launcher_id)


@on_page
async def fill(state: Screens, launcher_id: str) -> None:
    """Visual Pinball's half of the answer, from VPinFE's settings as they stand."""
    if not state.answered:
        return
    library = Library(ApiClient())
    try:
        seen = await _gather(library)
        here = screens.numbered(seen.monitors, seen.names)
        kind = (dmd_panel.kind_of(seen.values, seen.schema) or state.kind) \
            if dmd_panel.is_on(seen.values, seen.schema) else ""
        await vpx_displays.fill(ApiClient(), launcher_id,
                                displays.standing(seen.values, seen.schema), here, kind)
    except Exception as exc:  # noqa: BLE001 - say so, the step itself is answered
        logger.warning("Could not write the screens for Visual Pinball", exc_info=True)
        ui.notify(t("said.save_failed"), caption=why(exc), type="negative")
