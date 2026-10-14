"""Deleting a game's folder from the disk, and who may ask for it."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import httpapi
from common import api_tokens, sign_in
from common.host import launch_state
from httpapi import auth
from tests.api.test_create_game import CreateGameCase


class DeleteFolderCase(CreateGameCase):
    def setUp(self) -> None:
        super().setUp()
        self.add_location(self.library)
        self.game = self.create("Taxi").json()
        self.folder = Path(self.game["folder"])

    def delete(self, client: TestClient | None = None):
        return (client or self.client).delete(f"/games/{self.game['id']}/folder")


class WhatDeletingDoesTests(DeleteFolderCase):
    def test_the_whole_folder_goes_and_the_game_with_it(self) -> None:
        (self.folder / "Taxi.vpx").write_bytes(b"table")
        (self.folder / "medium").mkdir()
        (self.folder / "medium" / "wheel.png").write_bytes(b"picture")

        found = self.delete()

        self.assertEqual(found.status_code, 200, found.text)
        self.assertEqual(found.json(), {"deleted": True, "folder": str(self.folder)})
        self.assertFalse(self.folder.exists())
        self.assertEqual(self.client.get(f"/games/{self.game['id']}").status_code, 404)

    def test_a_game_that_is_running_is_left_alone(self) -> None:
        running = launch_state.LaunchState(launching=True, game_id=self.game["id"])

        with patch.object(launch_state, "current", return_value=running):
            found = self.delete()

        self.assertEqual(found.status_code, 409, found.text)
        self.assertTrue(self.folder.is_dir())

    def test_another_game_running_does_not_stop_it(self) -> None:
        running = launch_state.LaunchState(launching=True, game_id="someone-else")

        with patch.object(launch_state, "current", return_value=running):
            found = self.delete()

        self.assertEqual(found.status_code, 200, found.text)

    def test_a_folder_the_library_reads_is_left_alone(self) -> None:
        self.client.put("/config/locations/inside",
                        json={"path": str(self.folder), "kind": "game"})

        found = self.delete()

        self.assertEqual(found.status_code, 400, found.text)
        self.assertTrue(self.folder.is_dir())

    def test_a_game_that_is_not_there_is_not_found(self) -> None:
        self.assertEqual(self.client.delete("/games/nothing/folder").status_code, 404)


class WhoMayAskTests(DeleteFolderCase):
    def setUp(self) -> None:
        super().setUp()
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.signer = sign_in.SignIn(Path(holder.name) / "sessions.json")
        self.tokens = api_tokens.Tokens(Path(holder.name) / "tokens.json")
        self.addCleanup(sign_in.use, sign_in.instance())
        self.addCleanup(api_tokens.use, api_tokens.instance())
        sign_in.use(self.signer)
        api_tokens.use(self.tokens)

    def from_elsewhere(self, **headers):
        peer = "192.168.1.50"
        found = TestClient(httpapi.create_api_app(), raise_server_exceptions=False,
                           client=(peer, 50000), base_url="http://" + peer)
        return found.delete(f"/games/{self.game['id']}/folder", headers=headers)

    def test_a_full_control_token_is_refused(self) -> None:
        secret, _ = self.tokens.make("full", api_tokens.FULL, can_power=True)

        found = self.from_elsewhere(authorization="Bearer " + secret)

        self.assertEqual(found.status_code, 403, found.text)
        self.assertTrue(self.folder.is_dir())

    def test_a_remote_pass_is_refused(self) -> None:
        token, _ = self.signer.open(kind=sign_in.REMOTE, address="192.168.1.50")
        found = TestClient(httpapi.create_api_app(), raise_server_exceptions=False,
                           client=("192.168.1.50", 50000), base_url="http://192.168.1.50")
        found.cookies.set(auth.COOKIE, token)

        self.assertEqual(self.delete(found).status_code, 403)
        self.assertTrue(self.folder.is_dir())

    def test_an_owner_without_a_confirm_is_asked_for_one(self) -> None:
        token, session = self.signer.open(kind=sign_in.OWNER, address="192.168.1.50")
        found = TestClient(httpapi.create_api_app(), raise_server_exceptions=False,
                           client=("192.168.1.50", 50000), base_url="http://192.168.1.50")
        found.cookies.set(auth.COOKIE, token)
        with patch.object(self.signer, "is_confirmed", return_value=False):
            refused = self.delete(found)
        self.signer.confirm_grant(session.id)
        allowed = self.delete(found)

        self.assertEqual(refused.status_code, 403, refused.text)
        self.assertEqual(refused.json()["error"]["details"]["reason"], auth.CONFIRM_NEEDED)
        self.assertEqual(allowed.status_code, 200, allowed.text)
        self.assertFalse(self.folder.exists())
