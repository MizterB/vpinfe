"""The authorization boundary: identity in, declared scope enforced.

Who a request is comes from `SignInPolicy`. See docs/http-api.md.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.routing import APIRoute
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import HTTPConnection
from starlette.responses import Response
from starlette.routing import BaseRoute

from common import extensions, sign_in
from common.extensions import reach
from common.host import this_machine
from common.i18n import t

from . import scopes
from .errors import CODE_FORBIDDEN, ApiError

logger = logging.getLogger("vpinfe.httpapi.auth")

_SCOPE_ATTR = "__vpinfe_scope__"

COOKIE = "vpinfe_session"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


# Where a caller reached us from, recorded so a policy has the fact to hand.
LOCAL = "local"
NETWORK = "network"


@dataclass(frozen=True)
class Identity:
    name: str
    scopes: frozenset[str]
    # Defaults to the cautious answer: an identity that forgets to say must not
    # silently claim to be on the machine.
    origin: str = NETWORK
    # The sign-in a browser's cookie opened, when it was one.
    session_id: str = ""
    kind: str = ""

    def can(self, scope: str) -> bool:
        return scope in self.scopes

    @property
    def is_local(self) -> bool:
        return self.origin == LOCAL


def caller_is_local(request: HTTPConnection) -> bool:
    """Whether the request is this machine's own: its socket, a name it answers to, no
    forwarding header, and a page of VPinFE's own when a browser sent it. No client at all
    is an in-process call rather than a socket, so there is no remote party to be cautious
    about.
    """
    client = getattr(request, "client", None)
    if client is None or not getattr(client, "host", None):
        return True
    return this_machine.request_is_this_machine(client.host, request.headers)


def session_for(request: HTTPConnection) -> sign_in.Session | None:
    """The sign-in the request's cookie opens. A write the browser says another site began
    does not count, so a page of someone else's cannot act with a cookie it never held."""
    token = request.cookies.get(COOKIE, "")
    if not token:
        return None
    if (getattr(request, "method", "GET") not in SAFE_METHODS
            and request.headers.get("sec-fetch-site", "").lower() == "cross-site"):
        return None
    return sign_in.instance().lookup(token)


class SignInPolicy:
    """This machine is trusted; another computer is trusted once a code shown on this
    machine has signed its browser in. Anyone else may only ask what this instance is.

    `origin` records where the caller came from: a caller binds every interface by default,
    so "local" and "reachable" have never been the same question.
    """

    name = "sign-in"

    def identify(self, request: Request) -> Identity:
        everything = scopes.CORE | granted_extension_scopes()
        if caller_is_local(request):
            return Identity(name="local", scopes=everything, origin=LOCAL)
        session = session_for(request)
        if session is not None:
            return Identity(name=session.kind, scopes=everything, origin=NETWORK,
                            session_id=session.id, kind=session.kind)
        return Identity(name="network", scopes=frozenset({scopes.INSTANCE_READ}),
                        origin=NETWORK)


def granted_extension_scopes() -> frozenset[str]:
    """The `ext:` scopes an extension that is running has put on its own routes.

    Read per request, not held: disabling an extension takes its scopes with it, which
    is how the kill switch reaches a route that is already mounted.
    """
    return extensions.granted_scopes()


_policy: SignInPolicy = SignInPolicy()


def current_policy() -> SignInPolicy:
    return _policy


def set_policy(policy: SignInPolicy) -> None:
    """Swap the policy. For tests, and for whenever the deployment stops being local."""
    global _policy
    _policy = policy


class ScopeMiddleware(BaseHTTPMiddleware):
    """Stamps the caller's identity on every request into the API."""

    async def dispatch(self, request: Request,
                       call_next: RequestResponseEndpoint) -> Response:
        identity = _policy.identify(request)
        request.state.identity = identity
        # What an extension may change reads the tier off the request, so it is set around
        # everything the request runs, and ends with it.
        client = getattr(request, "client", None)
        origin = "this computer" if identity.is_local else str(getattr(client, "host", ""))
        with reach.marking(reach.PROTECTED if identity.is_local else reach.LIBRARY, origin):
            return await call_next(request)


class ForbiddenError(ApiError):
    def __init__(self, message: str = "", *,
                 details: dict[str, Any] | None = None) -> None:
        message = message or t("error.envelope.forbidden")
        super().__init__(CODE_FORBIDDEN, message, status_code=403, details=details)


def requires(scope: str) -> Any:
    """Declare the scope a route needs.

    Any because that is what it returns: FastAPI declares `Depends(...) -> Any` so a
    dependency can stand in for the value it resolves to. Narrowing it here would be
    a claim the framework does not make.

    Fails closed: if the identity is missing the boundary did not run, and the answer
    is no rather than a guess.
    """
    if not scopes.is_known(scope):
        raise ValueError(f"Unknown scope: {scope}")

    async def _check(request: Request) -> None:
        identity = getattr(request.state, "identity", None)
        if identity is None:
            logger.error("No identity on %s - the scope middleware did not run",
                         request.url.path)
            raise ForbiddenError(t("error.auth.unavailable"))
        if not identity.can(scope):
            raise ForbiddenError(t("error.auth.needs_scope", scope=scope))

    setattr(_check, _SCOPE_ATTR, scope)
    return Depends(_check)


def route_scope(route: APIRoute) -> str | None:
    """The scope a route declares, or None."""
    for dependency in route.dependencies:
        call = getattr(dependency, "dependency", None)
        scope = getattr(call, _SCOPE_ATTR, None)
        if scope is not None:
            return scope
    return None


def iter_api_routes(app: FastAPI) -> Iterator[tuple[str, APIRoute]]:
    """Every route on the app, including those inside included routers.

    FastAPI does not flatten an included router into app.routes, so a plain walk
    misses everything mounted through include_router - which is nearly all of it.
    """
    def walk(routes: Sequence[BaseRoute],
             prefix: str = "") -> Iterator[tuple[str, APIRoute]]:
        for route in routes:
            if isinstance(route, APIRoute):
                yield prefix + route.path, route
            elif type(route).__name__ == "_IncludedRouter":
                original = getattr(route, "original_router", None)
                context = getattr(route, "include_context", None)
                inner = getattr(context, "prefix", "") if context is not None else ""
                if original is not None:
                    yield from walk(original.routes, prefix + (inner or ""))

    yield from walk(app.routes)


def assert_every_route_declares_a_scope(app: FastAPI) -> None:
    """Refuse to start with an unguarded route.

    The boundary is only un-bypassable if forgetting to use it is impossible, and the
    cheapest way to make it impossible is to not start.
    """
    missing = [
        f"{','.join(sorted(route.methods or ()))} {path}"
        for path, route in iter_api_routes(app)
        if route_scope(route) is None
    ]
    if missing:
        raise RuntimeError(
            "These API routes declare no scope: " + "; ".join(sorted(missing))
            + ". Add requires(<scope>) to each."
        )
