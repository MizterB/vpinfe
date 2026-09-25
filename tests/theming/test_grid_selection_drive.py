"""Select-all on a grid too big to send whole, in a real browser.

The ids alone pass the socket's one-megabyte cap, so the selection only arrives if it
is sent in parts and put back together.

Slow: serves a bare page holding one Console grid and drives it in a real browser.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
import unittest
import urllib.request
from pathlib import Path
from tempfile import TemporaryDirectory

from tests.support.browser_session import BrowserSession, chromium_path, free_port

REPO = Path(__file__).resolve().parents[2]
ROWS = 5000
ID_CHARS = 210

API = ("(() => { const el = document.querySelector('.ag-root-wrapper')"
       ".closest('.nicegui-aggrid'); return getElement(Number(el.id.slice(1))).api; })()")
HEADER_BOX = ".ag-header-select-all .ag-checkbox-input-wrapper"


def _rows() -> list[dict[str, str]]:
    return [{"id": f"{n:05d}".ljust(ID_CHARS, "x"), "name": f"Row {n}"}
            for n in range(ROWS)]


def serve(port: int) -> None:
    """The page: one grid, and what its selection handler last received."""
    from nicegui import app, ui

    from console import api, grid

    api.local_base_url = lambda: "http://127.0.0.1:9"
    rows = _rows()
    heard: dict = {"ids": [], "calls": 0}

    @ui.page("/")
    def page() -> None:
        def picked(chosen: list[dict]) -> None:
            heard["ids"] = [row["id"] for row in chosen]
            heard["calls"] += 1

        with ui.element("div").classes("w-full h-[600px] flex flex-col"):
            grid.build([grid.identifier("name", "Name")], rows, "drive.selection",
                       on_select_rows=picked)

    @app.get("/heard")
    def said() -> dict:
        return heard

    ui.run(port=port, show=False, reload=False, title="Selection drive")


def _heard(port: int) -> dict:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/heard", timeout=5) as answer:
        return json.loads(answer.read())


class SelectionDrive(unittest.TestCase):
    seen: dict = {}

    @classmethod
    def setUpClass(cls) -> None:
        if not chromium_path():
            raise unittest.SkipTest("no Chromium on this machine")
        port = free_port()
        with TemporaryDirectory() as config:
            log = Path(config) / "page.log"
            with log.open("w") as out:
                page = subprocess.Popen(
                    [sys.executable, "-m", "tests.theming.test_grid_selection_drive",
                     "serve", str(port)],
                    cwd=REPO, stdout=out, stderr=subprocess.STDOUT,
                    env={**os.environ, "VPINFE_CONFIG_DIR": config})
            try:
                cls._wait_for_page(port, page, log)
                cls.seen = asyncio.run(cls._drive(port))
            finally:
                page.terminate()
                page.wait(timeout=10)

    @staticmethod
    def _wait_for_page(port: int, page: subprocess.Popen, log: Path) -> None:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if page.poll() is not None:
                raise AssertionError(f"the page exited:\n{log.read_text()}")
            try:
                _heard(port)
                return
            except OSError:
                time.sleep(0.2)
        raise AssertionError(f"the page never served:\n{log.read_text()}")

    @classmethod
    async def _drive(cls, port: int) -> dict:
        seen: dict = {}

        async def settled(calls: int) -> dict:
            for _ in range(200):
                heard = await asyncio.to_thread(_heard, port)
                if heard["calls"] >= calls:
                    return heard
                await asyncio.sleep(0.1)
            return heard

        async with BrowserSession(chromium_path()) as browser:
            await browser.navigate(f"http://127.0.0.1:{port}/")
            await browser.wait_for(API + f".getDisplayedRowCount() === {ROWS}", timeout=60.0)
            await browser.click(HEADER_BOX)
            seen["all"] = (await settled(1))["ids"]
            seen["ticked"] = await browser.evaluate(API + ".getSelectedNodes().length")
            await browser.click(HEADER_BOX)
            seen["cleared"] = (await settled(2))["ids"]
            await browser.evaluate(API + ".setGridOption('quickFilterText', 'Row 1')")
            await browser.wait_for(API + f".getDisplayedRowCount() < {ROWS}")
            seen["shown"] = await browser.evaluate(
                "(() => { const out = []; " + API + ".forEachNodeAfterFilter("
                "n => out.push(n.id)); return out; })()")
            await browser.click(HEADER_BOX)
            seen["filtered"] = (await settled(3))["ids"]
        return seen

    def test_the_ids_alone_pass_the_socket_s_cap(self) -> None:
        """Or this would pass without the parts it exists to exercise."""
        self.assertGreater(sum(len(row["id"]) for row in _rows()), 1_000_000)

    def test_select_all_reaches_the_handler_with_every_id_in_order(self) -> None:
        self.assertEqual(self.seen["ticked"], ROWS)
        self.assertEqual(self.seen["all"], [row["id"] for row in _rows()])

    def test_clearing_reaches_it_as_nothing(self) -> None:
        self.assertEqual(self.seen["cleared"], [])

    def test_select_all_under_a_filter_takes_the_rows_on_screen(self) -> None:
        self.assertTrue(0 < len(self.seen["shown"]) < ROWS)
        self.assertEqual(self.seen["filtered"], self.seen["shown"])


if __name__ == "__main__":
    if sys.argv[1:2] == ["serve"]:
        serve(int(sys.argv[2]))
    else:
        unittest.main()
