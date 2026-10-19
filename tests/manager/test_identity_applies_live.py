"""A feature switch is applied where the Manager stands: the shell follows, nothing reloads."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from common.devices import install_identity
from manager.kit import panel
from manager.settings import settings


class FeatureSwitchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.library = MagicMock()
        self.library.config_values.return_value = {
            "device": {"features": [install_identity.LIBRARY]}}
        self.calls: list[str] = []
        self.written = self.enterContext(patch.object(
            settings, "_write", new=AsyncMock(return_value=True)))
        self.enterContext(patch.object(
            settings.offload, "io",
            new=AsyncMock(side_effect=lambda call, *args, **kwargs: call(*args, **kwargs))))
        self.enterContext(patch("manager.kit.on_page.ui"))
        self.ui = self.enterContext(patch.object(settings, "ui"))
        self.enterContext(patch.object(settings.config_schema, "option", return_value=None))
        for name in ("facts", "field", "note", "intro", "action"):
            self.enterContext(patch.object(panel, name))
        self.select = self.enterContext(patch.object(panel, "select"))
        self.switch = self.enterContext(patch.object(panel, "switch"))
        self.state: dict[str, Any] = {
            "refresh_shell": AsyncMock(side_effect=lambda: self.calls.append("shell")),
            "reindex_settings": Mock(side_effect=lambda: self.calls.append("index"))}

    async def _page(self) -> dict[str, Any]:
        """The feature switches the page drew, by feature."""
        await settings._identity_page(self.library, "host", Mock(), self.state)
        names = list(install_identity.FEATURES)
        return {name: call.args[1] for name, call in zip(
            names, self.switch.call_args_list[-len(names):], strict=True)}

    async def test_a_switch_is_written_in_the_order_the_install_declares_them(self) -> None:
        switches = await self._page()

        await switches[install_identity.DEVICES](SimpleNamespace(value=True))

        self.written.assert_awaited_once_with(
            self.library, "device", "features",
            [install_identity.LIBRARY, install_identity.DEVICES])

    async def test_the_shell_reads_the_install_again_and_then_the_index_follows(self) -> None:
        switches = await self._page()

        await switches[install_identity.FRONTEND](SimpleNamespace(value=True))

        self.assertEqual(self.calls, ["shell", "index"])
        self.ui.navigate.reload.assert_not_called()

    async def test_a_refused_write_leaves_the_shell_as_it_was(self) -> None:
        self.written.return_value = False
        switches = await self._page()

        await switches[install_identity.FRONTEND](SimpleNamespace(value=True))

        self.assertEqual(self.calls, [])

    async def test_a_second_switch_builds_on_the_first(self) -> None:
        switches = await self._page()
        first, second = install_identity.DEVICES, install_identity.FRONTEND

        await switches[first](SimpleNamespace(value=True))
        await switches[second](SimpleNamespace(value=True))

        self.assertEqual(self.written.call_args.args[3],
                         [install_identity.LIBRARY, install_identity.FRONTEND,
                          install_identity.DEVICES])

    async def test_a_language_is_saved_and_its_restart_chip_drawn_without_a_reload(self) -> None:
        option = SimpleNamespace(label="Language", key="language", section="device",
                                 choices=("auto", "en"), choice_labels={},
                                 default="auto", description="")
        chips = self.enterContext(patch.object(settings, "Waiting"))
        chips.return_value.refresh = AsyncMock()
        self.enterContext(patch.object(settings, "_waiting", new=AsyncMock(return_value={})))
        self.enterContext(patch.object(settings.config_schema, "option", return_value=option))

        await settings._identity_page(self.library, "host", Mock(), self.state)
        picked = self.select.call_args.args[2]
        await picked(SimpleNamespace(value="en"))

        self.written.assert_awaited_once_with(self.library, "device", "language", "en")
        chips.return_value.refresh.assert_awaited_once()
        self.ui.navigate.reload.assert_not_called()

    async def test_a_page_with_no_shell_to_tell_still_writes(self) -> None:
        self.state.clear()
        switches = await self._page()

        await switches[install_identity.FRONTEND](SimpleNamespace(value=True))

        self.written.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
