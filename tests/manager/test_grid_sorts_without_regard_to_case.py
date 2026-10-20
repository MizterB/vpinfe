"""Grids are built with `accentedSort`, and no column orders text by code unit."""

from __future__ import annotations

import ast
import pathlib
import unittest
from unittest.mock import MagicMock, patch

from manager.kit import grid
from tests.support import trees

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
MANAGER = REPO / "manager"


def _options_of_a_built_grid() -> dict:
    columns = [grid.identifier("name", "Name", help="The name"),
               grid.column("author", "Author", help="Who made it")]
    with patch.object(grid, "ui", MagicMock()) as ui, \
            patch.object(grid.renderers, "install"):
        grid.build(columns, [], "manager.test.columns")
    return ui.aggrid.call_args.args[0]


def _own_comparators(tree: ast.Module) -> list[ast.Dict]:
    """Dicts that give a column an inline `:comparator` written as JavaScript."""
    return [node for node in ast.walk(tree) if isinstance(node, ast.Dict)
            and any(isinstance(key, ast.Constant) and key.value == ":comparator"
                    and isinstance(value, ast.Constant | ast.JoinedStr)
                    for key, value in zip(node.keys, node.values, strict=True))]


def _compares_by_code_unit(source: str) -> bool:
    """Whether the JavaScript orders with `<` or `>` and never asks the locale."""
    bare = source.replace("=>", "")
    return ("<" in bare or ">" in bare) and "localeCompare" not in bare


class EveryGridSortsText(unittest.TestCase):

    def test_the_one_place_grids_are_built_compares_text_by_locale(self) -> None:
        self.assertIs(_options_of_a_built_grid().get("accentedSort"), True)

    def test_the_default_column_does_not_replace_that_with_a_comparator(self) -> None:
        self.assertNotIn("comparator", grid.DEFAULT_COL_DEF)
        self.assertNotIn(":comparator", grid.DEFAULT_COL_DEF)

    def test_a_name_column_declares_no_comparator_of_its_own(self) -> None:
        for definition in (grid.identifier("name", "Name", help="x"),
                           grid.column("name", "Name", help="x")):
            self.assertNotIn(":comparator", definition)
            self.assertNotIn("comparator", definition)

    def test_no_column_in_manager_keeps_a_comparator_that_compares_by_code_unit(self) -> None:
        found = []
        for path in sorted(MANAGER.rglob("*.py")):
            for node in _own_comparators(trees.tree_for(path)):
                for key, value in zip(node.keys, node.values, strict=True):
                    if (isinstance(key, ast.Constant) and key.value == ":comparator"
                            and _compares_by_code_unit(ast.unparse(value))):
                        found.append(f"{path.relative_to(REPO).as_posix()}:{value.lineno}")
        self.assertEqual(found, [], "a column comparator uses < or > on text:\n  "
                         + "\n  ".join(found))

    def test_the_checker_can_actually_fail(self) -> None:
        bad = trees.parse_snippet("{':comparator': '(a, b) => a < b ? -1 : 1'}")
        self.assertEqual(len(_own_comparators(bad)), 1)
        self.assertTrue(_compares_by_code_unit("(a, b) => a < b ? -1 : 1"))
        self.assertFalse(_compares_by_code_unit("(a, b) => String(a).localeCompare(String(b))"))
        self.assertFalse(_compares_by_code_unit("(a, b) => a - b"))


if __name__ == "__main__":
    unittest.main()
