"""The screens picture: where a screen goes, which way the playfield faces, and what it draws."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

from nicegui import ui

from common.i18n import t
from manager.settings import screens_picture as picture
from manager.settings.screens import Screen
from tests.support.clicks import press

BIG = Screen(1, "Dell P2419H", 2560, 1440, 0, 0)
TALL = Screen(2, "", 1080, 1920, 2560, 0)
STRIP = Screen(3, "", 1280, 390, 0, 1440)
BARE = Screen(4, "", 1920, 1080, 3640, 0)


class PlacedTests(unittest.TestCase):
    def test_a_screen_put_on_a_part_is_on_it(self) -> None:
        after = picture.placed({"backglass": None, "playfield": 1}, "backglass", 2)

        self.assertEqual(after, {"backglass": 2, "playfield": 1})

    def test_a_screen_put_where_another_is_sends_that_one_to_where_it_came_from(self) -> None:
        after = picture.placed({"backglass": 1, "playfield": 2}, "backglass", 2)

        self.assertEqual(after, {"backglass": 2, "playfield": 1})

    def test_a_swap_with_an_empty_part_leaves_that_part_empty(self) -> None:
        after = picture.placed({"backglass": None, "playfield": 2}, "backglass", 2)

        self.assertEqual(after, {"backglass": 2, "playfield": None})

    def test_no_screen_leaves_the_part_empty_and_touches_no_other(self) -> None:
        after = picture.placed({"backglass": 1, "playfield": 2}, "backglass", None)

        self.assertEqual(after, {"backglass": None, "playfield": 2})

    def test_what_it_is_given_is_not_changed(self) -> None:
        on = {"backglass": 1, "playfield": 2}

        picture.placed(on, "backglass", 2)

        self.assertEqual(on, {"backglass": 1, "playfield": 2})

    def test_only_the_parts_that_differ_are_changes(self) -> None:
        before = {"backglass": 1, "playfield": 2, "scoreview": None}

        self.assertEqual(picture.changes(before, picture.placed(before, "backglass", 2)),
                         {"backglass": 2, "playfield": 1})
        self.assertEqual(picture.changes(before, dict(before)), {})


class InsideTests(unittest.TestCase):
    def test_visual_pinball_has_a_topper_above_the_backglass_and_the_playfield_last(self) -> None:
        self.assertEqual([part.key for part in picture.vpx_parts()],
                         ["topper", "backglass", "scoreview", "playfield"])

    def test_every_part_but_the_playfield_can_be_drawn_inside_it(self) -> None:
        self.assertEqual({part.key: part.inside for part in picture.vpx_parts()},
                         {"topper": True, "backglass": True, "scoreview": True,
                          "playfield": False})

    def test_vpinfe_has_a_topper_above_the_backglass_and_the_playfield_last(self) -> None:
        self.assertEqual([part.key for part in picture.vpinfe_parts()],
                         ["topper", "backglass", "scoreview", "playfield"])

    def test_vpinfe_s_parts_are_never_offered_inside(self) -> None:
        self.assertFalse([part for part in picture.vpinfe_parts() if part.inside])

    def test_inside_is_no_screen_and_displaces_nothing(self) -> None:
        self.assertEqual(picture.placed({"backglass": 2, "playfield": 1}, "scoreview",
                                        picture.INSIDE),
                         {"backglass": 2, "playfield": 1, "scoreview": picture.INSIDE})

    def test_a_screen_put_where_a_part_is_inside_sends_nothing_back(self) -> None:
        self.assertEqual(picture.placed({"backglass": picture.INSIDE, "playfield": 1},
                                        "backglass", 1),
                         {"backglass": 1, "playfield": picture.INSIDE})

    def test_the_playfield_cannot_be_drawn_inside_itself(self) -> None:
        self.assertFalse(next(part for part in picture.vpx_parts()
                              if part.key == picture.PLAYFIELD).inside)


class ArrowTests(unittest.TestCase):
    """The setups in docs/theme.md: a rotated portrait monitor, one the OS leaves alone, and a
    landscape one."""

    def test_a_tall_window_with_its_top_up_is_portrait_and_not_turned(self) -> None:
        self.assertEqual(picture.turn(picture.UP, TALL),
                         {"orientation": "portrait", "rotation": "0"})

    def test_a_wide_window_with_its_top_sideways_is_portrait_and_turned(self) -> None:
        self.assertEqual(picture.turn(picture.LEFT, BIG),
                         {"orientation": "portrait", "rotation": "90"})
        self.assertEqual(picture.turn(picture.RIGHT, BIG),
                         {"orientation": "portrait", "rotation": "270"})

    def test_a_wide_window_with_its_top_up_is_landscape_and_not_turned(self) -> None:
        self.assertEqual(picture.turn(picture.UP, BIG),
                         {"orientation": "landscape", "rotation": "0"})

    def test_a_tall_window_with_its_top_sideways_is_landscape(self) -> None:
        self.assertEqual(picture.turn(picture.LEFT, TALL),
                         {"orientation": "landscape", "rotation": "90"})

    def test_a_top_toward_the_player_is_a_half_turn(self) -> None:
        self.assertEqual(picture.turn(picture.DOWN, BIG),
                         {"orientation": "landscape", "rotation": "180"})
        self.assertEqual(picture.turn(picture.DOWN, TALL),
                         {"orientation": "portrait", "rotation": "180"})

    def test_a_screen_not_connected_is_taken_as_wide(self) -> None:
        self.assertEqual(picture.turn(picture.UP, None)["orientation"], "landscape")

    def test_each_arrow_is_what_its_rotation_says(self) -> None:
        for arrow in picture.ARROWS:
            with self.subTest(arrow=arrow):
                turned = picture.turn(arrow, BIG)["rotation"]
                self.assertEqual(picture.arrow_at(turned), arrow)

    def test_a_rotation_that_is_no_arrow_draws_none(self) -> None:
        for rotation in ("", None, "45", "auto"):
            with self.subTest(rotation=rotation):
                self.assertIsNone(picture.arrow_at(rotation))

    def test_a_rotation_stored_as_a_number_is_read(self) -> None:
        self.assertEqual(picture.arrow_at(90), picture.LEFT)


class GuessTests(unittest.TestCase):
    def test_no_screens_place_nothing(self) -> None:
        self.assertEqual(picture.guess([]), {})

    def test_a_lone_screen_is_the_playfield(self) -> None:
        self.assertEqual(picture.guess([STRIP]), {"playfield": 3})

    def test_a_strip_is_the_scoreview_and_the_biggest_of_the_rest_the_playfield(
            self) -> None:
        self.assertEqual(picture.guess([STRIP, BARE, BIG]),
                         {"scoreview": 3, "playfield": 1, "backglass": 4})

    def test_the_fourth_screen_is_the_topper(self) -> None:
        self.assertEqual(picture.guess([STRIP, BARE, BIG, TALL]),
                         {"scoreview": 3, "playfield": 1, "backglass": 4, "topper": 2})

    def test_three_screens_leave_the_topper_unplaced(self) -> None:
        self.assertNotIn("topper", picture.guess([STRIP, BARE, BIG]))

    def test_two_screens_of_one_size_are_not_told_apart(self) -> None:
        twin = Screen(5, "", 1920, 1080, 0, 0)

        self.assertEqual(picture.guess([BARE, twin]), {})

    def test_a_size_shared_leaves_the_others_to_be_placed(self) -> None:
        twin = Screen(5, "", 1920, 1080, 0, 0)

        self.assertEqual(picture.guess([BARE, twin, STRIP, BIG]),
                         {"scoreview": 3, "playfield": 1})

    def test_two_strips_are_not_told_apart(self) -> None:
        other = Screen(5, "", 1920, 600, 0, 0)

        self.assertEqual(picture.guess([STRIP, other, BIG]), {"playfield": 1})

    def test_an_ordinary_widescreen_is_not_a_strip(self) -> None:
        self.assertNotIn("scoreview", picture.guess([BIG, BARE]))

    def test_each_screen_is_given_to_one_part(self) -> None:
        found = picture.guess([STRIP, BARE, BIG, TALL])

        self.assertEqual(len(set(found.values())), len(found))


async def _no_move(_moved: dict[str, int | None]) -> bool:
    return True


def _drawn(on: dict[str, picture.Placement], screens: tuple[Screen, ...] = (BIG, TALL, STRIP),
           *, into: ui.element | None = None,
           **kwargs: Any) -> tuple[picture.Picture, ui.element]:
    with into or ui.column() as body:
        control = picture.Picture(screens, on, move=kwargs.pop("move", _no_move), **kwargs)
    return control, body


def _labels(body: ui.element) -> list[str]:
    return [one.text for one in body.descendants() if isinstance(one, ui.label)]


def _classes(body: ui.element) -> list[str]:
    return [name for one in body.descendants() for name in one.classes]


class DrawnTests(unittest.TestCase):
    def test_every_part_is_drawn_with_its_name(self) -> None:
        _, body = _drawn({})

        labels = _labels(body)
        for word in ("manager.screens.backglass", "manager.screens.scoreview",
                     "manager.screens.playfield"):
            self.assertIn(t(word), labels)

    def test_an_empty_part_reads_no_screen(self) -> None:
        _, body = _drawn({"backglass": None})

        self.assertIn(t("manager.screens.no_screen"), _labels(body))

    def test_a_filled_part_is_its_number_and_the_screen_s_name(self) -> None:
        _, body = _drawn({"playfield": 1})

        self.assertIn("1", _labels(body))
        self.assertIn("Dell P2419H", _labels(body))

    def test_a_screen_with_no_name_is_said_by_its_size(self) -> None:
        _, body = _drawn({"playfield": 2})

        self.assertIn(t("manager.screens.size", width=1080, height=1920), _labels(body))

    def test_a_part_whose_screen_is_not_connected_says_so_and_is_marked(self) -> None:
        _, body = _drawn({"backglass": 9})

        self.assertIn(t("manager.screens.not_connected"), _labels(body))
        self.assertIn("manager-part-slot--missing", _classes(body))

    def test_every_connected_screen_is_a_card_and_says_what_it_is_used_for(self) -> None:
        _, body = _drawn({"playfield": 1, "backglass": 2})

        labels = _labels(body)
        self.assertEqual(_classes(body).count("manager-screen-card"), 3)
        self.assertIn(t("manager.screens.playfield"), labels)
        self.assertIn(t("manager.screens.not_used"), labels)

    def test_a_screen_that_is_not_on_a_part_is_a_card_all_the_same(self) -> None:
        _, body = _drawn({})

        self.assertEqual(_classes(body).count("manager-screen-card"), 3)

    def test_no_screens_says_so_where_the_cards_would_be(self) -> None:
        _, body = _drawn({}, screens=())

        self.assertIn(t("manager.screens.none_found"), _labels(body))
        self.assertNotIn("manager-screen-card", _classes(body))

    def test_the_playfield_has_an_arrow_for_each_way_it_can_face(self) -> None:
        async def point(_arrow: str, _screen: Screen) -> bool:
            return True

        _, body = _drawn({"playfield": 1}, point=point, arrow=picture.LEFT)

        classes = _classes(body)
        for arrow in picture.ARROWS:
            self.assertIn(f"manager-pf-dir--{arrow}", classes)
        self.assertEqual(classes.count("manager-pf-dir--chosen"), 1)

    def test_the_arrow_is_the_one_the_playfield_faces(self) -> None:
        async def point(_arrow: str, _screen: Screen) -> bool:
            return True

        _, body = _drawn({"playfield": 1}, point=point, arrow=picture.DOWN)

        chosen = [one for one in body.descendants() if "manager-pf-dir--chosen" in one.classes]
        self.assertEqual([one for one in chosen[0].classes if one.startswith("manager-pf-dir--")
                          and one != "manager-pf-dir--chosen"], ["manager-pf-dir--down"])

    def test_a_desktop_page_draws_the_picture_without_the_arrows(self) -> None:
        async def point(_arrow: str, _screen: Screen) -> bool:
            return True

        _, body = _drawn({"playfield": 1}, point=point, arrows=False)

        self.assertFalse([name for name in _classes(body) if name.startswith("manager-pf-dir")])
        self.assertIn(t("manager.screens.hint_desktop"), _labels(body))

    def test_a_playfield_with_no_screen_has_no_arrows(self) -> None:
        async def point(_arrow: str, _screen: Screen) -> bool:
            return True

        _, body = _drawn({"playfield": None}, point=point)

        self.assertFalse([name for name in _classes(body) if name.startswith("manager-pf-dir")])

    def test_the_arrows_are_offered_only_where_something_hears_them(self) -> None:
        _, body = _drawn({"playfield": 1})

        self.assertFalse([name for name in _classes(body) if name.startswith("manager-pf-dir")])

    def test_show_numbers_is_offered_only_where_something_runs_it(self) -> None:
        _, without = _drawn({})
        _, with_it = _drawn({}, show=AsyncMock())

        self.assertNotIn(t("manager.screens.show_numbers"),
                         [one.text for one in without.descendants()
                          if isinstance(one, ui.button)])
        self.assertIn(t("manager.screens.show_numbers"),
                      [one.props.get("label") for one in with_it.descendants()
                       if isinstance(one, ui.button)])

    def test_the_part_a_hint_belongs_to_carries_it(self) -> None:
        [score] = [part for part in picture.vpinfe_parts() if part.key == picture.SCOREVIEW]

        self.assertEqual(score.hint, t("manager.screens.scoreview.help"))
        self.assertEqual(score.label, t("manager.screens.scoreview"))


class VpxDrawnTests(unittest.TestCase):
    def _vpx(self, on: dict, **kwargs: Any) -> tuple[picture.Picture, ui.element]:
        return _drawn(on, parts=picture.vpx_parts(), **kwargs)

    def test_a_topper_is_drawn_above_the_backglass(self) -> None:
        _, body = self._vpx({"topper": 2})

        labels = _labels(body)
        self.assertLess(labels.index(t("manager.screens.topper")),
                        labels.index(t("manager.screens.backglass")))
        self.assertIn("manager-part--topper", _classes(body))

    def test_a_part_inside_the_playfield_says_so_and_is_not_a_screen(self) -> None:
        _, body = self._vpx({"backglass": picture.INSIDE, "playfield": 1})

        self.assertIn(t("manager.screens.inside"), _labels(body))
        self.assertIn("manager-part-slot--inside", _classes(body))
        self.assertNotIn("manager-part-slot--missing", _classes(body))

    def test_a_part_inside_the_playfield_cannot_be_dragged_out(self) -> None:
        _, body = self._vpx({"backglass": picture.INSIDE})

        [slot] = [one for one in body.descendants() if "manager-part-slot--inside" in one.classes]
        self.assertNotIn("draggable", slot.props)

    def test_a_part_inside_can_be_put_back_on_no_screen(self) -> None:
        _, body = self._vpx({"backglass": picture.INSIDE})

        [slot] = [one for one in body.descendants() if "manager-part-slot--inside" in one.classes]
        self.assertIn("manager-part-slot-clear",
                      [name for one in slot.descendants() for name in one.classes])

    def test_the_menu_offers_inside_to_the_parts_that_can_be(self) -> None:
        _, body = self._vpx({})
        _, plain = _drawn({})

        said = [one.text for one in body.descendants() if isinstance(one, ui.label)
                and one.text == t("manager.screens.inside")]
        self.assertEqual(len(said), 3)
        self.assertNotIn(t("manager.screens.inside"), _labels(plain))

    def test_nothing_that_differs_draws_no_line_about_it(self) -> None:
        _, body = self._vpx({"playfield": 1})

        self.assertNotIn(t("manager.screens.different"), _labels(body))

    def test_a_part_that_differs_is_named_and_can_be_matched(self) -> None:
        _, body = self._vpx({"playfield": 1, "backglass": 2}, differs=["backglass"],
                            match=AsyncMock())

        self.assertIn(t("manager.screens.different"), _labels(body))
        self.assertIn(t("manager.screens.backglass"), _labels(body))
        self.assertIn("manager-part-name--differs", _classes(body))
        self.assertIn(t("manager.screens.match_vpinfe"),
                      [one.props.get("label") for one in body.descendants()
                       if isinstance(one, ui.button)])

    def test_the_arrow_differing_is_named_as_the_playfield_arrow(self) -> None:
        _, body = self._vpx({"playfield": 1}, arrow_differs=True, match=AsyncMock())

        self.assertIn(t("manager.screens.playfield_arrow"), _labels(body))
        self.assertNotIn("manager-part-name--differs", _classes(body))

    def test_with_nothing_to_match_with_the_line_still_says_it_differs(self) -> None:
        _, body = self._vpx({"playfield": 1, "backglass": 2}, differs=["backglass"])

        self.assertIn(t("manager.screens.different"), _labels(body))
        self.assertNotIn(t("manager.screens.match_vpinfe"),
                         [one.props.get("label") for one in body.descendants()
                          if isinstance(one, ui.button)])


class ActedOnTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        # Outside the test's task, which has no page to draw into.
        self.body = ui.column()

    def _drawn(self, on: dict[str, picture.Placement],
               **kwargs: Any) -> tuple[picture.Picture, Any]:
        return _drawn(on, into=self.body, **kwargs)

    async def test_a_screen_put_on_a_part_is_reported_and_then_drawn_there(self) -> None:
        move = AsyncMock(return_value=True)
        control, _ = self._drawn({"backglass": None, "playfield": 1}, move=move)

        await press(control._put, "backglass", 2)

        move.assert_awaited_once_with({"backglass": 2})
        self.assertEqual(control.on, {"backglass": 2, "playfield": 1})

    async def test_a_swap_is_reported_as_both_parts(self) -> None:
        move = AsyncMock(return_value=True)
        control, _ = self._drawn({"backglass": 1, "playfield": 2}, move=move)

        await press(control._put, "backglass", 2)

        move.assert_awaited_once_with({"backglass": 2, "playfield": 1})

    async def test_a_move_that_was_not_kept_leaves_the_picture_as_it_was(self) -> None:
        control, _ = self._drawn({"backglass": None}, move=AsyncMock(return_value=False))

        await press(control._put, "backglass", 2)

        self.assertEqual(control.on, {"backglass": None})

    async def test_putting_a_screen_where_it_already_is_reports_nothing(self) -> None:
        move = AsyncMock(return_value=True)
        control, _ = self._drawn({"backglass": 2}, move=move)

        await press(control._put, "backglass", 2)

        move.assert_not_awaited()

    async def test_a_part_cleared_is_reported_as_no_screen(self) -> None:
        move = AsyncMock(return_value=True)
        control, _ = self._drawn({"backglass": 2}, move=move)

        await press(control._put, "backglass", None)

        move.assert_awaited_once_with({"backglass": None})
        self.assertEqual(control.on, {"backglass": None})

    async def test_a_drop_of_a_connected_screen_puts_it_there(self) -> None:
        move = AsyncMock(return_value=True)
        control, _ = self._drawn({"backglass": None}, move=move)

        await press(control._dropped, "backglass", SimpleNamespace(args=2))

        move.assert_awaited_once_with({"backglass": 2})

    async def test_a_drop_of_anything_else_changes_nothing(self) -> None:
        move = AsyncMock(return_value=True)
        control, _ = self._drawn({"backglass": None}, move=move)

        for args in (9, None, "2", {"file": 1}, 0.5):
            with self.subTest(args=args):
                await press(control._dropped, "backglass", SimpleNamespace(args=args))

        move.assert_not_awaited()

    async def test_an_arrow_is_reported_with_the_playfield_s_screen(self) -> None:
        point = AsyncMock(return_value=True)
        control, _ = self._drawn({"playfield": 2}, point=point, arrow=picture.UP)

        await press(control._aim, picture.LEFT)

        point.assert_awaited_once_with(picture.LEFT, TALL)
        self.assertEqual(control.arrow, picture.LEFT)

    async def test_an_arrow_that_was_not_kept_stays_where_it_was(self) -> None:
        control, _ = self._drawn({"playfield": 2}, point=AsyncMock(return_value=False),
                            arrow=picture.UP)

        await press(control._aim, picture.LEFT)

        self.assertEqual(control.arrow, picture.UP)

    async def test_show_numbers_is_given_what_is_where_and_can_be_pressed_again(self) -> None:
        show = AsyncMock()
        control, _ = self._drawn({"playfield": 1}, show=show)

        await press(control._show)

        show.assert_awaited_once_with({"playfield": 1})
        self.assertFalse(control.showing)

    async def test_show_numbers_that_fails_still_lets_it_be_pressed_again(self) -> None:
        control, _ = self._drawn({}, show=AsyncMock(side_effect=RuntimeError("no")))

        with self.assertRaises(RuntimeError):
            await press(control._show)

        self.assertFalse(control.showing)

    async def test_matching_asks_the_page_to_put_the_parts_right(self) -> None:
        match = AsyncMock()
        control, _ = self._drawn({"playfield": 1, "backglass": 2}, parts=picture.vpx_parts(),
                                 differs=["backglass"], match=match)

        await press(control._match)

        match.assert_awaited_once_with()

    async def test_a_part_put_inside_is_reported_as_inside_and_drawn_so(self) -> None:
        move = AsyncMock(return_value=True)
        control, _ = self._drawn({"backglass": 2, "playfield": 1}, parts=picture.vpx_parts(),
                                 move=move)

        await press(control._put, "backglass", picture.INSIDE)

        move.assert_awaited_once_with({"backglass": picture.INSIDE})
        self.assertEqual(control.on["backglass"], picture.INSIDE)

    async def test_a_swap_does_not_leave_the_playfield_inside_itself(self) -> None:
        move = AsyncMock(return_value=True)
        control, _ = self._drawn({"backglass": picture.INSIDE, "playfield": 1},
                                 parts=picture.vpx_parts(), move=move)

        await press(control._put, "backglass", 1)

        move.assert_awaited_once_with({"backglass": 1, "playfield": None})

    async def test_a_swap_leaves_a_part_that_can_be_inside_where_it_is(self) -> None:
        move = AsyncMock(return_value=True)
        control, _ = self._drawn({"scoreview": picture.INSIDE, "backglass": 1},
                                 parts=picture.vpx_parts(), move=move)

        await press(control._put, "scoreview", 1)

        move.assert_awaited_once_with({"scoreview": 1, "backglass": picture.INSIDE})


if __name__ == "__main__":
    unittest.main()
