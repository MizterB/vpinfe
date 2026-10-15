"""The authenticator app on Settings > Security, and the one-time offer to set one up.

Setting up, setting up again after a lost phone, removing it and switching off the on-screen
sign-in code are all Protected, so the page only calls and the Console's boundary asks for
the Confirm. Nothing here needs an authenticator to exist.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from nicegui import run, ui

from common import authenticator, paths
from common.failures import why
from common.i18n import t
from common.install_identity import display_name
from console import confirm, deeplink, offload, panel, qr, verbs
from console import dialog as frame
from console.api import ApiError
from console.data import Library
from console.on_page import on_page

SECURITY_PAGE = "vpinfe.security"


def entries(state: dict[str, Any], device: str, set_up: Callable[[], Any],
            remove: Callable[[], Any],
            screen_codes: Callable[[bool], Any]) -> list[tuple[Any, ...]]:
    """What the Authenticator section shows, in order. Pure of the page, so a test reads it."""
    out: list[tuple[Any, ...]] = [(panel.HEADING, t("console.authenticator.heading"))]
    if not state.get("enabled"):
        out.append(panel.intro(t("console.authenticator.none")))
        out.append((panel.FULL, panel.action(t("console.authenticator.set_up"), set_up,
                                             icon=verbs.ADD,
                                             hint=t("console.authenticator.set_up_hint"))))
        return out
    out.append(panel.intro(t("console.authenticator.on")))
    out.append((t("console.authenticator.screen_codes", device=device),
                panel.switch(bool(state.get("screen_codes")),
                             lambda event: screen_codes(bool(event.value)),
                             hint=t("console.authenticator.screen_codes_hint"))))
    out.append((panel.FULL, panel.action(t("console.authenticator.again"), set_up,
                                         icon=verbs.REFRESH,
                                         hint=t("console.authenticator.again_hint"))))
    out.append((panel.FULL, panel.action(t("console.authenticator.remove"), remove,
                                         icon=verbs.DELETE, danger=True,
                                         hint=t("console.authenticator.remove_hint"))))
    return out


async def _enrol(library: Library) -> bool:
    """The QR and the key, and the first code from the app that learned them. Whether it was
    accepted; a refusal stays in the dialog so the person can try the next code."""
    try:
        made = await offload.io(library.authenticator_setup)
    except ApiError as exc:
        ui.notify(t("console.authenticator.setup_failed"), caption=why(exc), type="negative")
        return False
    secret = str(made.get("secret") or "")
    art = qr.svg(str(made.get("uri") or ""))

    @on_page
    async def send() -> None:
        try:
            await offload.io(library.authenticator_finish, str(code.value or ""))
        except ApiError as exc:
            problem.text = why(exc)
            code.value = ""
            return
        box.submit(True)

    with frame.opened(t("console.authenticator.title"), classes="console-confirm") as box:
        ui.label(t("console.authenticator.line")).classes("console-help px-3")
        if art:
            ui.html(art).classes("console-qr")
        ui.label(t("console.authenticator.key")).classes("console-help px-3")
        with ui.element("div").classes("w-full px-3"):
            ui.input(value=secret).props("outlined readonly dense").classes("w-full console-log")
        code = frame.field(placeholder=t("console.confirm.code"))
        problem = ui.label("").classes("console-help text-negative px-3")
        with frame.footer():
            frame.cancel(lambda: box.submit(False))
            go = frame.answer(t("console.authenticator.set_up"), send, icon=verbs.ACCEPT)
    frame.enter_presses(go)
    frame.focus(box, code)
    return bool(await box)


def page_parts(library: Library, redraw: Callable[[], None],
               state: dict[str, Any]) -> list[tuple[Any, ...]]:
    device = display_name(paths.get_ini_config())

    @on_page
    async def set_up() -> None:
        if await _enrol(library):
            redraw()

    @on_page
    async def remove() -> None:
        if not await confirm.ask(
                t("console.authenticator.remove_question"),
                detail=t("console.authenticator.remove_detail"),
                confirm=t("console.authenticator.remove"), icon=verbs.DELETE, danger=True):
            return
        try:
            await run.io_bound(library.authenticator_remove)
        except ApiError as exc:
            ui.notify(t("console.authenticator.not_changed"), caption=why(exc), type="negative")
        redraw()

    @on_page
    async def screen_codes(on: bool) -> None:
        try:
            await offload.io(library.set_screen_codes, on)
        except ApiError as exc:
            ui.notify(t("console.authenticator.not_changed"), caption=why(exc), type="negative")
        redraw()

    return entries(state, device, set_up, remove, screen_codes)


def offer_due(*, signed_in_owner: bool) -> bool:
    """Whether to offer an authenticator now: a browser another computer signed in, nobody
    has been offered one, and none is set up."""
    held = authenticator.instance()
    return signed_in_owner and not held.offered() and not held.enabled()


async def offer() -> None:
    """Ask once, and never again whatever the answer."""
    authenticator.instance().mark_offered()
    device = display_name(paths.get_ini_config())
    with frame.opened(t("console.authenticator.offer_title"), classes="console-confirm") as box:
        ui.label(t("console.authenticator.offer_line", device=device)).classes("console-help px-3")
        with frame.footer():
            frame.cancel(lambda: box.submit(False), t("console.authenticator.offer_not_now"))
            frame.answer(t("console.authenticator.set_up"), lambda: box.submit(True),
                         icon=verbs.ADD)
    if await box:
        ui.navigate.to("/console?" + deeplink.query({"view": "settings",
                                                     "settings_page": SECURITY_PAGE}))
