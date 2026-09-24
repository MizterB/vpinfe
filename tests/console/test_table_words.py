"""One name and one direction per fact, which is the rule three surfaces broke.

`Hidden` read one way in the grid and the opposite in the panel, and `Missing` did the
same - so the words are asserted here rather than left to each surface to spell.
"""

import unittest
from typing import Any

from common.i18n import t
from console import game_tables, games

WORDS = game_tables.DEFAULT_WORDS


class WordTests(unittest.TestCase):
    def test_the_notable_state_is_the_first_of_the_pair(self) -> None:
        """The direction every one of these reads: true is the state worth spotting."""
        self.assertEqual(game_tables.word_for(game_tables.HIDDEN_WORDS, True), "Hidden")
        self.assertEqual(game_tables.word_for(game_tables.FILE_WORDS, True), "Missing")

    def test_a_file_that_is_there_reads_present(self) -> None:
        """The inversion this helper exists to stop: a `pair[not present]` at the call
        site put "Missing" on a file that was on disk."""
        self.assertEqual(game_tables.word_for(game_tables.FILE_WORDS, False), "Present")
        self.assertEqual(game_tables.word_for(game_tables.HIDDEN_WORDS, False),
                         "Offered")

    def test_a_default_says_what_it_does_not_who_set_it(self) -> None:
        chosen, chosen_why = WORDS[game_tables.CHOSEN]
        automatic, automatic_why = WORDS[game_tables.DERIVED]

        self.assertEqual((chosen, automatic), ("Locked", "Automatic"))
        self.assertNotEqual(chosen_why, automatic_why)

    def test_a_locked_default_wears_a_held_collection_row_s_word(self) -> None:
        self.assertEqual(WORDS[game_tables.CHOSEN][0], game_tables.LOCKED_WORDS[0])

    def test_the_reason_is_what_happens_when_a_table_is_added(self) -> None:
        self.assertIn("Stays", WORDS[game_tables.CHOSEN][1])
        self.assertIn("newest", WORDS[game_tables.DERIVED][1])


def _table(table_id: str, **extra: Any) -> dict[str, Any]:
    return {"id": table_id, "version": table_id.title(), "authors": ["someone"], **extra}


AUTOMATIC = _table("alpha", default=True, default_kind=game_tables.DERIVED, automatic=True)
LOCKED = _table("alpha", default=True, default_kind=game_tables.CHOSEN)
OTHER = _table("beta")


class LockActTests(unittest.TestCase):
    """The act on the default row of a game's tables, and its words."""

    def test_an_automatic_default_is_offered_the_lock(self) -> None:
        self.assertEqual(game_tables.lock_act(AUTOMATIC, [AUTOMATIC, OTHER]),
                         (True, t("console.game_tables.lock")))

    def test_a_locked_default_is_offered_the_unlock(self) -> None:
        self.assertEqual(game_tables.lock_act(LOCKED, [LOCKED, OTHER]),
                         (False, t("console.game_tables.unlock")))

    def test_the_unlock_names_where_the_default_goes(self) -> None:
        goes = {**OTHER, "automatic": True}

        lock, words = game_tables.lock_act(LOCKED, [LOCKED, goes]) or (None, "")

        self.assertFalse(lock)
        self.assertIn(game_tables.table_name(goes), words)

    def test_a_leftover_lock_can_be_cleared_with_one_table(self) -> None:
        self.assertEqual(game_tables.lock_act(LOCKED, [LOCKED]),
                         (False, t("console.game_tables.unlock")))

    def test_one_table_has_nothing_to_lock_against(self) -> None:
        self.assertIsNone(game_tables.lock_act(AUTOMATIC, [AUTOMATIC]))

    def test_a_table_that_is_not_the_default_has_no_lock(self) -> None:
        """Its radio is the act: picking it makes it the default."""
        self.assertIsNone(game_tables.lock_act(OTHER, [AUTOMATIC, OTHER]))


class LockSaidTests(unittest.TestCase):
    def test_a_lock_names_the_table(self) -> None:
        said = game_tables.lock_said("Sample Game", OTHER, [], lock=True)

        self.assertIn(game_tables.table_name(OTHER), said)

    def test_an_unlock_that_moves_the_default_names_where_it_went(self) -> None:
        after = [{**LOCKED, "default": False}, {**OTHER, "default": True}]

        said = game_tables.lock_said("Sample Game", LOCKED, after, lock=False)

        self.assertIn("Sample Game", said)
        self.assertIn(game_tables.table_name(OTHER), said)

    def test_an_unlock_that_moves_nothing_says_only_that(self) -> None:
        said = game_tables.lock_said("Sample Game", LOCKED, [LOCKED], lock=False)

        self.assertEqual(said, t("console.game_tables.unlocked"))


class DefaultCellTests(unittest.TestCase):
    """The Tables grid's Default Table column."""

    def _cells(self, *rows: dict[str, Any]) -> list[str]:
        return [row["default_state"] for row in games.table_rows(list(rows))]

    def test_a_game_with_a_choice_says_which_and_how(self) -> None:
        rows = [{**AUTOMATIC, "game_id": "g1"}, {**OTHER, "game_id": "g1"}]

        self.assertEqual(self._cells(*rows), [game_tables.DERIVED, ""])

    def test_a_lock_is_said_even_on_a_game_with_one_table(self) -> None:
        self.assertEqual(self._cells({**LOCKED, "game_id": "g1"}), [game_tables.CHOSEN])

    def test_a_game_with_one_table_says_nothing_a_filter_would_name(self) -> None:
        (cell,) = self._cells({**AUTOMATIC, "game_id": "g1"})
        named = {choice["value"] for choice in _default_column()["filterParams"]["choices"]}

        self.assertNotIn(cell, named)


def _default_column() -> dict[str, Any]:
    return next(column for column in games.TABLE_COLUMNS
                if column.get("field") == "default_state")


if __name__ == "__main__":
    unittest.main()
