"""Tell every open Manager tab when VPinFE or the device is about to go away.

The restart, quit and power requests themselves go through common.runtime.lifecycle by way of the
HTTP API; this is only the announcement that reaches the tabs.
"""

from __future__ import annotations

import logging

from nicegui import Client, ui

from common import events
from common.i18n import t
from common.runtime import lifecycle

logger = logging.getLogger("vpinfe.manager.app_control")


def _said(scope: str, action: str) -> str:
    """What is about to happen, for the actions that take the page away. The windows' own
    actions say nothing here: the tab that asked shows the result."""
    pair = (scope, action)
    if pair == (lifecycle.VPINFE, lifecycle.RESTART):
        return t("manager.notice.restarting")
    if pair == (lifecycle.VPINFE, lifecycle.STOP):
        return t("manager.notice.quitting")
    if pair == (lifecycle.SYSTEM, lifecycle.RESTART):
        return t("manager.notice.rebooting")
    if pair == (lifecycle.SYSTEM, lifecycle.STOP):
        return t("manager.notice.powering_off")
    return ""


def _notice(*, scope: str, action: str, **_payload: object) -> None:
    """Tell every open tab. A tab with no live socket is skipped: NiceGUI would queue the
    notification for a reload that may never come."""
    description = _said(scope, action)
    if not description:
        return
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
