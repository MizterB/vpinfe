"""The open device's panel says what the probe found, on a fresh load of Devices.

The panel is already drawn when the first answer lands, so it has to be redrawn from the
probe's own task. Slow: boots a real instance and a real browser.
"""

from __future__ import annotations

import asyncio
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tests.support.browser_session import BrowserSession, chromium_path
from tests.support.console_walk import ConsoleWalk
from tests.support.live_instance import LiveInstance

# The panel's State and the grid's cell, each by its words.
PANEL = "[...document.querySelectorAll('.console-tier')].map(el => el.innerText.trim())"
GRID = "[...document.querySelectorAll('.ag-cell')].map(el => el.innerText.trim())"
PANEL_ANSWERS = f"{GRID}.includes('Answering') && {PANEL}.includes('Answering')"


class DevicePanelReachDrive(unittest.TestCase):
    answered = False

    @classmethod
    def setUpClass(cls) -> None:
        if not chromium_path():
            raise unittest.SkipTest("no Chromium on this machine")
        with TemporaryDirectory() as tmp, LiveInstance(Path(tmp)) as instance:
            cls.answered = asyncio.run(cls._drive(instance))

    @classmethod
    async def _drive(cls, instance: LiveInstance) -> bool:
        instance.wait_for_api()
        async with BrowserSession(chromium_path()) as browser:
            await ConsoleWalk(browser, instance).visit("/console?view=devices")
            await browser.wait_for(PANEL_ANSWERS)
            return True

    def test_the_open_panel_says_answering_once_the_device_answers(self) -> None:
        self.assertTrue(self.answered)


if __name__ == "__main__":
    unittest.main()
