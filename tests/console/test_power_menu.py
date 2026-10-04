"""The power icon at the foot of the rail: this install's own device menu."""

from __future__ import annotations

import asyncio
import unittest
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

from nicegui import background_tasks, ui

from common import lifecycle
from common.i18n import t
from console import offload, power, remembered, waiting
from tests.support.clicks import press

LOCAL = "Aaaa111111"
THIS = {"device_id": LOCAL, "display_name": "Basement", "kind": "vpinfe"}
PORTS = {"kind": "setting", "section": "network", "key": "http_port", "label": "HTTP port",
         "waits_for": "restart", "in_effect": 8001, "set": 8011}
SOCKET = {"kind": "setting", "section": "network", "key": "ws_port", "label": "WebSocket port",
          "waits_for": "restart", "in_effect": 8002, "set": 8012}
ROTATION = {"kind": "setting", "section": "display", "key": "rotation", "label": "Rotation",
            "waits_for": "reopen", "in_effect": 0, "set": 90}
_PAGE = ui.element()


def _entry(scope: str, action: str) -> dict[str, Any]:
    return {"scope": scope, "action": action, "label": lifecycle.label(scope, action),
            "available": True, "reason": "", "reason_key": ""}


EVERY = [_entry(scope, action) for scope, action in lifecycle.offered()]


def _answer(*entries: dict[str, Any], reopen: bool = False) -> dict[str, Any]:
    return {"waiting": list(entries), "reopen": reopen, "http_port": 8011}


async def _direct(call: Any, *args: Any) -> Any:
    return call(*args)


def _menu_labels(menu: ui.element) -> list[str]:
    return [str(one.text) for one in menu.descendants()
            if isinstance(one, ui.label) and not one.is_deleted]


async def _click(menu: ui.element, label: str) -> None:
    """Press the menu item that starts with `label` and wait for what it started."""
    item = next(one for one in menu.descendants()
                if isinstance(one, ui.menu_item)
                and any(isinstance(inner, ui.label) and str(inner.text).startswith(label)
                        for inner in one.descendants()))
    handler = next(listener.handler for listener in item._event_listeners.values()
                   if listener.type == "click")

    async def go() -> None:
        started: list[Any] = []
        with patch.object(background_tasks, "create_or_defer",
                          lambda awaitable, **_: started.append(awaitable)):
            handler(None)
        await asyncio.gather(*started)

    await press(go)


class ThePowerIcon(unittest.IsolatedAsyncioTestCase):

    def setUp(self) -> None:
        self.memory: dict[str, Any] = {}
        for one in (
                patch.object(remembered, "get",
                             lambda key, default=None: self.memory.get(key, default)),
                patch.object(remembered, "put",
                             lambda key, value: self.memory.__setitem__(key, value)),
                patch.object(offload, "io", AsyncMock(side_effect=_direct))):
            one.start()
            self.addCleanup(one.stop)
        self.library = Mock()
        self.library.config_waiting.return_value = _answer()
        self.library.actions.return_value = EVERY
        self.state: dict[str, Any] = {}

    async def _placed(self) -> tuple[power.Power, waiting.Bar]:
        with _PAGE:
            bar = waiting.Bar(self.library)
            bar.place()
            icon = power.Power(self.library, bar, self.state, [THIS], LOCAL)
            icon.place()
        await press(bar.refresh)
        await press(icon.load)
        assert icon._menu is not None and icon._button is not None
        self.addCleanup(icon._button.delete)
        return icon, bar

    async def test_the_menu_is_this_installs_verbs_with_no_forget(self) -> None:
        icon, _bar = await self._placed()
        assert icon._menu is not None

        shown = _menu_labels(icon._menu)

        self.assertIn(t("action.vpinfe.restart"), shown)
        self.assertIn(t("action.system.stop"), shown)
        self.assertNotIn(t("word.forget"), shown)

    async def test_no_dot_and_a_plain_restart_while_nothing_waits(self) -> None:
        icon, _bar = await self._placed()
        assert icon._menu is not None and icon._dot is not None

        self.assertFalse(icon._dot.visible)
        self.assertEqual(_menu_labels(icon._menu)[0], t("action.vpinfe.restart"))

    async def test_no_dot_while_the_line_is_showing(self) -> None:
        self.library.config_waiting.return_value = _answer(PORTS, SOCKET)
        icon, _bar = await self._placed()
        assert icon._dot is not None

        self.assertFalse(icon._dot.visible)

    async def test_the_dot_and_the_lead_follow_a_dismissed_line(self) -> None:
        self.library.config_waiting.return_value = _answer(PORTS, SOCKET)
        icon, bar = await self._placed()
        assert icon._menu is not None and icon._dot is not None

        bar._dismiss()

        self.assertTrue(icon._dot.visible)
        self.assertEqual(_menu_labels(icon._menu)[0],
                         f"{t('action.vpinfe.restart')} - 2 changes waiting")

    async def test_the_dot_goes_when_the_waiting_change_is_undone(self) -> None:
        self.library.config_waiting.return_value = _answer(PORTS)
        icon, bar = await self._placed()
        assert icon._menu is not None and icon._dot is not None
        bar._dismiss()
        self.library.config_waiting.return_value = _answer()

        await press(bar.refresh)

        self.assertFalse(icon._dot.visible)
        self.assertEqual(_menu_labels(icon._menu)[0], t("action.vpinfe.restart"))

    async def test_window_changes_alone_lead_with_the_reopen(self) -> None:
        self.library.config_waiting.return_value = _answer(ROTATION, reopen=True)
        icon, bar = await self._placed()
        assert icon._menu is not None

        bar._dismiss()

        self.assertEqual(_menu_labels(icon._menu)[0],
                         f"{t('action.frontend.restart')} - 1 change waiting")

    async def test_restart_from_the_menu_goes_through_the_line_and_follows_the_port(
            self) -> None:
        self.library.config_waiting.return_value = _answer(PORTS)
        icon, bar = await self._placed()
        bar._dismiss()
        assert icon._menu is not None

        with patch.object(waiting.confirm, "ask", AsyncMock(return_value=True)), \
                patch.object(ui, "run_javascript") as script:
            await _click(icon._menu, t("action.vpinfe.restart"))

        self.library.perform_action.assert_called_once_with("vpinfe", "restart")
        self.assertIn("String(8011)", script.call_args.args[0])

    async def test_restart_with_nothing_waiting_still_says_it_was_done(self) -> None:
        icon, _bar = await self._placed()
        assert icon._menu is not None

        with patch.object(waiting.confirm, "ask", AsyncMock(return_value=True)), \
                patch.object(ui, "run_javascript"), \
                patch.object(ui, "notify") as toast:
            await _click(icon._menu, t("action.vpinfe.restart"))

        toast.assert_called_once_with(t("action.vpinfe.restart"), type="positive")

    async def test_a_restart_that_was_not_performed_is_warned_about(self) -> None:
        self.library.perform_action.return_value = {"performed": False}
        icon, _bar = await self._placed()
        assert icon._menu is not None

        with patch.object(waiting.confirm, "ask", AsyncMock(return_value=True)), \
                patch.object(ui, "run_javascript") as script, \
                patch.object(ui, "notify") as toast:
            await _click(icon._menu, t("action.vpinfe.restart"))

        self.assertEqual(toast.call_args.kwargs["type"], "warning")
        script.assert_not_called()

    async def test_no_dot_when_the_device_does_not_offer_the_led_verb(self) -> None:
        self.library.config_waiting.return_value = _answer(PORTS)
        self.library.actions.return_value = [one for one in EVERY
                                             if one["scope"] != lifecycle.VPINFE]
        icon, bar = await self._placed()
        assert icon._dot is not None

        bar._dismiss()

        self.assertFalse(icon._dot.visible)

    async def test_an_install_that_performs_nothing_has_no_icon(self) -> None:
        self.library.actions.return_value = []
        icon, _bar = await self._placed()
        assert icon._button is not None

        self.assertFalse(icon._button.visible)

    async def test_what_the_page_already_read_is_not_read_again(self) -> None:
        self.state["device_actions"] = {LOCAL: EVERY}

        await self._placed()

        self.library.actions.assert_not_called()
