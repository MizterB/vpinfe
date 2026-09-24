"""What VPinPlay is configured with, offered in the shape core renders.

The fields are declared and core draws them, so an extension's settings look like every
other setting in the Console. Values live in this extension's own store, which is the
only place a change reaches: core does not read its `[vpinplay]` section, and a write
there is lost without saying so.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

ENDPOINT_KEY = "endpoint"
USER_KEY = "user_id"
INITIALS_KEY = "initials"
MACHINE_KEY = "machine_id"
SYNC_ON_EXIT_KEY = "sync_on_exit"


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


def fields(ctx: Any, default_endpoint: str) -> list[dict]:
    """Every setting, with what it is set to now."""
    held = ctx.config.all() if hasattr(ctx.config, "all") else {}
    return [
        {"key": ENDPOINT_KEY, "label": ctx.t("settings.endpoint.label"), "type": "string",
         "value": str(held.get(ENDPOINT_KEY) or ""), "placeholder": default_endpoint,
         "help": ctx.t("settings.endpoint.help", default=default_endpoint)},
        {"key": USER_KEY, "label": ctx.t("settings.user_id.label"), "type": "string",
         "value": str(held.get(USER_KEY) or ""), "help": ctx.t("settings.user_id.help")},
        {"key": INITIALS_KEY, "label": ctx.t("settings.initials.label"), "type": "string",
         "value": str(held.get(INITIALS_KEY) or ""),
         "help": ctx.t("settings.initials.help")},
        {"key": MACHINE_KEY, "label": ctx.t("settings.machine_id.label"), "type": "string",
         "value": str(held.get(MACHINE_KEY) or ""),
         "help": ctx.t("settings.machine_id.help")},
        {"key": SYNC_ON_EXIT_KEY, "label": ctx.t("settings.sync_on_exit.label"),
         "type": "switch", "value": _truthy(held.get(SYNC_ON_EXIT_KEY)),
         "help": ctx.t("settings.sync_on_exit.help")},
    ]


def routers(ctx: Any, default_endpoint: str) -> tuple[APIRouter, APIRouter]:
    """Reading and writing, so seeing an account id and changing it are separate
    permissions."""
    reading = APIRouter()
    writing = APIRouter()

    @reading.get("/settings")
    def read_settings() -> dict:
        return {"help": ctx.t("settings.help"), "fields": fields(ctx, default_endpoint)}

    @writing.put("/settings")
    def write_settings(payload: dict) -> dict:
        offered = dict((payload or {}).get("values") or {})
        known = {one["key"] for one in fields(ctx, default_endpoint)}
        for key, value in offered.items():
            if key not in known:
                continue
            ctx.config.set(key, "true" if value is True
                           else "false" if value is False else str(value or ""))
        return {"fields": fields(ctx, default_endpoint)}

    return reading, writing
