"""A sign-in request on a Manager open on this device, driven in a real browser.

Slow: boots a real instance and a real browser. A headless instance shows the digits at
once, which is the state the dialog draws after Show.
"""

from __future__ import annotations

import asyncio
import json
import time
import unittest
import urllib.request
from pathlib import Path
from tempfile import TemporaryDirectory

from common import sign_in
from common.i18n import t
from manager import signed_in_rows
from tests.support.browser_session import BrowserSession, chromium_path
from tests.support.live_instance import LiveInstance
from tests.support.manager_walk import ManagerWalk, clicked

DIALOG = ".manager-confirm"
SECURITY = "/manager?view=settings&page=vpinfe.security"
SUMMARY = ".manager-summary"
LIST = ".manager-signed-in-card"
NOTHING_SIGNED_IN = json.dumps(t("manager.security.none"))
TEXT_OF = "(() => { const el = document.querySelector(%s); return el ? el.innerText : null; })()"
SIGN_OUT_WORD = json.dumps(t("manager.security.sign_out"))
# A button's text starts with its icon's name.
NAMED = "el.innerText.trim().split('\\n').pop() === %s"
WAITING = ("[...document.querySelectorAll('.manager-fact-label')]"
           f".some(el => el.innerText.trim() === {json.dumps(t('manager.security.waiting'))})")
SIGN_OUT_BUTTON = ("[...document.querySelectorAll('.manager-signed-in-card "
                   ".manager-dialog-footer button')]"
                   f".find(el => {NAMED % SIGN_OUT_WORD})")
SIGN_OUT_ENABLED = (f"(() => {{ const b = {SIGN_OUT_BUTTON}; return !!b && "
                    "b.getAttribute('aria-disabled') !== 'true' && !b.disabled; })()")
SIGN_OUT_ALL_WORD = json.dumps(t("manager.security.sign_out_all"))
SIGN_OUT_ALL_ASIDE = ("[...document.querySelectorAll('.manager-signed-in-card button')]"
                      f".find(el => {NAMED % SIGN_OUT_ALL_WORD})")
SIGN_OUT_ALL_CONFIRM = ("[...document.querySelectorAll('.manager-confirm button')]"
                        f".find(el => {NAMED % SIGN_OUT_ALL_WORD})")
# The pinned checkbox column draws every row a second time, in its own container.
ROWS = f"{LIST} .ag-center-cols-container .ag-row"
ROW_BOX = f"{LIST} .ag-row .ag-selection-checkbox input"
CELL_OF = ("(() => { const el = document.querySelector("
           f"'{LIST} .ag-row .ag-cell[col-id=%s]'); return el ? el.innerText : null; }})()")
SIGN_OUT_HERE = ("[...document.querySelectorAll('.manager-invite')]"
                 f".some(el => el.innerText.includes({SIGN_OUT_WORD}))")
FILL = f"getComputedStyle(document.querySelector({json.dumps(SUMMARY)})).backgroundColor"
CLEAR = "rgba(0, 0, 0, 0)"
# The longest each column draws: every month's date, the last relative step before the date, an
# address, and the longest name a browser is given, with the chip on the one in use.
_AGO = (t("date.minutes_ago", count=59), t("date.hours_ago", count=23),
        t("date.days_ago", count=29), "28 Sep 2026")
LONGEST = [
    {"id": f"long{month}", "browser": t("signin.agent", browser="Firefox", device="Chromebook"),
     "here": month == 1, "address": "255.255.255.255",
     "access": "Remote", "created": f"2026-{month:02d}-28T00:00:00+00:00",
     "created_at": f"2026-{month:02d}-28 00:00",
     "created_day": f"28 {t(f'date.month.{month}')} 2026", "last_used": "2026-10-15T00:00:00+00:00",
     "last_used_ago": _AGO[month % len(_AGO)], "last_used_at": "2026-10-15 00:00"}
    for month in range(1, 13)]
CELLS = f"{LIST} .ag-center-cols-container .ag-cell"
_GRID_API = (f"getElement(Number(document.querySelector('{LIST} .ag-root-wrapper')"
             ".closest('.nicegui-aggrid').id.slice(1))).api")
# Replaces the list's rows with LONGEST, keeping the ones it had for CUT_OFF_AT_THE_LONGEST.
SHOW_LONGEST = (
    f"(() => {{ const api = {_GRID_API}; window.signedInRowsWere = [];"
    " api.forEachNode(node => window.signedInRowsWere.push(node.data));"
    f" api.setGridOption('rowData', {json.dumps(LONGEST)}); return true; }})()")
ALL_LONGEST_DRAWN = (f"document.querySelectorAll('{CELLS}').length"
                     f" === {len(LONGEST) * len(signed_in_rows.COLUMNS)}")
# Reports the cells that cut their text off, then puts the rows SHOW_LONGEST replaced back.
CUT_OFF_AT_THE_LONGEST = (
    f"(() => {{ const cells = [...document.querySelectorAll('{CELLS}')];"
    " const cut = cells.filter(cell => cell.scrollWidth > cell.clientWidth)"
    "  .map(cell => `${cell.getAttribute('col-id')} ${cell.scrollWidth}>${cell.clientWidth}:"
    " ${cell.innerText}`);"
    f" {_GRID_API}.setGridOption('rowData', window.signedInRowsWere);"
    " return {cut, cells: cells.length}; })()")


def _browser() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor())


def _post(instance: LiveInstance, path: str, body: dict,
          opener: urllib.request.OpenerDirector) -> dict:
    """The asking browser's cookie comes back with the code, as a real browser sends it."""
    request = urllib.request.Request(instance.manager_url(path), data=json.dumps(body).encode(),
                                     method="POST",
                                     headers={"Content-Type": "application/json"})
    with opener.open(request, timeout=10) as answer:
        return json.load(answer)


def _digits(words: object) -> str:
    return next(part for part in str(words).split() if part.isdigit() and len(part) == 6)


@unittest.skipIf(chromium_path() is None, "no Chromium on this machine")
class ManagerSignInNoticeDrive(unittest.TestCase):
    seen: dict = {}

    @classmethod
    def setUpClass(cls) -> None:
        binary = chromium_path()
        assert binary is not None
        with TemporaryDirectory() as tmp, LiveInstance(Path(tmp)) as instance:
            cls.seen = asyncio.run(cls._drive(instance, binary))

    @classmethod
    async def _drive(cls, instance: LiveInstance, binary: str) -> dict:
        seen: dict = {}
        first, second = _browser(), _browser()
        instance.wait_for_api()
        async with BrowserSession(binary) as browser:
            walk = ManagerWalk(browser, instance)
            await walk.visit("/")
            seen["quiet_before"] = await browser.evaluate(
                TEXT_OF % json.dumps(DIALOG))
            seen["sign_out_here"] = await browser.evaluate(SIGN_OUT_HERE)
            asked = _post(instance, "/api/v1/auth/code", {}, first)
            first_asked = time.monotonic()
            await browser.wait_for(f"!!document.querySelector({json.dumps(DIALOG)})", timeout=30)
            seen["asked"] = await browser.evaluate(TEXT_OF % json.dumps(DIALOG))
            _post(instance, "/api/v1/auth/session",
                  {"request_id": asked["request_id"], "code": _digits(seen["asked"])}, first)
            await browser.click(f"{DIALOG} .manager-dialog-footer button")
            await browser.wait_for(f"!document.querySelector({json.dumps(DIALOG)})", timeout=30)
            seen["closed"] = True

            await walk.visit(SECURITY)
            seen["waiting_before"] = await browser.evaluate(WAITING)
            seen["summary"] = await browser.evaluate(TEXT_OF % json.dumps(SUMMARY))
            await asyncio.sleep(max(0.0, sign_in.ASK_SPACING_SECONDS + 1
                                    - (time.monotonic() - first_asked)))
            asked = _post(instance, "/api/v1/auth/code", {}, second)
            await browser.wait_for(WAITING, timeout=30)
            seen["waiting_while_asked"] = True
            await browser.wait_for(
                f"/\\b\\d{{6}}\\b/.test({TEXT_OF % json.dumps(DIALOG)} || '')", timeout=30)
            popup = await browser.evaluate(TEXT_OF % json.dumps(DIALOG))
            _post(instance, "/api/v1/auth/session",
                  {"request_id": asked["request_id"], "code": _digits(popup)}, second)
            await browser.click(f"{DIALOG} .manager-dialog-footer button")
            await browser.wait_for(f"!({WAITING})", timeout=30)
            seen["waiting_after_sign_in"] = await browser.evaluate(WAITING)
            await browser.wait_for(
                f"document.querySelector({json.dumps(SUMMARY)}).innerText.includes('2 ')",
                timeout=30)
            seen["summary_after"] = await browser.evaluate(TEXT_OF % json.dumps(SUMMARY))
            await browser.unhover()
            await browser.wait_for(f"{FILL} === {json.dumps(CLEAR)}")
            seen["fill_at_rest"] = await browser.evaluate(FILL)
            await browser.hover(SUMMARY)
            await browser.wait_for(f"{FILL} !== {json.dumps(CLEAR)}")
            seen["fill_hovered"] = await browser.evaluate(FILL)
            await browser.unhover()

            await walk.act(clicked(browser, f"document.querySelector({json.dumps(SUMMARY)})"
                                            ".click() || true"),
                           until=f"document.querySelectorAll({json.dumps(ROWS)})"
                                 ".length === 2")
            seen["list_rows"] = await browser.evaluate(
                f"document.querySelectorAll({json.dumps(ROWS)}).length")
            seen["first_seen"] = await browser.evaluate(CELL_OF % "created")
            seen["last_used"] = await browser.evaluate(CELL_OF % "last_used")
            await browser.evaluate(SHOW_LONGEST)
            await browser.wait_for(ALL_LONGEST_DRAWN)
            seen["longest"] = await browser.evaluate(CUT_OFF_AT_THE_LONGEST)
            await browser.wait_for(f"document.querySelectorAll({json.dumps(ROWS)}).length === 2")
            seen["sign_out_before_pick"] = await browser.evaluate(SIGN_OUT_ENABLED)
            await walk.act(lambda: browser.click(ROW_BOX), until=SIGN_OUT_ENABLED)
            await walk.act(clicked(browser, f"({SIGN_OUT_BUTTON}).click() || true"),
                           until=f"document.querySelectorAll({json.dumps(ROWS)})"
                                 ".length === 1")
            seen["left"] = await browser.evaluate(
                f"document.querySelectorAll({json.dumps(ROWS)}).length")
            await walk.act(clicked(browser, f"({SIGN_OUT_ALL_ASIDE}).click() || true"),
                           until=f"!!document.querySelector({json.dumps(DIALOG)})")
            await walk.act(clicked(browser, f"({SIGN_OUT_ALL_CONFIRM}).click() || true"),
                           until=f"document.body.innerText.includes({NOTHING_SIGNED_IN})")
            seen["list_closed"] = not await browser.evaluate(
                f"!!document.querySelector({json.dumps(LIST)})")
        return seen

    def test_nothing_shows_until_a_device_asks(self) -> None:
        self.assertIsNone(self.seen["quiet_before"])

    def test_this_device_is_not_offered_a_sign_out(self) -> None:
        self.assertFalse(self.seen["sign_out_here"])

    def test_the_dialog_names_the_asker_and_shows_six_digits(self) -> None:
        words = str(self.seen["asked"])
        self.assertIn(t("manager.security.wants", address="\0").split("\0")[0].strip(), words)
        digits = [part for part in words.split() if part.isdigit() and len(part) == 6]
        self.assertEqual(len(digits), 1, words)

    def test_close_dismisses_it(self) -> None:
        self.assertTrue(self.seen["closed"])

    def test_a_device_waiting_to_sign_in_has_a_row_only_while_it_waits(self) -> None:
        self.assertFalse(self.seen["waiting_before"])
        self.assertTrue(self.seen["waiting_while_asked"])
        self.assertFalse(self.seen["waiting_after_sign_in"])

    def test_the_browsers_signed_in_are_one_summary_row_that_counts_them(self) -> None:
        self.assertIn(t("manager.security.count", count=1), self.seen["summary"])
        self.assertIn(t("manager.security.count", count=2), self.seen["summary_after"])

    def test_the_list_has_a_row_to_a_browser_with_first_seen_and_last_used(self) -> None:
        self.assertEqual(self.seen["list_rows"], 2)
        self.assertTrue(str(self.seen["first_seen"]).strip())
        self.assertTrue(str(self.seen["last_used"]).strip())

    def test_the_summary_lights_under_the_pointer_and_not_otherwise(self) -> None:
        self.assertEqual(self.seen["fill_at_rest"], CLEAR)
        self.assertNotEqual(self.seen["fill_hovered"], self.seen["fill_at_rest"])

    def test_no_cell_cuts_its_text_off_at_the_longest_time_and_date(self) -> None:
        self.assertEqual(self.seen["longest"]["cells"], len(LONGEST) * len(signed_in_rows.COLUMNS))
        self.assertEqual(self.seen["longest"]["cut"], [])

    def test_signing_out_waits_for_a_pick(self) -> None:
        self.assertFalse(self.seen["sign_out_before_pick"])

    def test_signing_one_browser_out_leaves_the_other(self) -> None:
        self.assertEqual(self.seen["left"], 1)

    def test_signing_everyone_out_closes_the_list_and_empties_the_page(self) -> None:
        self.assertTrue(self.seen["list_closed"])


if __name__ == "__main__":
    unittest.main()
