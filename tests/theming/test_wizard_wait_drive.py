"""A wizard's wait and its path fields, in a real browser with the real stylesheet.

A step that takes a while shows its bar above the buttons, outside the scroll, so it is on
screen whatever the step is scrolled to. A path that is longer than its field shows its end
and the mark that says its start is out of view, and that mark survives the field being
drawn again by the server.

Slow: serves a bare page holding the real wizard dialog over a fake flow, and drives it in
a real browser.
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from typing import Any

from tests.support.browser_session import BrowserSession
from tests.theming.test_grid_selection_drive import drive_page, exit_with_parent

# Long enough for the wait strip to be drawn, short enough that a run does not idle.
SLOW_CALL = 4
LONG = "/Volumes/share/Pinball/Migration/Visual Pinball/Tables/Some Very Long Folder Name/Tables"
# Tall enough that the bar would sit below the fold if it were drawn in the body.
TALL = [{"key": f"row{n}", "type": "string", "label": f"Row {n}", "value": ""}
        for n in range(14)]
STEP = {"step": "paths", "title": "Where", "help": "Two paths", "steps": [],
        "fields": [{"key": "tables", "type": "path", "wants": "dir", "label": "Tables",
                    "value": LONG}, *TALL]}

SETTLED = ("(() => !!document.querySelector('.manager-wizard-card input.manager-path-input')"
           " && document.getAnimations().every((a) => a.playState !== 'running'))()")
FORWARD = ".manager-wizard-card .manager-wizard-forward"
MARKED = "!!document.querySelector('.manager-wizard-card .q-field[data-path-cut]')"
BARRED = "!!document.querySelector('.manager-wizard-wait .q-linear-progress')"
WAIT = """(() => {
  const wait = document.querySelector('.manager-wizard-wait').getBoundingClientRect();
  const foot = document.querySelector('.manager-dialog-footer').getBoundingClientRect();
  const scroll = document.querySelector('.manager-wizard-scroll');
  const card = document.querySelector('.manager-wizard-card').getBoundingClientRect();
  return {
    outside: !scroll.contains(document.querySelector('.manager-wizard-wait')),
    above: wait.bottom <= foot.top + 1, inside: wait.top >= card.top && wait.bottom <= card.bottom,
    said: document.querySelector('.manager-wizard-wait').innerText,
  };
})()"""
PATH = """(() => {
  const input = document.querySelector('.manager-wizard-card input.manager-path-input');
  const field = input.closest('.q-field');
  return {
    cut: field.hasAttribute('data-path-cut'),
    atEnd: Math.abs(input.scrollLeft - (input.scrollWidth - input.clientWidth)) <= 1,
    clear: parseFloat(getComputedStyle(input).paddingRight) > 0,
  };
})()"""
# What the server's redraw does to a field: Vue writes its class attribute afresh, which
# drops any class a script added.
REDRAWN = """(() => {
  const field = document.querySelector('.manager-wizard-card input.manager-path-input')
    .closest('.q-field');
  field.setAttribute('class', field.className.replace('manager-path-cut', '').trim());
  return true;
})()"""


def serve(port: int) -> None:
    from nicegui import app, ui

    from manager import api, appearance, wizard

    api.local_base_url = lambda: "http://127.0.0.1:9"
    app.add_static_files(appearance.BASE_MOUNT, str(appearance.BASE_CSS.parent))

    async def first(_key: str | None) -> dict:
        return STEP

    async def slow(*_args: Any) -> dict:
        await asyncio.sleep(SLOW_CALL)
        return STEP

    async def progress() -> dict:
        return {"message": "Reading the games", "done": 1, "total": 4}

    @ui.page("/")
    def drawn() -> None:
        appearance.apply_mode()
        calls = wizard.Calls(first, slow, slow, slow, slow, progress)

        async def open_it() -> None:
            await wizard.open_dialog(label="Drive", calls=calls, under="drive.wizard",
                                     mark=True)

        ui.timer(0.1, open_it, once=True)

    @app.get("/heard")
    def said() -> dict:
        return {}

    ui.run(port=port, show=False, reload=False, title="Wizard wait drive")


class WizardWaitDrive(unittest.TestCase):
    seen: dict[str, dict] = {}

    @classmethod
    def setUpClass(cls) -> None:
        cls.seen = drive_page("tests.theming.test_wizard_wait_drive", cls._drive)

    @classmethod
    async def _drive(cls, binary: str, port: int) -> dict:
        seen: dict[str, dict] = {}
        async with BrowserSession(binary) as browser:
            await browser.navigate(f"http://127.0.0.1:{port}/")
            await browser.wait_for(SETTLED, timeout=30.0)
            await browser.wait_for(MARKED, timeout=10.0)
            seen["path"] = await browser.evaluate(PATH)
            await browser.evaluate(REDRAWN)
            seen["redrawn"] = await browser.evaluate(PATH)
            await browser.click(FORWARD)
            await browser.wait_for(BARRED, timeout=20.0)
            seen["wait"] = await browser.evaluate(WAIT)
        return seen

    def test_a_path_longer_than_its_field_shows_its_end_and_says_so(self) -> None:
        self.assertEqual(self.seen["path"], {"cut": True, "atEnd": True, "clear": True})

    def test_the_mark_survives_the_field_being_drawn_again(self) -> None:
        self.assertTrue(self.seen["redrawn"]["cut"])

    def test_the_bar_is_above_the_buttons_and_outside_the_scroll(self) -> None:
        wait = self.seen["wait"]
        self.assertTrue(wait["outside"] and wait["above"] and wait["inside"], wait)

    def test_the_bar_says_what_it_is_waiting_for(self) -> None:
        self.assertIn("Reading the games", self.seen["wait"]["said"])


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "serve":
        exit_with_parent()
        serve(int(sys.argv[2]))
    else:
        unittest.main()
