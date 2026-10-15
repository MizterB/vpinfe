"""The Console's nav rail at the widths a window can have, in a real browser.

Under a desk-sized window the rail gives up its labels, and at any width it stays beside the
page rather than over it. Slow: boots a real instance and a real browser.
"""

from __future__ import annotations

import asyncio
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tests.support.browser_session import BrowserSession, chromium_path
from tests.support.console_walk import ConsoleWalk
from tests.support.live_instance import LiveInstance

WIDTHS = (1500, 1050, 900, 500)
RAIL = ("(() => { const drawer = document.querySelector('.q-drawer');"
        " return {width: drawer.getBoundingClientRect().width,"
        " mini: drawer.classList.contains('q-drawer--mini'),"
        " overlay: drawer.classList.contains('q-drawer--mobile'),"
        " backdrop: !!document.querySelector('.q-drawer__backdrop'),"
        " title: getComputedStyle(document.querySelector('.console-nav-title')).display}; })()")


class NavRailWidthDrive(unittest.TestCase):
    seen: dict[int, dict] = {}

    @classmethod
    def setUpClass(cls) -> None:
        if not chromium_path():
            raise unittest.SkipTest("no Chromium on this machine")
        with TemporaryDirectory() as tmp, LiveInstance(Path(tmp)) as instance:
            cls.seen = asyncio.run(cls._drive(instance))

    @classmethod
    async def _drive(cls, instance: LiveInstance) -> dict[int, dict]:
        seen: dict[int, dict] = {}
        instance.wait_for_api()
        async with BrowserSession(chromium_path() or "") as browser:
            walk = ConsoleWalk(browser, instance)
            for width in WIDTHS:
                await browser.send("Emulation.setDeviceMetricsOverride",
                                   {"width": width, "height": 800, "deviceScaleFactor": 1,
                                    "mobile": False})
                await walk.visit("/console?view=devices")
                seen[width] = await browser.evaluate(RAIL)
        return seen

    def test_a_wide_window_shows_the_rail_in_full(self) -> None:
        self.assertEqual(self.seen[1500]["width"], 252)
        self.assertFalse(self.seen[1500]["mini"])
        self.assertEqual(self.seen[1500]["title"], "block")

    def test_a_narrow_window_shows_the_icon_rail_beside_the_page_at_every_width(self) -> None:
        for width in (1050, 900, 500):
            with self.subTest(width=width):
                shown = self.seen[width]
                self.assertEqual(shown["width"], 57)
                self.assertTrue(shown["mini"])
                self.assertFalse(shown["overlay"])
                self.assertFalse(shown["backdrop"])
                self.assertEqual(shown["title"], "none")


if __name__ == "__main__":
    unittest.main()
