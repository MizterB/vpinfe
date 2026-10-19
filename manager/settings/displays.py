"""Settings > Hardware > Displays: the screens picture, over the windows' config."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from nicegui import run, ui

from common.devices import device_client
from common.failures import why
from common.i18n import t
from manager.kit import panel
from manager.kit.on_page import on_page
from manager.settings import screens
from manager.settings import screens_picture as picture
from manager.settings.screens import Screen

KEY = "hardware.displays"

# What the picture draws, by config section.
DRAWN = {"windows.playfield": frozenset({"screen_id", "orientation", "rotation"}),
         "windows.backglass": frozenset({"screen_id"}),
         "windows.scoreview": frozenset({"screen_id"}),
         "windows.topper": frozenset({"screen_id"})}

Write = Callable[[dict[str, dict[str, Any]]], Awaitable[bool]]


@dataclass(frozen=True)
class Standing:
    """Where the screens are and how the playfield is turned: the answer other places
    (a launcher's own screens) are compared with, and move with."""
    on: Mapping[str, picture.Placement]
    turn: tuple[str, str]


# Told what the screens were and are after a change that was kept.
Follow = Callable[[Standing, Standing, Sequence[Screen]], Awaitable[Any]]


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


def placed(values: Mapping[str, Any], schema: Sequence[dict]) -> dict[str, picture.Placement]:
    return {part.key: number_of(stored(values, schema, f"windows.{part.key}", "screen_id"))
            for part in picture.vpinfe_parts()}


def standing(values: Mapping[str, Any], schema: Sequence[dict]) -> Standing:
    return Standing(placed(values, schema),
                    (str(stored(values, schema, "windows.playfield", "orientation")),
                     str(stored(values, schema, "windows.playfield", "rotation"))))


def cabinet(values: Mapping[str, Any], schema: Sequence[dict]) -> bool:
    return str(stored(values, schema, "presentation", "cab_mode")).strip().lower() in (
        "true", "1", "yes", "on")


def writes(moved: Mapping[str, picture.Placement], screens_here: Sequence[Screen],
           rotation: Any) -> dict[str, dict[str, Any]]:
    """The config for parts whose screen changed.

    A screen put on the playfield may stand in another shape, so its mounting is worked
    out again from the turn the playfield already has.
    """
    found = {f"windows.{part}": {"screen_id": number - 1 if isinstance(number, int) else ""}
             for part, number in moved.items()}
    number = moved.get(picture.PLAYFIELD)
    if isinstance(number, int):
        screen = next((one for one in screens_here if one.number == number), None)
        found["windows.playfield"]["orientation"] = picture.turn(
            picture.arrow_at(rotation) or picture.UP, screen)["orientation"]
    return found


def rows(values: Mapping[str, Any], schema: Sequence[dict], monitors: Sequence[Any],
         names: Sequence[str], write: Write,
         refill: Callable[[], None], follow: Follow | None = None) -> list[tuple[Any, Any]]:
    """The picture as a heading and a row spanning the page. `follow` is told of each
    change that was kept."""
    here = screens.numbered(monitors, names)
    held = placed(values, schema)
    turned = {"orientation": standing(values, schema).turn[0],
              "rotation": stored(values, schema, "windows.playfield", "rotation")}
    arrows = cabinet(values, schema)

    def now() -> Standing:
        return Standing(dict(held), (str(turned["orientation"]), str(turned["rotation"])))

    async def move(moved: dict[str, picture.Placement]) -> bool:
        lost = any(isinstance(number, int) and not any(one.number == number for one in here)
                   for number in held.values())
        before = now()
        found = writes(moved, here, turned["rotation"])
        if not await write(found):
            return False
        held.update(moved)
        turned["orientation"] = found.get("windows.playfield", {}).get(
            "orientation", turned["orientation"])
        if lost:
            refill()
        if follow is not None:
            await follow(before, now(), here)
        return True

    async def point(arrow: str, screen: Screen) -> bool:
        found = picture.turn(arrow, screen)
        before = now()
        if not await write({"windows.playfield": found}):
            return False
        turned.update(found)
        if follow is not None:
            await follow(before, now(), here)
        return True

    @on_page
    async def show(on: Mapping[str, picture.Placement]) -> None:
        playfield = on.get(picture.PLAYFIELD)
        try:
            await run.io_bound(device_client.local().show_numbers, here,
                               playfield if arrows and isinstance(playfield, int) else None)
        except Exception as exc:  # noqa: BLE001 - the reason belongs on the page
            ui.notify(t("manager.screens.show_failed"), caption=why(exc), type="negative")

    def draw() -> None:
        picture.Picture(here, held, move=move, arrows=arrows, show=show,
                        arrow=picture.arrow_at(turned["rotation"]),
                        point=point if arrows else None)

    return [(panel.HEADING, t("manager.settings.section_screens")), (panel.FULL, draw)]
