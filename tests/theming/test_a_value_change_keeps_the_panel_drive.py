"""A value changed on a Manager page leaves the page where it stands, in a real browser.

Slow: boots a real instance and a real browser. On each page, and in each section of its
panel, one control of each kind is changed. The page must not be taken again, dim, or lose
the landmarks it was standing on, whichever call the handler rebuilds through.
"""

from __future__ import annotations

import asyncio
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from tests.support import value_controls
from tests.support.browser_session import BrowserSession, chromium_path
from tests.support.library import game_info, write_game
from tests.support.live_instance import LiveInstance
from tests.support.manager_walk import ManagerWalk

VIEWS = ("settings", "games", "launchers", "collections", "devices", "logs")
GRIDS = ("games", "launchers")
ROW_CELL = ".ag-center-cols-container .ag-row .ag-cell"
PANE = "document.querySelector('.manager-sections') !== null"
ROWS = f"document.querySelector({ROW_CELL!r}) !== null"
KEEP_ALIVE_S = 0.4
LOAD_S = 30.0
KINDS_FLIPPED_BACK = ("toggle", "checkbox", "segmented", "select")
SETTINGS_SECTIONS = 5


@unittest.skipIf(chromium_path() is None, "no Chromium on this machine")
class ValueChangeKeepsThePanelDrive(unittest.TestCase):
    seen: list[dict[str, Any]] = []

    @classmethod
    def setUpClass(cls) -> None:
        binary = chromium_path()
        assert binary is not None
        with TemporaryDirectory() as tmp:
            for title in ("Alpha", "Bravo"):
                write_game(Path(tmp), title,
                           info=game_info(title, vps_id="", game_id=title.lower()),
                           files={f"{title}.ini": b"[Player]"})
            with LiveInstance(Path(tmp)) as instance:
                cls.seen = asyncio.run(cls._drive(instance, binary))

    @classmethod
    async def _drive(cls, instance: LiveInstance, binary: str) -> list[dict[str, Any]]:
        instance.wait_for_api()
        seen: list[dict[str, Any]] = []
        async with BrowserSession(binary) as browser:
            await browser.send("Emulation.setDeviceMetricsOverride",
                               {"width": 1800, "height": 1100, "deviceScaleFactor": 1,
                                "mobile": False})
            walk = ManagerWalk(browser, instance)
            for view in VIEWS:
                await walk.visit(f"/manager?view={view}")
                if view in GRIDS:
                    await browser.wait_for(ROWS, LOAD_S)
                await cls._change_each_kind(walk, browser, view, "page", seen)
                if view in GRIDS:
                    await cls._open_a_row(walk, browser)
                async for section in walk.sections():
                    await cls._change_each_kind(walk, browser, view, section, seen)
        return seen

    @staticmethod
    async def _open_a_row(walk: ManagerWalk, browser: BrowserSession) -> None:
        await browser.wait_for(ROWS, LOAD_S)
        await browser.click(ROW_CELL, nth=1)
        await browser.wait_for(PANE, LOAD_S)
        await walk.drawn()

    @staticmethod
    async def _change_each_kind(walk: ManagerWalk, browser: BrowserSession, view: str,
                                where: str, seen: list[dict[str, Any]]) -> None:
        in_pane = where != "page"
        tried: set[str] = set()
        skipped: set[value_controls.Control] = set()
        while True:
            # The page may have drawn its controls again, so what is there is read afresh.
            control = next((c for c in await value_controls.controls(browser, in_pane=in_pane)
                            if c not in skipped and c.kind not in tried), None)
            if control is None:
                return
            await value_controls.watch(browser)
            try:
                await value_controls.change(browser, control)
            except (AssertionError, ValueError, RuntimeError):
                await browser.escape()
                skipped.add(control)
                continue
            tried.add(control.kind)
            await asyncio.sleep(KEEP_ALIVE_S)
            await walk.listen()
            await walk.drawn()
            seen.append({"view": view, "where": where, "control": control.name,
                         **await value_controls.read(browser)})
            if control.kind in KINDS_FLIPPED_BACK:
                await value_controls.change(browser, control)
                await walk.drawn()

    def _each(self, failed: str) -> list[str]:
        return [f"{s['view']} > {s['where']} > {s['control']}" for s in self.seen
                if (failed == "reloaded" and s["reloaded"]
                    or failed == "dimmed" and not s["reloaded"] and (s["busy"] or s["dimmed"])
                    or failed == "landmarks" and not s["reloaded"]
                    and s["landmarksKept"] != s["landmarks"])]

    def test_every_view_had_a_control_changed(self) -> None:
        changed = {s["view"] for s in self.seen}
        self.assertEqual(changed, set(VIEWS), f"changed controls: {self.seen}")

    def test_settings_and_a_games_panel_were_walked_section_by_section(self) -> None:
        sections = {view: {s["where"] for s in self.seen if s["view"] == view} - {"page"}
                    for view in ("settings", "games")}
        self.assertGreaterEqual(len(sections["settings"]), SETTINGS_SECTIONS, sections)
        self.assertGreaterEqual(len(sections["games"]), 1, sections)

    def test_there_were_landmarks_to_lose(self) -> None:
        self.assertEqual([s for s in self.seen if not s["reloaded"] and not s["landmarks"]], [])

    def test_a_change_does_not_take_the_page_again(self) -> None:
        self.assertEqual(self._each("reloaded"), [])

    def test_a_change_does_not_dim_the_page(self) -> None:
        self.assertEqual(self._each("dimmed"), [])

    def test_a_change_keeps_the_landmarks_standing(self) -> None:
        self.assertEqual(self._each("landmarks"), [])


if __name__ == "__main__":
    unittest.main()
