"""The routes core mounts for what an extension declared through `ctx.ui`.

One router per extension, built at startup for every extension that has a manifest, so a
switched-off one keeps its paths and refuses on them. A route looks the extension up when
it is asked, so what answers is whatever the extension registered last. The work is in
`common.extensions.serving`; this module carries it over HTTP and words the refusals.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Request, Response

from common import extensions
from common.extensions import serving
from common.extensions.host import Record
from common.games import game_lens, table_ops
from common.i18n import t

from . import models, responses, scopes
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

    @post("/lists/{key}/verbs/{verb}", "Press one of a list's verbs on some of its rows")
    def post_list_verb(key: str, verb: str, body: models.ExtensionVerb) -> dict:
        return ask(serving.list_verb, key, verb, body.ids)

    @get("/lists/{key}/detail/{row_id:path}", "What the pane beside a list shows for a row")
    def get_list_detail(key: str, row_id: str) -> dict:
        return ask(serving.list_detail, key, row_id)

    @found.put("/lists/{key}/detail/{row_id:path}", summary="Change fields in a row's pane",
               dependencies=[running, requires(write)])
    def put_list_detail(key: str, row_id: str, body: models.ExtensionValues) -> dict:
        return ask(serving.list_save, key, row_id, body.values)

    @found.get("/pictures/{picture_id}", summary="A picture one of the extension's rows named",
               dependencies=[running, requires(read)])
    def get_picture(picture_id: str, request: Request) -> Response:
        return responses.media_file(ask(serving.picture, picture_id), request, "")

    # -- pages ---------------------------------------------------------------------

    @get("/pages/{key}", "What a page the extension declared shows")
    def get_page(key: str) -> dict:
        return ask(serving.page_read, key)

    @found.put("/pages/{key}", summary="Change fields on a page",
               dependencies=[running, requires(write)])
    def put_page(key: str, body: models.ExtensionValues) -> dict:
        return ask(serving.page_save, key, body.values)

    @get("/pages/{key}/about", "What a page offers to do")
    def get_page_about(key: str) -> dict:
        return ask(serving.page_about, key)

    @post("/pages/{key}/about/acts/{act}", "Do one of a page's acts")
    def post_page_act(key: str, act: str) -> dict:
        return ask(serving.page_act, key, act)

    # -- panel groups --------------------------------------------------------------

    def subject(game_id: str, table_id: str = "") -> dict:
        """Who a group is asked about, built here so an extension is told only the ids it
        can use. A Private game is `{}`: asking would tell the extension the library holds
        it."""
        game = game_lens.resource_of(game_id)
        if game["private"]:
            return {}
        who = {"game_id": game_id, "vps_id": game["vps_id"], "name": game["name"]}
        if not table_id:
            return who
        row = table_ops.row_or_refuse(game_lens.game_or_refuse(game_id), table_id)
        source = row.get("source") or {}
        return {**who, "table_id": table_id, "vps_file_id": str(source.get("vps_file_id") or ""),
                "version": str(row.get("version") or "")}

    def _asked(game_id: str, kind: str, table_id: str = "") -> dict:
        who = subject(game_id, table_id)
        if not who:
            raise NotFoundError(t("error.extensions.no_group", display=name, subject=kind))
        return who

    def group_read(kind: str, game_id: str, table_id: str = "") -> dict:
        who = subject(game_id, table_id)
        if not who:
            return {"title": "", "section": None, "acts": []}
        return ask(serving.group_read, kind, who)

    @get("/groups/game/{game_id}", "What the extension says on a game's panel")
    def get_game_group(game_id: str) -> dict:
        return group_read("game", game_id)

    @found.put("/groups/game/{game_id}", summary="Change fields in the group on a game's panel",
               dependencies=[running, requires(write)])
    def put_game_group(game_id: str, body: models.ExtensionValues) -> dict:
        who = subject(game_id)
        if not who:
            raise NotFoundError(t("error.extensions.no_group", display=name, subject="game"))
        return ask(serving.group_save, "game", who, body.values)

    @post("/groups/game/{game_id}/acts/{act}", "Do one of a game group's acts")
    def post_game_group_act(game_id: str, act: str) -> dict:
        return ask(serving.group_act, "game", _asked(game_id, "game"), act)

    @post("/groups/table/{game_id}/{table_id}/acts/{act}", "Do one of a table group's acts")
    def post_table_group_act(game_id: str, table_id: str, act: str) -> dict:
        return ask(serving.group_act, "table", _asked(game_id, "table", table_id), act)

    @get("/groups/table/{game_id}/{table_id}", "What the extension says on a table's panel")
    def get_table_group(game_id: str, table_id: str) -> dict:
        return group_read("table", game_id, table_id)

    @found.put("/groups/table/{game_id}/{table_id}",
               summary="Change fields in the group on a table's panel",
               dependencies=[running, requires(write)])
    def put_table_group(game_id: str, table_id: str, body: models.ExtensionValues) -> dict:
        who = subject(game_id, table_id)
        if not who:
            raise NotFoundError(t("error.extensions.no_group", display=name, subject="table"))
        return ask(serving.group_save, "table", who, body.values)

    # -- dialogs -------------------------------------------------------------------

    @get("/actions/{key}", "The step of a dialog the extension declared")
    def get_action(key: str, step: str = "") -> dict:
        return ask(serving.dialog_ask, key, step)

    @found.post("/actions/{key}/ask", summary="The step of a dialog opened over some rows",
                dependencies=[running, requires(read)])
    def post_action_ask(key: str, body: models.ExtensionAsk) -> dict:
        return ask(serving.dialog_ask, key, body.step, body.rows)

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
