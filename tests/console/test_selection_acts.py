"""What a selection of players, launchers, themes or devices offers: the verbs that apply to
any of them, over the ones they apply to."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

from common import lifecycle
from common.i18n import t
from console import devices, launchers, players, themes
from tests.support.clicks import press


def _player(player_id: str, **more: Any) -> dict[str, Any]:
    return {"id": player_id, "name": player_id, "initials": "", "owner": False,
            "guest": False, "up": False, "shares_initials_with": [], **more}


def _theme(key: str, **more: Any) -> dict[str, Any]:
    return {"key": key, "name": key, "installed": True, "active": False,
            "update_available": False, **more}


def _launcher(launcher_id: str) -> dict[str, Any]:
    return {"launcher_id": launcher_id, "display_name": launcher_id}


class Players(unittest.TestCase):
    def _acts(self, chosen: list[dict[str, Any]]) -> list:
        return players.acts(Mock(), {}, chosen, lambda: None)

    def test_guests_and_kept_players_together_offer_both_sign_out_and_remove(self) -> None:
        made = self._acts([_player("g", guest=True), _player("k")])

        self.assertEqual([one.label for one in made],
                         [t("console.players.sign_out"), t("word.remove")])

    def test_the_owner_among_others_is_left_out_of_remove(self) -> None:
        made = self._acts([_player("o", owner=True), _player("k")])

        self.assertEqual([one.label for one in made], [t("word.remove")])
        self.assertIsNotNone(made[0].run)

    def test_the_owner_alone_is_refused_with_why(self) -> None:
        (verb,) = self._acts([_player("o", owner=True)])

        self.assertIsNone(verb.run)
        self.assertTrue(verb.hint)


class RemovingSeveralPlayers(unittest.IsolatedAsyncioTestCase):
    async def test_the_owner_is_not_among_those_removed(self) -> None:
        made = players.acts(Mock(), {}, [_player("o", owner=True), _player("k")], lambda: None)
        remove = made[0]

        with patch.object(players, "remove", new=AsyncMock()) as removed:
            assert remove.run is not None
            await press(remove.run)

        self.assertEqual([one["id"] for one in removed.await_args.args[3]], ["k"])


class Themes(unittest.TestCase):
    def test_each_verb_shows_when_it_applies_to_any_of_them(self) -> None:
        chosen = [_theme("a", installed=False), _theme("b", update_available=True),
                  _theme("c")]

        made = themes.acts(Mock(), chosen, Mock())

        self.assertEqual([one.label for one in made],
                         [t("console.themes.install"), t("console.themes.update"),
                          t("word.make_active"), t("word.uninstall")])

    def test_make_active_is_for_one_at_a_time(self) -> None:
        made = themes.acts(Mock(), [_theme("a"), _theme("b")], Mock())

        self.assertEqual([one.one for one in made], [True, False])


class UninstallingSeveralThemes(unittest.IsolatedAsyncioTestCase):
    async def test_the_active_theme_is_left_out(self) -> None:
        made = themes.acts(Mock(), [_theme("a", active=True), _theme("b")], AsyncMock())
        uninstall = next(one for one in made if one.label == t("word.uninstall"))

        with patch.object(themes.confirm, "ask", new=AsyncMock(return_value=True)), \
                patch.object(themes.run, "io_bound", new=AsyncMock()) as removed, \
                patch.object(themes.ui, "notify"):
            assert uninstall.run is not None
            await press(uninstall.run)

        self.assertEqual([call.args[1] for call in removed.await_args_list], ["b"])


class Launchers(unittest.TestCase):
    def _acts(self, chosen: list[dict[str, Any]], count: int) -> list:
        return launchers.acts(Mock(), {}, chosen, count, lambda: None)

    def test_remove_is_refused_when_it_would_take_every_launcher(self) -> None:
        made = self._acts([_launcher("a"), _launcher("b")], 2)
        remove = next(one for one in made if one.label == t("word.remove"))

        self.assertIsNone(remove.run)
        self.assertEqual(remove.hint, t("console.launchers.keep_one"))

    def test_remove_is_offered_when_one_is_left_over(self) -> None:
        made = self._acts([_launcher("a"), _launcher("b")], 3)
        remove = next(one for one in made if one.label == t("word.remove"))

        self.assertIsNotNone(remove.run)
        self.assertTrue(remove.danger)


class Devices(unittest.TestCase):
    def _entry(self, scope: str, action: str, **more: Any) -> dict[str, Any]:
        return {"scope": scope, "action": action, "label": lifecycle.label(scope, action),
                "available": True, "reason": "", "reason_key": "", **more}

    def _target(self, name: str, *entries: dict[str, Any],
                forgettable: bool = True) -> devices.Target:
        return devices.Target({"device_id": name, "display_name": name}, Mock(),
                              list(entries), forgettable)

    def test_a_verb_shows_when_any_device_offers_it(self) -> None:
        restart = self._entry("vpinfe", "restart")
        stop = self._entry("vpinfe", "stop")

        made = devices.acts(Mock(), [self._target("a", restart),
                                     self._target("b", restart, stop)], None)

        self.assertEqual([one.label for one in made],
                         [t("action.vpinfe.restart"), t("action.vpinfe.stop"),
                          t("word.forget")])

    def test_forget_leaves_out_the_device_that_cannot_be_forgotten(self) -> None:
        made = devices.acts(Mock(), [self._target("a", forgettable=False)], None)

        self.assertEqual(made, [])

    def test_a_verb_every_device_refuses_is_refused_with_the_reason(self) -> None:
        busy = self._entry("vpinfe", "restart", available=False, reason="Updating")

        (verb, _forget) = devices.acts(Mock(), [self._target("a", busy),
                                                self._target("b", busy)], None)

        self.assertIsNone(verb.run)
        self.assertEqual(verb.hint, "Updating")

    def test_a_routed_handler_applies_to_a_single_device_only(self) -> None:
        restart = self._entry("vpinfe", "restart")
        handler = Mock()
        routed = {(lifecycle.VPINFE, lifecycle.RESTART): handler}

        (one,) = devices.acts(Mock(), [self._target("a", restart, forgettable=False)], None,
                              routed=routed)[:1]
        several = devices.acts(Mock(), [self._target("a", restart, forgettable=False),
                                        self._target("b", restart, forgettable=False)], None,
                               routed=routed)[0]

        self.assertIs(one.run, handler)
        self.assertIsNot(several.run, handler)


class SeveralDevices(unittest.IsolatedAsyncioTestCase):
    async def test_each_device_is_asked_once_and_the_question_names_how_many(self) -> None:
        entry = {"scope": "vpinfe", "action": "stop", "available": True, "reason": ""}
        targets = []
        for name in ("a", "b"):
            client = Mock()
            client.perform_action = Mock(return_value={"performed": True})
            targets.append(devices.Target({"device_id": name}, client, [entry], False))
        verb = devices.acts(Mock(), targets, None)[0]
        ask = AsyncMock(return_value=True)

        with patch.object(devices.confirm, "ask", new=ask), \
                patch.object(devices.offload, "io",
                             new=AsyncMock(side_effect=lambda call, *a: call(*a))), \
                patch.object(devices.ui, "notify"):
            assert verb.run is not None
            await press(verb.run)

        ask.assert_awaited_once()
        self.assertEqual(ask.call_args.args[0], t("console.devices.do_to_many",
                                                  label=verb.label, count=2))
        for target in targets:
            target.client.perform_action.assert_called_once_with("vpinfe", "stop")


class TheLocalDeviceGoesLast(unittest.IsolatedAsyncioTestCase):
    async def test_this_machine_is_asked_after_the_others(self) -> None:
        entry = {"scope": "vpinfe", "action": "stop", "available": True, "reason": ""}
        library = Mock()
        order: list[str] = []
        targets = []
        for name, client in (("here", library), ("there", Mock())):
            client.perform_action = Mock(
                side_effect=lambda *_, name=name: order.append(name) or {"performed": True})
            targets.append(devices.Target({"device_id": name}, client, [entry], False))
        verb = devices.acts(library, targets, None)[0]

        with patch.object(devices.confirm, "ask", new=AsyncMock(return_value=True)), \
                patch.object(devices.offload, "io",
                             new=AsyncMock(side_effect=lambda call, *a: call(*a))), \
                patch.object(devices.ui, "notify"):
            assert verb.run is not None
            await press(verb.run)

        self.assertEqual(order, ["there", "here"])


if __name__ == "__main__":
    unittest.main()
