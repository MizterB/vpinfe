"""A Manager opened from another device hears the controller and keys of the device it
serves: the row listens, the controller window's button or key reaches it, and the row
stores it.

Slow: boots a real instance and two real browsers, one standing for the other device's
Manager (reached by this machine's network address, so the server sees it as elsewhere) and
one for the controller window. Chrome has no controller, so one is stood in for on
`navigator.getGamepads`.
"""

from __future__ import annotations

import asyncio
import json
import socket
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from common.i18n import t
from tests.support.browser_session import BrowserSession, chromium_path
from tests.support.library import game_info, write_game
from tests.support.live_instance import LiveInstance
from tests.support.manager_walk import DRAWN

PAGE = "/manager?view=settings&page=hardware.input"


def _row(label: str) -> str:
    return ("[...document.querySelectorAll('.manager-binding-row')].find(row =>"
            f" row.querySelector('.manager-binding-label').textContent.trim() === '{label}')")


def _listening(label: str) -> str:
    return ("(row => !!row && row.classList.contains('manager-binding-row--listening'))"
            f"({_row(label)})")


LABELS = ("[...document.querySelectorAll('.manager-binding-row .manager-binding-label')]"
          ".map(el => el.textContent.trim())")
WORDS = "document.querySelector('.manager-bindings').parentElement.innerText"
PAD = """(() => {
  window.__pad = {index: 0, mapping: 'standard', id: 'Stand-in',
                  buttons: Array.from({length: 17}, () => ({pressed: false}))};
  Object.defineProperty(navigator, 'getGamepads',
                        {configurable: true, value: () => [window.__pad]});
})()"""
ARMED_FOR_THE_PAD_BY = 8.0
# The page reads a controller every 40ms, so a button held this long has been seen.
PAD_READ_S = 0.3
SAVED_POLL_S = 0.25
NOTE = t("manager.binding_table.no_frontend")
RELAYED_KEY = "F9"


def _this_machines_address() -> str | None:
    """The address another device would reach this machine by, or None if it has none."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))
        address = probe.getsockname()[0]
    except OSError:
        return None
    finally:
        probe.close()
    return None if address.startswith("127.") else address


class InputRelayDrive(unittest.TestCase):
    seen: dict = {}
    address: str | None = None

    @classmethod
    def setUpClass(cls) -> None:
        if not chromium_path():
            raise unittest.SkipTest("no Chromium on this machine")
        cls.address = _this_machines_address()
        if cls.address is None:
            raise unittest.SkipTest("this machine has no address another device could use")
        with TemporaryDirectory() as tmp:
            write_game(Path(tmp), "Alpha", info=game_info("Alpha", vps_id="", game_id="alpha"))
            with LiveInstance(Path(tmp)) as instance:
                cls.seen = asyncio.run(cls._drive(instance))

    @classmethod
    async def _drive(cls, instance: LiveInstance) -> dict:
        instance.wait_for_api()
        seen: dict = {}
        manager_at = f"http://{cls.address}:{instance.ports['manager']}{PAGE}"

        def stored(action: str) -> list[str]:
            value = instance.api("/api/v1/config/settings")["input"][action]
            return value.split(",") if isinstance(value, str) else list(value)

        async def listen(manager: BrowserSession, label: str) -> None:
            nth = await manager.evaluate(f"{LABELS}.indexOf('{label}')")
            await manager.click(".manager-binding-row .manager-binding-label", nth=nth)
            await manager.wait_for(_listening(label))

        async def saved(manager: BrowserSession, label: str, action: str, before: list[str]):
            await manager.wait_for(f"!({_listening(label)})", timeout=ARMED_FOR_THE_PAD_BY)
            after = before
            for _ in range(40):
                after = stored(action)
                if after != before:
                    break
                await asyncio.sleep(SAVED_POLL_S)
            return after

        async with BrowserSession(chromium_path() or "") as controller, \
                BrowserSession(chromium_path() or "") as manager:
            await manager.navigate(manager_at)
            await manager.wait_for(DRAWN)
            await manager.wait_for(f"!!{_row('Next')}")
            seen["before"] = stored("next")

            await listen(manager, "Next")
            seen["words_with_no_controller_window"] = await manager.evaluate(WORDS)

            await controller.navigate(instance.theme_url("playfield"))
            await controller.wait_for("window.vpin && window.vpin.contract !== undefined")
            await controller.evaluate(PAD)
            await manager.wait_for(f"!{WORDS}.includes({json.dumps(NOTE)})",
                                   timeout=ARMED_FOR_THE_PAD_BY)
            await controller.wait_for("window.vpin._captureArmed === true",
                                      timeout=ARMED_FOR_THE_PAD_BY)

            await controller.evaluate("window.__pad.buttons[3] = {pressed: true}")
            await asyncio.sleep(PAD_READ_S)
            await controller.evaluate("window.__pad.buttons[3] = {pressed: false}")
            seen["after"] = await saved(manager, "Next", "next", seen["before"])
            seen["pad_acts_again"] = await controller.evaluate(
                "window.vpin._captureArmed === false")

            seen["keys_before"] = stored("previous")
            await listen(manager, "Previous")
            await controller.wait_for("window.vpin._captureArmed === true",
                                      timeout=ARMED_FOR_THE_PAD_BY)
            await controller.press(RELAYED_KEY, RELAYED_KEY)
            seen["keys_after"] = await saved(manager, "Previous", "previous",
                                             seen["keys_before"])
        return seen

    def test_a_press_on_the_controller_is_stored_by_the_row_that_listened(self) -> None:
        added = [one for one in self.seen["after"] if one not in self.seen["before"]]
        self.assertEqual(len(added), 1, self.seen)
        self.assertTrue(added[0].startswith("pad:standard/button:3"), added)

    def test_the_note_about_a_closed_frontend_shows_until_a_controller_window_is_up(self) -> None:
        self.assertIn(NOTE, self.seen["words_with_no_controller_window"])

    def test_a_key_on_the_controller_window_is_stored_by_the_row_that_listened(self) -> None:
        added = [one for one in self.seen["keys_after"] if one not in self.seen["keys_before"]]
        self.assertEqual(added, [f"key:{RELAYED_KEY}"], self.seen)

    def test_the_controller_window_stops_relaying_once_the_row_has_what_it_heard(self) -> None:
        self.assertTrue(self.seen["pad_acts_again"], self.seen)


if __name__ == "__main__":
    unittest.main()
