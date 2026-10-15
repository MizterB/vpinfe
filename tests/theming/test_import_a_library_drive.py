"""Settings > Library > Folders beside Add: Import a library, through the Folders source, in a real
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
from tests.support.live_instance import LiveInstance
from tests.support.manager_walk import ManagerWalk

WORDS = json.loads((Path(__file__).resolve().parents[2] / "extensions" / "library_importer"
                    / "i18n" / "en.json").read_text(encoding="utf-8"))
CARD = ".manager-wizard-card"
TITLE = f"{CARD} .manager-dialog-title"
FORWARD = f"{CARD} .manager-wizard-forward"
RADIO = f"{CARD} .manager-wizard-pick"
SHOWS = "!!document.querySelector(%s)"
TEXT_OF = "(() => { const el = document.querySelector(%s); return el ? el.innerText : null; })()"
CHOICES = (f"[...document.querySelectorAll({json.dumps(RADIO)})]"
           ".map(el => [el.innerText.trim(), el.getAttribute('aria-checked') === 'true'])")
TABLES = ("Alpha", "Bravo")
# The pages between the folder and the question of how to bring the tables in; each is
# passed with what it offers ticked.
STEPS_BEFORE_HOW = ("games", "matches", "names", "media", "things")
ADDRESS = "/manager?view=settings&page=library.folders"
ROWS = ".manager-settings-body .manager-member-row"
ACTIONS = ".manager-settings-body .manager-action"
ROW_COUNT = f"document.querySelectorAll({json.dumps(ROWS)}).length === %d"


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

        async with BrowserSession(chromium_path() or "") as browser:
            walk = ManagerWalk(browser, instance)

            async def click_text(selector: str, text: str) -> None:
                await browser.click(selector, nth=int(await browser.wait_for(
                    "(() => { const i = [...document.querySelectorAll("
                    f"{json.dumps(selector)})].findIndex(el => el.innerText.includes("
                    f"{json.dumps(text)})); return i >= 0 ? i + 1 : 0; }})()")) - 1)

            async def type_into_the_path(text: str, nth: int = -1) -> None:
                """An input on the step, the last unless `nth` says: the source step opens
                with a select, which holds an input of its own, and the path is the field
                after it."""
                count = int(await browser.evaluate(
                    f"document.querySelectorAll({json.dumps(CARD + ' input')}).length"))
                at = nth % count
                await browser.click(f"{CARD} input", nth=at)
                await browser.evaluate(
                    f"[...document.querySelectorAll({json.dumps(CARD + ' input')})]"
                    f"[{at}].select()")
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

            await walk.visit(ADDRESS)
            await browser.wait_for(ROW_COUNT % 1)
            await browser.wait_for(f"document.querySelectorAll({json.dumps(ACTIONS)}).length === 2")
            # A reload would take this with it.
            await browser.evaluate("window.keptThroughTheImport = true")
            seen["buttons"] = await browser.evaluate(
                f"[...document.querySelectorAll({json.dumps(ACTIONS)})]"
                ".map(el => el.innerText.replace(/^[a-z_]+\\s*/, '').trim())")
            await walk.act(lambda: click_text(ACTIONS, WORDS["action.import.label"]),
                           until=SHOWS % json.dumps(CARD))

            seen["opening"] = await browser.evaluate(TEXT_OF % json.dumps(TITLE))
            await walk.act(lambda: browser.click(f"{CARD} .q-select"),
                           until=SHOWS % json.dumps(".q-menu .q-item"))
            await walk.act(lambda: click_text(".q-menu .q-item", WORDS["source.folders"]),
                           until=f"!document.querySelector({json.dumps('.q-menu')})")
            await forward()
            seen["sources"] = await browser.evaluate(TEXT_OF % json.dumps(CARD))
            await type_into_the_path(str(pile), 0)
            title = await forward()
            seen["tables"] = await browser.evaluate(TEXT_OF % json.dumps(CARD))
            for _ in range(len(STEPS_BEFORE_HOW)):
                if title == WORDS["wizard.how.title"]:
                    break
                title = await forward()
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
                await browser.wait_for(ROW_COUNT % 2)
            except TimeoutError:
                pass
            seen["rows_after"] = await browser.evaluate(
                f"[...document.querySelectorAll({json.dumps(ROWS)})].map(el => el.innerText)")
            seen["into"] = str(into)
            await browser.click('a.manager-nav-row[href="/manager?view=games"]')
            try:
                await browser.wait_for(
                    "TABLES.every(name => document.body.innerText.includes(name))"
                    .replace("TABLES", json.dumps(list(TABLES))))
                seen["games_after"] = True
            except TimeoutError:
                seen["games_after"] = False
            seen["kept"] = await browser.evaluate("window.keptThroughTheImport === true")
        return seen

    def test_the_page_offers_it_beside_add(self) -> None:
        self.assertEqual(self.seen["buttons"][:2], [t("manager.folders.add_folder"),
                                                     WORDS["action.import.label"]])

    def test_it_asks_where_the_library_is_first(self) -> None:
        self.assertEqual(self.seen["opening"], WORDS["wizard.source.title"])

    def test_a_folder_of_tables_is_asked_for_by_where_its_files_are(self) -> None:
        self.assertIn(WORDS["wizard.sources.no_frontend.title"], self.seen["sources"])

    def test_the_tables_are_listed_to_tick_before_it_asks_how(self) -> None:
        self.assertIn(WORDS["wizard.games.title"], self.seen["tables"])
        for name in TABLES:
            self.assertIn(name, self.seen["tables"])

    def test_copy_is_the_default(self) -> None:
        checked = [name for name, on in self.seen["how_choices"] if on]
        self.assertEqual(len(checked), 1)
        self.assertIn(WORDS["wizard.how.copy"], checked[0])

    def test_move_says_what_it_leaves_behind_before_it_is_chosen(self) -> None:
        self.assertIn(WORDS["wizard.how.move.folders_help"], self.seen["how_text"])
        self.assertIn(WORDS["wizard.how.move.folders_help"], self.seen["move_text"])

    def test_copy_and_move_both_ask_for_the_library_folder(self) -> None:
        label = WORDS["wizard.how.into.label"]
        self.assertIn(label, self.seen["how_text"])
        self.assertIn(label, self.seen["move_text"])

    def test_the_summary_says_what_a_copy_takes(self) -> None:
        self.assertIn(WORDS["wizard.summary.space"], self.seen["summary"])

    def test_every_table_is_copied_into_a_folder_of_its_own(self) -> None:
        self.assertEqual(self.seen["copied"], [True, True], self.seen["log"])

    def test_a_copy_leaves_the_source_where_it_was(self) -> None:
        self.assertEqual(self.seen["left"], [True, True])

    def test_the_folder_it_copied_into_shows_on_the_page_without_a_reload(self) -> None:
        self.assertTrue(self.seen["kept"], "the page was reloaded")
        self.assertEqual(len(self.seen["rows_after"]), 2)
        self.assertTrue(any(self.seen["into"] in row for row in self.seen["rows_after"]))

    def test_the_games_it_made_are_listed_without_a_reload(self) -> None:
        self.assertIs(self.seen["games_after"], True, self.seen["games_after"])
        self.assertTrue(self.seen["kept"], "the page was reloaded")


if __name__ == "__main__":
    unittest.main()
