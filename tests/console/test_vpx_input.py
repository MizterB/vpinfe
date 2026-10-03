"""Launchers > Visual Pinball X > Input: the binding table over the launcher's ini."""

from __future__ import annotations

import asyncio
import dataclasses
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

from nicegui import ui

from apps.vpx import areas, bindings
from apps.vpx.config import VPXConfig
from common.apps.contract import SCOPE_LAUNCHER
from common.i18n import t
from console import vpx_input, workbench
from tests.support.clicks import press

INI = ("[Input]\nMapping.LeftFlipper = Key;225 | SDLJoy_0300_1;4\nMapping.RightFlipper = \n"
       "Mapping.Tilt = Key;99999\nMapping.Custom1 = \n")


async def _now(callback: Any, *args: Any, **kwargs: Any) -> Any:
    return callback(*args, **kwargs)


class _Library:
    """What `write_launcher_config` does to the launcher's own file."""

    def __init__(self, settings: dict[str, Any]) -> None:
        self.settings = settings
        self.config = VPXConfig()
        self.calls: list[dict[str, str]] = []

    def write_launcher_config(self, _launcher_id: str, values: dict[str, str]) -> None:
        self.calls.append(dict(values))
        self.config.write(SCOPE_LAUNCHER, "", values, self.settings)


class ThePage(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        held = TemporaryDirectory()
        self.addCleanup(held.cleanup)
        self.path = Path(held.name) / "VPinballX.ini"
        self.path.write_text(INI, encoding="utf-8")
        self.library = _Library({"ini_path": str(self.path)})
        self.enterContext(patch("nicegui.run.io_bound", new=_now))
        self.notify = self.enterContext(patch.object(ui, "notify"))
        self.rebuilt = AsyncMock()
        self.context: dict[str, Any] = {
            "launcher": {"launcher_id": "vpx"}, "library": self.library,
            "rebuild": self.rebuilt, "config_values": {"stale": 1}}
        [self.group] = [g for g in self.library.config.groups(self.library.settings)
                        if g.key == areas.INPUT]
        read = self.library.config.read(SCOPE_LAUNCHER, "", self.library.settings)
        self.flat = {key: str(held.value or "") for key, held in read.items()}
        self.page = vpx_input.Page(self.library, self.context, self.group, dict(self.flat))

    def lines(self) -> list[str]:
        return self.path.read_text(encoding="utf-8").splitlines()

    def test_the_page_is_for_a_group_of_actions_only(self) -> None:
        self.assertTrue(vpx_input.applies(self.group))
        other = Mock(key="input", settings=[Mock(key="Input.JoyCustom1")])
        self.assertFalse(vpx_input.applies(other))
        self.assertFalse(vpx_input.applies(Mock(key="sound", settings=self.group.settings)))

    def test_all_settings_does_not_list_the_actions_a_second_time(self) -> None:
        sound = Mock(key="sound", summarized=False, read_only=False,
                     settings=[Mock(key="Player.PlaySound")])

        listed = workbench._listed_groups({"config_groups": [self.group, sound]})

        self.assertEqual(listed, [sound])

    def test_a_row_per_action_under_its_heading_in_the_order_drawn(self) -> None:
        rows = vpx_input.table_rows(self.group, self.flat)

        self.assertEqual([row.name for row in rows], [one.name for one in bindings.ACTIONS])
        self.assertFalse(any(row.holds for row in rows))

    def test_a_row_ships_with_the_program_s_keys(self) -> None:
        rows = {row.name: row for row in vpx_input.table_rows(self.group, self.flat)}

        self.assertEqual(rows["LeftFlipper"].defaults, ("key:ShiftLeft",))
        self.assertEqual(rows["GenTournament"].defaults, ("chord(key:AltLeft+key:Digit1)",))

    def test_a_controller_button_in_the_file_is_a_chip_that_is_kept(self) -> None:
        rows = {row.name: row for row in vpx_input.table_rows(self.group, self.flat)}

        self.assertEqual([one.label for one in rows["LeftFlipper"].kept],
                         [t("console.vpx_input.controller_button")])
        self.assertEqual(rows["RightFlipper"].kept, ())

    def test_a_chord_with_a_controller_button_in_it_reads_as_one(self) -> None:
        self.assertEqual(vpx_input._kept("Key;225 & SDLJoy_0300_1;3").label,
                         t("console.vpx_input.controller_button"))

    def test_a_key_with_no_name_here_is_a_chip_that_is_kept_too(self) -> None:
        rows = {row.name: row for row in vpx_input.table_rows(self.group, self.flat)}

        [one] = rows["Tilt"].kept
        self.assertEqual((one.label, one.pad), (t("console.vpx_input.other_key"), False))

    def test_the_table_is_told_what_each_action_is_bound_to(self) -> None:
        bound = self.page.bound()

        self.assertEqual(bound["LeftFlipper"], ["key:ShiftLeft"])
        self.assertEqual(bound["RightFlipper"], ["key:ShiftRight"])
        self.assertEqual(bound["Custom1"], [])

    def test_a_controller_press_is_refused_and_a_key_is_not(self) -> None:
        self.assertEqual(self.page.refuse("pad:standard/button:1"),
                         t("console.vpx_input.controllers_in_visual_pinball"))
        self.assertEqual(self.page.refuse("key:KeyA"), "")

    def test_a_key_the_program_has_no_number_for_is_refused(self) -> None:
        self.assertEqual(self.page.refuse("key:IntlRo"),
                         t("console.vpx_input.no_number_for_key"))

    async def test_a_new_key_is_one_line_and_the_controller_button_stays(self) -> None:
        kept = await press(self.page.put, {"LeftFlipper": ["key:KeyA"]})

        self.assertTrue(kept)
        self.assertEqual(self.library.calls,
                         [{"Input.Mapping.LeftFlipper": "Key;4 | SDLJoy_0300_1;4"}])
        self.assertEqual(self.lines()[1], "Mapping.LeftFlipper = Key;4 | SDLJoy_0300_1;4")
        self.assertEqual(self.lines()[2:], INI.splitlines()[2:])
        self.notify.assert_not_called()

    async def test_the_default_is_written_blank(self) -> None:
        await press(self.page.put, {"RightFlipper": ["key:KeyA"]})
        await press(self.page.put, {"RightFlipper": ["key:ShiftRight"]})

        self.assertEqual(self.lines()[2], "Mapping.RightFlipper = ")

    async def test_a_chord_is_written_with_its_parts_together(self) -> None:
        await press(self.page.put, {"Custom1": ["chord(key:AltLeft+key:KeyA)"]})

        self.assertIn("Mapping.Custom1 = Key;226 & Key;4", self.lines())

    async def test_a_row_left_as_it_is_writes_nothing(self) -> None:
        await press(self.page.put, {"Custom1": []})

        self.assertEqual(self.library.calls, [])

    async def test_a_save_that_fails_says_so_and_keeps_nothing(self) -> None:
        self.library.write_launcher_config = Mock(side_effect=OSError("read-only"))

        kept = await press(self.page.put, {"Custom1": ["key:KeyA"]})

        self.assertFalse(kept)
        self.assertEqual(self.notify.call_args.args, (t("said.could_not_save_it"),))
        self.assertEqual(self.page.flat, self.flat)

    async def test_a_row_emptied_that_has_a_default_comes_back_with_it_and_says_so(
            self) -> None:
        self.page.by_name["RightFlipper"] = dataclasses.replace(
            self.page.by_name["RightFlipper"], label="Right Flipper")
        await press(self.page.put, {"RightFlipper": ["key:KeyA"]})
        self.notify.reset_mock()

        await press(self.page.put, {"RightFlipper": []})
        await asyncio.sleep(0)

        self.assertEqual(self.lines()[2], "Mapping.RightFlipper = ")
        self.assertEqual(self.notify.call_args.args[0], t(
            "console.vpx_input.default_back", rows="Right Flipper"))
        self.assertIn("Right Flipper", self.notify.call_args.args[0])
        self.rebuilt.assert_awaited_once()
        self.assertNotIn("config_values", self.context)

    async def test_a_row_emptied_that_has_a_button_kept_keeps_just_the_button(self) -> None:
        await press(self.page.put, {"LeftFlipper": []})

        self.assertEqual(self.lines()[1], "Mapping.LeftFlipper = SDLJoy_0300_1;4")
        self.notify.assert_not_called()
        self.rebuilt.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
