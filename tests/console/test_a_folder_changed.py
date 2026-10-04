"""A Library folders row saved from its panel: the page is drawn again with the row
kept, and the panel is built after that draw, because the draw empties it."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import AsyncMock, patch

from console import workbench


class FolderChanged(unittest.IsolatedAsyncioTestCase):
    async def test_the_grid_lands_on_the_row_then_is_drawn_and_the_panel_rebuilt(self) -> None:
        order: list[str] = []
        context: dict[str, Any] = {
            "location": {"location_id": "loc-1"},
            "state": {"rerender": lambda: order.append("redraw")},
            "rebuild": AsyncMock(side_effect=lambda: order.append("rebuild")),
        }
        with patch.object(workbench.grid, "land_on",
                          side_effect=lambda *_: order.append("land")) as landed:
            await workbench._folders_changed(context)

        landed.assert_called_once_with(workbench.locations_page.SCOPE, {"id": "loc-1"})
        self.assertEqual(order, ["land", "redraw", "rebuild"])


if __name__ == "__main__":
    unittest.main()
