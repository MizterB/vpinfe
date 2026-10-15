"""The question a Protected change asks a signed-in Owner: a code from this computer's screen.

Only reached for a browser on another computer. Whoever is at the machine sees the six digits
at once, so reading them off its screen is the proof of being in front of it.
"""

from __future__ import annotations

import logging

from nicegui import run, ui

from common import sign_in
from common.failures import why
from common.i18n import t
from common.install_identity import display_name
from common.paths import get_ini_config
from console import dialog as frame
from console import offload, verbs
from console.api import ApiClient, ApiError
from console.on_page import on_page

logger = logging.getLogger("vpinfe.console.confirm_code")

# After these the code is gone and a new one is already on the screen.
NEW_CODE = ("no_code", "used_up")


async def ask() -> bool:
    """Whether the person confirmed. With an authenticator set up, its six digits; otherwise
    (or on request, when this computer shows them) the code drawn on this computer's screen,
    which the same six digits here answer."""
    device = display_name(get_ini_config())
    api = ApiClient()
    try:
        app = await run.io_bound(api.authenticator) or {}
    except ApiError as exc:
        ui.notify(t("console.confirm.not_asked"), caption=why(exc), type="negative")
        return False
    using_app = bool(app.get("enabled"))

    @on_page
    async def show_screen_code() -> bool:
        try:
            await run.io_bound(api.confirm_code)
        except ApiError as exc:
            ui.notify(t("console.confirm.not_asked"), caption=why(exc), type="negative")
            return False
        return True

    if not using_app and not await show_screen_code():
        return False

    def line_text() -> str:
        if using_app:
            return t("console.confirm.app_line", minutes=sign_in.CONFIRM_SECONDS // 60)
        return t("console.confirm.line", device=device, minutes=sign_in.CONFIRM_SECONDS // 60)

    def other_label() -> str:
        return t("console.confirm.use_screen", device=device) if using_app \
            else t("console.confirm.use_app")

    @on_page
    async def send() -> None:
        try:
            await offload.io(api.confirm_authenticator if using_app else api.confirm,
                             str(code.value or ""))
        except ApiError as exc:
            problem.text = why(exc)
            code.value = ""
            if not using_app and exc.details.get("reason") in NEW_CODE:
                await run.io_bound(api.confirm_code)
            return
        box.submit(True)

    @on_page
    async def switch() -> None:
        nonlocal using_app
        if using_app and not await show_screen_code():
            return
        using_app = not using_app
        said.text = line_text()
        other.text = other_label()
        problem.text = ""
        code.value = ""

    with frame.opened(t("console.confirm.title", device=device),
                      classes="console-confirm", persistent=True) as box:
        said = ui.label(line_text()).classes("console-help px-3")
        code = frame.field(placeholder=t("console.confirm.code"))
        problem = ui.label("").classes("console-help text-negative px-3")
        with frame.footer():
            if app.get("enabled"):
                other = frame.aside(other_label(), switch, icon=verbs.LOCK)
            frame.cancel(lambda: box.submit(False))
            go = frame.answer(t("word.confirm"), send, icon=verbs.ACCEPT)
    frame.enter_presses(go)
    frame.focus(box, code)
    return bool(await box)
