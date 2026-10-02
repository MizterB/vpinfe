"""Settings > Hardware > Displays: the screens picture, over the windows' config."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

from nicegui import run, ui

from common import device_client
from common.failures import why
from common.i18n import t
from console import panel, screens
from console import screens_picture as picture
from console.on_page import on_page
from console.screens import Screen

KEY = "hardware.displays"

# What the picture draws, by config section.
DRAWN = {"windows.playfield": frozenset({"screen_id", "orientation", "rotation"}),
         "windows.backglass": frozenset({"screen_id"}),
         "windows.score_view": frozenset({"screen_id"})}

Write = Callable[[dict[str, dict[str, Any]]], Awaitable[bool]]


def without_drawn(blocks: Sequence[dict]) -> list[dict]:
    """The schema's sections with the settings the picture draws taken out, and any
    section left with nothing in it dropped."""
    kept = [{**block, "options": [one for one in block.get("options") or []
                                  if one.get("key") not in DRAWN.get(str(block.get("name")), ())]}
            for block in blocks]
    return [block for block in kept if block["options"]]


def stored(values: Mapping[str, Any], schema: Sequence[dict], section: str, key: str) -> Any:
    """A setting as the page reads it: what is stored, else what the schema defaults to."""
    held = values.get(section) or {}
    if key in held:
        return held[key]
    return next((one.get("default") for block in schema if block.get("name") == section
                 for one in block.get("options") or [] if one.get("key") == key), None)


def number_of(screen_id: Any) -> int | None:
    """The number a person counts a stored screen id as, or None for a window with no
    screen."""
    said = str(screen_id if screen_id is not None else "").strip()
    return int(said) + 1 if said.isdigit() else None


def placed(values: Mapping[str, Any], schema: Sequence[dict]) -> dict[str, int | None]:
    return {part.key: number_of(stored(values, schema, f"windows.{part.key}", "screen_id"))
            for part in picture.vpinfe_parts()}


def cabinet(values: Mapping[str, Any], schema: Sequence[dict]) -> bool:
    return str(stored(values, schema, "presentation", "cab_mode")).strip().lower() in (
        "true", "1", "yes", "on")


def writes(moved: Mapping[str, int | None], screens_here: Sequence[Screen],
           rotation: Any) -> dict[str, dict[str, Any]]:
    """The config for parts whose screen changed.

    A screen put on the playfield may stand in another shape, so its mounting is worked
    out again from the turn the playfield already has.
    """
    found = {f"windows.{part}": {"screen_id": "" if number is None else number - 1}
             for part, number in moved.items()}
    number = moved.get(picture.PLAYFIELD)
    if number is not None:
        screen = next((one for one in screens_here if one.number == number), None)
        found["windows.playfield"]["orientation"] = picture.turn(
            picture.arrow_at(rotation) or picture.UP, screen)["orientation"]
    return found


def rows(values: Mapping[str, Any], schema: Sequence[dict], monitors: Sequence[Any],
         names: Sequence[str], write: Write,
         rerender: Callable[[], None]) -> list[tuple[Any, Any]]:
    """The picture as a heading and a row spanning the page."""
    here = screens.numbered(monitors, names)
    held = placed(values, schema)
    turned = {"rotation": stored(values, schema, "windows.playfield", "rotation")}
    arrows = cabinet(values, schema)

    async def move(moved: dict[str, int | None]) -> bool:
        lost = any(number is not None and not any(one.number == number for one in here)
                   for number in held.values())
        if not await write(writes(moved, here, turned["rotation"])):
            return False
        held.update(moved)
        if lost:
            rerender()
        return True

    async def point(arrow: str, screen: Screen) -> bool:
        found = picture.turn(arrow, screen)
        if not await write({"windows.playfield": found}):
            return False
        turned["rotation"] = found["rotation"]
        return True

    @on_page
    async def show(on: Mapping[str, int | None]) -> None:
        try:
            await run.io_bound(device_client.local().show_numbers, here,
                               on.get(picture.PLAYFIELD) if arrows else None)
        except Exception as exc:  # noqa: BLE001 - the reason belongs on the page
            ui.notify(t("console.screens.could_not_show"), caption=why(exc), type="negative")

    def draw() -> None:
        picture.Picture(here, held, move=move, arrows=arrows, show=show,
                        arrow=picture.arrow_at(turned["rotation"]),
                        point=point if arrows else None)

    return [(panel.HEADING, t("console.settings.section_screens")), (panel.FULL, draw)]
