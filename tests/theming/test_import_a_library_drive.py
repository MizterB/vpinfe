"""Library > Locations beside Add: Import a library, through the Folders source, in a real
browser - the entry, the questions, Copy or Move, the space line, and the copy itself.

Slow: boots a real instance and a real browser.
"""

from __future__ import annotations

import asyncio
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from common.i18n import t
from tests.support.browser_session import BrowserSession, chromium_path
from tests.support.console_walk import ConsoleWalk
from tests.support.live_instance import LiveInstance

WORDS = json.loads((Path(__file__).resolve().parents[2] / "extensions" / "library_importer"
                    / "i18n" / "en.json").read_text(encoding="utf-8"))
CARD = ".console-wizard-card"
TITLE = f"{CARD} .console-dialog-title"
FORWARD = f"{CARD} .console-wizard-forward"
RADIO = f"{CARD} .console-wizard-pick"
SHOWS = "!!document.querySelector(%s)"
TEXT_OF = "(() => { const el = document.querySelector(%s); return el ? el.innerText : null; })()"
CHOICES = (f"[...document.querySelectorAll({json.dumps(RADIO)})]"
           ".map(el => [el.innerText.trim(), el.getAttribute('aria-checked') === 'true'])")
TABLES = ("Alpha", "Bravo")


def counted(text: str) -> str:
    """True once the Locations count line reads `text`."""
    return ("[...document.querySelectorAll('.console-label')]"
            f".some(el => el.innerText.trim() === {json.dumps(text)})")


def chosen(label: str) -> str:
    """True once the picture row showing `label` is the checked one."""
    return (f"[...document.querySelectorAll({json.dumps(RADIO)})].some(el => "
            "el.getAttribute('aria-checked') === 'true' && "
            f"el.innerText.includes({json.dumps(label)}))")


class ImportALibraryDrive(unittest.TestCase):
    seen: dict = {}

    @classmethod
    def setUpClass(cls) -> None:
        if not chromium_path():
            raise unittest.SkipTest("no Chromium on this machine")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            pile, into = root / "pile", root / "second-library"
            pile.mkdir()
            into.mkdir()
            for name in TABLES:
                (pile / f"{name}.vpx").write_bytes(b"x" * 2048)
            (root / "library").mkdir()
            with LiveInstance(root / "library") as instance:
                cls.seen = asyncio.run(cls._drive(instance, pile, into))

    @classmethod
    async def _drive(cls, instance: LiveInstance, pile: Path, into: Path) -> dict:
        seen: dict = {"titles": []}
        instance.wait_for_api()

        async with BrowserSession(chromium_path()) as browser:
            walk = ConsoleWalk(browser, instance)

            async def click_text(selector: str, text: str) -> None:
                await browser.click(selector, nth=int(await browser.wait_for(
                    "(() => { const i = [...document.querySelectorAll("
                    f"{json.dumps(selector)})].findIndex(el => el.innerText.includes("
                    f"{json.dumps(text)})); return i >= 0 ? i + 1 : 0; }})()")) - 1)

            async def type_into_the_path(text: str) -> None:
                """The last input on the step: the source step opens with a select, which
                holds an input of its own, and the path is the field after it."""
                last = int(await browser.evaluate(
                    f"document.querySelectorAll({json.dumps(CARD + ' input')}).length")) - 1
                await browser.click(f"{CARD} input", nth=last)
                await browser.evaluate(
                    f"[...document.querySelectorAll({json.dumps(CARD + ' input')})]"
                    ".at(-1).select()")
                await browser.send("Input.insertText", {"text": text})

            async def forward() -> str:
                """Press the dialog's forward button; the title of the step that follows."""
                before = await browser.evaluate(TEXT_OF % json.dumps(TITLE))
                await browser.click(FORWARD)
                try:
                    await browser.wait_for(
                        f"(document.querySelector({json.dumps(TITLE)}) || {{}}).innerText"
                        f" !== {json.dumps(before)}")
                except TimeoutError as exc:
                    shown = await browser.evaluate(TEXT_OF % json.dumps(CARD))
                    raise AssertionError(
                        f"{exc}\n{shown}\n{instance.output()}") from exc
                await walk.drawn()
                title = await browser.evaluate(TEXT_OF % json.dumps(TITLE))
                seen["titles"].append(title)
                return title

            await walk.visit("/console?view=locations")
            await browser.wait_for("!!document.querySelector('.console-action')")
            await browser.wait_for(counted(t("console.locations.folder_count", count=1)))
            # A reload would take this with it.
            await browser.evaluate("window.keptThroughTheImport = true")
            await walk.act(lambda: browser.click(".console-action"),
                           until=SHOWS % json.dumps(".q-menu .console-menu-item"))
            seen["menu"] = await browser.evaluate(
                "[...document.querySelectorAll('.q-menu .console-menu-item')]"
                ".map(el => el.innerText.trim())")
            await walk.act(lambda: click_text(".q-menu .console-menu-item",
                                              WORDS["action.import.label"]),
                           until=SHOWS % json.dumps(CARD))

            seen["opening"] = await browser.evaluate(TEXT_OF % json.dumps(TITLE))
            await type_into_the_path(str(pile))
            await forward()
            seen["sources"] = await browser.evaluate(TEXT_OF % json.dumps(CARD))
            await forward()
            seen["how_choices"] = await browser.evaluate(CHOICES)
            seen["how_text"] = await browser.evaluate(TEXT_OF % json.dumps(CARD))

            await walk.act(lambda: click_text(RADIO, WORDS["wizard.how.move"]),
                           until=chosen(WORDS["wizard.how.move"]))
            seen["move_text"] = await browser.evaluate(TEXT_OF % json.dumps(CARD))
            await walk.act(lambda: click_text(RADIO, WORDS["wizard.how.copy"]),
                           until=chosen(WORDS["wizard.how.copy"]))

            await type_into_the_path(str(into))
            await forward()
            seen["summary"] = await browser.evaluate(TEXT_OF % json.dumps(CARD))
            seen["confirm"] = await browser.evaluate(
                f"document.querySelector({json.dumps(FORWARD)}).innerText")

            await browser.click(FORWARD)
            # Drawn disabled from the start of the run, and enabled when it is over.
            close = json.dumps(t("word.close"))
            await browser.wait_for(
                f"[...document.querySelectorAll({json.dumps(CARD + ' button')})]"
                f".some(el => !el.disabled && el.innerText.includes({close}))",
                timeout=60)
            seen["copied"] = [(into / name / f"{name}.vpx").exists() for name in TABLES]
            seen["left"] = [(pile / f"{name}.vpx").exists() for name in TABLES]
            seen["log"] = instance.output()

            await walk.act(lambda: click_text(f"{CARD} button", t("word.close")),
                           until=f"!document.querySelector({json.dumps(CARD)})")
            try:
                await browser.wait_for(counted(t("console.locations.folder_count", count=2)))
            except TimeoutError:
                pass
            seen["count_after"] = await browser.evaluate(
                "[...document.querySelectorAll('.console-label')].map(el => el.innerText.trim())")
            seen["listed"] = await browser.evaluate(
                "[...document.querySelectorAll('.ag-cell')]"
                f".some(el => el.innerText.includes({json.dumps(into.name)}))")
            seen["kept"] = await browser.evaluate("window.keptThroughTheImport === true")
        return seen

    def test_the_menu_offers_it_beside_add(self) -> None:
        self.assertEqual(self.seen["menu"], [t("console.locations.add_folder"),
                                              WORDS["action.import.label"]])

    def test_it_asks_where_the_library_is_first(self) -> None:
        self.assertEqual(self.seen["opening"], WORDS["wizard.source.title"])

    def test_a_folder_of_tables_is_asked_for_by_where_its_files_are(self) -> None:
        self.assertIn(WORDS["wizard.sources.no_frontend.title"], self.seen["sources"])

    def test_copy_is_the_default(self) -> None:
        checked = [name for name, on in self.seen["how_choices"] if on]
        self.assertEqual(len(checked), 1)
        self.assertIn(WORDS["wizard.how.copy"], checked[0])

    def test_move_says_what_it_leaves_behind_before_it_is_chosen(self) -> None:
        self.assertIn(WORDS["wizard.how.move.folders_help"], self.seen["how_text"])
        self.assertIn(WORDS["wizard.how.move.folders_help"], self.seen["move_text"])

    def test_the_summary_says_what_a_copy_takes(self) -> None:
        self.assertIn(WORDS["wizard.summary.space"], self.seen["summary"])

    def test_every_table_is_copied_into_a_folder_of_its_own(self) -> None:
        self.assertEqual(self.seen["copied"], [True, True], self.seen["log"])

    def test_a_copy_leaves_the_source_where_it_was(self) -> None:
        self.assertEqual(self.seen["left"], [True, True])

    def test_the_folder_it_copied_into_shows_on_the_page_without_a_reload(self) -> None:
        self.assertTrue(self.seen["kept"], "the page was reloaded")
        self.assertIn(t("console.locations.folder_count", count=2), self.seen["count_after"])
        self.assertTrue(self.seen["listed"])


if __name__ == "__main__":
    unittest.main()
