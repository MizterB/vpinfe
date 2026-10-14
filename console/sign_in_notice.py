"""A sign-in request, a Confirm Code or a pairing code, shown on a Console open on this
computer.

A sign-in waits for whoever sits at this computer: Show draws the six digits, Ignore turns
that address away. A Confirm Code and a pairing code are drawn at once, since the person
reading them off this screen is the proof they are here. A Console opened from another
computer is never given any of them, because the digits are what lets that computer in.
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
    held: dict[str, Any] = {"key": None, "dialog": None, "closed": set()}

    def poll() -> None:
        signer = sign_in.instance()
        code = next((one for one in signer.confirms() if one.id not in held["closed"]), None)
        request = None if code is not None else signer.pending()
        if code is not None:
            key: tuple[str, ...] | None = (code.id,)
        else:
            key = (request.id, request.state) if request is not None else None
        if key == held["key"]:
            return
        held["key"] = key
        if held["dialog"] is not None:
            held["dialog"].close()
            held["dialog"] = None
        if code is not None:
            held["dialog"] = _show(code, held["closed"])
        elif request is not None:
            held["dialog"] = _ask(request)

    ui.timer(POLL_SECONDS, poll)


def _show(code: sign_in.Confirm, closed: set[str]) -> ui.dialog:
    pairing = code.purpose == sign_in.PAIR

    def close() -> None:
        closed.add(code.id)
        sheet.close()

    with frame.made().props("persistent") as sheet, ui.card().classes("console-confirm"):
        ui.label(t("console.security.pair_code" if pairing else "console.security.confirm_code")) \
            .classes("console-confirm-title")
        ui.label(code.code).classes("text-h3 text-center") \
            .style("letter-spacing:0.3em;font-variant-numeric:tabular-nums")
        ui.label(t("console.security.pair_asked" if pairing else "console.security.confirm_asked",
                   address=code.address)).classes("console-help text-center")
        ui.label(t("console.security.code_good", minutes=sign_in.CODE_SECONDS // 60)) \
            .classes("console-help text-center")
        with ui.row().classes("justify-center w-full"):
            panel.action(t("word.close"), close, icon=verbs.CLOSE,
                         hint=t("console.security.close_hint"))()
    sheet.open()
    return sheet


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
