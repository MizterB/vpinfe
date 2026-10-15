"""A sign-in request on a Console open on this device, driven in a real browser.

Slow: boots a real instance and a real browser. A headless instance shows the digits at
once, which is the state the dialog draws after Show.
"""

from __future__ import annotations

import asyncio
import json
import unittest
import urllib.request
from pathlib import Path
from tempfile import TemporaryDirectory

from common.i18n import t
from tests.support.browser_session import BrowserSession, chromium_path
from tests.support.console_walk import ConsoleWalk
from tests.support.live_instance import LiveInstance

DIALOG = ".console-confirm"
SIGN_OUT_ROW = ".console-action--inline"
NOTHING_SIGNED_IN = json.dumps(t("console.security.none"))
TEXT_OF = "(() => { const el = document.querySelector(%s); return el ? el.innerText : null; })()"
SIGN_OUT_WORD = json.dumps(t("console.security.sign_out"))
SIGN_OUT_HERE = ("[...document.querySelectorAll('.console-invite')]"
                 f".some(el => el.innerText.includes({SIGN_OUT_WORD}))")


_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())


def _post(instance: LiveInstance, path: str, body: dict) -> dict:
    """The asking browser's cookie comes back with the code, as a real browser sends it."""
    request = urllib.request.Request(instance.console_url(path), data=json.dumps(body).encode(),
                                     method="POST",
                                     headers={"Content-Type": "application/json"})
    with _opener.open(request, timeout=10) as answer:
        return json.load(answer)


@unittest.skipIf(chromium_path() is None, "no Chromium on this machine")
class ConsoleSignInNoticeDrive(unittest.TestCase):
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
        instance.wait_for_api()
        async with BrowserSession(binary) as browser:
            walk = ConsoleWalk(browser, instance)
            await walk.visit("/")
            seen["quiet_before"] = await browser.evaluate(
                TEXT_OF % json.dumps(DIALOG))
            seen["sign_out_here"] = await browser.evaluate(SIGN_OUT_HERE)
            asked = _post(instance, "/api/v1/auth/code", {})
            await browser.wait_for(f"!!document.querySelector({json.dumps(DIALOG)})", timeout=30)
            seen["asked"] = await browser.evaluate(TEXT_OF % json.dumps(DIALOG))
            digits = [part for part in str(seen["asked"]).split()
                      if part.isdigit() and len(part) == 6]
            _post(instance, "/api/v1/auth/session",
                  {"request_id": asked["request_id"], "code": digits[0]})
            await browser.click(f"{DIALOG} .console-dialog-footer button")
            await browser.wait_for(f"!document.querySelector({json.dumps(DIALOG)})", timeout=30)
            seen["closed"] = True
            await walk.visit("/console?view=settings&page=vpinfe.security")
            seen["signed_in"] = await browser.evaluate(
                f"document.querySelectorAll({json.dumps(SIGN_OUT_ROW)}).length")
            await walk.act(lambda: browser.click(SIGN_OUT_ROW),
                           until=f"document.body.innerText.includes({NOTHING_SIGNED_IN})")
            seen["after_sign_out"] = await browser.evaluate(
                f"document.querySelectorAll({json.dumps(SIGN_OUT_ROW)}).length")
        return seen

    def test_nothing_shows_until_a_device_asks(self) -> None:
        self.assertIsNone(self.seen["quiet_before"])

    def test_this_device_is_not_offered_a_sign_out(self) -> None:
        self.assertFalse(self.seen["sign_out_here"])

    def test_the_dialog_names_the_asker_and_shows_six_digits(self) -> None:
        words = str(self.seen["asked"])
        self.assertIn(t("console.security.wants", address="\0").split("\0")[0].strip(), words)
        digits = [part for part in words.split() if part.isdigit() and len(part) == 6]
        self.assertEqual(len(digits), 1, words)

    def test_close_dismisses_it(self) -> None:
        self.assertTrue(self.seen["closed"])

    def test_signing_a_browser_out_takes_its_row_off_the_page(self) -> None:
        self.assertEqual(self.seen["signed_in"], 1)
        self.assertEqual(self.seen["after_sign_out"], 0)


if __name__ == "__main__":
    unittest.main()
