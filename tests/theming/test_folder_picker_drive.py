"""The folder picker's New folder, in a real browser: the row it names a folder in, the
folder it makes and goes into, and the picker that has no way to make one.

Slow: serves a bare page that opens the picker over a real folder on disk, and drives it.
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

from common.i18n import t
from tests.support.browser_session import BrowserSession
from tests.support.console_walk import ConsoleWalk
from tests.theming.test_grid_selection_drive import _heard, drive_page, exit_with_parent

TYPED = "Games"
DIALOG = ".q-dialog"
ASIDE = f"{DIALOG} .console-dialog-aside"
NAMING = f"{DIALOG} .console-folder-list input"
SHOWS = "!!document.querySelector(%s)"
GONE = "!document.querySelector(%s)"
FACE = f"{DIALOG} .console-where"
PATH_SHOWN = (f"((document.querySelector('{FACE} .console-where-path') || {{}}).innerText"
              " || '').replace(/\\u200e/g, '')")
MENU_ITEMS = ".q-menu .console-menu-item"
MENU_TEXTS = (f"[...document.querySelectorAll('{MENU_ITEMS}')]"
              ".map(el => el.querySelector('.nicegui-column > div').innerText)")
BUTTONS = ("[...document.querySelectorAll('" + DIALOG + " button')]"
           ".map(b => b.innerText.replace(/^[a-z_]+\\s*/, '').trim())")


class _Page:
    def __init__(self, port: int) -> None:
        self.port = port

    def console_url(self, path: str = "/") -> str:
        return f"http://127.0.0.1:{self.port}{path}"


def serve(port: int) -> None:
    """A button that opens the picker over a folder holding one folder, and another that
    opens it over a bare function that lists but cannot make."""
    from nicegui import app, ui

    from common import folder_browse
    from console import api, folder_picker

    api.local_base_url = lambda: "http://127.0.0.1:9"
    base = Path(os.environ["VPINFE_CONFIG_DIR"]) / "browse"
    (base / "Existing").mkdir(parents=True, exist_ok=True)
    heard: dict = {"picked": "unasked", "base": str(base), "home": str(Path.home())}

    class Folders:
        def folders(self, path: str, kind: str = "dir", suffixes: tuple = (),
                    hidden: bool = False) -> dict:
            return folder_browse.listing(path, kind, tuple(suffixes), hidden)

        def make_folder(self, parent: str, name: str) -> dict:
            return folder_browse.make_folder(parent, name)

    def only_listing(path: str, kind: str = "dir", suffixes: tuple = (),
                     hidden: bool = False) -> dict:
        return folder_browse.listing(path, kind, tuple(suffixes), hidden)

    @ui.page("/")
    def page() -> None:
        async def open_with(lister) -> None:
            heard["picked"] = "open"
            heard["picked"] = await folder_picker.pick_path(lister, str(base))

        ui.button("Make", on_click=lambda: open_with(Folders().folders)).props("id=make")
        ui.button("Bare", on_click=lambda: open_with(only_listing)).props("id=bare")

    @app.get("/heard")
    def said() -> dict:
        return {**heard, "made": (base / TYPED).is_dir(),
                "default_left": (base / t("console.folder_picker.new_folder")).exists()}

    ui.run(port=port, show=False, reload=False, title="Folder picker drive")


class FolderPickerDrive(unittest.TestCase):
    seen: dict = {}

    @classmethod
    def setUpClass(cls) -> None:
        cls.seen = drive_page("tests.theming.test_folder_picker_drive", cls._drive)

    @classmethod
    async def _drive(cls, binary: str, port: int) -> dict:
        seen: dict = {}
        async with BrowserSession(binary) as browser:
            walk = ConsoleWalk(browser, _Page(port))
            await walk.visit("/")

            async def click_text(selector: str, text: str) -> None:
                await browser.click(selector, nth=int(await browser.wait_for(
                    "(() => { const i = [...document.querySelectorAll("
                    f"{json.dumps(selector)})].findIndex(el => el.innerText.includes("
                    f"{json.dumps(text)})); return i >= 0 ? i + 1 : 0; }})()")) - 1)

            await walk.act(lambda: browser.click("#bare"), until=SHOWS % json.dumps(DIALOG))
            seen["bare_buttons"] = await browser.evaluate(BUTTONS)
            seen["bare_aside"] = await browser.evaluate(SHOWS % json.dumps(ASIDE))
            await walk.act(lambda: click_text(f"{DIALOG} button", t("word.cancel")),
                           until=GONE % json.dumps(DIALOG))

            await walk.act(lambda: browser.click("#make"), until=SHOWS % json.dumps(ASIDE))
            seen["buttons"] = await browser.evaluate(BUTTONS)
            seen["aside"] = await browser.evaluate(
                "document.querySelector(" + json.dumps(ASIDE) + ").innerText")
            await walk.act(lambda: browser.click(ASIDE), until=SHOWS % json.dumps(NAMING))
            seen["named"] = await browser.evaluate(
                "(() => { const el = document.querySelector(" + json.dumps(NAMING) + ");"
                " return {value: el.value, focused: document.activeElement === el,"
                " from: el.selectionStart, to: el.selectionEnd}; })()")
            await browser.wait_for(
                "document.activeElement === document.querySelector(" + json.dumps(NAMING) + ")")
            await browser.send("Input.insertText", {"text": TYPED})
            await walk.act(lambda: browser.press("Enter", "Enter"),
                           until=GONE % json.dumps(NAMING))
            await browser.wait_for(PATH_SHOWN + f".endsWith({json.dumps(TYPED)})")
            seen["inside"] = await browser.evaluate(PATH_SHOWN)
            await walk.act(lambda: click_text(f"{DIALOG} button", t(
                "console.folder_picker.choose_this_folder")), until=GONE % json.dumps(DIALOG))
            seen["heard"] = _heard(port)

            # The Where face: its menu, then a folder above and a place through it.
            await walk.act(lambda: browser.click("#make"), until=SHOWS % json.dumps(DIALOG))
            seen["face_start"] = await browser.evaluate(PATH_SHOWN)
            seen["face_label"] = await browser.evaluate(
                f"document.querySelector('{FACE}').getAttribute('aria-label')")
            await walk.act(lambda: browser.click(FACE), until=SHOWS % json.dumps(MENU_ITEMS))
            seen["menu"] = await browser.evaluate(MENU_TEXTS)
            seen["menu_rows"] = await browser.evaluate(
                f"[...document.querySelectorAll('{MENU_ITEMS}')].map(el => ["
                "el.querySelector('.console-menu-mark').innerText,"
                " (el.querySelector('.console-menu-sub') || {}).innerText || ''])")
            seen["menu_on"] = await browser.evaluate(
                f"[...document.querySelectorAll('{MENU_ITEMS}')]"
                ".map(el => el.classList.contains('console-menu-on'))")
            await walk.act(lambda: browser.click(MENU_ITEMS, nth=0), until=GONE % json.dumps(
                ".q-menu"))
            seen["after_current"] = await browser.evaluate(PATH_SHOWN)
            await walk.act(lambda: browser.click(FACE), until=SHOWS % json.dumps(MENU_ITEMS))
            await walk.act(lambda: browser.click(MENU_ITEMS, nth=1),
                           until=GONE % json.dumps(".q-menu"))
            await browser.wait_for(PATH_SHOWN + f" !== {json.dumps(seen['face_start'])}")
            seen["above_path"] = await browser.evaluate(PATH_SHOWN)
            await walk.act(lambda: browser.click(FACE), until=SHOWS % json.dumps(MENU_ITEMS))
            await walk.act(lambda: click_text(MENU_ITEMS, t("word.home")),
                           until=GONE % json.dumps(".q-menu"))
            await browser.wait_for(PATH_SHOWN + f" === {json.dumps(seen['heard']['home'])}")
            seen["home_path"] = await browser.evaluate(PATH_SHOWN)
            await walk.act(lambda: click_text(f"{DIALOG} button", t("word.cancel")),
                           until=GONE % json.dumps(DIALOG))
        return seen

    def test_the_picker_that_cannot_make_one_does_not_offer_it(self) -> None:
        self.assertFalse(self.seen["bare_aside"])
        self.assertNotIn(t("console.folder_picker.new_folder"), self.seen["bare_buttons"])

    def test_new_folder_is_offered_beside_the_answer(self) -> None:
        self.assertEqual(self.seen["aside"].split()[-2:],
                         t("console.folder_picker.new_folder").split())

    def test_the_row_is_named_and_selected_for_typing(self) -> None:
        named = self.seen["named"]
        self.assertEqual(named["value"], t("console.folder_picker.new_folder"))
        self.assertTrue(named["focused"])
        self.assertEqual((named["from"], named["to"]), (0, len(named["value"])))

    def test_typing_replaces_the_name_and_enter_makes_the_folder(self) -> None:
        self.assertTrue(self.seen["heard"]["made"])
        self.assertFalse(self.seen["heard"]["default_left"])

    def test_the_picker_goes_into_the_folder_it_made(self) -> None:
        self.assertTrue(self.seen["inside"].endswith(TYPED))
        self.assertEqual(self.seen["heard"]["picked"],
                         str(Path(self.seen["heard"]["base"]) / TYPED))

    def test_where_is_the_face_and_is_named(self) -> None:
        self.assertEqual(self.seen["face_start"], self.seen["heard"]["base"])
        self.assertEqual(self.seen["face_label"], t("word.where"))

    def test_the_menu_starts_with_the_current_folder_then_what_is_above_then_places(self) -> None:
        base = Path(self.seen["heard"]["base"])
        menu = self.seen["menu"]
        self.assertTrue(menu[0].endswith(base.name))
        self.assertIn(base.parent.name, menu[1])
        self.assertTrue(any(t("word.home") in one for one in menu))
        self.assertEqual(self.seen["menu_on"].count(True), 1)
        self.assertTrue(self.seen["menu_on"][0])

    def test_places_wear_their_icon_and_say_where_they_are(self) -> None:
        rows = dict(zip(self.seen["menu"], self.seen["menu_rows"], strict=True))
        self.assertEqual(rows[t("word.home")], ["home", self.seen["heard"]["home"]])
        self.assertEqual(rows["/"][0], "storage")
        self.assertEqual(rows[Path(self.seen["heard"]["base"]).name][0], "folder")

    def test_choosing_the_current_folder_does_nothing(self) -> None:
        self.assertEqual(self.seen["after_current"], self.seen["face_start"])

    def test_choosing_a_folder_above_lists_it(self) -> None:
        self.assertEqual(self.seen["above_path"], str(Path(self.seen["heard"]["base"]).parent))

    def test_choosing_a_place_lists_it(self) -> None:
        self.assertEqual(self.seen["home_path"], self.seen["heard"]["home"])


if __name__ == "__main__":
    if sys.argv[1:2] == ["serve"]:
        exit_with_parent()
        serve(int(sys.argv[2]))
    else:
        unittest.main()
