"""A disclosure is drawn one way, whatever it sits in.

Every `ui.expansion` in the Console is a disclosure, so each one carries
`console-disclosure`, and a stylesheet rule reaches Quasar's expansion only through it. A
rule scoped to a container instead restyles the disclosures that happen to sit there.
"""

from __future__ import annotations

import ast
import pathlib
import re
import unittest

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
CONSOLE = REPO / "console"
EXPANSION_PARTS = (".q-expansion-item", ".nicegui-expansion")


def _is_ui_expansion(node: ast.AST) -> bool:
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "expansion" and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "ui")


def _base(call: ast.Call) -> ast.AST:
    """The call a chain of `.props(...)`, `.classes(...)` and the like hangs from."""
    node: ast.AST = call
    while (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
           and isinstance(node.func.value, ast.Call)):
        node = node.func.value
    return node


def _expansions() -> list[tuple[str, int, list[str]]]:
    """Each `ui.expansion` with the words its chained `.classes` calls pass."""
    found = []
    for path in sorted(CONSOLE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        classes: dict[int, list[str]] = {}
        for node in ast.walk(tree):
            if _is_ui_expansion(node):
                classes.setdefault(id(node), [])
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "classes"):
                continue
            base = _base(node)
            if id(base) in classes:
                classes[id(base)] += [word for arg in node.args
                                      if isinstance(arg, ast.Constant)
                                      and isinstance(arg.value, str)
                                      for word in arg.value.split()]
        for node in ast.walk(tree):
            if _is_ui_expansion(node):
                found.append((str(path.relative_to(REPO)), node.lineno, classes[id(node)]))
    return found


def _selectors() -> list[tuple[str, str]]:
    found = []
    for sheet in sorted((CONSOLE / "static").rglob("*.css")):
        text = re.sub(r"/\*.*?\*/", "", sheet.read_text(encoding="utf-8"), flags=re.S)
        for group in re.findall(r"([^{}]+)\{[^{}]*\}", text):
            found += [(sheet.name, one.strip()) for one in group.split(",")]
    return found


class TestOneDisclosure(unittest.TestCase):
    def test_the_console_has_disclosures_to_check(self) -> None:
        self.assertTrue(_expansions(), "no ui.expansion found; the walk is broken")

    def test_every_expansion_is_a_disclosure(self) -> None:
        for where, line, words in _expansions():
            with self.subTest(f"{where}:{line}"):
                self.assertIn("console-disclosure", words)

    def test_no_disclosure_spans_the_pane(self) -> None:
        for where, line, words in _expansions():
            with self.subTest(f"{where}:{line}"):
                self.assertNotIn("w-full", words)

    def test_the_expansion_is_styled_only_as_a_disclosure(self) -> None:
        for sheet, selector in _selectors():
            if not any(part in selector for part in EXPANSION_PARTS):
                continue
            with self.subTest(f"{sheet}: {selector}"):
                self.assertRegex(selector, r"^\.console-disclosure[\s.]",
                                 "a rule on the expansion goes through .console-disclosure")


if __name__ == "__main__":
    unittest.main()
