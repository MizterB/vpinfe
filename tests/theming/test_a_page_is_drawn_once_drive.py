"""Every Console view and the remote are drawn once, in a real browser: no listener
reaches a layout the browser already has, which NiceGUI answers by drawing all of it
again.

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

DRAWN_AGAIN = "Event listeners changed after initial definition"
RAIL = "[...document.querySelectorAll('a.console-nav-row')].map(a => a.getAttribute('href'))"


class PagesDrawnOnce(unittest.TestCase):
    seen: dict = {}

    @classmethod
    def setUpClass(cls) -> None:
        if not chromium_path():
            raise unittest.SkipTest("no Chromium on this machine")
        with TemporaryDirectory() as tmp:
            write_game(Path(tmp), "Alpha",
                       info=game_info("Alpha", vps_id="", game_id="alpha"))
            with LiveInstance(Path(tmp)) as instance:
                cls.seen = asyncio.run(cls._drive(instance))

    @classmethod
    async def _drive(cls, instance: LiveInstance) -> dict:
        seen: dict = {}
        instance.wait_for_api()
        async with BrowserSession(chromium_path()) as browser:
            async def visit(path: str) -> list[str]:
                await browser.evaluate("window.__left = true")
                browser.console.clear()
                await browser.navigate(instance.console_url(path))
                await browser.wait_for("!window.__left && window.did_handshake", timeout=90.0)
                await asyncio.sleep(3.0)
                return [line for line in browser.console if DRAWN_AGAIN in line]

            seen["/console"] = await visit("/console")
            for path in await browser.evaluate(RAIL):
                seen[path] = await visit(path)
            seen["/remote"] = await visit("/remote")
        return seen

    def test_every_console_view_is_drawn_once(self) -> None:
        views = {path: said for path, said in self.seen.items()
                 if path.startswith("/console?view=")}
        self.assertGreater(len(views), 5, sorted(self.seen))
        self.assertEqual({}, {path: said for path, said in views.items() if said})

    def test_the_bare_address_is_drawn_once(self) -> None:
        self.assertEqual([], self.seen["/console"])

    def test_the_remote_is_drawn_once(self) -> None:
        self.assertEqual([], self.seen["/remote"])


if __name__ == "__main__":
    unittest.main()
