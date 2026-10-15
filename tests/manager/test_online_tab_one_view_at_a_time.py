"""The online tab shows a game's files or the search for another game, never both."""

from __future__ import annotations

import asyncio
import unittest
from typing import Any
from unittest.mock import Mock, patch

from nicegui import ui

from common.i18n import t
from manager import mediasource

_PAGE = ui.element()


async def _now(callback: Any, *args: Any, **kwargs: Any) -> Any:
    return callback(*args, **kwargs)


def _slot(vps_id: str = "own") -> mediasource._Slot:
    library = Mock()
    library.media_sources.return_value = []
    library.media_offers.return_value = []
    context = {"library": library, "game_id": "g-1", "lens": None,
               "game": {"name": "Own Game", "vps_id": vps_id}}
    return mediasource._Slot(context, "wheel", "Wheel", Mock(), Mock())


def _buttons(element: ui.element) -> list[str]:
    return [one.text for one in element.descendants() if isinstance(one, ui.button)]


class TheOnlineTab(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        patched = patch("manager.offload.run.io_bound", new=_now)
        patched.start()
        self.addCleanup(patched.stop)
        self.probe = _slot()
        with _PAGE:
            body = ui.column()
        await self.probe.online_tab(body)

    def _shown(self) -> tuple[bool, bool]:
        return self.probe.offers_view.visible, self.probe.search_view.visible

    async def test_opens_on_the_files(self) -> None:
        self.assertEqual((True, False), self._shown())

    async def test_the_search_takes_the_tab_from_the_files(self) -> None:
        self.probe._show_search()
        self.assertEqual((False, True), self._shown())

    async def test_back_returns_to_the_files(self) -> None:
        self.probe._show_search()
        self.probe._show_files()
        self.assertEqual((True, False), self._shown())

    async def test_a_game_picked_from_the_search_shows_its_files(self) -> None:
        self.probe._show_search()
        await self.probe._show_offers(self.probe.online_body, "other", "Other Game")

        self.assertEqual((True, False), self._shown())
        self.assertEqual(t("manager.mediasource.online_title", name="Other Game"),
                         self.probe.online_head.text)

    async def test_another_games_files_offer_the_way_back_to_this_ones(self) -> None:
        way_back = t("manager.mediasource.back_to_own", name="Own Game")
        self.assertNotIn(way_back, _buttons(self.probe.switch_row))

        await self.probe._show_offers(self.probe.online_body, "other", "Other Game")
        self.assertIn(way_back, _buttons(self.probe.switch_row))

        await self.probe._back_to_own()
        self.assertNotIn(way_back, _buttons(self.probe.switch_row))
        self.assertEqual(t("manager.mediasource.found_online"), self.probe.online_head.text)

    async def test_the_search_is_focused_when_it_opens(self) -> None:
        with patch.object(self.probe.search_box, "run_method") as run:
            self.probe._show_search()
        run.assert_called_once_with("focus")

    async def test_a_game_with_no_id_offers_the_search_and_no_way_back(self) -> None:
        probe = _slot(vps_id="")
        with _PAGE:
            body = ui.column()
        await probe.online_tab(body)

        self.assertEqual([t("manager.mediasource.other_game")], _buttons(probe.switch_row))
        self.assertIn(t("manager.mediasource.needs_id"), [
            one.text for one in probe.online_body.descendants() if isinstance(one, ui.label)])

    async def test_a_slower_earlier_load_draws_nothing(self) -> None:
        gate = asyncio.Event()

        async def gated(callback: Any, *args: Any, **kwargs: Any) -> Any:
            if args and args[0] == "other":
                await gate.wait()
            return callback(*args, **kwargs)

        self.probe.library.media_offers.side_effect = lambda vps_id, _kind: (
            [{"id": "x", "name": "from-other.png", "source": "x"}] if vps_id == "other" else [])
        with patch("manager.offload.run.io_bound", new=gated):
            slow = asyncio.ensure_future(self.probe._show_offers(
                self.probe.online_body, "other", "Other Game"))
            await asyncio.sleep(0)
            await self.probe._show_offers(self.probe.online_body, "own", "Own Game")
            gate.set()
            await slow

        drawn = [one.text for one in self.probe.online_body.descendants()
                 if isinstance(one, ui.label)]
        self.assertNotIn("from-other.png", drawn)
        self.assertEqual(t("manager.mediasource.found_online"), self.probe.online_head.text)


if __name__ == "__main__":
    unittest.main()
