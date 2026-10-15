"""What Security shows for encrypted connections, read off the entries without a browser."""

from __future__ import annotations

import unittest
from typing import Any
from unittest import mock

from common.i18n import t
from console import encrypted_panel, panel


def _noop(*_args: Any) -> None:
    return None


def _entries(**held: Any) -> list[tuple[Any, ...]]:
    return encrypted_panel.entries(
        held, "Game Room", add_proxy=_noop, remove_proxy=_noop, add_network=_noop,
        add_tailscale=_noop, remove_network=_noop, choose=_noop, clear=_noop)


def _headings(rows: list[tuple[Any, ...]]) -> list[str]:
    return [row[1] for row in rows if row[0] == panel.HEADING]


def _text(rows: list[tuple[Any, ...]]) -> list[str]:
    """The labels and values, and the lines a `note`, an `intro` or an entry would draw."""
    said = [str(cell) for row in rows for cell in row if isinstance(cell, str)]
    drawn: list[str] = []
    def label(text: str = "", **_: Any) -> mock.MagicMock:
        drawn.append(text)
        return mock.MagicMock()

    page = mock.MagicMock()
    page.label.side_effect = label
    with (mock.patch.object(panel, "line", lambda text, **_: drawn.append(text)),
          mock.patch.object(panel, "icon_action", lambda *_args, **_kw: _noop),
          mock.patch.object(encrypted_panel, "ui", page)):
        for row in rows:
            for cell in row:
                if getattr(cell, "__qualname__", "").split(".")[0] in ("note", "intro", "_entry"):
                    cell()
    return said + drawn


class WhatSecurityShows(unittest.TestCase):
    def test_the_lead_says_what_a_listing_would_skip_and_on_whose_screen(self) -> None:
        said = _text(_entries())

        self.assertIn(t("console.encrypted.lead", device="Game Room"), said)
        self.assertNotIn("{device}", " ".join(said))

    def test_the_two_lists_and_the_certificate_each_have_a_heading(self) -> None:
        self.assertEqual(_headings(_entries()), [
            t("console.encrypted.heading"), t("console.encrypted.proxies"),
            t("console.encrypted.networks"), t("console.encrypted.https")])

    def test_an_entry_is_listed_by_its_own_address(self) -> None:
        said = _text(_entries(proxies=["192.168.1.5"], networks=["100.64.0.0/10"]))

        self.assertIn("192.168.1.5", said)
        self.assertIn("100.64.0.0/10", said)

    def test_the_lead_stays_once_something_is_set_up(self) -> None:
        said = _text(_entries(networks=["100.64.0.0/10"]))

        self.assertIn(t("console.encrypted.lead", device="Game Room"), said)

    def test_each_empty_list_says_so_and_a_filled_one_does_not(self) -> None:
        empty = _text(_entries())
        filled = _text(_entries(proxies=["192.168.1.5"], networks=["100.64.0.0/10"]))

        for key in ("console.encrypted.proxies_none", "console.encrypted.networks_none"):
            self.assertIn(t(key), empty)
            self.assertNotIn(t(key), filled)

    def test_one_list_empty_leaves_the_other_alone(self) -> None:
        said = _text(_entries(networks=["100.64.0.0/10"]))

        self.assertIn(t("console.encrypted.proxies_none"), said)
        self.assertNotIn(t("console.encrypted.networks_none"), said)

    def test_each_remove_control_names_the_address_it_takes_off(self) -> None:
        named: list[str] = []
        page = mock.MagicMock()
        rows = _entries(proxies=["192.168.1.5"], networks=["100.64.0.0/10"])

        def record(label: str, *_args: Any, **_kw: Any) -> Any:
            named.append(label)
            return _noop

        with (mock.patch.object(panel, "icon_action", record),
              mock.patch.object(encrypted_panel, "ui", page)):
            for row in rows:
                for cell in row:
                    if getattr(cell, "__qualname__", "").split(".")[0] == "_entry":
                        cell()

        self.assertEqual(named, [t("console.encrypted.remove_entry", address="192.168.1.5"),
                                 t("console.encrypted.remove_entry", address="100.64.0.0/10")])

    def test_a_proxy_on_this_device_says_it_waits_for_https(self) -> None:
        for proxies in (["127.0.0.1"], ["10.0.0.5", "::1"]):
            with self.subTest(proxies=proxies):
                said = _text(_entries(proxies=proxies, https=False))

                self.assertIn(t("console.encrypted.proxy_here"), said)

    def test_that_line_goes_once_https_is_served(self) -> None:
        said = _text(_entries(proxies=["127.0.0.1"], https=True))

        self.assertNotIn(t("console.encrypted.proxy_here"), said)

    def test_a_proxy_on_another_device_has_no_such_line(self) -> None:
        with mock.patch.object(encrypted_panel.this_machine, "peer_is_this_machine",
                               return_value=False):
            said = _text(_entries(proxies=["10.0.0.5"], https=False))

        self.assertNotIn(t("console.encrypted.proxy_here"), said)

    def test_without_a_certificate_it_offers_to_choose_one(self) -> None:
        said = _text(_entries())

        self.assertIn(t("console.encrypted.https_none"), said)

    def test_a_certificate_shows_both_files_and_the_start_it_waits_for(self) -> None:
        said = _text(_entries(certfile="/certs/a.pem", keyfile="/certs/a.key", https=False))

        self.assertIn(t("console.encrypted.next_start"), said)
        self.assertNotIn(t("console.encrypted.https_none"), said)

    def test_a_certificate_being_served_has_no_start_to_wait_for(self) -> None:
        said = _text(_entries(certfile="/certs/a.pem", keyfile="/certs/a.key", https=True))

        self.assertNotIn(t("console.encrypted.next_start"), said)

    def test_a_certificate_that_would_not_load_says_why_it_did_not(self) -> None:
        said = _text(_entries(certfile="/certs/a.pem", keyfile="/certs/a.key", https=False,
                              problem="unreadable"))

        self.assertIn(t("console.encrypted.problem"), said)
        self.assertNotIn(t("console.encrypted.next_start"), said)


if __name__ == "__main__":
    unittest.main()
