"""A sign-in request, shown on a Console open on this computer.

Whoever sits at this computer decides: Show draws the six digits, Ignore turns that address
away. A Console opened from another computer is never given the request, because the
digits it carries are what lets that computer in.
"""

from __future__ import annotations

from typing import Any

from nicegui import ui

from common import sign_in
from common.i18n import t
from console import dialog as frame
from console import panel, verbs
from httpapi import auth

POLL_SECONDS = 2.0


def watch() -> None:
    """Start looking for a request, on a page this computer opened."""
    try:
        if not auth.caller_is_local(ui.context.client.request):
            return
    except Exception:  # noqa: BLE001 - a page with no request has nobody to ask
        return
    held: dict[str, Any] = {"key": None, "dialog": None}

    def poll() -> None:
        request = sign_in.instance().pending()
        key = (request.id, request.state) if request is not None else None
        if key == held["key"]:
            return
        held["key"] = key
        if held["dialog"] is not None:
            held["dialog"].close()
            held["dialog"] = None
        if request is not None:
            held["dialog"] = _ask(request)

    ui.timer(POLL_SECONDS, poll)


def _ask(request: sign_in.Request) -> ui.dialog:
    signer = sign_in.instance()
    with frame.made().props("persistent") as sheet, ui.card().classes("console-confirm"):
        ui.label(t("console.security.wants", address=request.address)) \
            .classes("console-confirm-title")
        if request.state == sign_in.SHOWN:
            ui.label(request.code).classes("text-h3 text-center") \
                .style("letter-spacing:0.3em;font-variant-numeric:tabular-nums")
            ui.label(t("console.security.type_it", address=request.address)) \
                .classes("console-help text-center")
            with ui.row().classes("justify-center w-full"):
                panel.action(t("word.close"), lambda: signer.dismiss(request.id),
                             icon=verbs.CLOSE, hint=t("console.security.close_hint"))()
        else:
            with ui.row().classes("justify-center w-full"):
                panel.action(t("console.security.show"), lambda: signer.reveal(request.id),
                             icon=verbs.UNHIDE, hint=t("console.security.show_hint"))()
                panel.action(t("console.security.ignore"), lambda: signer.ignore(request.id),
                             icon=verbs.IGNORE, danger=True,
                             hint=t("console.security.ignore_hint"))()
    sheet.open()
    return sheet
