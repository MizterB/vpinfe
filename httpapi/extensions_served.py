"""The routes core mounts for what an extension declared through `ctx.ui`.

One router per extension, built at startup for every extension that has a manifest, so a
switched-off one keeps its paths and refuses on them. A route looks the extension up when
it is asked, so what answers is whatever the extension registered last. The work is in
`common.extensions.serving`; this module carries it over HTTP and words the refusals.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Response

from common import extensions
from common.extensions import serving
from common.extensions.host import Record
from common.i18n import t

from . import models, scopes
from .auth import requires
from .errors import CODE_UPSTREAM_UNAVAILABLE, ApiError, InvalidRequestError, NotFoundError


def _envelope(exc: serving.ExtensionError) -> ApiError:
    """What an extension's failure looks like to the caller: an unreachable service is the
    upstream's, anything else is the request's, with the setting it belongs under."""
    if exc.unreachable:
        return ApiError(CODE_UPSTREAM_UNAVAILABLE, exc.message, status_code=502)
    return InvalidRequestError(exc.message,
                               details={"field": exc.field} if exc.field else None)


def router(name: str, running: Any) -> APIRouter:
    """The routes for extension `name`, each behind `running` and its read or write scope."""
    read, write = (scopes.extension_scope(name, "read"),
                   scopes.extension_scope(name, "write"))
    found = APIRouter(tags=["extensions"])

    def record() -> Record:
        one = extensions.registry().get(name)
        if one is None:
            raise NotFoundError(t("error.extensions.not_found", name=name))
        return one

    def ask(call: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        try:
            return call(record(), *args, **kwargs)
        except serving.ExtensionError as exc:
            raise _envelope(exc) from exc

    def get(path: str, summary: str) -> Callable[[Callable[..., Any]], Any]:
        return found.get(path, summary=summary, dependencies=[running, requires(read)])

    def post(path: str, summary: str) -> Callable[[Callable[..., Any]], Any]:
        return found.post(path, summary=summary, dependencies=[running, requires(write)])

    # -- settings ------------------------------------------------------------------

    @get("/settings", "The settings the extension declared, with their values")
    def get_settings() -> dict:
        return ask(serving.settings_read)

    @found.put("/settings", summary="Change settings the extension declared",
               dependencies=[running, requires(write)])
    def put_settings(body: models.ExtensionValues) -> dict:
        return ask(serving.settings_write, body.values)

    # -- lists ---------------------------------------------------------------------

    @get("/lists/{key}", "The rows of a list the extension declared")
    def get_list(key: str) -> dict:
        return ask(serving.list_rows, key)

    @get("/lists/{key}/about", "How a list stands, and what it offers to do")
    def get_list_about(key: str) -> dict:
        return ask(serving.list_about, key)

    @post("/lists/{key}/about/acts/{act}", "Do one of a list's acts")
    def post_list_act(key: str, act: str) -> dict:
        return ask(serving.list_act, key, act)

    # -- dialogs -------------------------------------------------------------------

    @get("/actions/{key}", "The step of a dialog the extension declared")
    def get_action(key: str, step: str = "") -> dict:
        return ask(serving.dialog_ask, key, step)

    @post("/actions/{key}/check", "Check a dialog's values")
    def post_action_check(key: str, body: models.ExtensionStep) -> dict:
        return ask(serving.dialog_check, key, body.values, body.step)

    @post("/actions/{key}/act", "Press one of a dialog's own buttons")
    def post_action_act(key: str, body: models.ExtensionAct) -> dict:
        return ask(serving.dialog_act, key, body.act, body.values, body.step)

    @post("/actions/{key}/run", "Run what a dialog asked for")
    def post_action_run(key: str, body: models.ExtensionStep, response: Response) -> dict:
        answer = ask(serving.dialog_run, key, body.values, body.step)
        if answer.get("job_id"):
            response.status_code = 202
        return answer

    @get("/actions/{key}/progress", "How far a dialog's run has got")
    def get_action_progress(key: str) -> dict:
        return ask(serving.dialog_progress, key)

    @post("/jobs/{kind}/stop", "Ask a running job of the extension to stop")
    def post_job_stop(kind: str) -> dict:
        return ask(serving.job_stop, kind)

    # -- accounts ------------------------------------------------------------------

    @get("/accounts/{player_id}", "A player's account with the extension's service")
    def get_account(player_id: str) -> dict:
        return ask(serving.account_read, player_id)

    @found.put("/accounts/{player_id}", summary="Change a player's account",
               dependencies=[running, requires(write)])
    def put_account(player_id: str, body: models.ExtensionValues) -> dict:
        return ask(serving.account_write, player_id, body.values)

    @post("/accounts/{player_id}/acts/{act}", "Do one of an account's acts")
    def post_account_act(player_id: str, act: str) -> dict:
        return ask(serving.account_act, player_id, act)

    @get("/accounts/{player_id}/card", "A player's card, to share")
    def get_account_card(player_id: str) -> dict:
        return ask(serving.account_card, player_id)

    @post("/accounts/cards", "Read a card a player pasted")
    def post_account_cards(body: models.ExtensionCard) -> dict:
        return ask(serving.account_read_card, body.card)

    @get("/available", "Whether a name is free to take")
    def get_available(candidate: str = "") -> dict:
        return ask(serving.account_available, candidate)

    return found
