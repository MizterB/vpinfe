"""The sign-in request on the machine's screen: what the windows are sent and what the
page's buttons do to the request."""

from __future__ import annotations

import unittest
from typing import Any

from common import approvals, sign_in
from frontend import sign_in_prompt
from frontend.api import API, API_ALLOWED_METHODS, API_INTERNAL_METHODS, API_PUBLISHED_METHODS

ADDRESS = "192.168.1.20"
METHODS = {"signin_pending", "signin_show", "signin_ignore", "signin_dismiss",
           "approval_approve", "approval_decline"}


class _Channel:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.with_iframe: list[dict[str, Any]] = []

    def send_event_all(self, message: dict[str, Any], exclude: str | None = None) -> None:
        self.sent.append(message)

    def send_event_all_with_iframe(self, message: dict[str, Any]) -> None:
        self.with_iframe.append(message)

    def requests(self) -> list[Any]:
        return [message["request"] for message in self.sent
                if message["type"] == sign_in_prompt.MESSAGE]


class _Prompt(unittest.TestCase):
    def setUp(self) -> None:
        self.model = sign_in.SignIn(path=None)
        sign_in.use(self.model)
        self.asks = approvals.Approvals()
        approvals.use(self.asks)
        self.channel = _Channel()
        sign_in_prompt.register(self.channel)  # type: ignore[arg-type]
        self.addCleanup(sign_in_prompt.reset_for_tests)
        self.addCleanup(sign_in.use, sign_in.SignIn())
        self.addCleanup(approvals.use, approvals.Approvals())
        self.api = API.__new__(API)


class WhatTheWindowsAreSent(_Prompt):
    def test_a_request_is_sent_without_its_digits(self) -> None:
        asked = self.model.ask(ADDRESS)

        (sent,) = self.channel.requests()
        self.assertEqual({k: sent[k] for k in ("id", "address", "state", "code")},
                         {"id": asked.id, "address": ADDRESS, "state": "waiting",
                          "code": ""})
        self.assertGreater(sent["expires_in"], sign_in.CODE_SECONDS - 5)
        self.assertLessEqual(sent["expires_in"], sign_in.CODE_SECONDS)

    def test_show_sends_the_digits_and_nothing_sent_before_it_held_them(self) -> None:
        asked = self.model.ask(ADDRESS)
        self.api.signin_show(asked.id)

        before, after = self.channel.requests()
        self.assertEqual((before["code"], after["state"]), ("", "shown"))
        self.assertRegex(after["code"], r"^\d{6}$")

    def test_a_request_gone_is_sent_as_null(self) -> None:
        asked = self.model.ask(ADDRESS)
        self.api.signin_dismiss(asked.id)

        self.assertIsNone(self.channel.requests()[-1])

    def test_ignore_ends_it_and_refuses_the_address_afterwards(self) -> None:
        asked = self.model.ask(ADDRESS)
        self.api.signin_ignore(asked.id)

        self.assertIsNone(self.channel.requests()[-1])
        with self.assertRaises(sign_in.SignInError) as refused:
            self.model.ask(ADDRESS)
        self.assertEqual(refused.exception.reason, sign_in.IGNORED)

    def test_the_digits_do_not_go_to_theme_iframes(self) -> None:
        asked = self.model.ask(ADDRESS)
        self.api.signin_show(asked.id)

        self.assertEqual(self.channel.with_iframe, [])

    def test_registering_again_does_not_send_everything_twice(self) -> None:
        sign_in_prompt.register(self.channel)  # type: ignore[arg-type]

        self.model.ask(ADDRESS)

        self.assertEqual(len(self.channel.requests()), 1)


class WhatThePageCanAsk(_Prompt):
    def test_pending_is_what_a_window_that_missed_the_push_needs(self) -> None:
        self.assertIsNone(self.api.signin_pending())
        asked = self.model.ask(ADDRESS)

        pending = self.api.signin_pending()

        assert pending is not None
        self.assertEqual((pending["id"], pending["state"]), (asked.id, "waiting"))

    def test_show_answers_with_the_digits_for_the_page_that_pressed_it(self) -> None:
        asked = self.model.ask(ADDRESS)

        shown = self.api.signin_show(asked.id)

        assert shown is not None
        self.assertEqual((shown["state"], len(shown["code"])), ("shown", 6))

    def test_show_for_a_request_that_has_gone_answers_none(self) -> None:
        self.assertIsNone(self.api.signin_show("no-such-request"))

    def test_expires_in_counts_down_from_when_it_was_asked(self) -> None:
        asked = self.model.ask(ADDRESS)
        asked.asked -= 125

        view = sign_in_prompt.view(asked)

        assert view is not None
        self.assertLessEqual(view["expires_in"], sign_in.CODE_SECONDS - 124)
        self.assertGreater(view["expires_in"], sign_in.CODE_SECONDS - 130)


class AProgramAsking(_Prompt):
    def ask(self, **body: Any) -> approvals.Ask:
        return self.asks.ask("t1", "Home", "DELETE", "/games/a/folder", body or None)

    def test_an_ask_is_sent_with_what_it_would_change(self) -> None:
        made = self.ask(force=True)

        (sent,) = self.channel.requests()
        self.assertEqual({k: sent[k] for k in ("id", "kind", "program", "method", "path",
                                                "body", "long")},
                         {"id": made.id, "kind": "approval", "program": "Home",
                          "method": "DELETE", "path": "/games/a/folder",
                          "body": '{"force":true}', "long": False})
        self.assertGreater(sent["expires_in"], 0)

    def test_approving_from_the_screen_answers_and_clears_it(self) -> None:
        made = self.ask()
        self.api.approval_approve(made.id)

        self.assertEqual(self.asks.get(made.id).state, approvals.APPROVED)
        self.assertIsNone(self.channel.requests()[-1])

    def test_declining_from_the_screen_answers_and_clears_it(self) -> None:
        made = self.ask()
        self.api.approval_decline(made.id)

        self.assertEqual(self.asks.get(made.id).state, approvals.DECLINED)
        self.assertIsNone(self.channel.requests()[-1])

    def test_close_leaves_the_screen_and_the_ask_waits(self) -> None:
        made = self.ask()
        self.api.signin_dismiss(made.id)

        self.assertEqual(self.asks.get(made.id).state, approvals.WAITING)
        self.assertIsNone(self.channel.requests()[-1])
        self.assertIsNone(self.api.signin_pending())

    def test_an_ask_too_long_to_read_across_the_room_is_not_approved_from_here(self) -> None:
        made = self.ask(text="x" * (sign_in_prompt.READABLE_LINE + 1))
        shown = self.api.signin_pending()

        assert shown is not None
        self.assertTrue(shown["long"])
        self.api.approval_approve(made.id)

        self.assertEqual(self.asks.get(made.id).state, approvals.WAITING)

    def test_a_sign_in_is_shown_first_and_the_ask_comes_back_after_it(self) -> None:
        made = self.ask()
        asked = self.model.ask(ADDRESS)

        shown = self.api.signin_pending()
        assert shown is not None
        self.assertEqual(shown["id"], asked.id)
        self.api.signin_dismiss(asked.id)

        again = self.channel.requests()[-1]
        assert again is not None
        self.assertEqual(again["id"], made.id)


class OnlyCoreCanReachThem(unittest.TestCase):
    def test_a_theme_cannot_call_them(self) -> None:
        self.assertTrue(METHODS <= API_INTERNAL_METHODS)
        self.assertEqual(METHODS & API_PUBLISHED_METHODS, set())

    def test_the_bridge_can_dispatch_them(self) -> None:
        self.assertTrue(METHODS <= API_ALLOWED_METHODS)


if __name__ == "__main__":
    unittest.main()
