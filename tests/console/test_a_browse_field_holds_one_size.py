"""The marks at the end of a field with Browse are one size.

A field that draws Browse wears the class the sizing rule is keyed on, or its error mark,
tick and folder glyph stop matching.
"""

from __future__ import annotations

import ast
import pathlib
import unittest

from tests.support import trees
from tests.support.stylesheet import declarations

CLASS = "console-adorned"
CONSOLE = pathlib.Path(__file__).resolve().parent.parent.parent / "console"


def _says_the_class(function: ast.AST) -> bool:
    """Whether the class reaches a `.classes(...)` call, not merely appears in a string."""
    return any(isinstance(call, ast.Call) and getattr(call.func, "attr", "") == "classes"
               and any(isinstance(one, ast.Constant) and isinstance(one.value, str)
                       and CLASS in one.value for one in ast.walk(call))
               for call in ast.walk(function))


def _draws_browse(function: ast.AST) -> bool:
    return any(isinstance(node, ast.Call)
               and getattr(node.func, "id", getattr(node.func, "attr", "")) == "browse_button"
               for node in ast.walk(function))


def _browse_fields() -> list[tuple[str, ast.FunctionDef, bool]]:
    """Each top-level function that draws a Browse button, and whether it names the class.

    Top-level only: `panel.field` draws Browse inside a nested `draw`, and the class is
    set in that same function, so the outer one answers for both.
    """
    found = []
    for path in sorted(CONSOLE.glob("*.py")):
        for node in trees.tree_for(path).body:
            if (isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
                    and node.name != "browse_button"
                    and _draws_browse(node)):
                found.append((f"console/{path.name}:{node.lineno} {node.name}", node,
                              _says_the_class(node)))
    return found


class ABrowseFieldHoldsOneSize(unittest.TestCase):
    def test_the_class_sizes_the_icons_in_the_append_slot(self) -> None:
        rule = declarations(f".{CLASS} .q-field__append .q-icon")
        self.assertEqual("var(--icon-mark)", rule.get("font-size"))

    def test_every_field_that_draws_browse_wears_the_class(self) -> None:
        without = [where for where, _, wears in _browse_fields() if not wears]
        self.assertEqual([], without, f"Browse drawn in a field without .{CLASS}")

    def test_it_found_the_fields(self) -> None:
        """An empty sweep passes and measures nothing, which reads the same as clean."""
        self.assertGreaterEqual(len(_browse_fields()), 3)


if __name__ == "__main__":
    unittest.main()
