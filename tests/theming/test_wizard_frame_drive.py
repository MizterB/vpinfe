"""A wizard's frame and its picture choices, measured in a real browser with the real
stylesheet: the body is as wide as the step row, a welcome's title sits on the card's
center, a pick row has the padding and the unclipped name the stylesheet declares, and a
choice without pictures starts at its field's edge.

A stylesheet read as text cannot see a rule outranked by one that comes later, nor a
container that shrinks to its content; only a computed style and a measured box can.

Slow: serves a bare page holding the real wizard dialog over a fake flow, and drives it in
a real browser.
"""

from __future__ import annotations

import sys
import unittest
from typing import Any

from tests.support.browser_session import BrowserSession
from tests.support.stylesheet import declarations
from tests.theming.test_grid_selection_drive import drive_page, exit_with_parent

STEPS = [{"key": "welcome", "label": "Welcome", "done": False},
         {"key": "tables", "label": "Tables", "done": False},
         {"key": "themes", "label": "Themes", "done": False},
         {"key": "finish", "label": "Finish", "done": False}]
PLAY = {"key": "play", "type": "choice", "label": "How do you play?", "value": "desktop",
        "choices": [["desktop", "Desktop", "One screen", "desktop"],
                    ["cabinet", "Cabinet", "Several screens", "cabinet"]]}
# Wider than a row can be, so a name that cannot wrap is clipped.
LONG = {**PLAY, "choices": [*PLAY["choices"],
                            ["other", "Something with a name long enough to wrap onto a "
                                      "second line when it must", "", "folder"]]}
# No pictures, so it draws as radios with each option's sentence under them.
PLAIN = {"step": "how", "title": "Copy or move?", "help": "Two tables", "steps": STEPS,
         "fields": [{"key": "how", "type": "choice", "label": "How", "value": "copy",
                     "choices": [["copy", "Copy them", "The folder stays as it is"],
                                 ["move", "Move them", "No second copy"]]}]}
FLOWS: dict[str, dict[str, Any]] = {
    "/welcome": {"step": "welcome", "welcome": True, "title": "Welcome to VPinFE",
                 "help": "A few questions and it is set up", "steps": STEPS,
                 "fields": [PLAY]},
    "/rows": {"step": "tables", "title": "How do you play?", "help": "Pick one",
              "steps": [{**STEPS[0], "done": True}, *STEPS[1:]], "fields": [LONG]},
}

# The card is measured once its entrance has finished: Quasar scales it in and grows it,
# and a box measured mid-transition is a different size from the one a person sees.
SETTLED = ("(() => !!document.querySelector('.manager-wizard-card')"
           " && !!document.querySelector('.manager-wizard-pick, .q-radio')"
           " && document.getAnimations().every((a) => a.playState !== 'running'))()")
MEASURE = """(() => {
  const wide = (selector) => document.querySelector(selector).offsetWidth;
  const row = document.querySelector('.manager-wizard-pick');
  const look = getComputedStyle(row);
  const card = document.querySelector('.manager-wizard-card').getBoundingClientRect();
  const text = document.createRange();
  text.selectNodeContents(document.querySelector('.manager-wizard-title'));
  const spoken = text.getBoundingClientRect();
  return {
    steps: wide('.manager-wizard-steps'), scroll: wide('.manager-wizard-scroll'),
    picks: wide('.manager-wizard-picks'), row: row.offsetWidth,
    padding: [look.paddingTop, look.paddingRight, look.paddingBottom, look.paddingLeft],
    wraps: getComputedStyle(
      [...document.querySelectorAll('.manager-wizard-pick .manager-source-name')].pop()
    ).whiteSpace,
    card: card.left + card.width / 2, title: spoken.left + spoken.width / 2,
  };
})()"""
STACKED = """(() => {
  const edge = (el) => el.getBoundingClientRect().left;
  const radio = document.querySelector('.manager-wizard-card .q-radio');
  const edit = radio.closest('.manager-fact-edit');
  return {edit: edge(edit), radio: edge(radio), help: edge(edit.querySelector('.manager-help'))};
})()"""


def serve(port: int) -> None:
    """One page per flow: the real dialog host over a flow that answers one step."""
    from nicegui import app, ui

    from manager import api, appearance, wizard

    api.local_base_url = lambda: "http://127.0.0.1:9"
    app.add_static_files(appearance.BASE_MOUNT, str(appearance.BASE_CSS.parent))

    def calls(step: dict[str, Any]) -> wizard.Calls:
        async def answer(*_args: Any) -> dict:
            return step

        return wizard.Calls(answer, answer, answer, answer, answer)

    def route(path: str, step: dict[str, Any]) -> None:
        @ui.page(path)
        def drawn() -> None:
            appearance.apply_mode()

            async def open_it() -> None:
                await wizard.open_dialog(label="Drive", calls=calls(step),
                                         under="drive.wizard", mark=True)

            ui.timer(0.1, open_it, once=True)

    for path, step in FLOWS.items():
        route(path, step)
    route("/plain", PLAIN)

    @app.get("/heard")
    def said() -> dict:
        return {}

    ui.run(port=port, show=False, reload=False, title="Wizard frame drive")


def sides(shorthand: str) -> list[str]:
    """A `padding` declaration as top, right, bottom, left, the way a computed style gives it."""
    parts = shorthand.split()
    top = parts[0]
    right = parts[1] if len(parts) > 1 else top
    bottom = parts[2] if len(parts) > 2 else top
    left = parts[3] if len(parts) > 3 else right
    return [top, right, bottom, left]


class WizardFrameDrive(unittest.TestCase):
    seen: dict[str, dict] = {}

    @classmethod
    def setUpClass(cls) -> None:
        cls.seen = drive_page("tests.theming.test_wizard_frame_drive", cls._drive)

    @classmethod
    async def _drive(cls, binary: str, port: int) -> dict:
        seen: dict[str, dict] = {}
        async with BrowserSession(binary) as browser:
            for path in FLOWS:
                await browser.navigate(f"http://127.0.0.1:{port}{path}")
                await browser.wait_for(SETTLED, timeout=30.0)
                seen[path] = await browser.evaluate(MEASURE)
            await browser.navigate(f"http://127.0.0.1:{port}/plain")
            await browser.wait_for(SETTLED, timeout=30.0)
            seen["plain"] = await browser.evaluate(STACKED)
        return seen

    def test_the_body_is_as_wide_as_the_step_row_on_a_welcome_and_on_any_step(self) -> None:
        for path in FLOWS:
            with self.subTest(path=path):
                self.assertEqual(self.seen[path]["steps"], self.seen[path]["scroll"])

    def test_a_welcome_title_sits_on_the_card_s_center(self) -> None:
        found = self.seen["/welcome"]

        self.assertAlmostEqual(found["card"], found["title"], delta=1.5)

    def test_a_picture_row_fills_its_group_on_a_step_that_is_not_a_welcome(self) -> None:
        found = self.seen["/rows"]

        self.assertEqual(found["picks"], found["row"])

    def test_a_row_has_the_padding_the_stylesheet_declares(self) -> None:
        rule = declarations(".manager-wizard-picks .manager-wizard-pick")

        self.assertIn("padding", rule)
        self.assertEqual(sides(rule["padding"]), self.seen["/rows"]["padding"])

    def test_a_tile_has_the_padding_the_stylesheet_declares(self) -> None:
        rule = declarations(".manager-wizard-picks .manager-wizard-pick--tile")

        self.assertIn("padding", rule)
        self.assertEqual(sides(rule["padding"]), self.seen["/welcome"]["padding"])

    def test_a_long_name_wraps_instead_of_clipping(self) -> None:
        for path in FLOWS:
            with self.subTest(path=path):
                self.assertEqual("normal", self.seen[path]["wraps"])

    def test_a_choice_without_pictures_starts_at_its_field_s_edge(self) -> None:
        found = self.seen["plain"]

        self.assertAlmostEqual(found["edit"], found["radio"], delta=1)
        self.assertAlmostEqual(found["edit"], found["help"], delta=1)


if __name__ == "__main__":
    if sys.argv[1:2] == ["serve"]:
        exit_with_parent()
        serve(int(sys.argv[2]))
    else:
        unittest.main()
