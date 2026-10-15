"""Tell every open Manager tab when VPinFE is about to be restarted or stopped.

The restart, quit and power requests themselves go through common.lifecycle by way of the
HTTP API; this is only the announcement that reaches the tabs.
"""

from __future__ import annotations

import logging

from nicegui import Client, ui

from common import events

logger = logging.getLogger("vpinfe.manager.app_control")


def _notice(*, description: str, **_payload: object) -> None:
    """Tell every open tab. A tab with no live socket is skipped: NiceGUI would queue the
    notification for a reload that may never come."""
    for client in list(Client.instances.values()):
        if not client.has_socket_connection:
            continue
        try:
            with client:
                ui.notify(description, type="warning")
        except Exception:
            logger.exception("Could not tell a Manager client about %s", description)


_notices_installed = False


def install_notices() -> None:
    """Subscribe the Manager to lifecycle announcements. Idempotent - subscribing twice
    would show every notice twice."""
    global _notices_installed
    if _notices_installed:
        return
    events.subscribe(events.LIFECYCLE_ACTING, _notice)
    _notices_installed = True
