"""A browser asking to sign in, put in front of whoever is at the machine.

`common.sign_in` holds the request and the digits. This sends what it says to the windows
as one `SignInRequest` message, and core draws it on the controller window. `request` is
null once there is nothing to show.

Pushed with `send_event_all`, not the variant that also reaches theme iframes, so the code
goes to the page core runs in and not on into every frame a theme embeds.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from common import sign_in

if TYPE_CHECKING:
    from frontend.device_channel import DeviceChannel

MESSAGE = "SignInRequest"

_bridge: DeviceChannel | None = None
_registered_on: sign_in.SignIn | None = None


def view(request: sign_in.Request | None) -> dict[str, Any] | None:
    """What the screen is given. `code` is empty until Show has been pressed."""
    if request is None:
        return None
    return {"id": request.id, "address": request.address, "state": request.state,
            "code": request.code if request.state == sign_in.SHOWN else "",
            "expires_in": sign_in.instance().seconds_left(request)}


def pending() -> dict[str, Any] | None:
    return view(sign_in.instance().pending())


def show(request_id: str) -> dict[str, Any] | None:
    """Show: the digits, for the screen that pressed it. None when the request has gone."""
    return view(sign_in.instance().reveal(request_id))


def ignore(request_id: str) -> None:
    sign_in.instance().ignore(request_id)


def dismiss(request_id: str) -> None:
    sign_in.instance().dismiss(request_id)


def _push(request: sign_in.Request | None) -> None:
    if _bridge is not None:
        _bridge.send_event_all({"type": MESSAGE, "request": view(request)})


def register(ws_bridge: DeviceChannel) -> None:
    """Attach the windows to the sign-in. Idempotent for one sign-in."""
    global _bridge, _registered_on
    _bridge = ws_bridge
    current = sign_in.instance()
    if _registered_on is current:
        return
    current.on_request(_push)
    _registered_on = current


def reset_for_tests() -> None:
    """Forget the bridge. The listener stays on its sign-in, which a test replaces with
    `sign_in.use`, and does nothing without a bridge."""
    global _bridge, _registered_on
    _bridge = None
    _registered_on = None
