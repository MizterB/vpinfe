"""What each caller reaches of an extension's routes, by the tier the route declares.

Driven over HTTP through core's own routes for an extension built in a temp folder, with
real identities, so a refusal comes back in the words an Owner or a token is given.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from fastapi import Depends, FastAPI, Request
from starlette.testclient import TestClient

from common import extensions, i18n, lifecycle, sign_in
from common.extensions import contract, host, reach, store, system
from httpapi import auth, errors, extensions_served, scopes
from tests.support.accepted import owner_accepts

MODULE = "tests.extensions.test_tiers"
NAME = "tiered"
WORDS = {
    "list.board.title": "Board",
    "list.board.act.look.label": "Look",
    "list.ops.title": "Operations",
    "list.ops.act.tidy.label": "Tidy",
    "list.ops.act.restart.label": "Restart",
    "list.locked.title": "Locked",
    "list.locked.act.tidy.label": "Tidy",
}

CALLS: list[str] = []


class Setup:
    """A Library dialog with no `check` of its own."""

    def ask(self, step: str, rows: Any = None) -> dict:
        return {"confirm": "Go"}


def tiered(ctx: Any) -> None:
    """A list at each tier, and an act at Protected on a Library list."""
    ctx.ui.action("setup", Setup())
    ctx.ui.list("board", lambda: [{"name": "a"}], columns=[{"field": "name"}],
                acts={"look": lambda: CALLS.append("look")}, area="community", tier=reach.PLAY)

    @contract.tier(reach.PROTECTED)
    def restart() -> None:
        CALLS.append("restart")

    @contract.tier(reach.PLAY)
    def sneak() -> None:
        CALLS.append("sneak")

    @contract.tier(reach.PROTECTED)
    def reboot_confirmed() -> None:
        ctx.system.reboot("confirmed")

    def reboot_unconfirmed() -> None:
        ctx.system.reboot("unconfirmed")

    def rows_that_reboot() -> list[dict]:
        ctx.system.reboot("from a read")
        return []

    ctx.ui.list("peek", rows_that_reboot, columns=[{"field": "name"}], area="community")

    ctx.ui.list("ops", lambda: [{"name": "a"}], columns=[{"field": "name"}],
                acts={"tidy": lambda: CALLS.append("tidy"), "restart": restart,
                      "sneak": sneak, "reboot_confirmed": reboot_confirmed,
                      "reboot_unconfirmed": reboot_unconfirmed},
                area="community")
    if reach.PROTECTED in ctx.reaches:
        ctx.ui.list("locked", lambda: [{"name": "a"}], columns=[{"field": "name"}],
                    acts={"tidy": lambda: CALLS.append("locked tidy")}, area="community",
                    tier=reach.PROTECTED)


def _installed(root: Path, tiers: list[str]) -> Path:
    directory = root / NAME
    (directory / "i18n").mkdir(parents=True)
    (directory / "extension.json").write_text(json.dumps({
        "name": NAME, "display_name": "Tiered", "version": "1.0.0",
        "description": "Declares a route at each tier, for the tests that reach them.",
        "requires_platform": contract.PLATFORM_ABI, "capabilities": ["ui:mount"],
        "scopes": ["system:admin"],
        "tiers": [one for one in tiers if one != "play"],
        "play": ["list:board"] if "play" in tiers else []}), encoding="utf-8")
    (directory / "i18n" / "en.json").write_text(json.dumps(WORDS), encoding="utf-8")
    (directory / "__init__.py").write_text(
        f"from {MODULE} import tiered as register\n", encoding="utf-8")
    return directory


def _identity(kind: str, *tiers: str) -> auth.Identity:
    return auth.Identity("caller", frozenset(scopes.extension_scope(NAME, one) for one in tiers),
                         kind=kind)


class TierCase(unittest.TestCase):
    listed = ["play", "protected"]

    def setUp(self) -> None:
        owner_accepts(self)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.registry = host.Registry(store.ExtensionStore(Path(tmp.name)))
        self.addCleanup(self.registry.clear)
        self.addCleanup(i18n.disown, f"ext.{NAME}")
        CALLS.clear()
        self.record = self.registry.load(_installed(Path(tmp.name) / "installed", self.listed))
        self.assertEqual(self.record.state, host.LOADED, self.record.error)
        extensions.set_registry(self.registry)
        self.addCleanup(extensions.set_registry, host.Registry())

    def call(self, identity: auth.Identity, path: str, method: str = "post",
             body: dict | None = None) -> Any:
        async def _who(request: Request) -> None:
            request.state.identity = identity

        app = FastAPI(dependencies=[Depends(_who)])

        @app.middleware("http")
        async def marked(request: Request, call_next: Any) -> Any:
            with reach.marking(identity.tier):
                return await call_next(request)

        errors.install_error_handlers(app)
        app.include_router(extensions_served.router(NAME, Depends(lambda: None)),
                           prefix=f"/ext/{NAME}")
        return getattr(TestClient(app), method)(f"/ext/{NAME}{path}", **(
            {"json": body} if body is not None else {}))

    def reason(self, response: Any) -> str:
        return str(response.json()["error"]["details"]["reason"])


class WhoReachesWhat(TierCase):
    def test_a_play_list_is_read_and_pressed_by_a_play_holder(self) -> None:
        play = _identity("", "play")

        read = self.call(play, "/lists/board", "get")
        pressed = self.call(play, "/lists/board/about/acts/look")

        self.assertEqual((read.status_code, pressed.status_code), (200, 200), pressed.text)
        self.assertEqual(CALLS, ["look"])

    def test_a_library_list_is_not_read_by_a_play_holder(self) -> None:
        play = _identity("", "play")

        read = self.call(play, "/lists/ops", "get")
        pressed = self.call(play, "/lists/ops/about/acts/tidy")

        self.assertEqual((read.status_code, pressed.status_code), (403, 403))
        self.assertEqual(CALLS, [])

    def test_an_act_marked_play_on_a_surface_the_manifest_does_not_list_is_refused(self) -> None:
        everything = _identity(sign_in.OWNER, "play", "library")

        pressed = self.call(everything, "/lists/ops/about/acts/sneak")

        self.assertEqual(pressed.status_code, 400, pressed.text)
        self.assertEqual(CALLS, [])
        self.assertIn("does not list under play", pressed.json()["error"]["message"])

    def test_a_library_act_runs_for_a_library_holder(self) -> None:
        response = self.call(_identity("", "play", "library"), "/lists/ops/about/acts/tidy")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(CALLS, ["tidy"])

    def test_a_protected_act_on_a_library_list_asks_an_owner_for_the_confirm(self) -> None:
        owner = _identity(sign_in.OWNER, "play", "library")

        response = self.call(owner, "/lists/ops/about/acts/restart")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.reason(response), auth.CONFIRM_NEEDED)
        self.assertEqual(CALLS, [])

    def test_a_protected_act_is_refused_to_a_token_for_good(self) -> None:
        token = _identity("", "play", "library")

        response = self.call(token, "/lists/ops/about/acts/restart")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.reason(response), auth.PROTECTED)
        self.assertEqual(CALLS, [])

    def test_a_protected_act_runs_for_an_owner_who_has_confirmed(self) -> None:
        owner = _identity(sign_in.OWNER, "play", "library", "protected")

        response = self.call(owner, "/lists/ops/about/acts/restart")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(CALLS, ["restart"])

    def test_a_library_dialog_is_not_opened_by_a_play_holder_by_any_route(self) -> None:
        play = _identity("", "play")
        library = _identity("", "play", "library")

        asked = self.call(play, "/actions/setup/ask", body={"step": "", "rows": []})
        checked = self.call(play, "/actions/setup/check", body={"values": {}})
        allowed = self.call(library, "/actions/setup/check", body={"values": {}})

        self.assertEqual((asked.status_code, checked.status_code), (403, 403))
        self.assertEqual(allowed.status_code, 200, allowed.text)

    def test_a_protected_list_is_read_with_the_library_and_changed_only_with_the_confirm(self):
        owner = _identity(sign_in.OWNER, "play", "library")

        read = self.call(owner, "/lists/locked", "get")
        pressed = self.call(owner, "/lists/locked/about/acts/tidy")

        self.assertEqual(read.status_code, 200, read.text)
        self.assertEqual(pressed.status_code, 403)
        self.assertEqual(self.reason(pressed), auth.CONFIRM_NEEDED)
        self.assertEqual(CALLS, [])


def _confirmed_owner() -> auth.Identity:
    """An Owner holding the Confirm, as the sign-in gives one: core's own scopes too, which
    are what the request's mark is read from."""
    return auth.Identity("owner", frozenset({
        scopes.CONFIG_WRITE, scopes.PROTECTED,
        *(scopes.extension_scope(NAME, one) for one in reach.TIERS)}), kind=sign_in.OWNER)


class ChangingTheComputer(TierCase):
    def setUp(self) -> None:
        super().setUp()
        self.asked: list[tuple] = []
        for held in (
            patch.object(lifecycle, "performable", return_value=True),
            patch.object(system, "DELAY", 0),
            patch.object(system.device_client.local(), "request",
                         side_effect=lambda *a, **k: self.asked.append((a, k)) or True),
        ):
            held.start()
            self.addCleanup(held.stop)

    def _settled(self) -> None:
        import threading
        for one in threading.enumerate():
            if isinstance(one, threading.Timer):
                one.join(2)

    def test_an_act_declared_protected_changes_it_for_an_owner_who_has_confirmed(self) -> None:
        owner = _confirmed_owner()

        response = self.call(owner, "/lists/ops/about/acts/reboot_confirmed")
        self._settled()

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(self.asked), 1)

    def test_an_act_not_declared_protected_cannot_even_under_a_live_confirm(self) -> None:
        owner = _confirmed_owner()

        response = self.call(owner, "/lists/ops/about/acts/reboot_unconfirmed")
        self._settled()

        self.assertGreaterEqual(response.status_code, 400, response.text)
        self.assertEqual(self.asked, [])


    def test_a_read_cannot_change_it_under_a_live_confirm_either(self) -> None:
        owner = _confirmed_owner()

        response = self.call(owner, "/lists/peek", method="get")
        self._settled()

        self.assertGreaterEqual(response.status_code, 400, response.text)
        self.assertEqual(self.asked, [])


class AnUnlistedTier(TierCase):
    listed = ["play"]

    def test_an_act_at_a_tier_the_manifest_does_not_list_is_refused_to_everyone(self) -> None:
        everything = _identity(sign_in.OWNER, "play", "library", "protected")

        response = self.call(everything, "/lists/ops/about/acts/restart")

        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(CALLS, [])
        self.assertIn("Tiered marks something protected", response.json()["error"]["message"])


class Marking(unittest.TestCase):
    def test_a_request_carries_the_tier_it_reached_and_an_owner_without_a_confirm_is_library(
            self) -> None:
        owner = auth.Identity("owner", frozenset({scopes.CONFIG_WRITE}), kind=sign_in.OWNER)
        remote = auth.Identity("remote", scopes.PLAY, kind=sign_in.REMOTE)

        self.assertEqual((owner.tier, remote.tier), (reach.LIBRARY, reach.PLAY))


    def test_an_act_holds_the_mark_to_its_tier_and_never_above_what_the_caller_reached(
            self) -> None:
        with reach.marking(reach.LIBRARY) as mark:
            reach.answer_at(reach.PLAY)
            self.assertEqual(mark.tier, reach.PLAY)
            reach.answer_at(reach.PROTECTED)
            self.assertEqual(mark.tier, reach.LIBRARY)

    def test_a_protected_act_after_a_library_one_keeps_what_an_owner_reached(self) -> None:
        with reach.marking(reach.PROTECTED) as mark:
            reach.answer_at(reach.LIBRARY)
            self.assertEqual(mark.tier, reach.LIBRARY)
            reach.answer_at(reach.PROTECTED)
            self.assertEqual(mark.tier, reach.PROTECTED)

    def test_answering_with_no_request_does_nothing(self) -> None:
        reach.answer_at(reach.PLAY)

        self.assertIsNone(reach.current())


if __name__ == "__main__":
    unittest.main()
