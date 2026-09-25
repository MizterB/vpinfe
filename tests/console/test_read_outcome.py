"""What Look for new tables says when it ends, and which new games it leads to."""

from __future__ import annotations

import unittest

from console.page import read_outcome


def _result(games: int, matched: int, waiting: list[str]) -> dict:
    return {"new_games": games, "new_matched": matched, "new_unmatched": len(waiting),
            "new_unmatched_ids": waiting}


class ReadOutcomeTests(unittest.TestCase):
    def test_nothing_new_is_up_to_date(self) -> None:
        self.assertEqual(read_outcome(_result(0, 0, [])),
                         ("The library is up to date", []))

    def test_every_new_game_matched_leads_nowhere(self) -> None:
        self.assertEqual(read_outcome(_result(3, 3, [])), ("Matched 3 new games", []))
        self.assertEqual(read_outcome(_result(1, 1, [])), ("Matched 1 new game", []))

    def test_some_matched_says_how_many_are_left(self) -> None:
        self.assertEqual(read_outcome(_result(12, 10, ["g1", "g2"])),
                         ("Matched 10 of 12 new games. 2 need a match.", ["g1", "g2"]))
        self.assertEqual(read_outcome(_result(3, 2, ["g1"])),
                         ("Matched 2 of 3 new games. 1 needs a match.", ["g1"]))

    def test_none_matched_says_they_need_one(self) -> None:
        self.assertEqual(read_outcome(_result(2, 0, ["g1", "g2"])),
                         ("2 new games need a match", ["g1", "g2"]))
        self.assertEqual(read_outcome(_result(1, 0, ["g1"])),
                         ("1 new game needs a match", ["g1"]))

    def test_a_job_that_said_nothing_is_up_to_date(self) -> None:
        self.assertEqual(read_outcome({}), ("The library is up to date", []))


if __name__ == "__main__":
    unittest.main()
