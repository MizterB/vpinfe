"""Binds the lifecycle vocabulary to the things that actually start and stop.

Every stop and restart of this process ends the same way: `run_frontend_loop` returns and
`main.py` runs `shutdown_services`. Reaching for the browser directly skips it, so those
performers only ever make that loop return.

Two stops are the exception and leave the loop alone. Stopping the frontend closes its
windows and VPinFE keeps running; starting or restarting it opens them again. Stopping a
table is the other: the table is a child of this install rather than a part of it, and
closing one leaves VPinFE and its windows up.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from common import events
from common.config_access import cfg_bool
from common.config_store import ConfigStore
from common.host import launch_state, system_actions
from common.runtime import lifecycle

if TYPE_CHECKING:
    from frontend.chromium_manager import ChromiumManager
    from frontend.device_channel import DeviceChannel

logger = logging.getLogger("vpinfe.frontend.lifecycle_host")

_config_store = None
_bridge = None


def confirm_scopes() -> tuple[str, ...]:
    """What asks first: quitting VPinFE and powering off the machine, or nothing.

    Stopping the frontend is not in it. The windows reopen from the Manager, so there
    is nothing to lose and it is the scope you would meet most often - a prompt there is
    the one that trains you to dismiss prompts.
    """
    if _config_store is None or not cfg_bool(_config_store, "behavior", "confirm"):
        return ()
    return (lifecycle.VPINFE, lifecycle.SYSTEM)


def wants_confirmation(scope: str) -> bool:
    """Whether a surface should put the question to the user before asking us. The
    bridge to a window is one-way, so the browser asks and reports the answer."""
    return scope in confirm_scopes()


def _announce(request: lifecycle.Request) -> None:
    events.emit(
        events.LIFECYCLE_ACTING,
        scope=request.scope,
        action=request.action,
        surface=request.origin.surface,
        address=request.origin.address,
        reason=request.reason,
        # The card asks a person, so it takes the label rather than the log's
        # English. `describe()` stays what the log lines use.
        description=lifecycle.label(*request.pair),
    )


def _notice(*, scope: str, action: str, surface: str, address: str,
            description: str, **_payload: Any) -> None:
    """Tell the windows what is happening, unless they are the ones who asked.

    The rule is a notice on every listening surface that did not start it. The window
    that did already has the answer on screen, so telling it again would talk over its
    own confirmation.
    """
    if _bridge is None:
        return
    message = {"type": "LifecycleActing", "scope": scope, "action": action,
               "description": description, "origin": surface}
    if surface == lifecycle.SURFACE_FRONTEND and address:
        _bridge.send_event_all(message, exclude=address)
    else:
        _bridge.send_event_all(message)


def install(*, config_store: ConfigStore,
            frontend_browser: ChromiumManager, shutdown_event: threading.Event,
            ws_bridge: DeviceChannel | None = None,
            open_windows: Callable[[], None] | None = None,
            close_windows: Callable[[], None] | None = None) -> None:
    """Wire this process's performers. Called once, from startup."""
    global _config_store, _bridge
    _config_store = config_store
    _bridge = ws_bridge
    # Unsubscribe first: install is called once at startup, but subscribing twice would
    # send every window two copies of the same notice.
    events.unsubscribe(events.LIFECYCLE_ACTING, _notice)
    if ws_bridge is not None:
        events.subscribe(events.LIFECYCLE_ACTING, _notice)

    def stop_app(_request: lifecycle.Request) -> None:
        # Both: the event ends the run, and the windows are taken down with it unless
        # Setup's wait, which blocks on the browser, is the one still running.
        shutdown_event.set()
        frontend_browser.terminate_all()

    def restart_app(_request: lifecycle.Request) -> None:
        # main.py checks for this after the services are down, so the request has to be
        # recorded before anything unblocks the loop.
        system_actions.request_app_restart()
        stop_app(_request)

    def stop_system(request: lifecycle.Request) -> None:
        system_actions.shutdown_system()
        stop_app(request)

    def restart_system(request: lifecycle.Request) -> None:
        system_actions.reboot_system()
        stop_app(request)

    def stop_table(_request: lifecycle.Request) -> None:
        launch_state.stop()

    lifecycle.register_performer(lifecycle.VPINFE, lifecycle.STOP, stop_app)
    lifecycle.register_performer(lifecycle.VPINFE, lifecycle.RESTART, restart_app)
    lifecycle.register_performer(lifecycle.SYSTEM, lifecycle.STOP, stop_system)
    lifecycle.register_performer(lifecycle.SYSTEM, lifecycle.RESTART, restart_system)
    lifecycle.register_performer(lifecycle.TABLE, lifecycle.STOP, stop_table)

    # Only registered when the caller owns windows to open and close: a headless instance
    # has none, and reports "nothing performs this" rather than offering buttons that do
    # nothing. Opening is also what restarting is - it closes whatever is up first - so
    # one performer serves both. Closing is the caller's, never terminate_all, which
    # would end the run.
    if open_windows is not None and close_windows is not None:
        lifecycle.register_performer(lifecycle.FRONTEND, lifecycle.STOP,
                                     lambda _request: close_windows())
        lifecycle.register_performer(lifecycle.FRONTEND, lifecycle.START,
                                     lambda _request: open_windows())
        lifecycle.register_performer(lifecycle.FRONTEND, lifecycle.RESTART,
                                     lambda _request: open_windows())

    lifecycle.register_notifier(_announce)


def request(scope: str, action: str, *, origin: lifecycle.Origin, reason: str = "",
            already_confirmed: bool = False) -> bool:
    """Make a request under this process's configured confirm policy.

    `already_confirmed` satisfies the policy rather than bypassing it: a surface that
    does not ask still gets asked.
    """
    scopes = () if already_confirmed else confirm_scopes()
    return lifecycle.request(scope, action, origin=origin,
                             confirm_scopes=scopes, reason=reason)
