"""What a launcher's Setup section does after it writes."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, Mock, patch

from console import workbench

LAUNCHER = {"launcher_id": "wide", "display_name": "VPX (4K)", "app_name": "Visual Pinball X",
            "app": "vpx", "enabled": True, "settings": {}, "fields": []}


class TroubleRecheck(unittest.IsolatedAsyncioTestCase):
    async def _rename(self, *, fails: bool = False) -> AsyncMock:
        recheck = AsyncMock()
        context = {"library": Mock(), "launcher": LAUNCHER, "launchers": [LAUNCHER, {}],
                   "state": {"recheck_trouble": recheck}, "defaults": {},
                   "rebuild": AsyncMock()}
        put = AsyncMock(side_effect=RuntimeError("refused") if fails else None)
        with patch.object(workbench, "ui"), patch.object(workbench, "_rows"), \
                patch.object(workbench.run, "io_bound", new=put), \
                patch.object(workbench.panel, "field") as field:
            await workbench._launcher_setup(context)
            await field.call_args.args[1]("Wide")
        return recheck

    async def test_a_saved_change_rechecks_the_badge(self) -> None:
        (await self._rename()).assert_awaited_once()

    async def test_a_refused_one_does_not(self) -> None:
        (await self._rename(fails=True)).assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
