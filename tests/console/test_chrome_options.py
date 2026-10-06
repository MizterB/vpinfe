"""Settings > Frontend > Browser: the flags a window opens with, as the three settings give them."""

from __future__ import annotations

import unittest

from console import chrome_options
from frontend.chromium_manager import CHROMIUM_BASE_FLAGS


class EffectiveFlags(unittest.TestCase):
    def test_the_built_in_flags_are_there_when_nothing_is_set(self) -> None:
        flags = chrome_options.effective({})

        self.assertTrue(set(CHROMIUM_BASE_FLAGS) <= set(flags))
        self.assertTrue(any(flag.startswith("--app=") for flag in flags))

    def test_what_is_added_comes_last_and_keeps_its_quoting(self) -> None:
        flags = chrome_options.effective(
            {"options": '--first\n--name="two words"'})

        self.assertEqual(flags[-2:], ["--first", "--name=two words"])

    def test_a_dropped_flag_leaves_the_rest(self) -> None:
        dropped = CHROMIUM_BASE_FLAGS[0]

        flags = chrome_options.effective({"options_exclude": dropped})

        self.assertNotIn(dropped, flags)
        self.assertIn(CHROMIUM_BASE_FLAGS[-1], flags)

    def test_turning_the_defaults_off_leaves_only_what_the_window_needs(self) -> None:
        for off in (True, "true", "True"):
            flags = chrome_options.effective({"disable_defaults": off, "options": "--mine"})

            self.assertFalse(set(CHROMIUM_BASE_FLAGS) & set(flags), off)
            self.assertIn("--mine", flags)

    def test_a_switch_that_is_off_keeps_the_defaults(self) -> None:
        for off in (False, "false", ""):
            self.assertTrue(set(CHROMIUM_BASE_FLAGS) <= set(
                chrome_options.effective({"disable_defaults": off})), off)

    def test_a_switch_that_is_not_a_yes_keeps_the_defaults(self) -> None:
        self.assertTrue(set(CHROMIUM_BASE_FLAGS) <= set(
            chrome_options.effective({"disable_defaults": "banana"})))

    def test_a_flag_with_a_value_is_dropped_by_its_name(self) -> None:
        valued = next(flag for flag in CHROMIUM_BASE_FLAGS if "=" in flag)

        flags = chrome_options.effective({"options_exclude": valued.split("=")[0]})

        self.assertNotIn(valued, flags)

    def test_a_line_that_will_not_parse_adds_nothing(self) -> None:
        flags = chrome_options.effective({"options": '--bad="unclosed'})

        self.assertFalse(any("unclosed" in flag for flag in flags))


class PreviewAfterASave(unittest.IsolatedAsyncioTestCase):
    async def test_a_saved_value_is_what_the_next_reading_uses(self) -> None:
        async def accepted(_value: object) -> bool:
            return True

        preview = chrome_options.Preview({"chromium": {"options": "--old"}})
        await preview.after("options", accepted)("--new")

        self.assertEqual(preview.held["options"], "--new")

    async def test_a_refused_save_leaves_the_reading_alone(self) -> None:
        async def refused(_value: object) -> bool:
            return False

        preview = chrome_options.Preview({"chromium": {"options": "--old"}})
        self.assertFalse(await preview.after("options", refused)("--new"))

        self.assertEqual(preview.held["options"], "--old")


if __name__ == "__main__":
    unittest.main()
