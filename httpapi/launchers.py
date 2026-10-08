"""The configured ways this install runs a table, over the wire.

The launchers themselves are the `launchers` list in `/config`: add, replace and remove
are `/config/launchers/{id}`. What stays here is what a list item cannot say - the
refusal a switch-off would get, the app's own settings, the default, and which table
runs on which.

It keeps the config scopes all the same: a token that can already change what program
plays a table should not need a new grant to keep doing it.

`common/games/launcher_ops.py` is what answers.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body

from common.games import launcher_ops

from . import scopes
from .auth import requires

router = APIRouter(prefix="/launchers", tags=["launchers"])


@router.get("", summary="Every launcher this install has",
            dependencies=[requires(scopes.CONFIG_READ)])
def list_launchers() -> dict[str, Any]:
    """The launchers in order, the tables that deviate, and which one is the default."""
    return launcher_ops.listing()


@router.post("/standing", summary="What an app's empty fields would read",
             dependencies=[requires(scopes.CONFIG_READ)])
def launcher_standing(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """For an app and the settings a launcher would hold, what each path field reads
    while left empty. A read: nothing is written, and no launcher need exist."""
    return launcher_ops.standing(str(body.get("app") or ""),
                                 dict(body.get("settings") or {}))


@router.get("/{launcher_id}/fallback", summary="Where its tables go if it is switched off",
            dependencies=[requires(scopes.CONFIG_READ)])
def launcher_fallback(launcher_id: str) -> dict[str, Any]:
    """How many tables it plays, what each group of them would use instead, and the
    refusal a switch-off would get, or ""."""
    return launcher_ops.fallback(launcher_id)


@router.get("/{launcher_id}/config", summary="What the app it runs can be set to",
            dependencies=[requires(scopes.CONFIG_READ)])
def launcher_config(launcher_id: str, table: str = "",
                    scope: str = "launcher") -> dict[str, Any]:
    """The declared groups, and every value as it stands at one scope."""
    return launcher_ops.app_config(launcher_id, table, scope)


@router.put("/{launcher_id}/config", summary="Set values on the app it runs",
            dependencies=[requires(scopes.CONFIG_WRITE)])
def write_launcher_config(launcher_id: str,
                          body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Values at one scope. The app writes them into its own file in place, and names
    under `cleared` the ones it cleared instead, for holding the launcher's own value."""
    return launcher_ops.write_config(launcher_id, body)


@router.post("/{launcher_id}/default", summary="Make it the default for its app",
             dependencies=[requires(scopes.CONFIG_WRITE)])
def make_launcher_default(launcher_id: str) -> dict[str, Any]:
    """The launcher its app's tables use unless they name another. It moves to the front
    of the list, since the default is the first one switched on."""
    return launcher_ops.make_default(launcher_id)


@router.put("/mappings/{table_id}", summary="Point a table at a launcher",
            dependencies=[requires(scopes.CONFIG_WRITE)])
def put_mapping(table_id: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """An empty `launcher_id` clears it, which is how a table goes back to the default."""
    return launcher_ops.assign(table_id, str(body.get("launcher_id") or ""))
