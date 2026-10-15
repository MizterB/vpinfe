"""A panel page below 760 px, in a real browser: the list takes the width, a picked row opens
its panel full width with a Back arrow, and a wide window shows both side by side.

Slow: boots a real instance and a real browser.
"""

from __future__ import annotations

import asyncio
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tests.support.browser_session import BrowserSession, chromium_path
from tests.support.library import game_info, write_game
from tests.support.live_instance import LiveInstance
from tests.support.manager_walk import ManagerWalk

WIDE, NARROW = 1400, 700
ROW = (".ag-center-cols-container .ag-row[row-index=\"%d\"] "
       ".ag-cell:not([col-id=\"ag-Grid-SelectionColumn\"])")
NEXT = ".manager-panel-header .q-btn"
FOCUSED = ("(() => { const el = document.querySelector('.nicegui-aggrid');"
           " const api = getElement(Number(el.id.slice(1))).api;"
           " const node = api.getRowNode(api.getGridOption('context').focusId);"
           " return node.rowIndex; })()")
SHOWN = ("(() => { const box = (selector) => { const el = document.querySelector(selector);"
         " if (!el) return null; const at = el.getBoundingClientRect();"
         " return at.width > 0 && getComputedStyle(el).display !== 'none' ? at.width : 0; };"
         " return {list: box('.manager-pane-box > .q-splitter__before'),"
         " panel: box('.manager-pane-box > .q-splitter__after'),"
         " back: box('.manager-pane-back'),"
         " box: box('.manager-pane-box')}; })()")
ROWS = "document.querySelectorAll('.ag-center-cols-container .ag-row').length > 0"


class PanelPagesStackDrive(unittest.TestCase):
    seen: dict[str, dict] = {}

    @classmethod
    def setUpClass(cls) -> None:
        if not chromium_path():
            raise unittest.SkipTest("no Chromium on this machine")
        with TemporaryDirectory() as tmp:
            for title in ("Alpha", "Bravo", "Charlie", "Delta"):
                write_game(Path(tmp), title,
                           info=game_info(title, vps_id="", game_id=title.lower()),
                           files={f"{title}.ini": b"[Player]"})
            with LiveInstance(Path(tmp)) as instance:
                cls.seen = asyncio.run(cls._drive(instance))

    @classmethod
    async def _drive(cls, instance: LiveInstance) -> dict[str, dict]:
        seen: dict[str, dict] = {}
        instance.wait_for_api()
        async with BrowserSession(chromium_path() or "") as browser:
            walk = ManagerWalk(browser, instance)

            async def window(width: int) -> None:
                await browser.send("Emulation.setDeviceMetricsOverride",
                                   {"width": width, "height": 800, "deviceScaleFactor": 1,
                                    "mobile": False})

            await window(NARROW)
            await walk.visit("/manager?view=games")
            await browser.wait_for(ROWS)
            seen["narrow list"] = await browser.evaluate(SHOWN)
            await browser.click(ROW % 1)
            await browser.wait_for(
                "!!document.querySelector('.manager-pane-box.manager-opened')")
            seen["narrow panel"] = await browser.evaluate(SHOWN)
            seen["stepped from"] = {"row": await browser.evaluate(FOCUSED)}
            await browser.click(NEXT, nth=2)
            await browser.wait_for(f"{FOCUSED} !== {seen['stepped from']['row']}")
            seen["stepped to"] = {"row": await browser.evaluate(FOCUSED)}
            await browser.click(".manager-pane-back")
            await browser.wait_for(
                "!document.querySelector('.manager-pane-box.manager-opened')")
            seen["narrow back"] = await browser.evaluate(SHOWN)

            await window(WIDE)
            await browser.wait_for(
                f"innerWidth === {WIDE} && document.querySelector("
                "'.manager-pane-box > .q-splitter__after').getBoundingClientRect().width > 0")
            seen["wide"] = await browser.evaluate(SHOWN)
        return seen

    def test_a_narrow_window_shows_the_list_alone(self) -> None:
        shown = self.seen["narrow list"]
        self.assertEqual(shown["list"], shown["box"])
        self.assertFalse(shown["panel"])
        self.assertFalse(shown["back"])

    def test_a_picked_row_opens_its_panel_full_width_with_a_back_arrow(self) -> None:
        shown = self.seen["narrow panel"]
        self.assertEqual(shown["panel"], shown["box"])
        self.assertFalse(shown["list"])
        self.assertTrue(shown["back"])

    def test_next_in_the_panel_steps_from_the_row_that_was_picked(self) -> None:
        self.assertEqual(self.seen["stepped from"]["row"], 1)
        self.assertEqual(self.seen["stepped to"]["row"], 2)

    def test_back_returns_to_the_list(self) -> None:
        shown = self.seen["narrow back"]
        self.assertEqual(shown["list"], shown["box"])
        self.assertFalse(shown["panel"])

    def test_a_wide_window_shows_both_with_no_back_arrow(self) -> None:
        shown = self.seen["wide"]
        self.assertGreater(shown["list"], 0)
        self.assertGreater(shown["panel"], 0)
        self.assertFalse(shown["back"])


if __name__ == "__main__":
    unittest.main()
