"""What the backglass preview draws, read from the settings in effect."""

from __future__ import annotations

import unittest

from common.games import backglass_ops, dmd_frame
from console import backglass_view as view

LEGACY, B2S = backglass_ops.LEGACY, backglass_ops.B2S
FLOATING = {"Backglass.BackglassOutput": "1"}


def _glass(*, size=(1000, 800), grill=200, score_view=None) -> dict:
    return {"size": size, "grill": grill, "score_view_art": score_view}


def _backglass(held: dict, **glass):
    return view.screens(held, _glass(**glass))[0]


class TheGrillCut(unittest.TestCase):
    def test_legacy_cuts_it_when_hide_grill_is_on(self) -> None:
        screen = _backglass({f"{LEGACY}B2SHideGrill": "1"})

        self.assertAlmostEqual(100 * 800 / 600, screen.scale)
        self.assertAlmostEqual(1000 / 600, screen.ratio)

    def test_legacy_keeps_it_when_hide_grill_is_off(self) -> None:
        screen = _backglass({f"{LEGACY}B2SHideGrill": "0"})

        self.assertEqual((100.0, 1000 / 800), (screen.scale, screen.ratio))

    def test_b2s_keeps_it_only_when_show_grill_is_on(self) -> None:
        off = {f"{LEGACY}Enable": "0"}
        on = {f"{LEGACY}Enable": "0", f"{B2S}ShowGrill": "1"}

        self.assertAlmostEqual(800 / 600 * 100, _backglass(off).scale)
        self.assertEqual(100.0, _backglass(on).scale)

    def test_a_file_with_no_grill_is_not_cut(self) -> None:
        self.assertEqual(100.0, _backglass({f"{LEGACY}B2SHideGrill": "1"}, grill=0).scale)


class TheWindow(unittest.TestCase):
    def test_a_floating_window_has_its_own_shape(self) -> None:
        held = {**FLOATING, "Backglass.BackglassWidth": "1920",
                "Backglass.BackglassHeight": "540"}

        self.assertAlmostEqual(1920 / 540, _backglass(held).ratio)

    def test_full_screen_takes_the_full_screen_size(self) -> None:
        held = {**FLOATING, "Backglass.BackglassFullScreen": "1",
                "Backglass.BackglassFSWidth": "1280", "Backglass.BackglassFSHeight": "1024",
                "Backglass.BackglassWidth": "1920", "Backglass.BackglassHeight": "540"}

        self.assertAlmostEqual(1280 / 1024, _backglass(held).ratio)

    def test_an_embedded_window_takes_the_arts_shape(self) -> None:
        held = {"Backglass.BackglassOutput": "2", "Backglass.BackglassWidth": "1920",
                "Backglass.BackglassHeight": "540"}

        self.assertAlmostEqual(1000 / 800, _backglass(held).ratio)

    def test_a_turned_window_without_a_size_swaps_the_arts_sides(self) -> None:
        screen = _backglass({"Backglass.BackglassRotation": "1"})

        self.assertEqual((1, 800 / 1000), (screen.turns, screen.ratio))

    def test_turns_wrap_at_four(self) -> None:
        self.assertEqual(1, _backglass({"Backglass.BackglassRotation": "5"}).turns)

    def test_an_output_of_zero_or_nothing_is_off(self) -> None:
        self.assertEqual((True, True, False),
                         (_backglass({}).off, _backglass({"Backglass.BackglassOutput": "0"}).off,
                          _backglass(FLOATING).off))


class TheDmd(unittest.TestCase):
    def _box(self, **keys: str) -> view.Box | None:
        held = {f"{LEGACY}BackglassDMD{name}": value for name, value in keys.items()}
        return _backglass({f"{LEGACY}B2SHideGrill": "1", **held}).dmd

    def test_it_is_not_drawn_with_the_overlay_off(self) -> None:
        self.assertIsNone(self._box(Overlay="0", X="1", Y="1", W="9", H="9"))

    def test_automatic_has_no_box(self) -> None:
        self.assertEqual(view.Box(auto=True), self._box(Overlay="1", AutoPos="1"))

    def test_a_legacy_box_is_in_percent_of_1024_by_768_counted_up_from_the_bottom(self) -> None:
        box = self._box(Overlay="1", X="256", Y="192", W="512", H="192")

        self.assertEqual((25.0, 50.0, 50.0, 25.0),
                         (box.left, box.top, box.width, box.height))

    def test_a_b2s_box_is_in_percent_of_the_art_with_the_grill_cut_counted_up_from_the_bottom(
            self) -> None:
        held = {f"{LEGACY}Enable": "0", f"{B2S}ShowGrill": "0", f"{B2S}BackglassDMDOverlay": "1",
                f"{B2S}BackglassDMDX": "100", f"{B2S}BackglassDMDY": "50",
                f"{B2S}BackglassDMDW": "500", f"{B2S}BackglassDMDH": "150"}

        box = _backglass(held).dmd

        self.assertEqual((10.0, 66.666667, 50.0, 25.0),
                         tuple(round(v, 6) for v in (box.left, box.top, box.width, box.height)))

    def test_a_box_with_no_size_is_not_drawn(self) -> None:
        self.assertIsNone(self._box(Overlay="1", X="1", Y="1", W="0", H="0"))

    def test_the_renderer_in_effect_names_the_keys(self) -> None:
        held = {f"{LEGACY}Enable": "0", f"{B2S}BackglassDMDOverlay": "1",
                f"{B2S}BackglassDMDAutoPos": "1", f"{LEGACY}BackglassDMDOverlay": "0"}

        self.assertEqual(view.Box(auto=True), _backglass(held).dmd)


class TheScoreView(unittest.TestCase):
    ON = {"ScoreView.ScoreViewOutput": "1", "ScoreView.ScoreViewWidth": "1000",
          "ScoreView.ScoreViewHeight": "250"}

    def _second(self, held: dict, art=(400, 100)):
        return view.screens(held, _glass(score_view=art))[1]

    def test_it_is_drawn_when_the_file_has_art_and_the_window_is_on(self) -> None:
        self.assertAlmostEqual(4.0, self._second(self.ON).ratio)

    def test_it_is_not_drawn_when_its_window_is_off(self) -> None:
        self.assertIsNone(self._second({}))

    def test_it_is_not_drawn_when_the_file_has_no_art(self) -> None:
        self.assertIsNone(self._second(self.ON, art=None))

    def test_a_b2s_dmd_is_in_the_pixels_of_its_own_art_counted_up_from_the_bottom(self) -> None:
        held = {**self.ON, f"{LEGACY}Enable": "0", f"{B2S}ScoreViewDMDOverlay": "1",
                f"{B2S}ScoreViewDMDX": "40", f"{B2S}ScoreViewDMDY": "10",
                f"{B2S}ScoreViewDMDW": "200", f"{B2S}ScoreViewDMDH": "50"}

        box = self._second(held).dmd

        self.assertEqual((10.0, 40.0, 50.0, 50.0),
                         (box.left, box.top, box.width, box.height))


class TheBoxWritten(unittest.TestCase):
    def test_a_legacy_box_is_written_in_1024_by_768_with_automatic_off(self) -> None:
        screen = _backglass({f"{LEGACY}B2SHideGrill": "1"})

        values = view.box_values(LEGACY, screen, view.Box(25.0, 50.0, 50.0, 25.0))

        self.assertEqual({f"{LEGACY}BackglassDMDAutoPos": "0", f"{LEGACY}BackglassDMDX": "256",
                          f"{LEGACY}BackglassDMDY": "192", f"{LEGACY}BackglassDMDW": "512",
                          f"{LEGACY}BackglassDMDH": "192"}, values)

    def test_a_b2s_box_is_written_in_the_pixels_of_the_cut_art(self) -> None:
        held = {f"{LEGACY}Enable": "0"}
        screen = _backglass(held)

        values = view.box_values(B2S, screen, view.Box(10.0, 200 / 3, 50.0, 25.0))

        self.assertEqual(("100", "50", "500", "150"),
                         tuple(values[f"{B2S}BackglassDMD{name}"] for name in "XYWH"))

    def test_the_score_view_has_its_own_keys_and_art(self) -> None:
        held = {**TheScoreView.ON, f"{LEGACY}Enable": "0"}
        screen = view.screens(held, _glass(score_view=(400, 100)))[1]

        values = view.box_values(B2S, screen, view.Box(10.0, 40.0, 50.0, 50.0))

        self.assertEqual(("40", "10", "200", "50"),
                         tuple(values[f"{B2S}ScoreViewDMD{name}"] for name in "XYWH"))

    def test_what_is_written_draws_the_same_box_again(self) -> None:
        for plugin in (LEGACY, B2S):
            with self.subTest(plugin=plugin):
                base = {f"{LEGACY}Enable": "1" if plugin == LEGACY else "0",
                        f"{LEGACY}B2SHideGrill": "1", f"{plugin}BackglassDMDOverlay": "1"}
                box = view.Box(12.5, 30.0, 40.0, 20.0)

                values = view.box_values(plugin, _backglass(base), box)
                again = _backglass({**base, **values}).dmd

                for want, got in zip((box.left, box.top, box.width, box.height),
                                     (again.left, again.top, again.width, again.height),
                                     strict=True):
                    self.assertAlmostEqual(want, got, delta=0.2)

    def test_a_box_cannot_be_written_outside_the_window_or_empty(self) -> None:
        screen = _backglass({})

        values = view.box_values(LEGACY, screen, view.Box(0.0, 100.0, 0.0, 0.0))

        self.assertEqual(("0", "0", "1", "1"),
                         tuple(values[f"{LEGACY}BackglassDMD{name}"] for name in "XYWH"))


class TheFrameFound(unittest.TestCase):
    def test_a_frame_counted_up_from_the_bottom_is_a_box_counted_down_from_the_top(self) -> None:
        box = view.frame_box(dmd_frame.Frame(100, 50, 500, 150), (1000, 600))

        self.assertEqual((10.0, 66.666667, 50.0, 25.0),
                         tuple(round(v, 6) for v in (box.left, box.top, box.width, box.height)))


class WhichEdition(unittest.TestCase):
    def test_dual_mode_two_is_fantasy_under_legacy(self) -> None:
        self.assertEqual("fantasy", view.edition_in_effect({f"{LEGACY}B2SDualMode": "2"}))

    def test_dual_mode_one_or_unset_is_authentic(self) -> None:
        self.assertEqual(("authentic", "authentic"),
                         (view.edition_in_effect({f"{LEGACY}B2SDualMode": "1"}),
                          view.edition_in_effect({})))

    def test_b2s_has_no_dual_mode(self) -> None:
        held = {f"{LEGACY}Enable": "0", f"{LEGACY}B2SDualMode": "2"}

        self.assertEqual("authentic", view.edition_in_effect(held))


class TheLauncherConfigShape(unittest.TestCase):
    def test_a_value_is_read_out_of_its_entry(self) -> None:
        self.assertEqual({"a": "1", "b": "", "c": "x"},
                         view.flat({"a": {"value": "1"}, "b": None, "c": "x"}))


if __name__ == "__main__":
    unittest.main()
