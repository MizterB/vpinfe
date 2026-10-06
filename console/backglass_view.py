"""A backglass file's panel picture as the cabinet draws it: shaped like the window, with
the grill cut as the renderer in effect cuts it and the DMD where the settings put it.

`screens` reads the settings and answers what to draw, with nothing drawn; `preview`
draws it. The browser is handed one uncut picture and the grill height, so a switch
redraws at once and the server cuts nothing.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, MutableSequence
from dataclasses import dataclass
from typing import Any

from nicegui import ui

from common.games import backglass_ops
from common.i18n import t
from console import art, mediaview

BACKGLASS_WINDOW = "Backglass.Backglass"
SCORE_VIEW_WINDOW = "ScoreView.ScoreView"
# The tallest a picture is drawn, in pixels; boxes beside each other share it.
HEIGHT = 180
LOOKS = ("off", "on", "every")
EDITIONS = ("authentic", "fantasy")


@dataclass(frozen=True)
class Box:
    """The DMD, in percent of the art it sits on. `auto` is a position VPX works out at
    launch, which has no box to draw."""

    left: float = 0.0
    top: float = 0.0
    width: float = 0.0
    height: float = 0.0
    auto: bool = False


@dataclass(frozen=True)
class Screen:
    """One window: its shape, the quarter turns its content is rotated clockwise, how tall
    the picture is stretched past the box to push the grill out of it, and its DMD."""

    ratio: float
    turns: int
    scale: float
    dmd: Box | None
    off: bool = False


def flat(values: Mapping[str, Any]) -> dict[str, str]:
    """The value of each setting, from the shape the launcher config answers in."""
    return {key: str((held or {}).get("value") or "") if isinstance(held, Mapping)
            else str(held or "") for key, held in values.items()}


def edition_in_effect(held: Mapping[str, str]) -> str:
    """The half of a two-version file the renderer shows: Dual Mode's value, which only
    B2S Legacy has."""
    if backglass_ops.renderer(held) == backglass_ops.LEGACY \
            and _number(held, backglass_ops.LEGACY + "B2SDualMode") == 2:
        return "fantasy"
    return "authentic"


def screens(held: Mapping[str, str], glass: Mapping[str, Any]) -> tuple[Screen, Screen | None]:
    """The backglass window, and beside it the score view where the file has art for it
    and its window is on."""
    plugin = backglass_ops.renderer(held)
    wide, high = glass["size"]
    cut = backglass_ops.cuts_grill(held) and 0 < glass["grill"] < high
    kept = high - glass["grill"] if cut else high
    scale = 100.0 * high / kept if cut else 100.0
    window, turns = _window(held, BACKGLASS_WINDOW)
    glass_screen = Screen(
        _ratio(window, (wide, kept), turns), turns, scale,
        _box(held, plugin, "Backglass", (wide, kept)),
        off=held.get(BACKGLASS_WINDOW + "Output", "0") in ("", "0"))
    art_size = glass.get("score_view_art")
    if not art_size or held.get(SCORE_VIEW_WINDOW + "Output", "0") in ("", "0"):
        return glass_screen, None
    window, turns = _window(held, SCORE_VIEW_WINDOW)
    return glass_screen, Screen(_ratio(window, tuple(art_size), turns), turns, 100.0,
                                _box(held, plugin, "ScoreView", tuple(art_size)))


def _number(held: Mapping[str, str], key: str) -> int:
    try:
        return int(float(held.get(key) or 0))
    except ValueError:
        return 0


def _window(held: Mapping[str, str], prefix: str) -> tuple[tuple[int, int] | None, int]:
    """A window's own shape - only a floating one has one - and its quarter turns."""
    turns = _number(held, prefix + "Rotation") % 4
    if held.get(prefix + "Output") != "1":
        return None, turns
    fills = held.get(prefix + "FullScreen", "").lower() in ("1", "true")
    wide, high = ((_number(held, prefix + "FSWidth"), _number(held, prefix + "FSHeight"))
                  if fills else (_number(held, prefix + "Width"),
                                 _number(held, prefix + "Height")))
    return ((wide, high) if wide > 0 and high > 0 else None), turns


def _ratio(window: tuple[int, int] | None, art_size: tuple[int, int], turns: int) -> float:
    wide, high = window or (art_size if turns % 2 == 0 else art_size[::-1])
    return wide / high


def _box(held: Mapping[str, str], plugin: str, part: str, space: tuple[int, int]) -> Box | None:
    prefix = plugin + part + "DMD"

    def on(name: str) -> bool:
        return held.get(prefix + name, "").lower() in ("1", "true")

    if not on("Overlay"):
        return None
    if on("AutoPos"):
        return Box(auto=True)
    x, y, wide, high = (_number(held, prefix + name) for name in "XYWH")
    if wide <= 0 or high <= 0:
        return None
    across, down = space
    return Box(100.0 * x / across, 100.0 * y / down, 100.0 * wide / across,
               100.0 * high / down)


def preview(game_id: str, path: str, glass: dict[str, Any], label: str,
            held: Mapping[str, str], followers: MutableSequence[Callable[[Any], None]],
            enlarge: Callable[[Callable[[], Any]], None]) -> None:
    """The picture, drawn from `held` and drawn again whenever a write calls the function
    added to `followers` with the settings as they now stand."""
    state: dict[str, Any] = {"look": "on", "edition": edition_in_effect(held),
                             "held": dict(held)}
    with ui.element("div").classes("console-slot-art"):
        holder = ui.element("div").classes("console-bgview")

    def draw() -> None:
        holder.clear()
        now = state["held"]
        glass_screen, score_screen = screens(now, glass)
        cut = glass_screen.scale != 100.0
        src = art.backglass(game_id, path, version=glass["version"], size=art.PANEL,
                            grill=False, look=state["look"], edition=state["edition"])
        with holder:
            with ui.row().classes("console-bgview-row items-center gap-2 w-full"):
                _stage(glass_screen, src)
                if score_screen is not None:
                    score = art.score_view(game_id, path, version=glass["version"],
                                           size=art.PANEL)
                    _stage(score_screen, score, t("console.backglass.score_view"))
            with ui.row().classes("console-bgview-bar items-center gap-2 w-full"):
                if not glass["still"] and glass["lamps"]:
                    ui.toggle({one: t(f"console.backglass.look.{one}") for one in LOOKS},
                              value=state["look"], on_change=_pick(state, "look", draw)) \
                        .props("dense no-caps size=sm")
                if glass["two_versions"]:
                    ui.toggle({one: t(f"console.backglass.edition.{one}") for one in EDITIONS},
                              value=state["edition"], on_change=_pick(state, "edition", draw)) \
                        .props("dense no-caps size=sm")
                if glass_screen.off:
                    ui.label(t("console.backglass.window_off")) \
                        .classes("console-tier console-tier--unknown") \
                        .tooltip(t("console.backglass.window_off.hint"))
            enlarge(lambda: mediaview.open_image(
                art.backglass(game_id, path, version=glass["version"], grill=cut,
                              look=state["look"], edition=state["edition"]), label))

    def follow(values: Any) -> None:
        if holder.is_deleted:
            followers.remove(follow)
            return
        before = edition_in_effect(state["held"])
        state["held"] = flat(values)
        if (now := edition_in_effect(state["held"])) != before:
            state["edition"] = now
        draw()

    followers.append(follow)
    draw()


def _pick(state: dict[str, Any], key: str, draw: Callable[[], None]) -> Callable[[Any], None]:
    def chose(event: Any) -> None:
        if event.value and event.value != state[key]:
            state[key] = event.value
            draw()
    return chose


def _stage(screen: Screen, src: str, caption: str = "") -> None:
    """One window. The content is stretched to fill the window's box, then turned: a
    quarter turn swaps the box it is stretched into."""
    sideways = screen.turns % 2 == 1
    across, down = ("100cqh", "100cqw") if sideways else ("100%", "100%")
    with ui.column().classes("console-bgview-fig gap-0").style(
            f"flex:0 1 {HEIGHT * screen.ratio:.0f}px"):
        with ui.element("div").classes("console-bgview-box") \
                .style(f"aspect-ratio:{screen.ratio:.5f}"):
            with ui.element("div").classes("console-bgview-stage").style(
                    f"width:{across};height:{down};"
                    f"transform:translate(-50%,-50%) rotate({90 * screen.turns}deg);"
                    f"background-image:url(\"{src}\");"
                    f"background-size:100% {screen.scale:.4f}%"):
                if screen.dmd is not None:
                    _dmd(screen.dmd)
        if caption:
            ui.label(caption).classes("console-help")


def _dmd(box: Box) -> None:
    if box.auto:
        ui.label(t("console.backglass.dmd_automatic")).classes("console-bgview-auto")
        return
    with ui.element("div").classes("console-bgview-dmd").style(
            f"left:{box.left:.3f}%;top:{box.top:.3f}%;width:{box.width:.3f}%;"
            f"height:{box.height:.3f}%"):
        ui.label(t("console.backglass.dmd_sample.player"))
        ui.label(t("console.backglass.dmd_sample.score"))
