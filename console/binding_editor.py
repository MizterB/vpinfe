"""What a player presses to do something, said by pressing it.

The bindings for one action, as chips, with a capture that listens for the next key or
controller button. A binding is a selector - `pad:0/button:3` - and typing ten of those
into a text field is what made input feel like configuration rather than a choice.

**A binding two actions claim is the defect this exists to close.** Dispatch resolves a
key to the first action that lists it, so the second one silently does nothing and no
surface ever said so. Here a claimed binding is marked on every action holding it and
named in the tooltip, and taking one is refused before it is stored.

Capture runs in the browser. A key press is a browser event and a gamepad is only
readable there, so the whole listen happens client-side and emits the selector it heard.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from nicegui import ui

from common import input_registry
from console import panel

logger = logging.getLogger("vpinfe.console.binding_editor")

# Listens for whichever comes first, then stops. Escape cancels rather than binding, so
# there is a way out that does not cost a binding - and a player about to bind Escape
# can still do it from the keyboard field's own entry.
_CAPTURE_JS = """() => {
  const stop = (value) => {
    window.removeEventListener('keydown', onKey, true);
    if (timer) { clearInterval(timer); timer = null; }
    if (window.__captureOverlay) {
      window.__captureOverlay.remove();
      window.__captureOverlay = null;
    }
    emit(value);
  };
  const onKey = (e) => {
    e.preventDefault();
    e.stopPropagation();
    stop(e.code === 'Escape' ? '' : 'key:' + e.code);
  };
  // Which buttons were already down when the capture opened, so a held flipper does not
  // bind itself the instant the dialog appears.
  const held = new Set();
  const pads = () => [...(navigator.getGamepads ? navigator.getGamepads() : [])]
    .filter(Boolean);
  pads().forEach(p => p.buttons.forEach((b, i) => { if (b.pressed) held.add(p.index + ':' + i); }));
  let timer = setInterval(() => {
    for (const pad of pads()) {
      pad.buttons.forEach((b, i) => {
        const id = pad.index + ':' + i;
        if (!b.pressed) { held.delete(id); return; }
        if (held.has(id)) return;
        stop('pad:' + pad.index + '/button:' + i);
      });
    }
  }, 60);
  const note = document.createElement('div');
  note.className = 'console-capture';
  note.textContent = %s;
  document.body.appendChild(note);
  window.__captureOverlay = note;
  window.addEventListener('keydown', onKey, true);
  setTimeout(() => { if (window.__captureOverlay === note) stop(''); }, 10000);
}"""


def rows(option: dict[str, Any], value: Any, save: Callable[[Any], Any], *,
         section: dict[str, Any] | None = None,
         writable: bool = True,
         rerender: Callable[[], None] | None = None) -> Callable[[], None]:
    """One action's bindings, and the way to add another.

    `section` is every action's bindings, because a collision is a fact about two rows
    and this one cannot see it alone - and `rerender` redraws the page rather than this
    row, for the same reason: taking a binding off one action can clear a mark on
    another, and a row that only refreshed itself would leave the other one lying.
    """
    held = _selectors(value)
    # Who holds each binding, not just what clashes: refusing a binding another action
    # already holds is the whole point, and a clash list only names what is *already*
    # broken.
    claimed = input_registry.holders(
        {name: _selectors(one) for name, one in (section or {}).items()})

    async def store(wanted: list[str]) -> None:
        if await save(list(wanted)) is False:
            return
        held[:] = list(wanted)
        if rerender is not None:
            rerender()

    def draw() -> None:
        with ui.element("div").classes("console-chips"):
            for binding in held:
                _chip(binding, store, claimed.get(str(binding)) or [], held,
                      writable=writable)
            if not held:
                ui.label("Nothing bound").classes("console-member-chip console-chip-quiet")
            if writable:
                _capture(option, held, store, claimed)

    return draw


def _selectors(value: Any) -> list[str]:
    """A binding list, whatever shape it arrived in.

    A stored value is a list and a schema default is the comma-joined string the config
    file would hold. Taking `list()` of the second gives one chip per character, which is
    what this exists to stop.
    """
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return [str(one).strip() for one in (value or []) if str(one).strip()]


def _chip(binding: str, store: Callable[[list], Any], claimed_by: list[str],
          held: list, *, writable: bool) -> None:
    """One binding. Marked where another action claims it too, because the one that
    loses is invisible everywhere else."""
    text = str(binding)
    shown = input_registry.describe(text)
    tone = "console-chip-warn" if len(claimed_by) > 1 else "console-chip-quiet"
    chip = ui.label(shown).classes(f"console-member-chip {tone}")
    if len(claimed_by) > 1:
        others = [_label_for(name) for name in claimed_by]
        chip.tooltip(f"Also bound to {_and(others)}. Only the first one gets it.")
    elif text != shown:
        # The stored selector, for somebody reading it against a config file.
        chip.tooltip(text)
    if writable:
        chip.classes("cursor-pointer") \
            .on("click", lambda: store([one for one in held if str(one) != text]))
        if len(claimed_by) <= 1:
            chip.tooltip(f"{text} - click to remove")


def _capture(option: dict[str, Any], held: list, store: Callable[[list], Any],
             claimed: dict[str, list[str]]) -> None:
    label = str(option.get("label") or option.get("key") or "this")
    said = f'"Press a key or a controller button for {label}. Esc cancels."'

    async def heard(event: Any) -> None:
        selector = str(event.args or "").strip()
        if not selector:
            return
        shown = input_registry.describe(selector)
        if selector in [str(one) for one in held]:
            ui.notify(f"{shown} already does this.", type="warning")
            return
        # Refused rather than taken with a warning. Dispatch gives a key to the first
        # action that lists it, so taking one that is spoken for would not move it - it
        # would make a binding that looks set and never fires.
        owner = _owner(selector, claimed, option)
        if owner:
            ui.notify(f"{shown} is already {owner}. Take it off there first.",
                      type="warning")
            return
        await store([*held, selector])

    panel.action("Bind", heard, icon="add", inline=True,
                 hint="Listen for the next key or button",
                 js=_CAPTURE_JS % said)()


def _owner(selector: str, claimed: dict[str, list[str]],
           option: dict[str, Any]) -> str:
    """Which other action holds this binding, said as a person would name it."""
    names = [name for name in claimed.get(selector, [])
             if name != option.get("key")]
    return _and([_label_for(name) for name in names]) if names else ""


def _label_for(name: str) -> str:
    found = next((one for one in input_registry.actions() if one.name == name), None)
    return found.label if found is not None else name


def _and(names: list[str]) -> str:
    if len(names) < 3:
        return " and ".join(names)
    return f"{', '.join(names[:-1])} and {names[-1]}"
