"""What this install can be told to do to itself.

`common/lifecycle.py` owns which pairs exist, what each is called and what performs them,
so this serves that rather than restating it - a pair added there appears here without
this file being touched.

What the vocabulary allows is fixed by the build; what is wired up depends on the install,
and a headless one owns no frontend windows. A button that reports success while nothing
happened is worse than one that is not offered, so only what this install performs is
listed.
"""

from __future__ import annotations

import logging

from common import device_client, lifecycle, service_errors
from common.host import play_service
from common.i18n import t

logger = logging.getLogger("vpinfe.common.host.action_ops")

# The ones that take the answer with them. A process that is stopping cannot report
# whether it stopped, so a caller hands these to a background task and answers first.
GOES_AWAY = frozenset({
    (lifecycle.VPINFE, lifecycle.STOP), (lifecycle.VPINFE, lifecycle.RESTART),
    (lifecycle.SYSTEM, lifecycle.STOP), (lifecycle.SYSTEM, lifecycle.RESTART),
})

# Why a request for an action nothing performs is refused. Older installs also sent it
# as the reason on a listed entry, which is why a client drops entries carrying it.
NOT_WIRED = "error.actions.nothing_performs_that"


def _describe(scope: str, action: str) -> dict:
    # `available` and `reason` stay on the wire for an action that can run but not now.
    # Nothing is in that state today, so every entry is available.
    return {"scope": scope, "action": action,
            "label": lifecycle.label(scope, action),
            "label_key": f"action.{scope}.{action}",
            "available": True, "reason": "", "reason_key": ""}


def listing() -> dict:
    """Only the pairs this install performs. One it can never perform is not offered; one
    that can run but not now would stay, with `available` false and its reason."""
    found = [_describe(scope, action) for scope, action in lifecycle.offered()
             if lifecycle.performable(scope, action)]
    return {"count": len(found), "actions": found}


def check(scope: str, action: str) -> tuple[str, str]:
    """The pair as the vocabulary spells it, or a refusal. Nothing is performed."""
    scope, action = scope.strip().lower(), action.strip().lower()
    if (scope, action) not in lifecycle.offered():
        raise service_errors.RefusedError(
            t("error.actions.not_something_vpinfe_does", action=(action), scope=(scope)))
    if not lifecycle.performable(scope, action):
        raise service_errors.UnavailableError(
            t(NOT_WIRED), details={"scope": scope, "action": action})
    return scope, action


def perform(scope: str, action: str, reason: str) -> bool:
    """Do one of them, through the same path every other surface takes."""
    # Closing a table goes through the play service rather than straight to the lifecycle
    # scope. That one checks whether a table is running first, so asking to close one when
    # none is reports honestly instead of reporting that it closed one.
    if (scope, action) == (lifecycle.TABLE, lifecycle.STOP):
        return bool(play_service.stop_playing(reason)["stopped"])
    return device_client.local().request(
        scope, action, origin=lifecycle.Origin(lifecycle.SURFACE_API), reason=reason)
