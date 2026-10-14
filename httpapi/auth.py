"""The authorization boundary: identity in, declared scope enforced.

Who a request is comes from `SignInPolicy`. See docs/http-api.md.
"""

from __future__ import annotations

import hmac
import logging
import re
import time
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.routing import APIRoute
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import HTTPConnection
from starlette.responses import Response
from starlette.routing import BaseRoute, compile_path

from common import api_tokens as tokens
from common import extensions, machine_secrets, sign_in
from common.extensions import reach
from common.host import this_machine
from common.i18n import t

from . import scopes
from .errors import CODE_FORBIDDEN, ApiError

logger = logging.getLogger("vpinfe.httpapi.auth")

_SCOPE_ATTR = "__vpinfe_scope__"

COOKIE = "vpinfe_session"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# The Console's own calls to this API are made over loopback for a browser that may be on
# another computer. This header says which sign-in a call is made for, so the API holds it
# to that sign-in's tier. Only a loopback caller holding the machine secret can sign one.
ACTING_HEADER = "x-vpinfe-acting"
ACTING_SECONDS = 60


# Where a caller reached us from, recorded so a policy has the fact to hand.
LOCAL = "local"
NETWORK = "network"

# The reasons a refusal carries in `details`, for a surface to act on rather than parse.
CONFIRM_NEEDED = "confirm_needed"
PROTECTED = "protected"


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
    token_id: str = ""

    def can(self, scope: str) -> bool:
        return scope in self.scopes

    @property
    def is_local(self) -> bool:
        return self.origin == LOCAL

    @property
    def tier(self) -> str:
        """How far this caller reaches: what an extension is told it may change."""
        if self.can(scopes.PROTECTED):
            return reach.PROTECTED
        return reach.LIBRARY if self.can(scopes.CONFIG_WRITE) else reach.PLAY


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


# What a Console page open in a browser that is no longer signed in says it acts for. It names
# no sign-in, so the call is held to a stranger's tier rather than this computer's.
NOBODY = "-"


def sign_acting(session_id: str) -> str:
    """The header value saying a loopback call is made for this sign-in, or for nobody."""
    body = f"{session_id}.{int(time.time()) + ACTING_SECONDS}"
    return f"{body}.{_acting_mac(body)}"


def _acting_mac(body: str) -> str:
    return hmac.new(machine_secrets.session_secret().encode(), body.encode(),
                    "sha256").hexdigest()


def acting_for(request: HTTPConnection) -> str | None:
    """Who a loopback call says it is made for: a sign-in's id, `NOBODY`, or None when it
    says nothing, or says something that does not hold: a header from anywhere but this
    computer, a stale one, one signed with another secret. `identify` tells those two apart."""
    headers = getattr(request, "headers", None)
    value = headers.get(ACTING_HEADER, "") if headers is not None else ""
    if not value or not caller_is_local(request):
        return None
    session_id, _, rest = value.partition(".")
    expires, _, mac = rest.partition(".")
    if not session_id or not expires.isdigit() or int(expires) < time.time():
        return None
    if not hmac.compare_digest(_acting_mac(f"{session_id}.{expires}"), mac):
        return None
    return session_id


def acting_session(request: HTTPConnection) -> sign_in.Session | None:
    """The sign-in a loopback call says it is made for, if that sign-in still exists."""
    claimed = acting_for(request)
    return sign_in.instance().session(claimed) if claimed else None


def caller_session(request: HTTPConnection) -> sign_in.Session | None:
    """The sign-in whose tier this request is held to: the one a Console call says it acts
    for, else the one its own cookie opens."""
    return acting_session(request) or session_for(request)


def bearer_token(request: HTTPConnection) -> str:
    scheme, _, value = request.headers.get("authorization", "").partition(" ")
    return value.strip() if scheme.lower() == "bearer" else ""


class SignInPolicy:
    """This machine is trusted; another computer is trusted once a code shown on this
    machine has signed its browser in, or when it holds a token. Anyone else may only ask what
    this instance is.

    `origin` records where the caller came from: a caller binds every interface by default,
    so "local" and "reachable" have never been the same question.
    """

    name = "sign-in"

    def identify(self, request: Request) -> Identity:
        everything = scopes.CORE | granted_extension_scopes()
        if caller_is_local(request):
            claimed = acting_for(request)
            if claimed is None:
                if (getattr(request, "headers", None) or {}).get(ACTING_HEADER):
                    return self._stranger()
                return Identity(name="local", scopes=everything, origin=LOCAL)
            acting = sign_in.instance().session(claimed)
            return self._signed_in(acting, everything) if acting is not None \
                else self._stranger()
        bearer = bearer_token(request)
        if bearer:
            token = tokens.instance().lookup(bearer)
            return self._holder(token) if token is not None else self._stranger()
        session = session_for(request)
        return self._signed_in(session, everything) if session is not None \
            else self._stranger()

    @staticmethod
    def _stranger() -> Identity:
        return Identity(name="network", scopes=frozenset({scopes.INSTANCE_READ}),
                        origin=NETWORK)

    @staticmethod
    def _signed_in(session: sign_in.Session, everything: frozenset[str]) -> Identity:
        """A Remote pass is Play and nothing more.  An Owner holds everything but the Protected
        tier, which a live Confirm adds."""
        if session.kind != sign_in.OWNER:
            held = scopes.PLAY
        elif sign_in.instance().is_confirmed(session.id):
            held = everything
        else:
            held = everything - scopes.CONFIRMED
        return Identity(name=session.kind, scopes=frozenset(held), origin=NETWORK,
                        session_id=session.id, kind=session.kind)

    @staticmethod
    def _holder(token: tokens.Token) -> Identity:
        if token.access == tokens.PLAY:
            held = scopes.PLAY
        else:
            held = scopes.LIBRARY | granted_extension_scopes()
            if token.can_power:
                held = held | {scopes.SYSTEM_ADMIN}
        return Identity(name=token.name, scopes=frozenset(held), origin=NETWORK,
                        kind="token", token_id=token.id)


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
        with reach.marking(identity.tier, origin):
            return await call_next(request)


class ForbiddenError(ApiError):
    def __init__(self, message: str = "", *,
                 details: dict[str, Any] | None = None) -> None:
        message = message or t("error.envelope.forbidden")
        super().__init__(CODE_FORBIDDEN, message, status_code=403, details=details)


def _refusal(identity: Identity, scope: str) -> ForbiddenError:
    """Why this caller may not have `scope`.  An Owner without a Confirm is told to confirm;
    a token or a Remote pass is told it never can."""
    if scope in scopes.CONFIRMED:
        if identity.kind == sign_in.OWNER:
            return ForbiddenError(t("error.auth.confirm_needed"),
                                  details={"reason": CONFIRM_NEEDED, "scope": scope})
        return ForbiddenError(t("error.auth.protected"),
                              details={"reason": PROTECTED, "scope": scope})
    return ForbiddenError(t("error.auth.needs_scope", scope=scope),
                          details={"reason": "scope", "scope": scope})


def check(identity: Identity | None, scope: str, path: str = "") -> None:
    """Raise unless `identity` holds `scope`.  Using a Protected scope under a live Confirm
    extends the Confirm."""
    if identity is None:
        logger.error("No identity on %s - the scope middleware did not run", path)
        raise ForbiddenError(t("error.auth.unavailable"))
    if not identity.can(scope):
        raise _refusal(identity, scope)
    if scope in scopes.CONFIRMED and identity.session_id:
        sign_in.instance().is_confirmed(identity.session_id, use=True)


def require(request: Request, scope: str) -> None:
    """For a handler whose route is declared at a lower scope but whose body reaches for a
    higher one: a config key that names a command, an action that powers off."""
    check(getattr(request.state, "identity", None), scope, request.url.path)


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
        check(getattr(request.state, "identity", None), scope, request.url.path)

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
    _remember_routes(app)


_known_routes: list[tuple[re.Pattern[str], frozenset[str], str]] = []


def _remember_routes(app: FastAPI) -> None:
    _known_routes[:] = [
        (compile_path(path)[0], frozenset(route.methods or ()), scope)
        for path, route in iter_api_routes(app)
        if (scope := route_scope(route)) is not None
    ]


def request_scope(method: str, path: str) -> str | None:
    """The scope this API demands for `method` on `path` (relative to the API prefix), or
    None for a route it does not know - which a caller holding less than everything must
    treat as refused."""
    for pattern, methods, scope in _known_routes:
        if method.upper() in methods and pattern.match(path):
            return scope
    return None
