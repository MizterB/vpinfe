"""Encrypted Connections on Settings > Security: the two lists and the certificate.

Each edit is Protected, so the Console only calls and its boundary asks for the Confirm.
What an entry means is explained by the lines under it; the page carries no logic of its own.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from nicegui import run, ui

from common.failures import why
from common.host import this_machine
from common.i18n import t
from common.install_identity import display_name
from common.paths import get_ini_config
from console import dialog as frame
from console import folder_picker, offload, panel, verbs
from console.api import ApiError
from console.data import Library
from console.on_page import on_page

CERTIFICATE_SUFFIXES = (".pem", ".crt", ".cer", ".key")


def _entry(remove: Callable[[str], Any], value: str, hint: str) -> tuple[Any, ...]:
    """One address or range, with the way to take it off the list."""
    def draw() -> None:
        with ui.row().classes("items-center no-wrap gap-2 w-full"):
            ui.label(value).classes("console-fact-value min-w-0 truncate").tooltip(value)
            panel.icon_action(t("console.encrypted.remove_entry", address=value),
                              lambda: remove(value), icon=verbs.REMOVE, hint=hint)()

    return (panel.FULL, draw)


def _certificate_rows(held: dict[str, Any], choose: Callable[[], Any],
                      clear: Callable[[], Any]) -> list[tuple[Any, ...]]:
    certfile, keyfile = str(held.get("certfile") or ""), str(held.get("keyfile") or "")
    out: list[tuple[Any, ...]] = [(panel.HEADING, t("console.encrypted.https"))]
    if certfile:
        out.append((t("console.encrypted.certificate_file"), panel.path_value(certfile)))
        out.append((t("console.encrypted.key_file"), panel.path_value(keyfile)))
        out.append((panel.FULL, panel.action(t("console.encrypted.certificate_change"), choose,
                                             icon=verbs.CHOOSE,
                                             hint=t("console.encrypted.certificate_hint"))))
        out.append((panel.FULL, panel.action(t("console.encrypted.certificate_clear"), clear,
                                             icon=verbs.CLEAR, danger=True,
                                             hint=t("console.encrypted.certificate_clear_hint"))))
    else:
        out.append(panel.intro(t("console.encrypted.https_none")))
        out.append((panel.FULL, panel.action(t("console.encrypted.certificate_choose"), choose,
                                             icon=verbs.CHOOSE,
                                             hint=t("console.encrypted.certificate_hint"))))
    problem = str(held.get("problem") or "")
    if problem:
        out.append(panel.note(t("console.encrypted.problem"),
                              hint=t(f"console.encrypted.problem_{problem}")))
    elif certfile and not held.get("https"):
        out.append(panel.note(t("console.encrypted.next_start")))
    return out


def entries(held: dict[str, Any], device: str, *, add_proxy: Callable[[], Any],
            remove_proxy: Callable[[str], Any], add_network: Callable[[], Any],
            add_tailscale: Callable[[], Any], remove_network: Callable[[str], Any],
            choose: Callable[[], Any], clear: Callable[[], Any]) -> list[tuple[Any, ...]]:
    """What the section shows, in order.  Pure of the page, so a test reads it."""
    proxies = [str(one) for one in held.get("proxies") or []]
    networks = [str(one) for one in held.get("networks") or []]
    out: list[tuple[Any, ...]] = [(panel.HEADING, t("console.encrypted.heading")),
                                  panel.intro(t("console.encrypted.lead", device=device))]
    out.append((panel.HEADING, t("console.encrypted.proxies")))
    out += [_entry(remove_proxy, address, t("console.encrypted.remove_proxy_hint"))
            for address in proxies] or [panel.intro(t("console.encrypted.proxies_none"))]
    out.append((panel.FULL, panel.action(t("console.encrypted.add_proxy"), add_proxy,
                                         icon=verbs.ADD,
                                         hint=t("console.encrypted.add_proxy_hint"))))
    out.append(panel.note(t("console.encrypted.proxies_line")))
    if not held.get("https") and any(this_machine.peer_is_this_machine(one) for one in proxies):
        out.append(panel.note(t("console.encrypted.proxy_here")))
    out.append((panel.HEADING, t("console.encrypted.networks")))
    out += [_entry(remove_network, text, t("console.encrypted.remove_network_hint"))
            for text in networks] or [panel.intro(t("console.encrypted.networks_none"))]
    out.append((panel.FULL, panel.action(t("console.encrypted.add_network"), add_network,
                                         icon=verbs.ADD,
                                         hint=t("console.encrypted.add_network_hint"))))
    out.append((panel.FULL, panel.action(t("console.encrypted.add_tailscale"), add_tailscale,
                                         icon=verbs.ADD,
                                         hint=t("console.encrypted.add_tailscale_hint"))))
    out.append(panel.note(t("console.encrypted.networks_line")))
    out += _certificate_rows(held, choose, clear)
    return out


async def _ask_entry(title: str, label: str, help_line: str) -> str | None:
    fields: dict[str, Any] = {}

    def keep() -> None:
        text = str(fields["value"].value or "").strip()
        if not text:
            frame.said(fields["value"], t("console.encrypted.needs_address"))
            return
        box.submit(text)

    with frame.opened(title, classes="console-confirm", ignore_outside_click=True) as box:
        panel.facts(ui, [(label, lambda: fields.update(
            value=frame.field(name=label, room=True)))])
        ui.label(help_line).classes("console-help px-3")
        with frame.footer():
            frame.cancel(lambda: box.submit(None))
            go = frame.answer(t("console.encrypted.add"), keep, icon=verbs.ADD)
    frame.enter_presses(go)
    frame.focus(box, fields["value"])
    return await box or None


async def _ask_certificate(library: Library, certfile: str,
                           keyfile: str) -> tuple[str, str] | None:
    async def browse(start: str) -> str | None:
        return await folder_picker.pick_path(library.folders, start, kind="file",
                                             suffixes=CERTIFICATE_SUFFIXES)

    fields: dict[str, Any] = {}

    def keep() -> None:
        cert, key = (str(fields[one].value or "").strip() for one in ("cert", "key"))
        if not cert:
            frame.said(fields["cert"], t("console.encrypted.needs_certificate"))
        if not key:
            frame.said(fields["key"], t("console.encrypted.needs_key"))
        if cert and key:
            box.submit((cert, key))

    with frame.opened(t("console.encrypted.certificate_title"), wide=True,
                      ignore_outside_click=True) as box:
        panel.facts(ui, [
            (t("console.encrypted.certificate_file"),
             lambda: fields.update(cert=frame.field(
                 certfile, browse=browse, name=t("console.encrypted.certificate_file"),
                 room=True))),
            (t("console.encrypted.key_file"),
             lambda: fields.update(key=frame.field(
                 keyfile, browse=browse, name=t("console.encrypted.key_file"), room=True))),
        ])
        ui.label(t("console.encrypted.certificate_hint")).classes("console-help px-3")
        with frame.footer():
            frame.cancel(lambda: box.submit(None))
            go = frame.answer(t("console.encrypted.use_certificate"), keep, icon=verbs.CHOOSE)
    frame.enter_presses(go)
    frame.focus(box, fields["cert"])
    return await box


def page_parts(library: Library, redraw: Callable[[], None],
               held: dict[str, Any]) -> list[tuple[Any, ...]]:
    def failed(exc: ApiError) -> None:
        ui.notify(t("console.encrypted.not_changed"), caption=why(exc), type="negative")

    @on_page
    async def attempt(call: Callable[..., Any], *args: str) -> None:
        try:
            await offload.io(call, *args)
        except ApiError as exc:
            failed(exc)
            return
        redraw()

    @on_page
    async def add_proxy() -> None:
        address = await _ask_entry(t("console.encrypted.add_proxy_title"),
                                   t("console.encrypted.proxy_label"),
                                   t("console.encrypted.add_proxy_help"))
        if address:
            await attempt(library.add_trusted_proxy, address)

    @on_page
    async def add_network() -> None:
        text = await _ask_entry(t("console.encrypted.add_network_title"),
                                t("console.encrypted.network_label"),
                                t("console.encrypted.add_network_help"))
        if text:
            await attempt(library.add_encrypted_network, text)

    @on_page
    async def add_tailscale() -> None:
        await attempt(library.add_tailscale)

    @on_page
    async def remove_proxy(address: str) -> None:
        await run.io_bound(library.remove_trusted_proxy, address)
        redraw()

    @on_page
    async def remove_network(text: str) -> None:
        await run.io_bound(library.remove_encrypted_network, text)
        redraw()

    @on_page
    async def choose() -> None:
        wanted = await _ask_certificate(library, str(held.get("certfile") or ""),
                                        str(held.get("keyfile") or ""))
        if wanted is not None:
            await attempt(library.choose_certificate, *wanted)

    @on_page
    async def clear() -> None:
        await run.io_bound(library.clear_certificate)
        redraw()

    return entries(held, display_name(get_ini_config()),
                   add_proxy=add_proxy, remove_proxy=remove_proxy,
                   add_network=add_network, add_tailscale=add_tailscale,
                   remove_network=remove_network, choose=choose, clear=clear)
