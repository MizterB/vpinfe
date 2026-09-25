"""A table VPS lists a newer version of, on the Tables page."""

from __future__ import annotations

import unittest
from unittest.mock import Mock

from console import data, games, views


class TableUpdateTests(unittest.TestCase):
    def _row(self, **wire) -> dict:
        return games.table_rows([{"id": "t1", "game": "A", **wire}])[0]

    def test_a_newer_release_reads_newer_beside_the_version_vps_lists(self) -> None:
        row = self._row(version="1.0", update_available=True,
                        source={"vps_file_id": "release01", "version": "1.2"})

        self.assertEqual(("1.2", games._NEWER), (row["on_vps"], row["update"]))

    def test_nothing_known_reads_blank(self) -> None:
        for known in (False, None):
            with self.subTest(known=known):
                self.assertEqual("", self._row(update_available=known)["update"])

    def test_the_updates_view_holds_only_those_rows(self) -> None:
        view = next(view for view in views.builtins(games.TABLE_VIEWS)
                    if view.name == "Updates")
        column = next(definition for definition in games.TABLE_COLUMNS
                      if definition["field"] == "update")

        self.assertEqual({"update": {"values": [games._NEWER]}}, view.filters)
        self.assertIn(games._NEWER, [choice["value"]
                                     for choice in column["filterParams"]["choices"]])


class MatchingAReleaseTests(unittest.TestCase):
    def test_the_tables_are_read_again_with_what_the_match_changed(self) -> None:
        client = Mock()
        client.all_tables.return_value = []
        client.tables.return_value = []
        client.games.return_value = []
        library = data.Library(client)
        library.load_tables()
        library.tables_for("game")

        library.set_table_source("game", "t1", "release01")
        library.load_tables()
        library.tables_for("game")

        self.assertEqual((2, 2), (client.all_tables.call_count, client.tables.call_count))


if __name__ == "__main__":
    unittest.main()
