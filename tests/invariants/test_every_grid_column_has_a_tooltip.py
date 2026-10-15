"""Every grid column carries a header tooltip: `grid.column`, `grid.identifier` and
`grid.list_column` each pass a `help=`, and it is never empty. `grid.build` refuses a
set with a bare column at run time; this finds the call that declares one without
drawing the page."""

from __future__ import annotations

import ast
import pathlib
import unittest

from tests.support import trees

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
MANAGER = REPO / "manager"

DECLARERS = {"column", "identifier", "list_column"}
GRID_MODULES = {"grid", "grid_module"}


def _declarations(tree: ast.Module) -> list[ast.Call]:
    return [node for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr in DECLARERS
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in GRID_MODULES]


def _says_something(node: ast.Call) -> bool:
    help_kw = next((kw for kw in node.keywords if kw.arg == "help"), None)
    if help_kw is None:
        return False
    return not (isinstance(help_kw.value, ast.Constant) and help_kw.value.value == "")


class EveryGridColumnHasATooltip(unittest.TestCase):
    def test_every_declared_column_passes_help(self) -> None:
        found = 0
        bare = []
        for path in sorted(MANAGER.rglob("*.py")):
            if path.name == "grid.py":
                continue
            for node in _declarations(trees.tree_for(path)):
                found += 1
                if not _says_something(node):
                    field = ast.unparse(node.args[0]) if node.args else "?"
                    bare.append(f"{path.relative_to(REPO).as_posix()}:{node.lineno} {field}")
        self.assertGreater(found, 100, "the scan stopped finding column declarations")
        self.assertEqual(bare, [],
                         "a column explains itself in its header tooltip, passed as "
                         "help=:\n  " + "\n  ".join(bare))


if __name__ == "__main__":
    unittest.main()
