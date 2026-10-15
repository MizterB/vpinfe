"""Settings > Security: which browsers are signed in to this install, and ending them.

A browser on another device gets in by a code this machine shows. This page is where the
Owner sees what that let in, and takes it back.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from nicegui import run, ui

from common import paths, sign_in
from common import serving as serving_state
from common.failures import why
from common.i18n import t
from console import (
    authenticator_panel,
    confirm,
    deeplink,
    encrypted_panel,
    offload,
    panel,
    token_panel,
    verbs,
    when,
)
from console.data import Library
from console.on_page import on_page
from httpapi import auth

logger = logging.getLogger("vpinfe.console.security")

NETWORK_PAGE = "vpinfe.network"


def this_session_id() -> str:
    """The sign-in the browser drawing this page holds, or "" for this machine's own."""
    try:
        session = auth.session_for(ui.context.client.request)
    except Exception:  # noqa: BLE001 - a page without a request is the machine's own
        return ""
    return session.id if session is not None else ""


def name_of(row: dict[str, Any]) -> str:
    """"Safari on iPhone, 192.168.1.31", or the address alone where the browser never said."""
    agent, address = str(row.get("agent") or ""), str(row.get("address") or "")
    return t("console.security.browser_at", agent=agent, address=address) \
        if agent and address else agent or address


def kind_label(kind: str) -> str:
    return t("console.security.kind_remote" if kind == sign_in.REMOTE
             else "console.security.kind_owner")


def last_used(row: dict[str, Any]) -> str:
    stamp = when.from_epoch(float(row.get("last_used") or 0)).isoformat()
    return t("console.security.last_used", when=when.ago(stamp, inline=True))


def _session_value(row: dict[str, Any], mine: str,
                   sign_out: Callable[[str], Any]) -> Callable[[], None]:
    def draw() -> None:
        with ui.row().classes("items-center no-wrap gap-3 w-full"):
            ui.label(kind_label(str(row.get("kind") or ""))).classes("console-help")
            ui.label(last_used(row)).classes("console-help grow")
            if row.get("id") == mine:
                ui.label(t("console.security.this_browser")).classes("console-help")
            panel.action(t("console.security.sign_out"), lambda: sign_out(str(row["id"])),
                         icon=verbs.SIGN_OUT, inline=True,
                         hint=t("console.security.sign_out_hint"))()

    return draw


def entries(rows: list[dict[str, Any]], mine: str, sign_out: Callable[[str], Any],
            sign_out_all: Callable[[], Any], bind: str,
            https: bool = False) -> list[tuple[Any, ...]]:
    """What the page shows, in order. Pure of the page, so a test reads it."""
    out: list[tuple[Any, ...]] = [(panel.HEADING, t("console.security.signed_in"))]
    if rows:
        out += [(name_of(row), _session_value(row, mine, sign_out)) for row in rows]
        out.append((panel.FULL, panel.action(t("console.security.sign_out_all"), sign_out_all,
                                             icon=verbs.SIGN_OUT,
                                             hint=t("console.security.everyone_hint"))))
    else:
        out.append(panel.intro(t("console.security.none")))
    out.append(panel.note(t("console.security.idle")))
    if serving_state.reachable_from_elsewhere(bind):
        out.append((panel.HEADING, t("console.security.other_devices")))
        out.append(panel.intro(t("console.security.sign_in_steps")))
        if not https:
            out.append(panel.intro(t("console.security.unencrypted")))
        out.append((panel.FULL, panel.link(
            t("console.settings.page_network"),
            to="/console?" + deeplink.query({"view": "settings",
                                             "settings_page": NETWORK_PAGE}))))
    return out


async def page(library: Library, redraw: Callable[[], None],
               state: dict[str, Any]) -> Callable[[], None]:
    """Read who is signed in, and hand back the draw."""
    mine = this_session_id()
    try:
        rows = await offload.io(library.sessions)
        made = await offload.io(library.tokens)
        held = await offload.io(library.encrypted)
        app = await offload.io(library.authenticator)
    except Exception as exc:  # noqa: BLE001 - this page says why, never 500s
        reason = why(exc)
        return lambda: panel.facts(ui, [panel.intro(t("console.security.read_failed"),
                                                    hint=reason)])
    bind = serving_state.network(paths.get_ini_config()).http_bind

    @on_page
    async def sign_out(session_id: str) -> None:
        await run.io_bound(library.sign_out_session, session_id)
        redraw()

    @on_page
    async def sign_out_all() -> None:
        if not await confirm.ask(
                t("console.security.everyone_question"),
                detail=t("console.security.everyone_detail"),
                confirm=t("console.security.sign_out_all"), icon=verbs.SIGN_OUT,
                danger=False):
            return
        await run.io_bound(library.sign_out_everyone)
        redraw()

    return lambda: panel.facts(
        ui, entries(rows, mine, sign_out, sign_out_all, bind, bool(held.get("https")))
        + authenticator_panel.page_parts(library, redraw, app)
        + token_panel.page_parts(library, redraw, made)
        + encrypted_panel.page_parts(library, redraw, held))


_SIGN_OUT_HERE = ("async () => { await fetch('/api/v1/auth/sign_out', "
                  "{method: 'POST', credentials: 'same-origin'}); location.replace('/signin'); }")


def sign_out_here(labels: list) -> None:
    """The nav's own Sign Out, drawn only for a browser another device signed in. This
    device is never signed in, so it has nothing to sign out of."""
    if not this_session_id():
        return
    with ui.row().classes("items-center justify-center gap-2 w-full no-wrap "
                          "console-invite").on("click", js_handler=_SIGN_OUT_HERE):
        ui.icon(verbs.SIGN_OUT).classes("shrink-0")
        labels.append(ui.label(t("console.security.sign_out")).classes("text-xs"))
