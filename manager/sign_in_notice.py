"""A sign-in request, a Confirm Code, a pairing code or a program's ask to make a change,
shown on a Manager open on this device.

A sign-in waits for whoever sits at this device: Show draws the six digits, Ignore turns
that address away. A Confirm Code and a pairing code are drawn at once, since the person
reading them off this screen is the proof they are here. An ask is answered here with
Approve or Decline, or left for Needs You with Close. A Manager opened from another
device is never given any of them, because the digits are what lets that device in.
"""

from __future__ import annotations

from typing import Any

from nicegui import ui

from common import approvals, sign_in
from common.i18n import t
from httpapi import auth
from manager import dialog as frame
from manager import verbs

POLL_SECONDS = 2.0


def watch() -> None:
    """Start looking for a request, on a page this device opened."""
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
        asked = None if code is not None or request is not None \
            else approvals.instance().on_screen()
        if code is not None:
            key: tuple[str, ...] | None = (code.id,)
        elif request is not None:
            key = (request.id, request.state)
        else:
            key = (asked.id,) if asked is not None else None
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
        elif asked is not None:
            held["dialog"] = _approve(asked)

    ui.timer(POLL_SECONDS, poll)


def _show(code: sign_in.Confirm, closed: set[str]) -> ui.dialog:
    pairing = code.purpose == sign_in.PAIR

    def close() -> None:
        closed.add(code.id)
        sheet.close()

    with frame.opened(t("manager.security.pair_code" if pairing
                        else "manager.security.confirm_code"),
                      classes="manager-confirm", ignore_outside_click=True) as sheet:
        ui.label(code.code).classes("manager-digits w-full")
        ui.label(t("manager.security.pair_asked" if pairing else "manager.security.confirm_asked",
                   address=code.address)).classes("manager-help text-center px-3")
        ui.label(t("manager.security.code_good", minutes=sign_in.CODE_SECONDS // 60)) \
            .classes("manager-help text-center px-3")
        with frame.footer():
            frame.answer(t("word.close"), close, icon=verbs.CLOSE) \
                .tooltip(t("manager.security.code_close_hint"))
    frame.on_escape(sheet, lambda: closed.add(code.id))
    sheet.open()
    return sheet


def _ask(request: sign_in.Request) -> ui.dialog:
    signer = sign_in.instance()
    shown = request.state == sign_in.SHOWN
    # A request still waiting is answered with Show or Ignore; leaving it any other way
    # would strand it with nothing on this device to answer it.
    with frame.opened(t("manager.security.wants", address=request.address),
                      classes="manager-confirm", persistent=not shown,
                      ignore_outside_click=shown) as sheet:
        if shown:
            ui.label(request.code).classes("manager-digits w-full")
            ui.label(t("manager.security.type_it", address=request.address)) \
                .classes("manager-help text-center px-3")
            with frame.footer():
                frame.answer(t("word.close"), lambda: signer.dismiss(request.id),
                             icon=verbs.CLOSE).tooltip(t("manager.security.close_hint"))
        else:
            with frame.footer():
                frame.aside(t("manager.security.ignore"), lambda: signer.ignore(request.id),
                            icon=verbs.IGNORE).tooltip(t("manager.security.ignore_hint"))
                frame.answer(t("manager.security.show"), lambda: signer.reveal(request.id),
                             icon=verbs.UNHIDE).tooltip(t("manager.security.show_hint"))
    if shown:
        frame.on_escape(sheet, lambda: signer.dismiss(request.id))
    sheet.open()
    return sheet


def _approve(ask: approvals.Ask) -> ui.dialog:
    asks = approvals.instance()
    change = "\n".join(part for part in (" ".join((ask.method, ask.path)), ask.body) if part)
    with frame.opened(t("manager.security.asks", program=ask.token_name),
                      classes="manager-confirm", ignore_outside_click=True) as sheet:
        ui.label(change).classes("manager-need-change px-3").props("tabindex=0")
        ui.label(t("manager.security.asks_lapse", count=max(1, asks.seconds_left(ask) // 60))) \
            .classes("manager-help px-3")
        with frame.footer():
            frame.aside(t("manager.needs.decline"), lambda: asks.decline(ask.id),
                        icon=verbs.IGNORE).tooltip(t("manager.needs.decline.help"))
            frame.cancel(lambda: asks.leave_screen(ask.id), t("word.close")) \
                .tooltip(t("manager.security.asks_close_hint"))
            frame.answer(t("manager.needs.approve"), lambda: asks.approve(ask.id),
                         icon=verbs.ACCEPT).tooltip(t("manager.needs.approve.help"))
    frame.on_escape(sheet, lambda: asks.leave_screen(ask.id))
    sheet.open()
    return sheet
