"""Signing a browser in: ask for a code, type it, and manage who is signed in.

The code itself is shown on this computer and never answered here. See common/sign_in.py.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request, Response

from common import access_keys, paths, sign_in
from common import api_tokens as tokens
from common.host import this_machine
from common.i18n import t
from common.install_identity import display_name

from . import scopes
from .auth import COOKIE, caller_is_local, caller_session, requires, session_for
from .errors import CODE_FORBIDDEN, CODE_TOO_MANY_REQUESTS, ApiError
from .models import (
    ConfirmAsk,
    ConfirmAttempt,
    ConfirmState,
    PairAsk,
    PairAttempt,
    Paired,
    RemoteCodeRenewed,
    SessionInfo,
    SessionList,
    SessionsEnded,
    SignedIn,
    SignInAsk,
    SignInAttempt,
    WhoAmI,
)

router = APIRouter(prefix="/auth", tags=["auth"])

_REFUSALS = {
    sign_in.IGNORED: "error.signin.ignored",
    sign_in.NO_CODE: "error.signin.no_code",
    sign_in.WRONG: "error.signin.wrong",
    sign_in.USED_UP: "error.signin.used_up",
    sign_in.EXPIRED: "error.signin.no_code",
}


def _device() -> str:
    return display_name(paths.get_ini_config())


def _refusal(error: sign_in.SignInError) -> ApiError:
    if error.reason == sign_in.TOO_SOON:
        return ApiError(CODE_TOO_MANY_REQUESTS,
                        t("error.signin.too_soon", seconds=error.wait),
                        status_code=429, details={"reason": error.reason, "wait": error.wait})
    return ApiError(CODE_FORBIDDEN, t(_REFUSALS[error.reason], device=_device()),
                    status_code=403, details={"reason": error.reason})


def _address(request: Request) -> str:
    client = request.client
    return this_machine.normalized(client.host) if client and client.host else ""


def _same_site(request: Request) -> None:
    if request.headers.get("sec-fetch-site", "").lower() == this_machine.CROSS_SITE:
        raise ApiError(CODE_FORBIDDEN, t("error.signin.cross_site"), status_code=403)


def _asked(address: str) -> SignInAsk:
    signer = sign_in.instance()
    try:
        made = signer.ask(address)
    except sign_in.SignInError as error:
        raise _refusal(error) from error
    return SignInAsk(request_id=made.id, expires_in=signer.seconds_left(made),
                     can_ask_again_in=max(0, int(signer.next_ask_in())))


def _verified(attempt: SignInAttempt, request: Request) -> str:
    try:
        token, _ = sign_in.instance().verify(
            attempt.request_id, attempt.code, address=_address(request),
            agent=sign_in.describe_agent(request.headers.get("user-agent", "")))
    except sign_in.SignInError as error:
        raise _refusal(error) from error
    return token


@router.post("/code", summary="Ask for a sign-in code", response_model=SignInAsk,
             dependencies=[requires(scopes.INSTANCE_READ), Depends(_same_site)])
def ask(request: Request) -> SignInAsk:
    """Makes a request this computer shows as "{address} wants to sign in". The digits appear
    only after someone here chooses Show, so this answer holds none."""
    return _asked(_address(request))


@router.post("/session", summary="Sign in with the code this computer showed",
             response_model=SignedIn,
             dependencies=[requires(scopes.INSTANCE_READ), Depends(_same_site)])
def sign_in_with_code(attempt: SignInAttempt, request: Request, response: Response) -> SignedIn:
    token = _verified(attempt, request)
    response.set_cookie(COOKIE, token, max_age=sign_in.SESSION_SECONDS, httponly=True,
                        samesite="lax", secure=request.url.scheme == "https", path="/")
    return SignedIn()


@router.get("/me", summary="Whether this browser is signed in", response_model=WhoAmI,
            dependencies=[requires(scopes.INSTANCE_READ)])
def me(request: Request) -> WhoAmI:
    session = session_for(request)
    return WhoAmI(signed_in=session is not None, local=caller_is_local(request),
                  kind=session.kind if session else "",
                  session_id=session.id if session else "",
                  confirmed=session is not None
                  and sign_in.instance().is_confirmed(session.id))


@router.post("/sign_out", summary="Sign this browser out", response_model=SignedIn,
             dependencies=[requires(scopes.INSTANCE_READ), Depends(_same_site)])
def sign_out(request: Request, response: Response) -> SignedIn:
    """Ends the session this request's cookie opens. Signed out already is still signed out."""
    sign_in.instance().sign_out_token(request.cookies.get(COOKIE, ""))
    response.delete_cookie(COOKIE, path="/")
    return SignedIn(signed_in=False)


@router.get("/sessions", summary="The browsers signed in", response_model=SessionList,
            dependencies=[requires(scopes.ACCESS_READ)])
def sessions(request: Request) -> SessionList:
    current = session_for(request)
    rows: list[dict[str, Any]] = [
        {**vars(one), "current": current is not None and current.id == one.id}
        for one in sign_in.instance().sessions()]
    return SessionList(sessions=[SessionInfo(**row) for row in rows])


@router.delete("/sessions/{session_id}", summary="Sign one browser out",
               response_model=SessionsEnded, dependencies=[requires(scopes.ACCESS_WRITE)])
def end_one(session_id: str) -> SessionsEnded:
    return SessionsEnded(ended=1 if sign_in.instance().sign_out(session_id) else 0)


@router.delete("/sessions", summary="Sign every browser out", response_model=SessionsEnded,
               dependencies=[requires(scopes.ACCESS_WRITE)])
def end_all() -> SessionsEnded:
    return SessionsEnded(ended=sign_in.instance().sign_out_everywhere())


@router.post("/confirm/code", summary="Ask for a Confirm Code", response_model=ConfirmAsk,
             dependencies=[requires(scopes.INSTANCE_READ), Depends(_same_site)])
def ask_confirm(request: Request) -> ConfirmAsk:
    """Draws six digits on this computer's screen. Only a signed-in Owner can ask: this
    computer itself and a token hold no Confirm to ask for."""
    session = caller_session(request)
    if session is None:
        raise ApiError(CODE_FORBIDDEN, t("error.signin.required"), status_code=403)
    try:
        sign_in.instance().confirm_ask(session.id, _address(request))
    except sign_in.SignInError as error:
        raise _refusal(error) from error
    return ConfirmAsk(expires_in=sign_in.CODE_SECONDS)


@router.post("/confirm", summary="Confirm with the code this computer showed",
             response_model=ConfirmState,
             dependencies=[requires(scopes.INSTANCE_READ), Depends(_same_site)])
def confirm(attempt: ConfirmAttempt, request: Request) -> ConfirmState:
    session = caller_session(request)
    if session is None:
        raise ApiError(CODE_FORBIDDEN, t("error.signin.required"), status_code=403)
    try:
        sign_in.instance().confirm_verify(session.id, attempt.code)
    except sign_in.SignInError as error:
        raise _refusal(error) from error
    return ConfirmState(confirmed=True, expires_in=sign_in.instance().confirm_left(session.id))


@router.get("/confirm", summary="Whether the caller holds a Confirm", response_model=ConfirmState,
            dependencies=[requires(scopes.INSTANCE_READ)])
def confirmed(request: Request) -> ConfirmState:
    if caller_is_local(request) and caller_session(request) is None:
        return ConfirmState(confirmed=True, expires_in=sign_in.CONFIRM_SECONDS)
    session = caller_session(request)
    left = sign_in.instance().confirm_left(session.id) if session else 0
    return ConfirmState(confirmed=left > 0, expires_in=left)


@router.post("/pair/code", summary="Ask this install for a pairing code",
             response_model=PairAsk,
             dependencies=[requires(scopes.INSTANCE_READ), Depends(_same_site)])
def ask_pair(request: Request) -> PairAsk:
    """Another install wants to be paired.  The six digits appear on this computer's screen
    and in no answer."""
    try:
        made = sign_in.instance().pair_ask(_address(request))
    except sign_in.SignInError as error:
        raise _refusal(error) from error
    return PairAsk(request_id=made.id, expires_in=sign_in.CODE_SECONDS)


@router.post("/pair", summary="Pair with the code this install showed", response_model=Paired,
             dependencies=[requires(scopes.INSTANCE_READ), Depends(_same_site)])
def pair(attempt: PairAttempt) -> Paired:
    """Exchanges the code read off this screen for a Full Control token, shown here once."""
    try:
        sign_in.instance().pair_verify(attempt.request_id, attempt.code)
    except sign_in.SignInError as error:
        raise _refusal(error) from error
    name = attempt.name.strip() or t("auth.tokens.paired_name")
    secret, _ = tokens.instance().make(name, tokens.FULL)
    return Paired(secret=secret)


@router.post("/remote_code/renew", summary="Make a new Remote Code",
             response_model=RemoteCodeRenewed, dependencies=[requires(scopes.ACCESS_WRITE)])
def renew_remote_code() -> RemoteCodeRenewed:
    """Every phone that came in with the old code is signed out."""
    old_id, _ = access_keys.renew_remote_pass()
    return RemoteCodeRenewed(ended=sign_in.instance().sign_out_via(old_id))
