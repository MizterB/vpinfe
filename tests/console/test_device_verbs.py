"""What a device's menu offers: the verbs it says it performs, then Forget."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

from common import device_client, lifecycle
from common.host import action_ops
from common.i18n import t
from console import devices
from tests.support.clicks import press

DEVICE = {"device_id": "Bbbb222222", "display_name": "Basement", "kind": "vpinfe",
          "address": "10.0.0.7", "port": 8001}


def entry(scope: str, action: str, **more: Any) -> dict[str, Any]:
    return {"scope": scope, "action": action, "label": lifecycle.label(scope, action),
            "available": True, "reason": "", "reason_key": "", **more}


EVERY = [entry(scope, action) for scope, action in lifecycle.offered()]


def labels(verbs: list) -> list[str]:
    return [one.label for one in verbs]


class MenuOrderTests(unittest.TestCase):
    def test_the_verbs_come_in_menu_order_with_forget_last(self) -> None:
        verbs = devices.acts(Mock(), DEVICE, None, client=Mock(), offered=EVERY)

        self.assertEqual(labels(verbs), [
            t("action.vpinfe.restart"), t("action.frontend.restart"),
            t("action.vpinfe.stop"), t("action.system.restart"),
            t("action.system.stop"), t("word.forget")])

    def test_only_the_ones_that_take_the_machine_or_the_entry_are_dangerous(self) -> None:
        verbs = devices.acts(Mock(), DEVICE, None, client=Mock(), offered=EVERY)

        self.assertEqual([one.danger for one in verbs],
                         [False, False, False, True, True, True])

    def test_this_installs_own_entry_has_no_forget(self) -> None:
        verbs = devices.acts(Mock(), DEVICE, None, client=Mock(), offered=EVERY,
                             forgettable=False)

        self.assertNotIn(t("word.forget"), labels(verbs))

    def test_a_device_that_is_not_asked_offers_only_forget(self) -> None:
        verbs = devices.acts(Mock(), DEVICE, None)

        self.assertEqual(labels(verbs), [t("word.forget")])

    def test_a_headless_install_offers_no_window_item(self) -> None:
        headless = [one for one in EVERY if one["scope"] != lifecycle.FRONTEND]

        verbs = devices.acts(Mock(), DEVICE, None, client=Mock(), offered=headless)

        self.assertNotIn(t("action.frontend.restart"), labels(verbs))
        self.assertIn(t("action.vpinfe.restart"), labels(verbs))

    def test_a_pair_the_menu_does_not_carry_is_not_added(self) -> None:
        verbs = devices.acts(Mock(), DEVICE, None, client=Mock(),
                             offered=[entry("table", "stop"), entry("frontend", "start")])

        self.assertEqual(labels(verbs), [t("word.forget")])


class RoutedAndLedTests(unittest.TestCase):
    def test_a_routed_pair_runs_what_it_was_given_and_asks_nothing_itself(self) -> None:
        handler = Mock()

        verbs = devices.acts(Mock(), DEVICE, None, client=Mock(), offered=EVERY,
                             forgettable=False,
                             routed={(lifecycle.VPINFE, lifecycle.RESTART): handler})

        self.assertIs(verbs[0].run, handler)
        self.assertIsNot(verbs[1].run, handler)

    def test_a_led_pair_goes_first_with_its_note_after_the_label(self) -> None:
        verbs = devices.acts(Mock(), DEVICE, None, client=Mock(), offered=EVERY,
                             forgettable=False,
                             led=((lifecycle.FRONTEND, lifecycle.RESTART), "2 changes waiting"))

        self.assertEqual(labels(verbs)[:3], [
            f"{t('action.frontend.restart')} - 2 changes waiting",
            t("action.vpinfe.restart"), t("action.vpinfe.stop")])

    def test_a_led_pair_this_device_does_not_offer_leaves_the_menu_as_it_was(self) -> None:
        headless = [one for one in EVERY if one["scope"] != lifecycle.FRONTEND]

        verbs = devices.acts(Mock(), DEVICE, None, client=Mock(), offered=headless,
                             forgettable=False,
                             led=((lifecycle.FRONTEND, lifecycle.RESTART), "1 change waiting"))

        self.assertEqual(labels(verbs)[0], t("action.vpinfe.restart"))


class OlderInstallTests(unittest.TestCase):
    def test_an_entry_an_older_install_listed_to_say_nothing_performs_it_is_dropped(self) -> None:
        said = entry("frontend", "restart", available=False,
                     reason_key=action_ops.NOT_WIRED, reason="Nothing performs that")

        self.assertEqual(devices.usable([said, entry("vpinfe", "restart")]),
                         [entry("vpinfe", "restart")])

    def test_one_that_can_run_but_not_now_stays_refused_with_its_reason(self) -> None:
        busy = entry("vpinfe", "restart", available=False, reason="Updating", reason_key="x")

        verbs = devices.acts(Mock(), DEVICE, None, client=Mock(), offered=[busy],
                             forgettable=False)

        self.assertIsNone(verbs[0].run)
        self.assertEqual(verbs[0].hint, "Updating")


class AskingTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self, scope: str, action: str, *, yes: bool = True) -> tuple[AsyncMock, Mock]:
        client = Mock()
        client.perform_action = Mock(return_value={"performed": True})
        verb = devices.acts(Mock(), DEVICE, None, client=client,
                            offered=[entry(scope, action)], forgettable=False)[0]
        ask = AsyncMock(return_value=yes)
        with patch.object(devices.confirm, "ask", new=ask), \
                patch.object(devices.offload, "io",
                             new=AsyncMock(side_effect=lambda call, *a: call(*a))), \
                patch.object(devices.ui, "notify", new=Mock()):
            assert verb.run is not None
            await press(verb.run)
        return ask, client

    async def test_quit_says_it_has_to_be_started_again_on_that_machine(self) -> None:
        ask, client = await self._run("vpinfe", "stop")

        self.assertEqual(ask.call_args.kwargs["detail"],
                         t("console.devices.quit_detail", device_label="Basement"))
        client.perform_action.assert_called_once_with("vpinfe", "stop")

    async def test_restart_and_reboot_keep_the_question_they_had(self) -> None:
        for scope, action in (("vpinfe", "restart"), ("system", "restart"),
                              ("system", "stop")):
            with self.subTest(pair=(scope, action)):
                ask, _client = await self._run(scope, action)

                self.assertEqual(ask.call_args.kwargs["detail"],
                                 t("console.devices.happens_now", device_label="Basement"))

    async def test_reopening_the_windows_is_not_asked_about(self) -> None:
        ask, client = await self._run("frontend", "restart")

        ask.assert_not_called()
        client.perform_action.assert_called_once_with("frontend", "restart")

    async def test_a_no_does_nothing(self) -> None:
        _ask, client = await self._run("system", "stop", yes=False)

        client.perform_action.assert_not_called()


class LoadActionsTests(unittest.IsolatedAsyncioTestCase):
    async def _load(self, device: dict, reach: dict | None, client: Any,
                    local: str | None = "Aaaa111111") -> list:
        with patch.object(devices.device_client, "for_device", return_value=client), \
                patch.object(devices.offload, "io",
                             new=AsyncMock(side_effect=lambda call, *a: call(*a))):
            return await devices.load_actions(client, device, local, reach)

    async def test_a_remote_device_is_asked_for_its_own_list(self) -> None:
        client = Mock()
        client.actions = Mock(return_value=[entry("vpinfe", "restart")])

        found = await self._load(DEVICE, {"state": device_client.ANSWERING}, client)

        self.assertEqual(found, [entry("vpinfe", "restart")])

    async def test_one_that_is_not_answering_is_not_asked(self) -> None:
        client = Mock()

        found = await self._load(DEVICE, {"state": device_client.UNREACHABLE}, client)

        self.assertEqual(found, [])
        client.actions.assert_not_called()

    async def test_this_install_is_asked_without_a_probe(self) -> None:
        client = Mock()
        client.actions = Mock(return_value=[entry("vpinfe", "stop")])

        found = await self._load({**DEVICE, "device_id": "Aaaa111111"}, None, client)

        self.assertEqual(found, [entry("vpinfe", "stop")])

    async def test_a_phone_has_none(self) -> None:
        client = Mock()

        found = await self._load({**DEVICE, "kind": "vpx_mobile"},
                                 {"state": device_client.ANSWERING}, client)

        self.assertEqual(found, [])

    async def test_an_install_from_before_the_route_has_none(self) -> None:
        client = Mock()
        client.actions = Mock(side_effect=device_client.TooOldError("old"))

        found = await self._load(DEVICE, {"state": device_client.ANSWERING}, client)

        self.assertEqual(found, [])

    async def test_a_failed_ask_is_none_not_a_crash(self) -> None:
        client = Mock()
        client.actions = Mock(side_effect=OSError("down"))

        found = await self._load(DEVICE, {"state": device_client.ANSWERING}, client)

        self.assertEqual(found, [])


class PlayingRowTests(unittest.IsolatedAsyncioTestCase):
    def _context(self, actions: list) -> dict[str, Any]:
        return {"device": DEVICE, "local_device_id": "Aaaa111111", "actions": actions,
                "rebuild": AsyncMock()}

    async def _rows(self, context: dict, playing: dict | Exception) -> tuple[list, Mock]:
        client = Mock()
        client.play_state = Mock(side_effect=playing if isinstance(playing, Exception)
                                 else None, return_value=playing)
        client.perform_action = Mock(return_value={"performed": True})
        with patch.object(devices, "client_for", return_value=client), \
                patch.object(devices.offload, "io",
                             new=AsyncMock(side_effect=lambda call, *a: call(*a))):
            return await devices._playing_rows(context), client

    async def test_nothing_while_no_table_plays(self) -> None:
        rows, _client = await self._rows(self._context([entry("table", "stop")]),
                                         {"launching": False})

        self.assertEqual(rows, [])

    async def test_a_row_while_one_does(self) -> None:
        rows, _client = await self._rows(self._context([entry("table", "stop")]),
                                         {"launching": True, "game_name": "Medieval Madness"})

        self.assertEqual([label for label, _draw in rows], [t("console.devices.playing")])

    async def test_closing_it_asks_the_device_and_rebuilds_the_panel(self) -> None:
        context = self._context([entry("table", "stop")])
        rows, client = await self._rows(
            context, {"launching": True, "game_name": "Medieval Madness"})
        pressed: dict[str, Any] = {}

        def action(label: str, on_click: Any = None, **more: Any) -> Any:
            pressed.update(label=label, on_click=on_click, hint=more.get("hint"))
            return lambda: None

        async def draw() -> None:
            with patch.object(devices.panel, "action", new=action):
                rows[0][1]()

        await press(draw)
        with patch.object(devices.offload, "io",
                          new=AsyncMock(side_effect=lambda call, *a: call(*a))):
            await press(pressed["on_click"])

        self.assertEqual(pressed["label"], t("console.devices.close_action"))
        self.assertTrue(pressed["hint"])
        client.perform_action.assert_called_once_with("table", "stop")
        context["rebuild"].assert_awaited_once()

    async def test_a_device_that_cannot_close_one_shows_no_row(self) -> None:
        rows, client = await self._rows(self._context([entry("vpinfe", "restart")]),
                                        {"launching": True, "game_name": "Medieval Madness"})

        self.assertEqual(rows, [])
        client.play_state.assert_not_called()

    async def test_a_device_that_does_not_answer_shows_no_row(self) -> None:
        rows, _client = await self._rows(self._context([entry("table", "stop")]),
                                         OSError("down"))

        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
