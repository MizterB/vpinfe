"""The first column of Assets and Media says whether a file is the game's or one table's.

A version and author under the name is a file for that one table; a bare name is the
game's. The Table column that said the same thing a second time is in no shipped view,
and the chip that said it a third time is gone from the file panel.
"""

from __future__ import annotations

import unittest

from common.i18n import t
from console import assets, game_tables, grid, media, media_ownership

TABLES = {
    "t1": {"id": "t1", "filename": "Example (Author) v1.vpx", "version": "1.2",
           "authors": ["Someone"]},
    "t2": {"id": "t2", "filename": "Example Bare.vpx"},
}


class NamedIn(unittest.TestCase):
    def test_a_table_file_reads_as_the_table_does_in_the_tables_grid(self) -> None:
        said = game_tables.named_in({"table": "t1", "table_file": "x.vpx"}, TABLES)

        self.assertEqual(game_tables.table_name(TABLES["t1"]), said["said_built"])
        self.assertFalse(said["said_built_file"])

    def test_a_table_with_no_version_or_author_is_named_by_its_file(self) -> None:
        said = game_tables.named_in({"table": "t2"}, TABLES)

        self.assertEqual("Example Bare.vpx", said["said_built"])
        self.assertTrue(said["said_built_file"])

    def test_a_file_of_the_games_own_names_no_table(self) -> None:
        said = game_tables.named_in({"table": "", "table_file": ""}, TABLES)

        self.assertEqual({"said_built": "", "said_built_file": False}, said)

    def test_an_orphan_is_its_stem_in_the_file_style(self) -> None:
        said = game_tables.named_in({"table": "", "table_file": "Gone v2"}, TABLES)

        self.assertEqual({"said_built": "Gone v2", "said_built_file": True}, said)


class TheShippedViews(unittest.TestCase):
    def test_no_view_shows_the_table_column(self) -> None:
        for lens in (assets, media):
            for name, preset in lens.VIEWS.items():
                columns = preset.columns if hasattr(preset, "columns") else preset
                self.assertNotIn("table_file", columns, f"{lens.__name__}: {name}")

    def test_the_picker_still_offers_it(self) -> None:
        for lens in (assets, media):
            self.assertIn("table_file", [one["field"] for one in lens.COLUMNS])

    def test_the_first_column_says_what_the_second_line_is(self) -> None:
        for lens in (assets, media):
            game = next(one for one in lens.COLUMNS if one["field"] == "game")
            self.assertIn("said_built", game[":cellRenderer"])
            self.assertIn(t("console.media_ownership.named_for"), game[":cellRenderer"])


class TheNameAndScopeColumns(unittest.TestCase):
    def test_the_first_column_is_headed_name(self) -> None:
        for lens in (assets, media):
            first = next(one for one in lens.COLUMNS if one["field"] == "game")
            self.assertEqual(t("word.name"), first["headerName"])

    def test_scope_is_a_game_or_table_pick_list_in_the_picker_and_the_everything_view(
            self) -> None:
        for lens in (assets, media):
            scope = next(one for one in lens.COLUMNS if one["field"] == "scope")
            self.assertEqual(["game", "table"],
                             [one["value"] for one in scope["filterParams"]["choices"]])
            self.assertIn("scope", lens.VIEWS["console.view.everything"].columns)

    def test_scope_follows_what_the_yellow_line_says(self) -> None:
        for row, scope in (({"table": "", "table_file": ""}, "game"),
                           ({"table": "t1", "table_file": "x.vpx"}, "table"),
                           ({"table": "t2", "table_file": ""}, "table"),
                           ({"table": "", "table_file": "Gone v2"}, "table")):
            self.assertEqual(scope, game_tables.scope_of(row), row)
            self.assertEqual(scope, assets.rows([row])[0]["scope"], row)
            self.assertEqual(scope, media.rows([row])[0]["scope"], row)


class TheRenderer(unittest.TestCase):
    def test_no_tip_puts_no_title_on_the_line(self) -> None:
        plain = grid.identifier("name", "Game", subtitle=("a", "", "b"))

        self.assertIn("const tip = \"\";", plain[":cellRenderer"])


class TheFilePanelDrawsNoScopeChip(unittest.TestCase):
    def test_table_and_game_are_the_two_scopes(self) -> None:
        self.assertEqual((media_ownership.TABLE, media_ownership.GAME),
                         media_ownership.SCOPES)

    def test_a_state_is_not_a_scope(self) -> None:
        for state in (media_ownership.ORPHAN, media_ownership.UNUSED,
                      media_ownership.STAND_IN, media_ownership.MISSING):
            self.assertNotIn(state, media_ownership.SCOPES)


if __name__ == "__main__":
    unittest.main()
