"""A backglass file's panel picture as the cabinet draws it: shaped like the window, with
the grill cut as the renderer in effect cuts it and the DMD where the settings put it.

`screens` reads the settings and answers what to draw, with nothing drawn; `preview`
draws it. The browser is handed one uncut picture and the grill height, so a switch
redraws at once and the server cuts nothing.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Awaitable, Callable, Mapping, MutableMapping, MutableSequence
from dataclasses import dataclass
from typing import Any

from nicegui import run, ui
from PIL import Image

from common.games import backglass_ops, dmd_frame
from common.i18n import t
from console import art, mediaview, panel
from console.on_page import on_page

logger = logging.getLogger(__name__)

GLASS_PART = "Backglass"
SCORE_PART = "ScoreView"
BACKGLASS_WINDOW = "Backglass.Backglass"
SCORE_VIEW_WINDOW = "ScoreView.ScoreView"
BAR_PX = 46
CAPTION_PX = 28
GAP_PX = 8
LEGACY_DMD_SPACE = (1024, 768)
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
    part: str = GLASS_PART
    space: tuple[int, int] = (1, 1)


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
        _box(held, plugin, GLASS_PART, (wide, kept)),
        off=held.get(BACKGLASS_WINDOW + "Output", "0") in ("", "0"),
        space=(wide, kept))
    art_size = glass.get("score_view_art")
    if not art_size or held.get(SCORE_VIEW_WINDOW + "Output", "0") in ("", "0"):
        return glass_screen, None
    window, turns = _window(held, SCORE_VIEW_WINDOW)
    return glass_screen, Screen(_ratio(window, tuple(art_size), turns), turns, 100.0,
                                _box(held, plugin, SCORE_PART, tuple(art_size)),
                                part=SCORE_PART, space=tuple(art_size))


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
    """Y counts up from the window's bottom edge. B2S counts in the pixels of `space`;
    Legacy counts in 1024x768 whatever the picture's size."""
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
    across, down = _counted_in(plugin, space)
    return Box(100.0 * x / across, 100.0 * (down - y - high) / down, 100.0 * wide / across,
               100.0 * high / down)


def _counted_in(plugin: str, space: tuple[int, int]) -> tuple[int, int]:
    return LEGACY_DMD_SPACE if plugin == backglass_ops.LEGACY else space


def box_values(plugin: str, screen: Screen, box: Box) -> dict[str, str]:
    """The settings that put the DMD where `box` is, with Automatic off: `_box` the other
    way, in the renderer's own units."""
    across, down = _counted_in(plugin, screen.space)
    prefix = plugin + screen.part + "DMD"
    wide, high = max(1, round(across * box.width / 100)), max(1, round(down * box.height / 100))
    return {prefix + "AutoPos": "0",
            prefix + "X": str(max(0, round(across * box.left / 100))),
            prefix + "Y": str(max(0, round(down * (1 - (box.top + box.height) / 100)))),
            prefix + "W": str(wide), prefix + "H": str(high)}


def frame_box(frame: dmd_frame.Frame, size: tuple[int, int]) -> Box:
    """A frame found on a picture of `size`, counted up from the bottom as Visual Pinball
    counts it, as the box that covers it."""
    wide, high = size
    return Box(100.0 * frame.x / wide, 100.0 * (high - frame.y - frame.height) / high,
               100.0 * frame.width / wide, 100.0 * frame.height / high)


def found(game_id: str, path: str, *, look: str, edition: str, cut: bool,
          score_view: bool) -> Box | None:
    """Where Automatic would put the DMD on the picture the preview shows, or None where
    the art has no window for it."""
    served = (backglass_ops.score_view_file(game_id, path=path) if score_view
              else backglass_ops.picture_file(game_id, look=look, version=edition, grill=cut,
                                              path=path))
    with Image.open(served.path) as picture:
        frame = dmd_frame.find(picture)
        size = picture.size
    return frame_box(frame, size) if frame else None


def fit_target(held: Mapping[str, str], glass: Mapping[str, Any],
               part: str) -> tuple[Screen, bool] | None:
    """The window `part` names, and whether its picture is drawn with the grill cut. The
    score view's own window may be off while its settings are open, so it is built from
    the art; None where the file has no art for it."""
    glass_screen, score_screen = screens(held, glass)
    if part == GLASS_PART:
        return glass_screen, glass_screen.scale != 100.0
    if score_screen is not None:
        return score_screen, False
    art_size = glass.get("score_view_art")
    if not art_size:
        return None
    return Screen(1.0, 0, 100.0, None, part=SCORE_PART, space=tuple(art_size)), False


def preview(game_id: str, path: str, glass: dict[str, Any], label: str,
            held: Mapping[str, str], followers: MutableSequence[Callable[[Any], None]],
            enlarge: Callable[[Callable[[], Any]], None],
            write: Callable[..., Awaitable[Any]] | None,
            memory: dict[str, Any],
            fits: MutableMapping[str, Callable[[], Awaitable[None]]]) -> None:
    """The picture, drawn from `held` and drawn again whenever a write calls the function
    added to `followers` with the settings as they now stand. A box moved or fitted is
    written by `write`, which draws the settings beside it again and calls the followers;
    a box that was dragged is already where the write puts it, so it is not drawn again.
    `memory` carries the Look and Version picked across a redraw of the whole panel.
    `fits` is given, under "Backglass" and "ScoreView", what puts a window's box on the
    DMD window in the picture; the settings beside it hold the button. Without `write`
    the box cannot be moved or fitted and `fits` stays empty."""
    state = memory.setdefault("preview", {"look": "on", "edition": edition_in_effect(held)})
    state["held"] = dict(held)
    holder = ui.element("div").classes("console-bgview")
    notes = ui.column().classes("console-bgview-notes gap-1")

    def moved(screen: Screen) -> Callable[[Box], Awaitable[None]] | None:
        if write is None:
            return None

        async def set_box(box: Box) -> None:
            state["dragged"] = True
            try:
                await write(box_values(backglass_ops.renderer(state["held"]), screen, box),
                            in_place=True)
            finally:
                state.pop("dragged", None)
        return set_box

    searching: set[str] = set()

    def fitter(part: str, put: Callable[..., Awaitable[Any]]) -> Callable[[], Awaitable[None]]:
        @on_page
        async def fit() -> None:
            if part in searching:
                return
            target = fit_target(state["held"], glass, part)
            if target is None:
                ui.notify(t("console.backglass.dmd_fit.none"), type="warning")
                return
            screen, cut = target
            searching.add(part)
            try:
                working = ui.notification(t("console.backglass.dmd_fit.working"), spinner=True,
                                          timeout=None)
                try:
                    box = await run.io_bound(
                        lambda: found(game_id, path, look=state["look"],
                                      edition=state["edition"], cut=cut,
                                      score_view=part == SCORE_PART))
                except Exception:  # noqa: BLE001 - a file that cannot be drawn says so
                    logger.exception("Could not search the backglass picture for the DMD")
                    ui.notify(t("console.backglass.damaged"), type="negative")
                    return
                finally:
                    with contextlib.suppress(TimeoutError):
                        await ui.run_javascript(f"getElement({working.id}).dismiss()")
                if box is None:
                    ui.notify(t("console.backglass.dmd_fit.none"), type="warning")
                    return
                await put(box_values(backglass_ops.renderer(state["held"]), screen, box),
                          in_place=True)
            finally:
                searching.discard(part)
        return fit

    if write is not None:
        fits.update({part: fitter(part, write) for part in (GLASS_PART, SCORE_PART)})

    def draw() -> None:
        holder.clear()
        now = state["held"]
        glass_screen, score_screen = screens(now, glass)
        src = art.backglass(game_id, path, version=glass["version"], size=art.PANEL,
                            grill=False, look=state["look"], edition=state["edition"])
        with holder:
            plugin = backglass_ops.renderer(now)
            shown = [one for one in (glass_screen, score_screen) if one is not None]
            both = len(shown) == 2
            if both:
                ui.html(_beside(shown[0].ratio, shown[1].ratio), sanitize=False, tag="style")
            with ui.row().classes(
                    "console-bgview-row items-center w-full"
                    + (" console-bgview-row--pair" if both else "")).style(
                    f"gap:{GAP_PX}px;--gap:{GAP_PX}px;"
                    f"--sum:{sum(one.ratio for one in shown):.5f};--gaps:{int(both)};"
                    f"--chrome:{BAR_PX + CAPTION_PX}px;"
                    f"--tall:{sum(1 / one.ratio for one in shown):.5f};"
                    f"--stack:{CAPTION_PX * len(shown) + GAP_PX * (len(shown) - 1)}px;"
                    f"--cap:{CAPTION_PX}px"):
                _stage(glass_screen, src, moved(glass_screen), t("console.backglass.glass"),
                       _counted_in(plugin, glass_screen.space))
                if score_screen is not None:
                    score = art.score_view(game_id, path, version=glass["version"],
                                           size=art.PANEL)
                    _stage(score_screen, score, moved(score_screen),
                           t("console.backglass.score_view"),
                           _counted_in(plugin, score_screen.space))
            with ui.row().classes("console-bgview-bar items-center gap-2 w-full"):
                if not glass["still"] and glass["lamps"]:
                    ui.label(t("console.backglass.lamps")).classes("console-bgview-name")
                    panel.segmented({one: t(f"console.backglass.look.{one}") for one in LOOKS},
                                    state["look"], _pick(state, "look", draw))
                if glass["two_versions"]:
                    ui.label(t("console.backglass.version")).classes("console-bgview-name")
                    panel.segmented({one: t(f"console.backglass.edition.{one}")
                                     for one in EDITIONS},
                                    state["edition"], _pick(state, "edition", draw))
                if glass_screen.off:
                    ui.label(t("console.backglass.window_off")) \
                        .classes("console-tier console-tier--unknown") \
                        .tooltip(t("console.backglass.window_off.hint"))
            cut = glass_screen.scale != 100.0
            enlarge(lambda: mediaview.open_image(
                art.backglass(game_id, path, version=glass["version"], grill=cut,
                              look=state["look"], edition=state["edition"]), label))
        _say(notes, glass, [glass_screen, score_screen], write is not None)

    def follow(values: Any) -> None:
        if holder.is_deleted:
            followers.remove(follow)
            return
        before = edition_in_effect(state["held"])
        state["held"] = flat(values)
        if (now := edition_in_effect(state["held"])) != before:
            state["edition"] = now
        if not state.get("dragged"):
            draw()

    followers.append(follow)
    draw()


def _pick(state: dict[str, Any], key: str, draw: Callable[[], None]) -> Callable[[Any], None]:
    def chose(event: Any) -> None:
        if event.value and event.value != state[key]:
            state[key] = event.value
            draw()
    return chose


def _say(notes: ui.element, glass: Mapping[str, Any], shown: list[Screen | None],
         live: bool) -> None:
    """The lines under the picture: what the two controls do not do, and what the DMD box
    can be made to do."""
    notes.clear()
    boxes = [one.dmd for one in shown if one is not None and one.dmd is not None]
    controls = " ".join(name for name, drawn in (
        ("lamps", not glass["still"] and glass["lamps"]),
        ("version", glass["two_versions"])) if drawn)
    with notes:
        if kind := {"lamps": "looking_lamps", "version": "version",
                    "lamps version": "looking"}.get(controls):
            ui.label(t(f"console.backglass.preview.{kind}")).classes("console-help")
        if live and any(not one.auto for one in boxes):
            ui.label(t("console.backglass.preview.dmd")).classes("console-help")
            ui.label(t("console.backglass.preview.fit")).classes("console-help")
        if live and any(one.auto for one in boxes):
            ui.label(t("console.backglass.preview.automatic")).classes("console-help")


def _beside(first: float, second: float) -> str:
    """The rule that sets two windows side by side, once the stage is wider than the two
    shapes would make a stack: the point where both layouts draw them the same size. A
    container query takes no variable, so the threshold is written into the rule."""
    return (f"@container (min-aspect-ratio: {(first * second) ** 0.5:.4f}) {{"
            ".console-bgview-row--pair { flex-direction: row; }"
            ".console-bgview-row--pair .console-bgview-box "
            "{ width: auto; height: max(var(--fit), 40px); } }")


def _stage(screen: Screen, src: str, on_set: Callable[[Box], Awaitable[None]] | None,
           caption: str, units: tuple[int, int]) -> None:
    """One window. The content is stretched to fill the window's box, then turned: a
    quarter turn swaps the box it is stretched into. `units` is what the DMD fields count
    in across and down."""
    sideways = screen.turns % 2 == 1
    across, down = ("100cqh", "100cqw") if sideways else ("100%", "100%")
    with ui.column().classes("console-bgview-fig gap-0"):
        with ui.row().classes("console-bgview-cap items-center gap-2 no-wrap"):
            ui.label(caption).classes("console-bgview-heading")
        with ui.element("div").classes("console-bgview-box") \
                .style(f"aspect-ratio:{screen.ratio:.5f}"):
            with ui.element("div").classes("console-bgview-stage").style(
                    f"width:{across};height:{down};"
                    f"transform:translate(-50%,-50%) rotate({90 * screen.turns}deg);"
                    f"background-image:url(\"{src}\");"
                    f"background-size:100% {screen.scale:.4f}%"):
                if screen.dmd is not None:
                    _dmd(screen.dmd, screen.turns, on_set, units)


GRIPS = ("nw", "ne", "sw", "se")

# The box is moved by its body and sized by its corners, in percent of the stage it sits
# in. A pointer's travel is turned back through the stage's quarter turns first, so a
# drag follows the pointer on a window that is turned. Nothing is sent until it is let go.
# While it moves, a readout beside it counts X, Y, W and H the way the settings do.
BOX_JS = """(() => {
  let tries = 0;
  const wire = () => {
    const el = document.getElementById('c__ID__');
    if (!el) { if (tries++ < 40) setTimeout(wire, 50); return; }
    const stage = el.parentElement;
    const turns = __TURNS__;
    const cos = Math.round(Math.cos(Math.PI / 2 * turns));
    const sin = Math.round(Math.sin(Math.PI / 2 * turns));
    const MIN = 2;
    const clamp = (v, lo, hi) => Math.min(Math.max(lo, hi), Math.max(lo, v));
    const SLOP = 3;
    const across = __ACROSS__, down = __DOWN__;
    const frame = stage.parentElement;
    let drag = null, chip = null;
    const readout = (b) => {
      const w = Math.max(1, Math.round(across * b.width / 100));
      const h = Math.max(1, Math.round(down * b.height / 100));
      const x = Math.max(0, Math.round(across * b.left / 100));
      const y = Math.max(0, Math.round(down * (1 - (b.top + b.height) / 100)));
      if (!chip) {
        chip = document.createElement('div');
        chip.className = 'console-bgview-readout';
        frame.appendChild(chip);
      }
      chip.textContent = x + ', ' + y + ' \\u00b7 ' + w + ' \\u00d7 ' + h;
      const at = frame.getBoundingClientRect(), on = el.getBoundingClientRect();
      const above = on.top - at.top - chip.offsetHeight - 4;
      const top = above >= 0 ? above : on.bottom - at.top + 4;
      chip.style.top = clamp(top, 0, frame.clientHeight - chip.offsetHeight) + 'px';
      chip.style.left = clamp(on.left - at.left, 0, frame.clientWidth - chip.offsetWidth) + 'px';
    };
    const read = () => ({left: parseFloat(el.style.left), top: parseFloat(el.style.top),
                         width: parseFloat(el.style.width), height: parseFloat(el.style.height)});
    el.addEventListener('pointerdown', (e) => {
      if (e.button) return;
      e.preventDefault();
      const grip = e.target.closest('[data-grip]');
      drag = {grip: grip ? grip.dataset.grip : 'move', x: e.clientX, y: e.clientY,
              from: read(), now: null};
      el.setPointerCapture(e.pointerId);
    });
    el.addEventListener('pointermove', (e) => {
      if (!drag) return;
      const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
      if (!drag.now && Math.hypot(dx, dy) < SLOP) return;
      const lx = (cos * dx + sin * dy) / stage.offsetWidth * 100;
      const ly = (-sin * dx + cos * dy) / stage.offsetHeight * 100;
      let {left, top, width, height} = drag.from;
      const g = drag.grip;
      if (g === 'move') {
        left = clamp(left + lx, 0, 100 - width);
        top = clamp(top + ly, 0, 100 - height);
      } else {
        if (g.includes('w')) {
          const r = left + width;
          left = clamp(left + lx, 0, r - MIN);
          width = r - left;
        }
        if (g.includes('e')) width = clamp(width + lx, MIN, 100 - left);
        if (g.includes('n')) {
          const b = top + height;
          top = clamp(top + ly, 0, b - MIN);
          height = b - top;
        }
        if (g.includes('s')) height = clamp(height + ly, MIN, 100 - top);
      }
      drag.now = {left, top, width, height};
      el.style.left = left + '%'; el.style.top = top + '%';
      el.style.width = width + '%'; el.style.height = height + '%';
      readout(drag.now);
    });
    const end = (e) => {
      if (!drag) return;
      const done = drag.now;
      drag = null;
      if (chip) { chip.remove(); chip = null; }
      if (done) el.dispatchEvent(new CustomEvent('boxset', {detail: done}));
    };
    el.addEventListener('pointerup', end);
    el.addEventListener('pointercancel', end);
  };
  wire();
})()
"""


def _dmd(box: Box, turns: int, on_set: Callable[[Box], Awaitable[None]] | None,
         units: tuple[int, int]) -> None:
    if box.auto:
        ui.label(t("console.backglass.dmd_automatic")).classes("console-bgview-auto")
        return
    style = (f"left:{box.left:.3f}%;top:{box.top:.3f}%;width:{box.width:.3f}%;"
             f"height:{box.height:.3f}%")
    if on_set is None:
        with ui.element("div").classes("console-bgview-dmd").style(style):
            ui.label(t("console.backglass.dmd_sample.player"))
            ui.label(t("console.backglass.dmd_sample.score"))
        return

    async def set_box(event: Any) -> None:
        detail = event.args
        await on_set(Box(float(detail["left"]), float(detail["top"]), float(detail["width"]),
                         float(detail["height"])))

    with ui.element("div").classes("console-bgview-dmd console-bgview-dmd--live") \
            .style(style) as shape:
        ui.label(t("console.backglass.dmd_sample.player"))
        ui.label(t("console.backglass.dmd_sample.score"))
        for grip in GRIPS:
            ui.element("div").classes(f"console-bgview-grip console-bgview-grip--{grip}") \
                .props(f"data-grip={grip}")
    shape.tooltip(t("console.backglass.dmd_move.hint"))
    shape.on("boxset", set_box, js_handler="(e) => emit(e.detail)")
    ui.run_javascript(BOX_JS.replace("__ID__", str(shape.id)).replace("__TURNS__", str(turns))
                      .replace("__ACROSS__", str(units[0])).replace("__DOWN__", str(units[1])))
