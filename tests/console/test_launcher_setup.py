"""What a launcher's Setup section does after it writes."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

from console import workbench

LAUNCHER = {"launcher_id": "wide", "display_name": "VPX (4K)", "app_name": "Visual Pinball X",
            "app": "vpx", "enabled": True, "settings": {}, "fields": []}


class Setup:
    """A launcher's Setup section drawn with its writes caught, and its controls' saves
    in hand."""

    def __init__(self, *, refused: str = "") -> None:
        self.launcher = dict(LAUNCHER)
        self.recheck, self.refresh, self.retitle = AsyncMock(), AsyncMock(), Mock()
        self.put = AsyncMock(side_effect=RuntimeError(refused) if refused else None)
        self.context: dict[str, Any] = {
            "library": Mock(), "launcher": self.launcher,
            "launchers": [self.launcher, {}], "defaults": {}, "rebuild": AsyncMock(),
            "retitle": self.retitle,
            "state": {"recheck_trouble": self.recheck, "refresh_launchers": self.refresh}}

    async def __aenter__(self) -> Setup:
        self._patches = [patch.object(workbench, "ui"), patch.object(workbench, "_rows"),
                         patch.object(workbench.run, "io_bound", new=self.put)]
        for one in self._patches:
            one.start()
        field = patch.object(workbench.panel, "field").start()
        switch = patch.object(workbench.panel, "switch").start()
        self._patches += [field, switch]
        await workbench._launcher_setup(self.context)
        self.rename = field.call_args.args[1]
        self.flip = switch.call_args.args[1]
        return self

    async def __aexit__(self, *_exc: object) -> None:
        patch.stopall()

    def sent(self) -> list[dict[str, Any]]:
        return [one.args[2] for one in self.put.await_args_list]


class TroubleRecheck(unittest.IsolatedAsyncioTestCase):
    async def test_a_saved_change_rechecks_the_badge(self) -> None:
        async with Setup() as setup:
            await setup.rename("Wide")
        setup.recheck.assert_awaited_once()

    async def test_a_refused_one_does_not(self) -> None:
        async with Setup(refused="refused") as setup:
            await setup.rename("Wide")
        setup.recheck.assert_not_awaited()


class Rename(unittest.IsolatedAsyncioTestCase):
    async def test_the_next_write_carries_the_new_name(self) -> None:
        async with Setup() as setup:
            await setup.rename("Wide")
            await setup.flip(Mock(value=True))
        self.assertEqual([one["display_name"] for one in setup.sent()], ["Wide", "Wide"])

    async def test_the_grid_and_the_title_follow_it(self) -> None:
        async with Setup() as setup:
            await setup.rename("Wide")
        setup.refresh.assert_awaited_once()
        setup.retitle.assert_called_once_with("Wide")

    async def test_a_refusal_is_the_fields_to_say(self) -> None:
        taken = "Another launcher is already called Wide."
        async with Setup(refused=taken) as setup:
            said = await setup.rename("Wide")
        self.assertEqual(said, taken)
        self.assertEqual(setup.launcher["display_name"], "VPX (4K)")
        setup.retitle.assert_not_called()

    async def test_the_same_name_writes_nothing(self) -> None:
        async with Setup() as setup:
            self.assertEqual(await setup.rename(" VPX (4K) "), "")
        setup.put.assert_not_awaited()

    async def test_blank_is_the_programs_name(self) -> None:
        async with Setup() as setup:
            await setup.rename("  ")
        self.assertEqual(setup.sent()[0]["display_name"], "Visual Pinball X")


if __name__ == "__main__":
    unittest.main()
