"""The tokens a program holds to call this install, on Settings > Security.

A token is made here, shown once, and taken back here. Making one hands out access, so it
asks the Confirm like any Protected change; the page only calls and the Console's
boundary asks.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from nicegui import run, ui

from common import api_tokens
from common.failures import why
from common.i18n import t
from console import about, offload, panel, verbs, when
from console import dialog as frame
from console.api import ApiError
from console.data import Library
from console.on_page import on_page


def access_label(access: str) -> str:
    return t("console.tokens.full" if access == api_tokens.FULL else "console.tokens.play")


def last_used(row: dict[str, Any]) -> str:
    stamp = float(row.get("last_used") or 0)
    if not stamp:
        return t("console.tokens.never_used")
    return t("console.security.last_used", when=when.ago(when.from_epoch(stamp).isoformat(),
                                                         inline=True))


def _row_value(row: dict[str, Any], revoke: Callable[[str], Any],
               power: Callable[[str, bool], Any]) -> Callable[[], None]:
    def draw() -> None:
        with ui.row().classes("items-center no-wrap gap-3 w-full"):
            ui.label(access_label(str(row.get("access") or ""))).classes("console-help")
            ui.label(last_used(row)).classes("console-help grow")
            if row.get("access") == api_tokens.FULL:
                ui.label(t("console.tokens.power")).classes("console-help")
                panel.switch(bool(row.get("can_power")),
                             lambda event: power(str(row["id"]), bool(event.value)),
                             hint=t("console.tokens.power_hint"))()
            panel.action(t("console.tokens.revoke"), lambda: revoke(str(row["id"])),
                         icon=verbs.DELETE, inline=True, danger=True,
                         hint=t("console.tokens.revoke_hint"))()

    return draw


def entries(rows: list[dict[str, Any]], make: Callable[[], Any],
            revoke: Callable[[str], Any],
            power: Callable[[str, bool], Any]) -> list[tuple[Any, ...]]:
    """What the Tokens section shows, in order. Pure of the page, so a test reads it."""
    out: list[tuple[Any, ...]] = [(panel.HEADING, t("console.tokens.heading"))]
    if rows:
        out += [(str(row.get("name") or ""), _row_value(row, revoke, power)) for row in rows]
    else:
        out.append(panel.intro(t("console.tokens.none")))
    out.append((panel.FULL, panel.action(t("console.tokens.new"), make, icon=verbs.ADD,
                                         hint=t("console.tokens.new_hint"))))
    out.append(panel.note(t("console.tokens.limits")))
    return out


async def _shown_once(name: str, secret: str) -> None:
    """The secret, and the one chance to copy it."""
    with frame.opened(t("console.tokens.made_title", name=name), wide=True) as box:
        ui.label(t("console.tokens.made_line")).classes("console-help px-3")
        with ui.element("div").classes("w-full px-3"):
            ui.input(value=secret).props("outlined readonly dense") \
                .classes("w-full console-log")
        with frame.footer():
            panel.action(t("word.copy"), lambda event: about.copied(bool(event.args), secret),
                         icon=verbs.COPY, hint=t("console.about.copy_hint"),
                         js=about.COPY_JS % json.dumps(secret))()
            frame.answer(t("word.done"), box.close, icon=verbs.DONE)
    box.open()
    await box


async def _ask_new() -> tuple[str, str, bool] | None:
    """The name, the access and the power switch, or None where it was cancelled."""
    held: dict[str, Any] = {"access": api_tokens.FULL, "power": False}
    with frame.opened(t("console.tokens.new_title"), classes="console-confirm") as box:
        name = frame.field(placeholder=t("console.tokens.name"))
        panel.segmented({api_tokens.FULL: access_label(api_tokens.FULL),
                         api_tokens.PLAY: access_label(api_tokens.PLAY)},
                        api_tokens.FULL,
                        lambda event: (held.update(access=event.value),
                                       power_row.set_visibility(event.value == api_tokens.FULL)))
        with ui.row().classes("items-center no-wrap gap-3 px-3") as power_row:
            ui.label(t("console.tokens.power")).classes("console-help grow")
            panel.switch(False, lambda event: held.update(power=bool(event.value)),
                         hint=t("console.tokens.power_hint"))()
        with frame.footer():
            frame.cancel(lambda: box.submit(None))
            go = frame.answer(t("console.tokens.make"),
                              lambda: box.submit((str(name.value or "").strip(),
                                                  held["access"], bool(held["power"]))),
                              icon=verbs.CREATE)
    frame.enter_presses(go)
    frame.focus(box, name)
    return await box


def page_parts(library: Library, redraw: Callable[[], None],
               rows: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
    @on_page
    async def make() -> None:
        wanted = await _ask_new()
        if wanted is None:
            return
        name, access, can_power = wanted
        try:
            made = await offload.io(library.make_token, name, access, can_power)
        except ApiError as exc:
            ui.notify(t("console.tokens.not_made"), caption=why(exc), type="negative")
            return
        redraw()
        await _shown_once(name, str(made.get("secret") or ""))

    @on_page
    async def revoke(token_id: str) -> None:
        await run.io_bound(library.revoke_token, token_id)
        redraw()

    @on_page
    async def power(token_id: str, on: bool) -> None:
        try:
            await offload.io(library.set_token_power, token_id, on)
        except ApiError as exc:
            ui.notify(t("console.tokens.not_changed"), caption=why(exc), type="negative")
        redraw()

    return entries(rows, make, revoke, power)
