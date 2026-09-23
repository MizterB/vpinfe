"""Every section a rail opens, in a real browser: when any group in it is headed, the
first one is too, and a lone heading never says the rail row again.

Slow: boots a real instance and a real browser.
"""

from __future__ import annotations

import asyncio
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import quote

from tests.support.browser_session import BrowserSession, chromium_path
from tests.support.library import game_info, write_game
from tests.support.live_instance import LiveInstance

PICKED = "Hand Picked"
SMART = "Smart Bally"

# Where each rail lives, and the address that puts a subject under it. None selects the
# first row of that view's list.
VIEWS = (
    ("games", "game=alpha"),
    ("tables", None),
    ("collections", f"collection={quote(PICKED)}"),
    ("collections", f"collection={quote(SMART)}"),
    ("tags", None),
    ("locations", None),
    ("launchers", None),
    ("devices", None),
    ("media", None),
    ("assets", None),
    ("settings", None),
)

ROWS = ("[...document.querySelectorAll('.console-section-row')]"
        ".filter(el => el.getClientRects().length).length")
PICK_FIRST = """(() => {
  const cell = document.querySelector('.ag-center-cols-container .ag-row .ag-cell');
  if (!cell) return false;
  for (const kind of ['mousedown', 'mouseup', 'click'])
    cell.dispatchEvent(new MouseEvent(kind, {bubbles: true, button: 0}));
  return true;
})()"""
# Opens every row in turn. A page's own name (`panel.header`, Settings) is the page, not a
# group, so it is set aside before either question is asked.
AUDIT = """(async () => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const HEAD = '.console-fact-heading, .console-card-title,'
    + ' .console-group:not(.console-rail-group)';
  const shown = el => el.getClientRects().length > 0
    && getComputedStyle(el).visibility !== 'hidden';
  const ownText = el => [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
  const content = el => shown(el) && (ownText(el)
    || el.matches('input,textarea,img,video,canvas,.q-field,.q-btn,.q-toggle,.q-checkbox'));
  const rows = () => [...document.querySelectorAll('.console-section-row')].filter(shown);
  const work = () => [...document.querySelectorAll('.console-section-work')].find(shown);
  const hit = row => (row.querySelector('.console-section-hit') || row).click();
  const bare = text => text.trim().split('\\n')[0].replace(/\\s*\\(.*\\)$/, '').toLowerCase();
  const opened = [], problems = [];
  const count = rows().length;
  for (let i = 0; i < count; i++) {
    const name = rows()[i].innerText.trim().split('\\n')[0];
    hit(rows()[i]);
    await sleep(1200);
    if (!work()) { hit(rows()[i]); await sleep(1200); }
    const area = work();
    if (!area) { problems.push([name, 'opened onto nothing']); continue; }
    opened.push(name);
    const page = area.querySelector('.console-panel-heading');
    const outside = el => !(page && page.contains(el));
    const heads = [...area.querySelectorAll(HEAD)].filter(shown).filter(outside);
    const first = [...area.querySelectorAll('*')].filter(outside).find(content);
    if (heads.length && first && !heads.some(h => h === first || h.contains(first)))
      problems.push([name, 'above its first heading: '
        + (first.innerText || first.value || first.tagName).trim().slice(0, 60)]);
    if (heads.length === 1 && bare(heads[0].innerText) === bare(name))
      problems.push([name, 'its one heading says the row again']);
  }
  return {opened, problems};
})()"""


class SectionHeadingsDrive(unittest.TestCase):
    seen: dict = {}

    @classmethod
    def setUpClass(cls) -> None:
        if not chromium_path():
            raise unittest.SkipTest("no Chromium on this machine")
        with TemporaryDirectory() as tmp:
            tables = {"t-a1": {"id": "t-a1", "filename": "Alpha 1.vpx", "version": "1"},
                      "t-a2": {"id": "t-a2", "filename": "Alpha 2.vpx", "version": "2"}}
            info = game_info("Alpha", vps_id="", game_id="alpha", tables=tables,
                             Info={"Manufacturer": "Bally", "Year": "1992"},
                             User={"Tags": ["Late Night"]})
            info["vpinfe"]["default_table"] = "t-a2"
            write_game(Path(tmp), "Alpha", info=info, vpx=False,
                       files={"Alpha 1.vpx": b"x", "Alpha 2.vpx": b"x",
                              "pinmame/roms/alpha.zip": b"x"},
                       medias={"wheel.png": b"x"})
            write_game(Path(tmp), "Bravo",
                       info=game_info("Bravo", vps_id="", game_id="bravo",
                                      Info={"Manufacturer": "Williams", "Year": "1995"}))
            with LiveInstance(Path(tmp)) as instance:
                cls.seen = asyncio.run(cls._drive(instance))

    @classmethod
    async def _drive(cls, instance: LiveInstance) -> dict:
        instance.wait_for_api()
        instance.post("/api/v1/collections", {"name": PICKED, "games": ["alpha", "bravo"]})
        instance.post("/api/v1/collections",
                      {"name": SMART, "filters": {"manufacturer": ["Bally"]}})
        seen: dict = {}
        async with BrowserSession(chromium_path()) as browser:
            await browser.send("Emulation.setDeviceMetricsOverride",
                               {"width": 1700, "height": 1000, "deviceScaleFactor": 1,
                                "mobile": False})
            for view, subject in VIEWS:
                query = f"view={view}" + (f"&{subject}" if subject else "")
                await browser.navigate(instance.console_url(f"/console?{query}"))
                await asyncio.sleep(2)
                if not await browser.evaluate(ROWS):
                    await browser.wait_for(PICK_FIRST)
                    await browser.wait_for(ROWS)
                seen[query] = await browser.evaluate(AUDIT)
        return seen

    def test_every_rail_opened_something(self) -> None:
        for query, found in self.seen.items():
            with self.subTest(query):
                self.assertTrue(found["opened"])

    def test_a_headed_section_opens_with_a_heading(self) -> None:
        problems = {query: found["problems"] for query, found in self.seen.items()
                    if found["problems"]}
        self.assertEqual(problems, {})


if __name__ == "__main__":
    unittest.main()
