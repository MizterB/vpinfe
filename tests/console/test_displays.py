"""Settings > Hardware > Displays: what the picture reads from the config and writes to it."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

from screeninfo import Monitor

from common import config_service
from common.i18n import t
from console import displays, panel
from console import screens_picture as picture
from console.screens import Screen
from tests.support.clicks import press

SCHEMA = config_service.schema()["sections"]

BIG = Monitor(x=0, y=0, width=2560, height=1440, width_mm=597, height_mm=336,
              name="DP-1", is_primary=True)
TALL = Monitor(x=2560, y=0, width=1080, height=1920, width_mm=336, height_mm=597,
               name="HDMI-1", is_primary=False)
STRIP = Monitor(x=0, y=1440, width=1280, height=390, width_mm=300, height_mm=90,
                name="HDMI-2", is_primary=False)

FIRST = Screen(1, "", 2560, 1440, 0, 0)
SECOND = Screen(2, "", 1080, 1920, 2560, 0)


def _values(**windows: Any) -> dict[str, dict[str, Any]]:
    return {f"windows.{part}": settings for part, settings in windows.items()}


class StoredTests(unittest.TestCase):
    def test_what_is_stored_is_read(self) -> None:
        self.assertEqual(displays.stored(_values(backglass={"screen_id": 2}), SCHEMA,
                                         "windows.backglass", "screen_id"), 2)

    def test_what_is_not_stored_is_the_schema_s_default(self) -> None:
        self.assertEqual(displays.stored({}, SCHEMA, "windows.playfield", "screen_id"), "0")
        self.assertEqual(displays.stored({}, SCHEMA, "windows.backglass", "screen_id"), "")

    def test_a_setting_nobody_declares_is_none(self) -> None:
        self.assertIsNone(displays.stored({}, SCHEMA, "windows.apron", "screen_id"))


class NumberOfTests(unittest.TestCase):
    def test_the_first_stored_screen_is_the_one_a_person_counts_as_1(self) -> None:
        self.assertEqual(displays.number_of(0), 1)
        self.assertEqual(displays.number_of("2"), 3)

    def test_no_screen_is_no_number(self) -> None:
        for stored in ("", None, " ", "-1", "left"):
            with self.subTest(stored=stored):
                self.assertIsNone(displays.number_of(stored))


class PlacedTests(unittest.TestCase):
    def test_each_part_is_where_its_window_is_stored(self) -> None:
        held = displays.placed(_values(playfield={"screen_id": 1}, backglass={"screen_id": 0},
                                       score_view={"screen_id": ""}), SCHEMA)

        self.assertEqual(held, {"backglass": 1, "score_view": None, "playfield": 2})

    def test_a_fresh_install_has_the_playfield_on_the_first_screen_and_the_rest_on_none(
            self) -> None:
        self.assertEqual(displays.placed({}, SCHEMA),
                         {"backglass": None, "score_view": None, "playfield": 1})


class StandingTests(unittest.TestCase):
    def test_it_is_where_the_parts_are_and_how_the_playfield_is_turned(self) -> None:
        held = displays.standing(_values(playfield={"screen_id": 1, "orientation": "portrait",
                                                    "rotation": "90"},
                                         backglass={"screen_id": 0}), SCHEMA)

        self.assertEqual(held.on, {"backglass": 1, "score_view": None, "playfield": 2})
        self.assertEqual(held.turn, ("portrait", "90"))

    def test_a_fresh_install_is_a_landscape_playfield_turned_nowhere(self) -> None:
        self.assertEqual(displays.standing({}, SCHEMA).turn, ("landscape", "0"))


class CabinetTests(unittest.TestCase):
    def test_cab_mode_decides(self) -> None:
        for stored, expected in (("true", True), (True, True), ("false", False), (False, False),
                                 ("", False), (None, False)):
            with self.subTest(stored=stored):
                self.assertEqual(
                    displays.cabinet({"presentation": {"cab_mode": stored}}, SCHEMA), expected)

    def test_it_is_off_until_it_is_set(self) -> None:
        self.assertFalse(displays.cabinet({}, SCHEMA))


class WithoutDrawnTests(unittest.TestCase):
    def _blocks(self) -> list[dict]:
        return [block for block in SCHEMA if str(block.get("name")) in (
            "windows.playfield", "windows.backglass", "windows.score_view", "real_dmd")]

    def test_what_the_picture_draws_is_taken_out(self) -> None:
        kept = {block["name"]: [one["key"] for one in block["options"]]
                for block in displays.without_drawn(self._blocks())}

        self.assertEqual(kept["windows.backglass"], ["override"])
        self.assertEqual(kept["windows.score_view"], ["override"])

    def test_a_section_with_nothing_left_is_dropped(self) -> None:
        self.assertNotIn("windows.playfield",
                         [block["name"] for block in displays.without_drawn(self._blocks())])

    def test_a_section_the_picture_does_not_draw_is_whole(self) -> None:
        [dmd] = [block for block in displays.without_drawn(self._blocks())
                 if block["name"] == "real_dmd"]
        [original] = [block for block in self._blocks() if block["name"] == "real_dmd"]

        self.assertEqual(dmd["options"], original["options"])

    def test_the_schema_it_is_given_is_not_changed(self) -> None:
        blocks = self._blocks()
        before = [len(block["options"]) for block in blocks]

        displays.without_drawn(blocks)

        self.assertEqual([len(block["options"]) for block in blocks], before)

    def test_every_setting_the_picture_draws_is_in_the_schema(self) -> None:
        declared = {(block["name"], one["key"]) for block in SCHEMA
                    for one in block.get("options") or []}

        for section, keys in displays.DRAWN.items():
            for key in keys:
                with self.subTest(section=section, key=key):
                    self.assertIn((section, key), declared)


class WritesTests(unittest.TestCase):
    def test_a_part_moved_is_the_screen_id_its_window_stores(self) -> None:
        self.assertEqual(displays.writes({"backglass": 2}, [FIRST, SECOND], "0"),
                         {"windows.backglass": {"screen_id": 1}})

    def test_a_part_cleared_stores_no_screen(self) -> None:
        self.assertEqual(displays.writes({"score_view": None}, [FIRST], "0"),
                         {"windows.score_view": {"screen_id": ""}})

    def test_a_swap_is_both_windows(self) -> None:
        self.assertEqual(displays.writes({"backglass": 2, "score_view": 1}, [FIRST, SECOND], "0"),
                         {"windows.backglass": {"screen_id": 1},
                          "windows.score_view": {"screen_id": 0}})

    def test_the_playfield_on_another_shape_of_screen_has_its_mounting_worked_out_again(
            self) -> None:
        self.assertEqual(displays.writes({"playfield": 2}, [FIRST, SECOND], "0"),
                         {"windows.playfield": {"screen_id": 1, "orientation": "portrait"}})
        self.assertEqual(displays.writes({"playfield": 1}, [FIRST, SECOND], "0"),
                         {"windows.playfield": {"screen_id": 0, "orientation": "landscape"}})

    def test_the_turn_the_playfield_already_has_is_kept_in_working_it_out(self) -> None:
        self.assertEqual(displays.writes({"playfield": 1}, [FIRST, SECOND], "90"),
                         {"windows.playfield": {"screen_id": 0, "orientation": "portrait"}})

    def test_the_playfield_cleared_has_no_mounting_to_work_out(self) -> None:
        self.assertEqual(displays.writes({"playfield": None}, [FIRST], "0"),
                         {"windows.playfield": {"screen_id": ""}})

    def test_a_turn_stored_as_something_else_is_taken_as_up(self) -> None:
        self.assertEqual(displays.writes({"playfield": 2}, [FIRST, SECOND], "auto"),
                         {"windows.playfield": {"screen_id": 1, "orientation": "portrait"}})

    def test_a_placement_that_is_no_screen_stores_none(self) -> None:
        self.assertEqual(displays.writes({"backglass": picture.INSIDE}, [FIRST], "0"),
                         {"windows.backglass": {"screen_id": ""}})

    def test_the_playfield_on_a_screen_not_connected_is_taken_as_wide(self) -> None:
        self.assertEqual(displays.writes({"playfield": 7}, [FIRST], "0"),
                         {"windows.playfield": {"screen_id": 6, "orientation": "landscape"}})


class RowsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.write = AsyncMock(return_value=True)
        self.rerender = Mock()
        self.control = self.enterContext(patch.object(displays.picture, "Picture"))

    def _drawn(self, values: dict | None = None, monitors: tuple = (BIG, TALL),
               names: tuple = ("", "")) -> dict[str, Any]:
        entries = displays.rows(values or {}, SCHEMA, list(monitors), list(names), self.write,
                                self.rerender)
        [(_, draw)] = [entry for entry in entries if entry[0] is panel.FULL]
        draw()
        return self.control.call_args.kwargs

    def test_it_is_a_heading_and_a_row_across_the_page(self) -> None:
        entries = displays.rows({}, SCHEMA, [BIG], [""], self.write, self.rerender)

        self.assertEqual([label for label, _ in entries], [panel.HEADING, panel.FULL])
        self.assertEqual(entries[0][1], t("console.settings.section_screens"))

    def test_it_draws_the_screens_with_their_names_and_numbers(self) -> None:
        self._drawn(names=("Dell P2419H", ""))

        screens, held = self.control.call_args.args
        self.assertEqual([(one.number, one.name) for one in screens],
                         [(1, "Dell P2419H"), (2, "")])
        self.assertEqual(held, {"backglass": None, "score_view": None, "playfield": 1})

    def test_the_arrows_are_for_a_cabinet_and_not_for_a_desk(self) -> None:
        on_a_cab = self._drawn({"presentation": {"cab_mode": "true"}})
        on_a_desk = self._drawn({"presentation": {"cab_mode": "false"}})

        self.assertTrue(on_a_cab["arrows"])
        self.assertIsNotNone(on_a_cab["point"])
        self.assertFalse(on_a_desk["arrows"])
        self.assertIsNone(on_a_desk["point"])

    def test_the_arrow_is_the_stored_rotation(self) -> None:
        drawn = self._drawn(_values(playfield={"rotation": "270"}))

        self.assertEqual(drawn["arrow"], picture.RIGHT)

    async def test_a_part_moved_is_written_as_its_screen_id(self) -> None:
        drawn = self._drawn()

        self.assertTrue(await drawn["move"]({"backglass": 2}))

        self.write.assert_awaited_once_with({"windows.backglass": {"screen_id": 1}})
        self.rerender.assert_not_called()

    async def test_a_write_that_fails_says_so_and_holds_nothing(self) -> None:
        self.write.return_value = False
        drawn = self._drawn(_values(backglass={"screen_id": 4}))

        self.assertFalse(await drawn["move"]({"backglass": 1}))
        self.write.return_value = True
        await drawn["move"]({"score_view": 2})

        self.rerender.assert_called_once_with()

    async def test_a_part_stored_on_a_screen_that_is_gone_redraws_the_page_once_moved(
            self) -> None:
        drawn = self._drawn(_values(backglass={"screen_id": 4}))

        await drawn["move"]({"backglass": 1})

        self.rerender.assert_called_once_with()

    async def test_a_write_that_fails_does_not_redraw_the_page(self) -> None:
        self.write.return_value = False
        drawn = self._drawn(_values(backglass={"screen_id": 4}))

        await drawn["move"]({"backglass": 1})

        self.rerender.assert_not_called()

    async def test_an_arrow_is_written_as_the_playfield_s_mounting_and_turn(self) -> None:
        drawn = self._drawn({"presentation": {"cab_mode": "true"}})

        self.assertTrue(await drawn["point"](picture.LEFT, FIRST))

        self.write.assert_awaited_once_with(
            {"windows.playfield": {"orientation": "portrait", "rotation": "90"}})

    async def test_the_turn_just_chosen_is_the_one_a_later_move_keeps(self) -> None:
        drawn = self._drawn({"presentation": {"cab_mode": "true"}})
        await drawn["point"](picture.LEFT, FIRST)
        self.write.reset_mock()

        await drawn["move"]({"playfield": 1})

        self.write.assert_awaited_once_with(
            {"windows.playfield": {"screen_id": 0, "orientation": "portrait"}})

    async def test_an_arrow_that_was_not_saved_is_not_the_turn_kept(self) -> None:
        drawn = self._drawn({"presentation": {"cab_mode": "true"}})
        self.write.return_value = False
        await drawn["point"](picture.LEFT, FIRST)
        self.write.reset_mock()
        self.write.return_value = True

        await drawn["move"]({"playfield": 1})

        self.write.assert_awaited_once_with(
            {"windows.playfield": {"screen_id": 0, "orientation": "landscape"}})

    async def test_show_numbers_is_given_the_screens_and_the_playfield_on_a_cabinet(
            self) -> None:
        local = self.enterContext(patch.object(displays.device_client, "local"))
        self.enterContext(patch.object(displays.run, "io_bound", new=AsyncMock()))
        drawn = self._drawn({"presentation": {"cab_mode": "true"}})

        await press(drawn["show"], {"playfield": 2})

        displays.run.io_bound.assert_awaited_once()
        args = displays.run.io_bound.await_args.args
        self.assertIs(args[0], local.return_value.show_numbers)
        self.assertEqual([one.number for one in args[1]], [1, 2])
        self.assertEqual(args[2], 2)

    async def test_show_numbers_on_a_desk_marks_no_playfield(self) -> None:
        self.enterContext(patch.object(displays.device_client, "local"))
        self.enterContext(patch.object(displays.run, "io_bound", new=AsyncMock()))
        drawn = self._drawn()

        await press(drawn["show"], {"playfield": 2})

        self.assertIsNone(displays.run.io_bound.await_args.args[2])

    async def test_show_numbers_that_cannot_open_a_window_says_why(self) -> None:
        self.enterContext(patch.object(displays.device_client, "local"))
        self.enterContext(patch.object(displays.run, "io_bound",
                                       new=AsyncMock(side_effect=RuntimeError("No browser"))))
        notify = self.enterContext(patch.object(displays.ui, "notify"))
        drawn = self._drawn()

        await press(drawn["show"], {})

        notify.assert_called_once()
        self.assertEqual(notify.call_args.args, (t("console.screens.show_failed"),))
        self.assertIn("No browser", notify.call_args.kwargs["caption"])


class FollowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.write = AsyncMock(return_value=True)
        self.follow = AsyncMock()
        self.control = self.enterContext(patch.object(displays.picture, "Picture"))

    def _drawn(self, values: dict | None = None) -> dict[str, Any]:
        entries = displays.rows(values or {"presentation": {"cab_mode": "true"}}, SCHEMA,
                                [BIG, TALL], ["", ""], self.write, Mock(), self.follow)
        [(_, draw)] = [entry for entry in entries if entry[0] is panel.FULL]
        draw()
        return self.control.call_args.kwargs

    async def test_a_part_moved_tells_what_it_was_and_what_it_is(self) -> None:
        drawn = self._drawn()

        await drawn["move"]({"backglass": 2})

        [(before, after, here)] = [call.args for call in self.follow.await_args_list]
        self.assertEqual(before.on["backglass"], None)
        self.assertEqual(after.on["backglass"], 2)
        self.assertEqual([one.number for one in here], [1, 2])

    async def test_the_playfield_moved_to_another_shape_of_screen_tells_its_new_mounting(
            self) -> None:
        drawn = self._drawn()

        await drawn["move"]({"playfield": 2})

        [(before, after, _)] = [call.args for call in self.follow.await_args_list]
        self.assertEqual(before.turn, ("landscape", "0"))
        self.assertEqual(after.turn, ("portrait", "0"))

    async def test_an_arrow_tells_the_turn_it_made(self) -> None:
        drawn = self._drawn()

        await drawn["point"](picture.LEFT, FIRST)

        [(before, after, _)] = [call.args for call in self.follow.await_args_list]
        self.assertEqual((before.turn, after.turn), (("landscape", "0"), ("portrait", "90")))
        self.assertEqual(before.on, after.on)

    async def test_a_change_that_was_not_kept_tells_nothing(self) -> None:
        self.write.return_value = False
        drawn = self._drawn()

        await drawn["move"]({"backglass": 2})
        await drawn["point"](picture.LEFT, FIRST)

        self.follow.assert_not_awaited()

    async def test_each_change_is_told_from_where_the_last_one_left_it(self) -> None:
        drawn = self._drawn()

        await drawn["move"]({"backglass": 2})
        await drawn["move"]({"backglass": 1})

        [(_, first, _), (before, after, _)] = [call.args for call in self.follow.await_args_list]
        self.assertEqual(before.on, first.on)
        self.assertEqual(after.on["backglass"], 1)

    async def test_nothing_is_asked_to_follow_where_nothing_is_listening(self) -> None:
        entries = displays.rows({}, SCHEMA, [BIG], [""], self.write, Mock())
        [(_, draw)] = [entry for entry in entries if entry[0] is panel.FULL]
        draw()

        self.assertTrue(await self.control.call_args.kwargs["move"]({"backglass": 1}))


if __name__ == "__main__":
    unittest.main()
