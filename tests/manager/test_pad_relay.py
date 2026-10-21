"""A Manager opened on another device hears the cabinet's controller: a table that listens
asks for it over the bus, and each button reported comes back to the pages that asked."""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import PropertyMock, patch

from nicegui import Client, ui

from common import events
from common.i18n import t
from manager.settings import binding_table as table
from manager.settings import pad_relay
from tests.manager.test_binding_table import _drawn
from tests.support.clicks import press, said


class _Page:
    """What a Manager page is to the relay: an id, a way to run script in it, and a way to
    be told when it goes."""

    def __init__(self, name: str) -> None:
        self.id = name
        self.is_deleted = False
        self.has_socket_connection = True
        self.ran: list[str] = []
        self.gone: list[Any] = []

    def run_javascript(self, code: str) -> None:
        self.ran.append(code)

    def on_disconnect(self, handler: Any) -> None:
        self.gone.append(handler)

    def on_delete(self, handler: Any) -> None:
        self.gone.append(handler)


class _Asked:
    def __init__(self) -> None:
        self.seen: list[dict] = []
        events.subscribe(events.PAD_CAPTURE_ARMED, self._note)

    def _note(self, **payload: Any) -> None:
        self.seen.append(payload)

    @property
    def armed(self) -> list[bool]:
        return [one["armed"] for one in self.seen]


class _RelayCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        events.clear()
        pad_relay.reset_for_tests()
        self.asked = _Asked()
        self.addCleanup(events.clear)
        self.addCleanup(pad_relay.reset_for_tests)


class RelayTests(_RelayCase):
    async def test_a_press_goes_to_every_page_that_is_listening(self) -> None:
        one, two = _Page("one"), _Page("two")
        pad_relay.arm(one)  # type: ignore[arg-type]
        pad_relay.arm(two)  # type: ignore[arg-type]

        events.emit(events.PAD_CAPTURE_PRESS, token="pad:standard/button:4", phase="down")
        await asyncio.sleep(0)

        for page in (one, two):
            self.assertEqual(page.ran, [
                'window.__bindingListen && window.__bindingListen.relay('
                '"pad:standard/button:4", true)'])

    async def test_a_release_says_so(self) -> None:
        page = _Page("one")
        pad_relay.arm(page)  # type: ignore[arg-type]

        events.emit(events.PAD_CAPTURE_PRESS, token="pad:2/button:0", phase="up")
        await asyncio.sleep(0)

        self.assertTrue(page.ran[0].endswith(', false)'))

    async def test_a_page_that_stopped_listening_hears_nothing(self) -> None:
        page = _Page("one")
        pad_relay.arm(page)  # type: ignore[arg-type]
        pad_relay.disarm(page)  # type: ignore[arg-type]

        events.emit(events.PAD_CAPTURE_PRESS, token="pad:standard/button:4", phase="down")
        await asyncio.sleep(0)

        self.assertEqual(page.ran, [])

    async def test_a_page_that_has_gone_is_dropped_and_not_written_to(self) -> None:
        page = _Page("one")
        pad_relay.arm(page)  # type: ignore[arg-type]
        page.is_deleted = True

        events.emit(events.PAD_CAPTURE_PRESS, token="pad:standard/button:4", phase="down")
        await asyncio.sleep(0)

        self.assertEqual(page.ran, [])
        self.assertEqual(self.asked.armed, [True, False])

    async def test_the_cabinet_is_given_its_buttons_back_when_the_last_page_stops(self) -> None:
        one, two = _Page("one"), _Page("two")
        pad_relay.arm(one)  # type: ignore[arg-type]
        pad_relay.arm(two)  # type: ignore[arg-type]

        pad_relay.disarm(one)  # type: ignore[arg-type]
        self.assertNotIn(False, self.asked.armed)
        pad_relay.disarm(two)  # type: ignore[arg-type]

        self.assertEqual(self.asked.armed, [True, True, False])

    async def test_a_page_that_closes_stops_listening(self) -> None:
        page = _Page("one")
        pad_relay.arm(page)  # type: ignore[arg-type]

        for handler in page.gone:
            handler()

        self.assertEqual(self.asked.armed, [True, False])

    async def test_asking_again_leaves_one_listener_and_asks_again(self) -> None:
        page = _Page("one")
        pad_relay.arm(page)  # type: ignore[arg-type]
        pad_relay.arm(page)  # type: ignore[arg-type]

        self.assertEqual(len(page.gone), 2)
        pad_relay.disarm(page)  # type: ignore[arg-type]
        pad_relay.arm(page)  # type: ignore[arg-type]
        self.assertEqual(len(page.gone), 2, "the hooks are added once per page")
        self.assertEqual(self.asked.armed, [True, True, False, True])
        self.assertEqual({one["ttl_ms"] for one in self.asked.seen if one["armed"]},
                         {pad_relay.TTL_MS})

    async def test_a_page_with_no_connection_yet_is_not_asked_for(self) -> None:
        page = _Page("one")
        page.has_socket_connection = False

        pad_relay.arm(page)  # type: ignore[arg-type]

        self.assertEqual(self.asked.armed, [])
        self.assertEqual(page.gone, [])

    async def test_the_ask_lapses_well_after_the_next_one_is_due(self) -> None:
        self.assertGreater(pad_relay.TTL_MS / 1000, 2 * pad_relay.REFRESH_S)


class ATableOnAnotherDevice(_RelayCase):
    def setUp(self) -> None:
        super().setUp()
        self.body = ui.column()
        self.up = True
        for held in (patch.object(table, "opened_elsewhere", return_value=True),
                     patch.object(Client, "has_socket_connection", new_callable=PropertyMock,
                                  return_value=True),
                     patch.object(pad_relay, "frontend_up", side_effect=lambda: self.up)):
            held.start()
            self.addCleanup(held.stop)

    def drawn(self, **kwargs: Any) -> table.Table:
        control, _ = _drawn(into=self.body, **kwargs)
        return control

    @staticmethod
    def _words(control: table.Table) -> list[str]:
        return [one.text for one in control.line.descendants() if isinstance(one, ui.label)]

    async def test_a_row_that_listens_asks_for_the_controller(self) -> None:
        control = self.drawn()

        said(control.line, "listen", "back")

        self.assertEqual(self.asked.armed, [True])

    async def test_clicking_away_gives_it_back(self) -> None:
        control = self.drawn()
        said(control.line, "listen", "back")

        said(control.line, "listen", "")

        self.assertEqual(self.asked.armed, [True, False])

    async def test_a_press_heard_gives_it_back(self) -> None:
        control = self.drawn()
        said(control.line, "listen", "back")

        await press(control._captured, SimpleNamespace(args={"row": "back", "token": ""}))

        self.assertEqual(self.asked.armed, [True, False])

    async def test_it_keeps_asking_while_the_row_listens_and_not_after(self) -> None:
        control = self.drawn()
        await control._keep_listening()
        self.assertEqual(self.asked.armed, [])
        said(control.line, "listen", "back")

        await control._keep_listening()
        said(control.line, "listen", "")
        await control._keep_listening()

        self.assertEqual(self.asked.armed, [True, True, False])

    async def test_it_says_when_the_frontend_is_closed_and_how_to_fix_that(self) -> None:
        self.up = False
        control = self.drawn()

        said(control.line, "listen", "back")

        self.assertIn(t("manager.binding_table.no_frontend"), self._words(control))
        self.assertIn(t("manager.binding_table.no_frontend_fix"), self._words(control))

    async def test_a_table_that_is_gone_gives_the_controller_back(self) -> None:
        control = self.drawn()
        said(control.line, "listen", "back")

        control.container.delete()
        await control._keep_listening()

        self.assertEqual(self.asked.armed, [True, False])

    async def test_it_says_nothing_of_the_kind_when_the_frontend_is_open(self) -> None:
        control = self.drawn()

        said(control.line, "listen", "back")

        self.assertNotIn(t("manager.binding_table.no_frontend"), self._words(control))

    async def test_the_note_comes_and_goes_as_the_frontend_does(self) -> None:
        control = self.drawn()
        said(control.line, "listen", "back")

        self.up = False
        await control._keep_listening()
        self.assertIn(t("manager.binding_table.no_frontend"), self._words(control))

        self.up = True
        await control._keep_listening()
        self.assertNotIn(t("manager.binding_table.no_frontend"), self._words(control))


class ATableOnTheServingDevice(_RelayCase):
    def setUp(self) -> None:
        super().setUp()
        self.body = ui.column()

    async def test_it_asks_for_nothing_because_its_own_browser_hears_the_controller(self) -> None:
        with patch.object(table, "opened_elsewhere", return_value=False):
            control, _ = _drawn(into=self.body)

        said(control.line, "listen", "back")
        await control._keep_listening()

        self.assertEqual(self.asked.armed, [])
        words = [one.text for one in control.line.descendants() if isinstance(one, ui.label)]
        self.assertNotIn(t("manager.binding_table.no_frontend"), words)
