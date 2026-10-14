"""The Security page lists the browsers signed in and offers to end them."""

from __future__ import annotations

import unittest
from unittest import mock

from common import sign_in
from console import panel, security, settings

IPHONE = {"id": "a1", "kind": sign_in.OWNER, "address": "192.168.1.31",
          "agent": "Safari on iPhone", "created": 1_000_000.0, "last_used": 1_000_100.0,
          "current": False}


def _rows(found: list[tuple]) -> list[tuple]:
    return [entry for entry in found if entry[0] is not panel.HEADING
            and entry[0] is not panel.FULL and entry[0] is not panel.ASIDE]


class WhatTheRowsSay(unittest.TestCase):
    def test_a_browser_is_named_by_its_kind_and_where_it_is(self) -> None:
        self.assertEqual(security.name_of(IPHONE), "Safari on iPhone, 192.168.1.31")

    def test_a_browser_that_never_said_what_it_is_is_named_by_its_address(self) -> None:
        self.assertEqual(security.name_of({**IPHONE, "agent": ""}), "192.168.1.31")

    def test_the_kinds_have_their_own_words(self) -> None:
        self.assertEqual(security.kind_label(sign_in.OWNER), "Owner")
        self.assertEqual(security.kind_label(sign_in.REMOTE), "Remote")


class WhatThePageShows(unittest.TestCase):
    def shown(self, rows: list[dict], bind: str = "127.0.0.1") -> list[tuple]:
        return security.entries(rows, "", mock.Mock(), mock.Mock(), bind)

    def test_one_row_to_a_browser(self) -> None:
        found = self.shown([IPHONE, {**IPHONE, "id": "b2", "address": "192.168.1.40"}])

        self.assertEqual([row[0] for row in _rows(found)],
                         ["Safari on iPhone, 192.168.1.31", "Safari on iPhone, 192.168.1.40"])

    def test_no_browser_says_so_and_has_no_row(self) -> None:
        self.assertEqual(_rows(self.shown([])), [])

    def test_signing_everyone_out_is_offered_only_with_someone_to_sign_out(self) -> None:
        self.assertEqual(len(self.shown([IPHONE])) - len(self.shown([])), 1)
        self.assertEqual(len(self.shown([IPHONE, {**IPHONE, "id": "b2"}]))
                         - len(self.shown([IPHONE])), 1)

    def test_the_network_warning_shows_only_where_other_computers_can_reach_us(self) -> None:
        closed = self.shown([IPHONE], "127.0.0.1")
        open_ = self.shown([IPHONE], "0.0.0.0")

        self.assertLess(len(closed), len(open_))

    def test_which_addresses_are_reachable_from_elsewhere(self) -> None:
        for bind, expected in (("0.0.0.0", True), ("192.168.1.5", True), ("::", True),
                               ("127.0.0.1", False), ("::1", False), ("localhost", False)):
            with self.subTest(bind=bind):
                self.assertEqual(security.reachable_from_elsewhere(bind), expected)


class WhereItLives(unittest.TestCase):
    def test_it_is_a_page_of_the_vpinfe_group(self) -> None:
        group = dict(settings.DEVICE_INDEX)["console.settings.group_vpinfe"]

        self.assertIn(settings.SECURITY_PAGE, [page[0] for page in group])
        self.assertIn(settings.SECURITY_PAGE, settings.PAGES)
