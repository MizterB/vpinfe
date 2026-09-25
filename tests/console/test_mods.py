"""How a mod reads, and where it sits in the release picker."""

from __future__ import annotations

import unittest
from typing import Any

from console import game_tables
from console.workbench import in_lineage


def _mod(parent: str = "", **said: Any) -> dict[str, Any]:
    return {"vps_file_id": parent, "version": "", "authors": [], "game": "", "url": "",
            "note": "", "game_id": "", "table_id": "", **said}


def _release(own: str, mod_of: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"vps_file_id": own, "mod_of": mod_of}


def _order(releases: list[dict[str, Any]]) -> list[tuple[str, bool]]:
    return [(one["vps_file_id"], under) for one, under in in_lineage(releases)]


class Words(unittest.TestCase):
    def test_a_linked_mod_names_the_version_and_makers(self) -> None:
        self.assertEqual("Mod of 1.2 · VPW", game_tables.mod_line(
            _mod("p", version="1.2", authors=["VPW"])))

    def test_the_game_is_named_only_where_it_is_another(self) -> None:
        self.assertEqual("Mod of The Addams Family · 1.2 · VPW", game_tables.mod_line(
            _mod("p", version="1.2", authors=["VPW"], game="The Addams Family")))

    def test_a_tagged_mod_reads_as_vps_wrote_it(self) -> None:
        self.assertEqual("Mod · FSS MOD", game_tables.mod_line(_mod(note="FSS MOD")))
        self.assertEqual("FSS MOD", game_tables.mod_of_said(_mod(note="FSS MOD")))

    def test_with_nothing_to_go_on_it_is_a_mod_of_something_unknown(self) -> None:
        self.assertEqual("Mod of Unknown", game_tables.mod_line(_mod()))

    def test_a_release_that_is_no_mod_says_nothing(self) -> None:
        self.assertEqual(("", ""), (game_tables.mod_line(None),
                                    game_tables.mod_of_said(None)))


class Lineage(unittest.TestCase):
    def test_a_mod_follows_the_release_it_is_based_on_one_step_in(self) -> None:
        releases = [_release("mod", _mod("base")), _release("other"), _release("base")]
        self.assertEqual([("other", False), ("base", False), ("mod", True)],
                         _order(releases))

    def test_a_mod_of_a_mod_is_one_step_in_too_and_follows_its_own(self) -> None:
        releases = [_release("base"), _release("deeper", _mod("mod")),
                    _release("mod", _mod("base")), _release("second", _mod("base"))]
        self.assertEqual([("base", False), ("mod", True), ("deeper", True),
                          ("second", True)], _order(releases))

    def test_a_mod_of_something_not_listed_keeps_its_place(self) -> None:
        releases = [_release("a"), _release("elsewhere", _mod("another-game")),
                    _release("tagged", _mod()), _release("b")]
        self.assertEqual([("a", False), ("elsewhere", False), ("tagged", False),
                          ("b", False)], _order(releases))

    def test_a_loop_of_links_is_listed_once_each(self) -> None:
        releases = [_release("x"), _release("one", _mod("two")),
                    _release("two", _mod("one"))]
        self.assertEqual([("x", False), ("one", False), ("two", True)], _order(releases))


if __name__ == "__main__":
    unittest.main()
