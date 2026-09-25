"""Get missing art: which kinds start ticked, what is kept, and what it says at the end."""

from __future__ import annotations

import unittest

from console.art_fill import outcome, remember, ticked

KINDS = [{"kind": "wheel", "missing": 12, "available": 9},
         {"kind": "backglass", "missing": 4, "available": 2},
         {"kind": "flyer", "missing": 0, "available": 0},
         {"kind": "topper", "missing": 5, "available": 0}]


class TickTests(unittest.TestCase):
    def test_first_time_every_kind_with_something_to_get_is_ticked(self) -> None:
        self.assertEqual(ticked(KINDS, {}), {"wheel": True, "backglass": True,
                                             "flyer": False, "topper": False})

    def test_a_kind_left_unticked_stays_unticked(self) -> None:
        self.assertEqual(ticked(KINDS, {"backglass": False})["backglass"], False)

    def test_a_kind_ticked_before_with_nothing_to_get_now_is_not(self) -> None:
        self.assertEqual(ticked(KINDS, {"topper": True})["topper"], False)

    def test_a_dimmed_row_keeps_what_was_held_for_it(self) -> None:
        held = {"topper": True, "wheel": True}
        chosen = {"wheel": False, "backglass": True, "flyer": False, "topper": False}

        self.assertEqual(remember(held, chosen, KINDS),
                         {"topper": True, "wheel": False, "backglass": True})


class OutcomeTests(unittest.TestCase):
    def test_it_says_how_many_files_it_got(self) -> None:
        self.assertEqual(outcome({"filled": 1}), ("Got 1 file", "positive"))
        self.assertEqual(outcome({"filled": 18, "unmatched": 3}),
                         ("Got 18 files", "positive"))

    def test_failures_are_counted_beside_what_it_got(self) -> None:
        self.assertEqual(outcome({"filled": 5, "failed": 2}),
                         ("Got 5 files, 2 failed", "warning"))
        self.assertEqual(outcome({"failed": 2}), ("Could not get 2 files", "warning"))

    def test_nothing_found_is_not_a_failure(self) -> None:
        self.assertEqual(outcome({"games": 3, "filled": 0}), ("No art found", "info"))


if __name__ == "__main__":
    unittest.main()
