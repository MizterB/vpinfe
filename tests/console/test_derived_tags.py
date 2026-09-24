"""A tag an extension derives, as the Console shows it: in the grids beside the user's
own, never offered by hand, and moved by nobody but its extension."""

from __future__ import annotations

import unittest
from typing import Any

from console import games, tageditor
from console.data import Library

SOURCE = {"extension": "challenge", "display_name": "Challenge", "list": "releases",
          "title": "Weekly Challenge", "read_at": "2026-09-23T12:00:00Z", "stale": False}
DERIVED = "Weekly Challenge"


class _Client:
    def tags(self) -> list[dict[str, Any]]:
        return [{"name": "Wide Body", "games": 1, "tables": 0},
                {"name": "wide body", "games": 1, "tables": 0},
                {"name": DERIVED, "games": 0, "tables": 1, "sources": [SOURCE]},
                {"name": "weekly challenge", "games": 1, "tables": 0}]


def _library() -> Library:
    library = Library(_Client())  # type: ignore[arg-type]
    library.games = [{"id": "afm", "name": "Attack from Mars",
                      "user": {"tags": ["Wide Body"]}, "derived_tags": [DERIVED]}]
    library.read_tags()
    return library


async def _after(_next: str | None) -> None:
    return None


class InTheGrids(unittest.TestCase):
    def test_a_game_row_carries_both(self) -> None:
        (row,) = _library().game_rows()

        self.assertEqual(["Wide Body", DERIVED], row["tags"])

    def test_a_table_row_carries_both(self) -> None:
        (row,) = games.table_rows([{"id": "t", "game_id": "afm",
                                    "user": {"tags": ["Wide Body"]},
                                    "derived_tags": [DERIVED]}])

        self.assertEqual(["Wide Body", DERIVED], row["tags"])


class OnTheTagsPage(unittest.TestCase):
    def test_the_picker_does_not_offer_one(self) -> None:
        self.assertNotIn(DERIVED, _library().tags())

    def test_its_row_names_the_source(self) -> None:
        said = {row["tag"]: row for row in _library().tag_rows()}

        self.assertEqual("Challenge: Weekly Challenge", said[DERIVED]["source"])
        self.assertEqual("", said["Wide Body"]["source"])

    def test_it_is_not_a_spelling_to_merge(self) -> None:
        groups = tageditor.rows_by_key(_library().tag_rows())

        self.assertEqual([["Wide Body", "wide body"]],
                         [sorted(row["tag"] for row in group) for group in groups])

    def test_its_menu_offers_nothing(self) -> None:
        self.assertEqual([], tageditor.acts(_library(), DERIVED, 0, _after))

    def test_another_tag_cannot_be_merged_into_it(self) -> None:
        verbs = tageditor.acts(_library(), "weekly challenge", 1, _after)
        into = next(verb for verb in verbs if verb.choices)

        self.assertNotIn(DERIVED, [label for label, _ in into.choices])


if __name__ == "__main__":
    unittest.main()
