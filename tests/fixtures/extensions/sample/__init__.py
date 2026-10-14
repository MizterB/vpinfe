"""A fixture extension that uses the whole contract, and does nothing real with it.

Committed rather than written into a temporary directory by the test that loads it, so
the worked example of an extension is something an author can read - the same reason
`apps/generic` is a file rather than a stub. It reaches VPinFE only through the context
it is handed.

Its account answers its secrets with their values on purpose: core takes them out on the
way to a client, and the tests hold it to that.
"""

from __future__ import annotations

import io

from fastapi import APIRouter, HTTPException, Response
from PIL import Image

# The core event it listens to. A name, not an import: the event vocabulary is part of
# the platform ABI the manifest names, and an extension holds no reference into core.
GAME_SELECTED = "game.selected"

# The one kind of card it reads, and the version of it it writes.
CARD = "sample_card"
CARD_VERSION = 1

# What a player's `picture` value names, and so what its service answers with.
PICTURES = {"red": (200, 30, 30), "blue": (30, 30, 200)}


def register(ctx) -> None:
    ctx.logger.info("Registering")
    seen: list[dict] = []
    router = APIRouter()
    writing = APIRouter()

    @router.get("/hello")
    def hello() -> dict:
        return {"name": ctx.name, "greeting": ctx.config.get("greeting")}

    @router.get("/seen")
    def how_many() -> dict:
        return {"seen": len(seen)}

    @writing.post("/forget")
    def forget() -> dict:
        seen.clear()
        return {"seen": 0}

    @router.get("/boom")
    def boom() -> dict:
        raise RuntimeError("the fixture was asked to fail")

    @router.get("/accounts/{player_id}/picture")
    def picture(player_id: str) -> Response:
        named = ctx.players.account(player_id).get("picture", "")
        if named == "denied":
            raise HTTPException(403, detail="The service refused")
        if named == "text":
            return Response(b"not an image", media_type="text/plain")
        color = PICTURES.get(named.removesuffix("-jpg"))
        if color is None:
            raise HTTPException(404, detail="No picture yet")
        out = io.BytesIO()
        if named.endswith("-jpg"):
            Image.new("RGB", (40, 20), color).save(out, format="JPEG")
            return Response(out.getvalue(), media_type="image/jpg")
        Image.new("RGB", (40, 20), color).save(out, format="PNG")
        return Response(out.getvalue(), media_type="image/png")

    def read_account(player_id: str) -> dict:
        held = ctx.players.account(player_id)
        return {"fields": [
                    {"key": "handle", "label": "Handle", "type": "string",
                     "value": held.get("handle", "")},
                    {"key": "token", "label": "Token", "type": "secret",
                     "value": held.get("token", "")}],
                "status": "Ready" if held.get("handle") else "No handle",
                "acts": [{"key": "ping", "label": "Ping"}],
                "card": bool(held.get("handle") and held.get("token")),
                "picture": held.get("picture") in PICTURES}

    def write_account(player_id: str, values: dict) -> None:
        ctx.players.set_account(player_id, {**ctx.players.account(player_id), **values})

    def ping(player_id: str) -> dict:
        return {"message": f"Pinged {ctx.players.account(player_id).get('handle', '')}"}

    def card(player_id: str) -> dict | None:
        held = ctx.players.account(player_id)
        player = ctx.players.get(player_id) or {}
        if not (held.get("handle") and held.get("token")):
            return None
        return {"card": {"type": CARD, "version": CARD_VERSION, "handle": held["handle"],
                         "token": held["token"], "initials": player.get("initials", "")},
                "filename": f"sample-{held['handle']}"}

    def read_card(found: dict) -> dict:
        if (found or {}).get("version") != CARD_VERSION:
            raise ValueError("Not a card this reads")
        return {"name": "", "initials": str(found.get("initials") or ""),
                "values": {"handle": str(found.get("handle") or ""),
                           "token": str(found.get("token") or "")}}

    def on_selected(**payload) -> None:
        if payload.get("game_id") == "fail":
            raise RuntimeError("the fixture was asked to fail")
        seen.append(payload)
        ctx.events.publish("noticed", game_id=payload.get("game_id"))

    ctx.events.subscribe(GAME_SELECTED, on_selected)
    ctx.add_router(router)
    ctx.add_router(writing)
    ctx.ui.settings([{"key": "greeting", "type": "string", "default": "hello"},
                     {"key": "token", "type": "secret"}])
    ctx.ui.account(read=read_account, write=write_account, acts={"ping": ping}, card=card,
                   read_card=read_card, label="Sample", cards=(CARD,))
