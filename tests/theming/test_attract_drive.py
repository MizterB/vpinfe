"""Attract mode: core moves the wheel when nobody has, and gives it back when someone does.

Driven in a real browser against a real backend, because the moving parts are a timer in
the page, a setting read over the bridge, and the key press that has to cancel it. Each
piece has a unit-sized reason to pass on its own; only the whole shows the wheel move.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import unittest
import urllib.request
from pathlib import Path
from tempfile import TemporaryDirectory

from tests.support.browser_session import BrowserSession, chromium_path
from tests.support.library import TempTree, write_game
from tests.support.live_instance import HARNESS_THEME, LiveInstance

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000100fd5c9a6b0000000049454e44ae426082")

GAMES = ("Alpha Table", "Beta Table", "Gamma Table", "Delta Table")

# Written to the ini directly, below the range the Manager offers, so a test waits seconds
# and not a minute.
FAST = {("behavior", "attract_idle"): 1, ("behavior", "attract_step_time"): 1,
        ("behavior", "attract_order"): "in_order"}

# The settings a test can change over the Manager's API, which refuses the timings above.
CHANGEABLE = {"attract_enabled": True, "attract_order": "in_order",
              "attract_on_return": "restore"}

# A check that the wheel stayed still waits as long as attract could have started and
# stepped twice: FAST's idle time plus two steps, with a second to spare.
QUIET_WINDOW_S = 4
# A press that was not swallowed acts on the very next frame.
PRESS_ACTS_WITHIN_S = 0.5

# Wraps moveTo before attract can call it, so the page keeps a record of who moved it.
RECORD = """
(() => {
  window.__moves = [];
  const was = vpin.moveTo.bind(vpin);
  vpin.moveTo = (index, options = {}) => {
    window.__moves.push({index, source: options.source || "user", reason: options.reason || ""});
    return was(index, options);
  };
})()
"""

SELECTED = "Number(document.body.dataset.selected)"
ATTRACTING = "window.vpin.attractActive"


def _info(name: str) -> dict:
    return {"Info": {"Name": name}, "VPinFE": {}, "User": {}}


def _write_library(root: Path) -> None:
    for name in GAMES:
        write_game(root, name, info=_info(name), medias={"wheel.png": PNG, "table.png": PNG})


def _save(instance: LiveInstance, **changes) -> None:
    request = urllib.request.Request(
        f"http://127.0.0.1:{instance.ports['manager']}/api/v1/config",
        data=json.dumps({"settings": {"behavior": changes}}).encode(), method="PUT",
        headers={"Content-Type": "application/json"})
    urllib.request.urlopen(request, timeout=10).close()


async def _open(instance: LiveInstance, browser: BrowserSession) -> None:
    await browser.navigate(instance.theme_url("playfield"))
    await browser.wait_for("document.body.dataset.ready === 'true'", timeout=90.0)
    await browser.evaluate(RECORD)


def _theme_dir(instance: LiveInstance) -> Path:
    return instance.config_dir / "frontend_themes" / instance.theme


@unittest.skipIf(chromium_path() is None, "no Chromium on this machine")
class AttractDriveTests(unittest.TestCase):
    """Settings and the theme's two files are read when a page loads, and each test loads
    its own, so putting them back before each test is all the isolation it needs."""

    shared: LiveInstance

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        tmp = TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        _write_library(Path(tmp.name))
        cls.shared = cls.enterClassContext(LiveInstance(Path(tmp.name), extra_settings=FAST))
        cls.shared.wait_for_api()

    def setUp(self) -> None:
        super().setUp()
        theme = _theme_dir(self.shared)
        shutil.copyfile(HARNESS_THEME / "manifest.json", theme / "manifest.json")
        (theme / "config.json").unlink(missing_ok=True)
        _save(self.shared, **CHANGEABLE)

    def _drive(self, scenario, settings=None, *, prepare=None):
        async def run(instance: LiveInstance):
            async with BrowserSession(chromium_path() or "") as browser:
                await _open(instance, browser)
                return await scenario(browser)

        if settings:
            assert set(settings) <= set(CHANGEABLE), "setUp would not put this back"
            _save(self.shared, **settings)
        if prepare:
            prepare(_theme_dir(self.shared))
        return asyncio.run(run(self.shared))

    # -- on -----------------------------------------------------------------

    def test_an_idle_wheel_moves_and_says_it_was_attract(self) -> None:
        async def scenario(browser):
            await browser.wait_for(ATTRACTING, timeout=30.0)
            await browser.wait_for("window.__moves.length >= 2", timeout=30.0)
            return await browser.evaluate("window.__moves")

        moves = self._drive(scenario)
        self.assertTrue(all(move["source"] == "attract" for move in moves), moves)

    def test_in_order_walks_the_whole_list(self) -> None:
        async def scenario(browser):
            await browser.wait_for("window.__moves.length >= 4", timeout=30.0)
            return await browser.evaluate("window.__moves.slice(0, 4).map(m => m.index)")

        indexes = self._drive(scenario)
        self.assertEqual(indexes, [1, 2, 3, 0])

    def test_random_visits_every_other_game_before_repeating_one(self) -> None:
        async def scenario(browser):
            await browser.wait_for("window.__moves.length >= 3", timeout=40.0)
            return await browser.evaluate("window.__moves.slice(0, 3).map(m => m.index)")

        indexes = self._drive(scenario, {"attract_order": "random"})
        self.assertEqual(sorted(indexes), [1, 2, 3], indexes)

    def test_a_press_puts_the_wheel_back_and_does_nothing_else(self) -> None:
        async def scenario(browser):
            await browser.wait_for("window.__moves.length >= 2", timeout=30.0)
            await browser.press("ArrowRight", "ArrowRight")
            await browser.wait_for(f"!{ATTRACTING}", timeout=10.0)
            await browser.wait_for(f"{SELECTED} === 0", timeout=10.0)
            # Long enough for a press that was not swallowed to have moved it on.
            await asyncio.sleep(PRESS_ACTS_WITHIN_S)
            return (await browser.evaluate(SELECTED),
                    await browser.evaluate("window.__moves.filter(m => m.source === 'user')"))

        selected, by_user = self._drive(scenario)
        self.assertEqual(selected, 0)
        self.assertEqual([move["reason"] for move in by_user], ["restore"])

    def test_the_next_press_is_an_ordinary_one(self) -> None:
        async def scenario(browser):
            await browser.wait_for("window.__moves.length >= 2", timeout=30.0)
            await browser.press("ArrowRight", "ArrowRight")
            await browser.wait_for(f"!{ATTRACTING} && {SELECTED} === 0", timeout=10.0)
            await browser.press("ArrowRight", "ArrowRight")
            return await browser.wait_for(
                "window.__moves.filter(m => m.source === 'user' && m.reason !== 'restore')"
                ".length === 1 && 'moved'", timeout=10.0)

        self.assertEqual(self._drive(scenario), "moved")

    def test_stay_leaves_the_wheel_where_attract_stopped_it_and_swallows_the_press(self) -> None:
        async def scenario(browser):
            await browser.wait_for("window.__moves.length >= 2", timeout=30.0)
            await browser.press("ArrowRight", "ArrowRight")
            await browser.wait_for(f"!{ATTRACTING}", timeout=10.0)
            await asyncio.sleep(PRESS_ACTS_WITHIN_S)
            return await browser.evaluate(
                "window.__moves.filter(m => m.source === 'user')")

        by_user = self._drive(scenario, {"attract_on_return": "stay"})
        self.assertEqual(by_user, [])

    def test_it_starts_again_after_the_press(self) -> None:
        async def scenario(browser):
            await browser.wait_for(ATTRACTING, timeout=30.0)
            await browser.press("ArrowRight", "ArrowRight")
            await browser.wait_for(f"!{ATTRACTING}", timeout=10.0)
            return await browser.wait_for(f"{ATTRACTING} && 'again'", timeout=30.0)

        self.assertEqual(self._drive(scenario), "again")

    # -- held off -----------------------------------------------------------

    def test_a_theme_can_hold_it_off_and_let_go(self) -> None:
        async def scenario(browser):
            await browser.evaluate("vpin.suspendAttract('theme')")
            await asyncio.sleep(QUIET_WINDOW_S)
            held = await browser.evaluate(ATTRACTING)
            await browser.evaluate("vpin.resumeAttract('theme')")
            await browser.wait_for(ATTRACTING, timeout=30.0)
            return held

        self.assertFalse(self._drive(scenario))

    def test_it_runs_again_only_when_every_reason_has_let_go(self) -> None:
        async def scenario(browser):
            await browser.evaluate("vpin.suspendAttract('a'); vpin.suspendAttract('b')")
            await browser.evaluate("vpin.resumeAttract('a')")
            await asyncio.sleep(QUIET_WINDOW_S)
            return await browser.evaluate(ATTRACTING)

        self.assertFalse(self._drive(scenario))

    def test_suspending_stops_the_wheel_that_is_moving(self) -> None:
        async def scenario(browser):
            await browser.wait_for(ATTRACTING, timeout=30.0)
            await browser.evaluate("vpin.suspendAttract('theme')")
            count = await browser.evaluate("window.__moves.length")
            await asyncio.sleep(QUIET_WINDOW_S)
            return count, await browser.evaluate("window.__moves.length")

        before, after = self._drive(scenario)
        self.assertEqual(before, after)

    # -- off ----------------------------------------------------------------

    def _stays_still(self, settings=None, *, prepare=None) -> int:
        async def scenario(browser):
            await asyncio.sleep(QUIET_WINDOW_S)
            return await browser.evaluate("window.__moves.length")

        return self._drive(scenario, settings, prepare=prepare)

    def test_the_person_s_switch_turns_it_off(self) -> None:
        self.assertEqual(self._stays_still({"attract_enabled": False}), 0)

    def test_a_theme_can_turn_it_off_for_itself(self) -> None:
        def opt_out(theme):
            (theme / "config.json").write_text(json.dumps({"attract": {"enabled": False}}))

        self.assertEqual(self._stays_still(prepare=opt_out), 0)

    def test_a_contract_1_theme_gets_none_unless_it_asks(self) -> None:
        def contract_1(theme):
            manifest = json.loads((theme / "manifest.json").read_text())
            manifest.pop("min_vpinfe")
            (theme / "manifest.json").write_text(json.dumps(manifest))

        self.assertEqual(self._stays_still(prepare=contract_1), 0)

    def test_a_contract_1_theme_can_ask_for_it(self) -> None:
        def contract_1_asking(theme):
            manifest = json.loads((theme / "manifest.json").read_text())
            manifest.pop("min_vpinfe")
            (theme / "manifest.json").write_text(json.dumps(manifest))
            (theme / "config.json").write_text(json.dumps({"attract": {"enabled": True}}))

        self.assertGreater(self._stays_still(prepare=contract_1_asking), 0)


@unittest.skipIf(chromium_path() is None, "no Chromium on this machine")
class AttractChangedWhileOpenTests(TempTree):
    BOOTS_PER_TEST = ("It raises the step time through the Manager's API, which has no way "
                      "to lower it again for the next test.")

    def test_a_change_saved_while_the_page_is_open_applies_without_reopening_it(self) -> None:
        _write_library(self.root)

        async def run(instance: LiveInstance):
            async with BrowserSession(chromium_path() or "") as browser:
                await _open(instance, browser)
                await asyncio.sleep(QUIET_WINDOW_S)
                still = await browser.evaluate("window.__moves.length")
                _save(instance, attract_enabled=True)
                await browser.wait_for(ATTRACTING, timeout=30.0)
                _save(instance, attract_step_time=2)
                await asyncio.sleep(PRESS_ACTS_WITHIN_S)
                kept = await browser.evaluate(ATTRACTING)
                _save(instance, attract_enabled=False)
                await browser.wait_for(f"!{ATTRACTING}", timeout=30.0)
                await browser.wait_for(f"{SELECTED} === 0", timeout=10.0)
                return still, kept

        with LiveInstance(self.root, extra_settings={
                **FAST, ("behavior", "attract_enabled"): False}) as instance:
            instance.wait_for_api()
            still, kept = asyncio.run(run(instance))
        self.assertEqual(still, 0)
        self.assertTrue(kept, "a new step time does not end the run in progress")


if __name__ == "__main__":
    unittest.main()
