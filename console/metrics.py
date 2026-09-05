"""What this machine is doing, and what it has been doing this session.

The live half. A machine's host, OS and browser are facts rather than readings and they
belong to the device that reports them - the Devices workbench answers *is that machine
healthy*, and this answers *what is this one doing, and what has it been doing*.

Reading is what fills the history, so leaving this page open is what builds the record.
Nothing samples in the background: a machine nobody is watching does not need a log of
having been idle.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from nicegui import run, ui

from console import panel

logger = logging.getLogger("vpinfe.console.metrics")

# The cadence the job line already uses, so a page with both on it ticks once rather
# than twice out of step.
EVERY_SECONDS = 2.0

# How far back the graphs reach. Ten minutes answers "did that scan do this?" without
# turning a sparkline into a smear.
WINDOW_SECONDS = 600

# Where a reading stops being ordinary. Two thresholds rather than a gradient: a color
# that changes continuously says something is changing, which is not the question.
WARN, BAD = 75.0, 90.0


def build(library, state: dict[str, Any], redraw: Callable[[], None]) -> None:
    """The readings, refreshed in place. Drawn once and updated on a timer rather than
    rebuilt: a page that rebuilds every two seconds loses a scroll position and a
    selection, and there is nothing here to select yet but the scroll is real."""
    body = ui.column().classes("w-full gap-3")
    held: dict[str, Any] = {"seen": None}

    async def tick() -> None:
        try:
            found = await run.io_bound(library.metrics, WINDOW_SECONDS)
        except Exception as exc:  # noqa: BLE001 - this page says why, never 500s
            held["seen"] = {"error": str(exc)}
        else:
            held["seen"] = found
        _draw(body, held["seen"])

    ui.timer(0.01, tick, once=True)
    ui.timer(EVERY_SECONDS, tick)


def _draw(body, found: dict[str, Any] | None) -> None:
    body.clear()
    with body:
        if not found:
            return
        if found.get("error"):
            panel.facts(ui, [panel.intro(
                f"Could not read this machine: {found['error']}")])
            return
        now = found.get("now") or {}
        if not now.get("measurable"):
            # Offered with the reason rather than hidden: a page that simply omits the
            # readings leaves somebody unsure whether the machine is fine or this is.
            panel.facts(ui, [panel.intro(
                now.get("reason") or "This machine cannot report its readings.")])
            return
        _live(now, found.get("history") or [])


def _live(now: dict[str, Any], history: list[dict[str, Any]]) -> None:
    with ui.row().classes("w-full gap-4 no-wrap items-stretch"):
        _reading("Processor", now.get("cpu_percent"),
                 [one.get("cpu_percent") for one in history],
                 said=_load_said(now.get("load")))
        _reading("Memory", now.get("memory_percent"),
                 [one.get("memory_percent") for one in history],
                 said=_bytes_said(now.get("memory_used"), now.get("memory_total")))

    disks = [one for one in (now.get("disks") or [])]
    if not disks:
        return
    ui.label("Free space").classes("console-group mt-2")
    with ui.element("div").classes("console-card w-full"):
        for disk in disks:
            _disk_row(disk)


def _reading(title: str, value: Any, series: list[Any], said: str = "") -> None:
    """One number, its trend, and the sentence underneath that says what it is of.

    A percentage on its own does not say how much: 80% of 8GB and 80% of 64GB are
    different machines, and the number alone reads the same.
    """
    with ui.element("div").classes("console-card grow min-w-0"):
        ui.label(title).classes("console-card-title")
        shown = "-" if value is None else f"{value:.0f}%"
        ui.label(shown).classes("console-kpi").style(f"color: {_tone(value)}")
        _spark([one for one in series if one is not None])
        if said:
            ui.label(said).classes("text-xs opacity-60")


def _disk_row(disk: dict[str, Any]) -> None:
    with ui.row().classes("items-center gap-3 w-full no-wrap py-1"):
        with ui.column().classes("gap-0 grow min-w-0"):
            ui.label(disk.get("path", "")).classes("console-setting truncate")
            for also in disk.get("also") or []:
                # Same volume, so the same numbers. Named rather than left out, or
                # somebody looking for it concludes it is not watched.
                ui.label(also).classes("console-help truncate")
        if disk.get("error"):
            # A share that has gone away is exactly what this reports, and saying
            # nothing would show it as a path with no numbers.
            ui.label("cannot be read").classes("text-xs").style(f"color: {_tone(100)}")
            return
        with ui.element("div").classes("w-40 shrink-0"):
            _bar((disk.get("percent") or 0) / 100, _tone(disk.get("percent")))
        # The bar fills as the disk fills, so the words say full too. A bar reading
        # "used" beside a number reading "free" is two directions in one row.
        ui.label(f"{(disk.get('percent') or 0):.0f}% full - "
                 f"{_size(disk.get('free'))} free") \
            .classes("text-xs opacity-60 shrink-0")


def _spark(series: list[float]) -> None:
    """The shape of the last few minutes, drawn as bars rather than a line.

    A number says where it is; this says whether it got there. Nothing at all until
    there are two points - one bar is a shape that implies a trend it cannot have.
    """
    if len(series) < 2:
        ui.label("collecting").classes("text-xs opacity-40")
        return
    # Every other point at most, so a ten-minute window is a readable width rather than
    # three hundred hairlines.
    step = max(1, len(series) // 60)
    shown = series[::step][-60:]
    with ui.row().classes("items-end gap-px w-full no-wrap").style("height:28px"):
        for one in shown:
            ui.element("div").style(
                f"flex:1 1 0; min-width:1px; height:{max(2, min(100, one)):.0f}%;"
                f" background:{_tone(one)}; opacity:0.55; border-radius:1px")


def _bar(fraction: float, color: str) -> None:
    with ui.element("div").classes("console-bar w-full"):
        ui.element("div").style(
            f"width:{max(0.0, min(1.0, fraction)) * 100:.0f}%; background:{color}")


def _tone(value: Any) -> str:
    """The declared tokens, not the obvious names: this tree has `--warm` and `--danger`,
    and `--warning`/`--negative` are not declared - a var() naming one is invisible."""
    if value is None:
        return "var(--ink-3)"
    if value >= BAD:
        return "var(--danger)"
    if value >= WARN:
        return "var(--warm)"
    return "var(--accent)"


def _size(value: Any) -> str:
    if value is None:
        return "-"
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _bytes_said(used: Any, total: Any) -> str:
    if used is None or total is None:
        return ""
    return f"{_size(used)} of {_size(total)}"


def _load_said(load: Any) -> str:
    """Load average, where the platform has one. Windows does not, and that is a number
    it does not have rather than one we failed to read."""
    if not load:
        return ""
    return "load " + ", ".join(f"{one:g}" for one in load)
