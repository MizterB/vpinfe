"""A fixture extension whose Community lists derive tags and rank, and nothing real behind
them.

Kept in its own root so the suites that load every extension under `fixtures/extensions`
do not grow lists they never asked for. Its settings say which ids each list holds,
comma-separated, and whether a read fails, so a test sets up the week it wants. The two
ranked lists hold `id=rating` pairs, a rating left empty for one nobody rated.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

COLUMNS = [{"field": "name", "header": "Table"}, {"field": "vps_id", "header": "VPS"}]
RATED = [*COLUMNS, {"field": "rating", "header": "Rating", "kind": "number"}]
TOP = [{"key": "top", "name": "Top Rated", "ranks": True,
        "sort": [{"field": "rating", "desc": True}]}]


def register(ctx) -> None:
    router = APIRouter()

    def said(setting: str) -> list[str]:
        if ctx.config.get("fail"):
            raise HTTPException(status_code=503, detail="the fixture was asked to fail")
        return [one.strip() for one in ctx.config.get(setting).split(",") if one.strip()]

    def rows(setting: str) -> dict:
        return {"rows": [{"name": one, "vps_id": one} for one in said(setting)]}

    def rated(setting: str) -> dict:
        pairs = [one.partition("=") for one in said(setting)]
        return {"rows": [{"name": held, "vps_id": held,
                          "rating": float(rating) if rating else None}
                         for held, _, rating in pairs]}

    @router.get("/machines")
    def machines() -> dict:
        return rows("machines")

    @router.get("/releases")
    def releases() -> dict:
        return rows("releases")

    @router.get("/ratings")
    def ratings() -> dict:
        return rated("ratings")

    @router.get("/builds")
    def builds() -> dict:
        return rated("builds")

    ctx.add_router(router, scope=ctx.scope("read"))
    ctx.ui.community("machines", "/machines", title="Machines of the Month",
                     columns=COLUMNS,
                     relation={"field": "vps_id", "keys": "vps_entry"},
                     tag="Machine of the Month")
    ctx.ui.community("releases", "/releases", title="Weekly Challenge", columns=COLUMNS,
                     relation={"field": "vps_id", "keys": "vps_release"},
                     tag="Weekly Challenge")
    ctx.ui.community("ratings", "/ratings", title="Ratings", columns=RATED, views=TOP,
                     relation={"field": "vps_id", "keys": "vps_entry"})
    ctx.ui.community("builds", "/builds", title="Build Ratings", columns=RATED, views=TOP,
                     relation={"field": "vps_id", "keys": "vps_release"})
