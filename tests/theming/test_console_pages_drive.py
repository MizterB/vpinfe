"""Every Console page and the remote, walked in a real browser.

Each is drawn once: no listener reaches a layout the browser already has, which NiceGUI
answers by drawing all of it again. And every section a rail opens is headed properly:
when any group in it is headed, the first one is too, and a lone heading never says the
rail row again. Every dropdown on screen is a `console.dropdown.Select`, and the text in
each one stands at the middle of its box.

Slow: boots a real instance and a real browser.
"""

from __future__ import annotations

import asyncio
import json
import unittest
import urllib.request
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import quote

from apps.vpx.setting_types import TYPES
from tests.support.browser_session import BrowserSession, chromium_path
from tests.support.console_walk import ConsoleWalk, clicked
from tests.support.library import game_info, write_game
from tests.support.live_instance import LiveInstance

PICKED = "Hand Picked"
SMART = "Smart Bally"
VPX = "vpx-drive"
WHOLE_PANEL = "(whole panel)"

# Where each rail lives, and the address that puts a subject under it. None selects the
# first row of that view's list, LAST its last.
LAST = "last"
VIEWS = (
    ("games", "game=alpha"),
    ("tables", None),
    ("collections", f"collection={quote(PICKED)}"),
    ("collections", f"collection={quote(SMART)}"),
    ("tags", None),
    ("locations", None),
    ("locations", LAST),
    ("launchers", None),
    ("launchers", f"launcher={VPX}"),
    ("players", None),
    ("devices", None),
    ("media", None),
    ("assets", None),
    ("settings", None),
)

DRAWN_AGAIN = "Event listeners changed after initial definition"
RAIL = "[...document.querySelectorAll('a.console-nav-row')].map(a => a.getAttribute('href'))"
ROWS = ("[...document.querySelectorAll('.console-section-row')]"
        ".filter(el => el.getClientRects().length).length")
PICK = """(last => {
  const rows = [...document.querySelectorAll('.ag-center-cols-container .ag-row')]
    .sort((a, b) => a.getAttribute('row-index') - b.getAttribute('row-index'));
  const cell = (last ? rows[rows.length - 1] : rows[0])?.querySelector('.ag-cell');
  if (!cell) return false;
  for (const kind of ['mousedown', 'mouseup', 'click'])
    cell.dispatchEvent(new MouseEvent(kind, {bubbles: true, button: 0}));
  return true;
})(%s)"""
# The open section. A page's own name (`panel.header`, Settings) is the page, not a
# group, and a section bar is the whole section's; both are set aside before either
# question is asked, and so are a page's intro and the input table's live line, which each
# speak for the whole page and so read above its first group.
HEADINGS = """(name => {
  const HEAD = '.console-fact-heading, .console-card-title,'
    + ' .console-group:not(.console-rail-group)';
  const shown = el => el.getClientRects().length > 0
    && getComputedStyle(el).visibility !== 'hidden';
  const ownText = el => [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
  const content = el => shown(el) && (ownText(el)
    || el.matches('input,textarea,img,video,canvas,.q-field,.q-btn,.q-toggle,.q-checkbox'));
  const bare = text => text.trim().split('\\n')[0].replace(/\\s*\\(.*\\)$/, '').toLowerCase();
  const area = [...document.querySelectorAll('.console-section-work')].find(shown);
  const problems = [];
  const aside = [...area.querySelectorAll(
    '.console-panel-heading, .console-section-bar, .console-binding-live, .console-intro')];
  const outside = el => !aside.some(a => a.contains(el));
  const heads = [...area.querySelectorAll(HEAD)].filter(shown).filter(outside);
  const first = [...area.querySelectorAll('*')].filter(outside).find(content);
  if (heads.length && first && !heads.some(h => h === first || h.contains(first)))
    problems.push([name, 'above its first heading: '
      + (first.innerText || first.value || first.tagName).trim().slice(0, 60)]);
  if (heads.length === 1 && bare(heads[0].innerText) === bare(name))
    problems.push([name, 'its one heading says the row again']);
  return {count: heads.length, problems};
})(%s)"""
# Every dropdown on screen. A one-line value is measured from the middle of its text to
# the middle of its box; one that carries a label is a label over a value by design, and
# a multiple one is chips, so neither is.
DROPDOWNS = """(() => {
  const shown = el => el.getClientRects().length > 0
    && getComputedStyle(el).visibility !== 'hidden';
  const problems = [];
  let measured = 0;
  for (const select of document.querySelectorAll('.q-select')) {
    if (!shown(select)) continue;
    const name = (select.innerText || '').trim().split('\\n')[0].slice(0, 30);
    if (!select.classList.contains('console-select')) {
      problems.push([name, 'is not a console Select']);
      continue;
    }
    const control = select.querySelector('.q-field__control');
    const value = select.querySelector('.q-field__native span, .q-field__native input');
    if (select.querySelector('.q-field__label') || select.classList.contains('q-select--multiple')
        || !control || !value) continue;
    const text = document.createRange();
    text.selectNodeContents(value);
    const at = (value.tagName === 'INPUT' ? value : text).getBoundingClientRect();
    const box = control.getBoundingClientRect();
    if (!at.height || !box.height) continue;
    measured += 1;
    const off = (at.top + at.height / 2) - (box.top + box.height / 2);
    if (Math.abs(off) >= 0.5) problems.push([name, 'sits ' + off.toFixed(1) + 'px off center']);
  }
  return {measured, problems};
})()"""


def _vpx_install(root: Path) -> dict[str, str]:
    defaults = {"bool": "0", "int": "0", "number": "1.0", "string": "''",
                "choice": "0, 0='One', 1='Two'"}
    sections: dict[str, list[str]] = {}
    for qualified, kind in TYPES.items():
        section, key = qualified.rsplit(".", 1)
        value = defaults[kind].split(",")[0].strip("'")
        sections.setdefault(section, []).append(
            f"; {key}: {key} [Default: {defaults[kind]}]\n{key} = {value}")
    ini = root / "VPinballX.ini"
    ini.write_text("".join(f"[{name}]\n" + "\n".join(lines) + "\n\n"
                           for name, lines in sections.items()))
    program = root / "VPinballX_BGFX"
    program.write_text("#!/bin/sh\nexit 0\n")
    program.chmod(0o755)
    return {"bin_path": str(program), "ini_path": str(ini)}


class ConsolePagesDrive(unittest.TestCase):
    # `headings`: per address, the sections its rail opened and what each is headed
    # with. `drawn`: per address, what the browser said about redrawing as it loaded.
    seen: dict = {}

    @classmethod
    def setUpClass(cls) -> None:
        if not chromium_path():
            raise unittest.SkipTest("no Chromium on this machine")
        with TemporaryDirectory() as tmp, TemporaryDirectory() as second, \
                TemporaryDirectory() as program:
            tables = {"t-a1": {"id": "t-a1", "filename": "Alpha 1.vpx", "version": "1"},
                      "t-a2": {"id": "t-a2", "filename": "Alpha 2.vpx", "version": "2"}}
            info = game_info("Alpha", vps_id="", game_id="alpha", tables=tables,
                             Info={"Manufacturer": "Bally", "Year": "1992"},
                             User={"Tags": ["Late Night"]})
            info["vpinfe"]["default_table"] = "t-a2"
            write_game(Path(tmp), "Alpha", info=info, vpx=False,
                       files={"Alpha 1.vpx": b"x", "Alpha 2.vpx": b"x",
                              "pinmame/roms/alpha.zip": b"x", "Alpha 1.ini": b"[Player]"},
                       medias={"wheel.png": b"x"})
            bravo = game_info("Bravo", vps_id="", game_id="bravo",
                              Info={"Manufacturer": "Williams", "Year": "1995"})
            write_game(Path(tmp), "Bravo", info=bravo)
            write_game(Path(second), "Bravo", info=bravo)
            with LiveInstance(Path(tmp)) as instance:
                cls.seen = asyncio.run(cls._drive(instance, second,
                                                  _vpx_install(Path(program))))

    @classmethod
    async def _drive(cls, instance: LiveInstance, second: str,
                     vpx: dict[str, str]) -> dict:
        instance.wait_for_api()
        instance.post("/api/v1/collections", {"name": PICKED, "games": ["alpha", "bravo"]})
        instance.post("/api/v1/collections",
                      {"name": SMART, "filters": {"manufacturer": ["Bally"]}})
        for path, body in (("locations/second", {"path": second, "kind": "root"}),
                           (f"launchers/{VPX}", {"app": "vpx", "enabled": True,
                                                 "display_name": "Drive", "settings": vpx})):
            urllib.request.urlopen(urllib.request.Request(
                instance.console_url(f"/api/v1/{path}"),
                data=json.dumps(body).encode(), method="PUT",
                headers={"Content-Type": "application/json"}), timeout=10).close()
        headings: dict = {}
        drawn: dict[str, list[str]] = {}
        dropdowns: dict = {"measured": 0, "problems": []}

        async def look(where: str) -> None:
            said = await browser.evaluate(DROPDOWNS)
            dropdowns["measured"] += said["measured"]
            dropdowns["problems"] += [[where, *one] for one in said["problems"]]

        async with BrowserSession(chromium_path()) as browser:
            await browser.send("Emulation.setDeviceMetricsOverride",
                               {"width": 1700, "height": 1000, "deviceScaleFactor": 1,
                                "mobile": False})
            walk = ConsoleWalk(browser, instance)

            async def visit(path: str) -> None:
                said = await walk.visit(path, listen=True)
                drawn.setdefault(path, []).extend(line for line in said if DRAWN_AGAIN in line)
                await look(path)

            await visit("/console")
            rail = await browser.evaluate(RAIL)
            for view, subject in VIEWS:
                query = f"view={view}" + (f"&{subject}" if subject not in (None, LAST) else "")
                await visit(f"/console?{query}")
                if subject == LAST or not await browser.evaluate(ROWS):
                    await walk.open_pane(clicked(browser, PICK % json.dumps(subject == LAST)))
                found: dict = {"opened": [], "problems": [], "headings": {}}
                async for name in walk.sections():
                    said = await browser.evaluate(HEADINGS % json.dumps(name))
                    found["opened"].append(name)
                    found["headings"][name] = said["count"]
                    found["problems"] += said["problems"]
                    await look(f"{query} / {name}")
                if not found["opened"]:
                    # A rail of one section is not drawn, so its section is the panel.
                    said = await browser.evaluate(HEADINGS % json.dumps(""))
                    found["opened"].append(WHOLE_PANEL)
                    found["headings"][WHOLE_PANEL] = said["count"]
                    found["problems"] += said["problems"]
                headings[query + (" (last row)" if subject == LAST else "")] = found
            for path in rail:
                if path not in drawn:
                    await visit(path)
            await visit("/remote")
        return {"headings": headings, "drawn": drawn, "dropdowns": dropdowns}

    def test_every_rail_opened_something(self) -> None:
        for query, found in self.seen["headings"].items():
            with self.subTest(query):
                self.assertTrue(found["opened"])

    def test_a_shadowed_location_draws_its_second_group(self) -> None:
        self.assertEqual(self.seen["headings"]["view=locations (last row)"]["headings"],
                         {WHOLE_PANEL: 2})

    def test_a_vpx_install_opens_each_area_of_its_settings(self) -> None:
        self.assertEqual(self.seen["headings"][f"view=launchers&launcher={VPX}"]["opened"],
                         ["Details", "Displays", "Input", "Sound", "Graphics", "Plugins",
                          "All Settings", "Settings file"])

    def test_a_section_that_reads_before_it_draws_is_read_once_drawn(self) -> None:
        opened = self.seen["headings"][f"view=launchers&launcher={VPX}"]["headings"]
        self.assertGreater(opened["All Settings"], 0)

    def test_a_headed_section_opens_with_a_heading(self) -> None:
        problems = {query: found["problems"] for query, found in self.seen["headings"].items()
                    if found["problems"]}
        self.assertEqual(problems, {})

    def test_every_console_view_is_drawn_once(self) -> None:
        views = {path: said for path, said in self.seen["drawn"].items()
                 if path.startswith("/console?view=")}
        self.assertGreater(len(views), 5, sorted(self.seen["drawn"]))
        self.assertEqual({}, {path: said for path, said in views.items() if said})

    def test_the_bare_address_is_drawn_once(self) -> None:
        self.assertEqual([], self.seen["drawn"]["/console"])

    def test_the_remote_is_drawn_once(self) -> None:
        self.assertEqual([], self.seen["drawn"]["/remote"])

    def test_every_dropdown_is_a_console_select_with_its_text_centered(self) -> None:
        self.assertGreater(self.seen["dropdowns"]["measured"], 20,
                           "an empty sweep passes and measures nothing")
        self.assertEqual([], self.seen["dropdowns"]["problems"])


if __name__ == "__main__":
    unittest.main()
