"""This device's DOF, the cabinet's lights and solenoids.

Firing an event drives hardware somebody may be standing at, which is what `input:act`
is declared for. It reaches only this install's DOF; a client aimed at another machine
calls that machine's copy of the route.
"""

from __future__ import annotations

from fastapi import APIRouter

from common.host import dof_service
from common.paths import get_ini_config

from . import models, scopes
from .auth import requires

router = APIRouter(prefix="/dof", tags=["dof"])


@router.post("/event", summary="Turn a DOF event on until it is stopped",
             dependencies=[requires(scopes.INPUT_ACT)])
def fire(payload: models.DofEventRequest) -> models.DofEventResult:
    """Turn the event on, firing it again if it is already on."""
    return models.DofEventResult(event=dof_service.turn_on(get_ini_config(), payload.event))


@router.delete("/event", summary="Turn the DOF event off",
               dependencies=[requires(scopes.INPUT_ACT)])
def stop() -> models.DofEventResult:
    """Clear the event now on. Nothing on is not an error."""
    dof_service.clear_active_dof_event(get_ini_config())
    return models.DofEventResult(event=None)
