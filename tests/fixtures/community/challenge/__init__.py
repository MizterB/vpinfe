"""A fixture extension whose Community lists derive tags, and nothing real behind them.

Kept in its own root so the suites that load every extension under `fixtures/extensions`
do not grow two lists they never asked for. Its settings say which ids each list holds,
comma-separated, and whether a read fails, so a test sets up the week it wants.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

COLUMNS = [{"field": "name", "header": "Table"}, {"field": "vps_id", "header": "VPS"}]


def register(ctx) -> None:
    router = APIRouter()

    def rows(setting: str) -> dict:
        if ctx.config.get("fail"):
            raise HTTPException(status_code=503, detail="the fixture was asked to fail")
        held = [one.strip() for one in ctx.config.get(setting).split(",") if one.strip()]
        return {"rows": [{"name": one, "vps_id": one} for one in held]}

    @router.get("/machines")
    def machines() -> dict:
        return rows("machines")

    @router.get("/releases")
    def releases() -> dict:
        return rows("releases")

    ctx.add_router(router, scope=ctx.scope("read"))
    ctx.ui.community("machines", "/machines", title="Machines of the Month",
                     columns=COLUMNS,
                     relation={"field": "vps_id", "keys": "vps_entry"},
                     tag="Machine of the Month")
    ctx.ui.community("releases", "/releases", title="Weekly Challenge", columns=COLUMNS,
                     relation={"field": "vps_id", "keys": "vps_release"},
                     tag="Weekly Challenge")
