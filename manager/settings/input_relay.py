"""Hearing the buttons and keys VPinFE runs with from a Manager opened on another device.

The browser reads a gamepad and a keyboard only on its own device, so a binding table
opened elsewhere cannot hear the ones VPinFE runs with. While one of its rows listens it
asks, over `common.events`, for the frontend's controller window to report them, and passes
each one to the page's own listener. The Manager does not import the frontend: the bus is
the only thing between them.
"""

from __future__ import annotations

import asyncio
import json
import logging

from nicegui import Client

from common import events
from common.host import frontend_state

logger = logging.getLogger("vpinfe.manager.settings.input_relay")

# How long the frontend keeps the controller for one ask, and how often a listening table
# asks again. A page that is closed or navigated away stops asking, and the cabinet's
# buttons and keys come back on their own after the first.
TTL_MS = 6000
REFRESH_S = 2.0

_listening: dict[str, tuple[Client, asyncio.AbstractEventLoop]] = {}
_hooked: set[str] = set()
_subscribed = False


def frontend_up() -> bool:
    return frontend_state.current().running


def arm(client: Client) -> None:
    """The table on `client` is listening. Called again to keep it so. A page with no
    connection is not asked for: it is asleep or gone, and its table keeps its row listening
    until the page is deleted."""
    if not client.has_socket_connection:
        return
    _subscribe()
    if client.id not in _hooked:
        _hooked.add(client.id)
        client.on_disconnect(lambda: disarm(client))
        client.on_delete(lambda: _forget(client))
    _listening[client.id] = (client, asyncio.get_running_loop())
    events.emit(events.INPUT_CAPTURE_ARMED, armed=True, ttl_ms=TTL_MS)


def disarm(client: Client) -> None:
    if _listening.pop(client.id, None) is not None and not _listening:
        events.emit(events.INPUT_CAPTURE_ARMED, armed=False, ttl_ms=0)


def _forget(client: Client) -> None:
    _hooked.discard(client.id)
    disarm(client)


def _subscribe() -> None:
    global _subscribed
    if not _subscribed:
        events.subscribe(events.INPUT_CAPTURE_PRESS, _pressed)
        _subscribed = True


def _pressed(*, token: str, phase: str, **_payload: object) -> None:
    """A button or key on the cabinet. Runs on whichever thread the frontend's call arrived on."""
    code = f"window.__bindingListen && window.__bindingListen.relay({json.dumps(token)}, " \
           f"{'true' if phase == 'down' else 'false'})"
    for client, loop in list(_listening.values()):
        loop.call_soon_threadsafe(_push, client, code)


def _push(client: Client, code: str) -> None:
    if client.is_deleted:
        _forget(client)
        return
    try:
        client.run_javascript(code)
    except Exception:
        logger.exception("Could not pass a controller button to a Manager page")


def reset_for_tests() -> None:
    global _subscribed
    _listening.clear()
    _hooked.clear()
    _subscribed = False
