"""What the Tokens section lists, what a paired device is sent, and what a Remote pass sees."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from common import access_keys, api_tokens, paths, sign_in
from console import acting, panel, token_panel
from httpapi import auth


def _row(token_id: str, access: str, *, can_power: bool = False,
         last_used: float = 0.0) -> dict:
    return {"id": token_id, "name": "name " + token_id, "access": access,
            "can_power": can_power, "created": 1.0, "last_used": last_used}


class TheTokensSectionTests(unittest.TestCase):
    def entries(self, rows):
        return token_panel.entries(rows, lambda: None, lambda _id: None, lambda _id, _on: None)

    def test_no_tokens_say_so_and_still_offer_to_make_one(self) -> None:
        entries = self.entries([])

        self.assertEqual(entries[0][0], panel.HEADING)
        self.assertEqual(entries[-2][0], panel.FULL)

    def test_each_token_is_a_row_named_for_the_token(self) -> None:
        entries = self.entries([_row("a", api_tokens.FULL), _row("b", api_tokens.PLAY)])

        names = [one[0] for one in entries if isinstance(one[0], str) and one[0].startswith("name")]
        self.assertEqual(names, ["name a", "name b"])

    def test_a_token_never_used_says_so(self) -> None:
        self.assertEqual(token_panel.last_used(_row("a", api_tokens.FULL)),
                         token_panel.t("console.tokens.never_used"))

    def test_the_access_is_named_in_the_users_words(self) -> None:
        self.assertNotEqual(token_panel.access_label(api_tokens.FULL),
                            token_panel.access_label(api_tokens.PLAY))


class ThePairingTokenTests(unittest.TestCase):
    def test_a_device_never_paired_is_sent_nothing(self) -> None:
        self.assertIsNone(access_keys.pairing_header("nothing-paired"))
        self.assertIsNone(access_keys.pairing_header(""))

    def test_a_paired_device_is_sent_its_token_and_forgetting_stops_it(self) -> None:
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        with mock.patch.object(paths, "SECRETS_PATH", Path(holder.name) / "secrets.json"):
            access_keys.keep_pairing_token("dev", "vpf_x")
            header = access_keys.pairing_header("dev")
            access_keys.forget_pairing_token("dev")
            forgotten = access_keys.pairing_header("dev")

        self.assertEqual(header, {"Authorization": "bearer vpf_x"})
        self.assertIsNone(forgotten)


class APlayPassTests(unittest.TestCase):
    def setUp(self) -> None:
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.addCleanup(sign_in.use, sign_in.instance())
        self.signer = sign_in.SignIn(Path(holder.name) / "sessions.json")
        sign_in.use(self.signer)

    def page_for(self, peer, cookies):
        request = SimpleNamespace(client=SimpleNamespace(host=peer), headers={},
                                  cookies=cookies, method="GET")
        client = SimpleNamespace(request=request)
        return mock.patch.object(acting.ui, "context", SimpleNamespace(client=client))

    def test_a_remote_pass_on_another_device_is_play_only(self) -> None:
        token, _ = self.signer.open(kind=sign_in.REMOTE, address="192.168.1.21")

        with self.page_for("192.168.1.21", {auth.COOKIE: token}):
            self.assertTrue(acting.play_only())

    def test_an_owner_is_not(self) -> None:
        token, _ = self.signer.open(kind=sign_in.OWNER, address="192.168.1.20")

        with self.page_for("192.168.1.20", {auth.COOKIE: token}):
            self.assertFalse(acting.play_only())

    def test_this_device_is_not(self) -> None:
        with self.page_for("127.0.0.1", {}):
            self.assertFalse(acting.play_only())

    def test_a_page_with_no_request_is_not(self) -> None:
        with mock.patch.object(acting.ui, "context", SimpleNamespace(client=None)):
            self.assertFalse(acting.play_only())


if __name__ == "__main__":
    unittest.main()
