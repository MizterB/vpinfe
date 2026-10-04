"""An action sits with what it acts on, never under a heading that says "Actions".

The placement rule is `docs/conventions.md`, "An action sits with what it acts on". What
this reads is its residue: a section or heading named for the mechanism, a subject whose
panel menu and grid menu are drawn from different lists, and buttons built by hand
instead of through `panel.py`, which is where a verb's treatment is decided.
"""

from __future__ import annotations

import ast
import json
import pathlib
import unittest

from tests.support import trees

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
CONSOLE = REPO / "console"
CATALOG = REPO / "common" / "i18n" / "catalogs" / "en.json"

# `panel.py` is the ⋮ that opens a subject's verbs.
ACTIONS_WORD_AT = {"panel.py"}

# Every subject with a panel ⋮: the module and function that write its list of verbs, and
# the module whose grid row menu draws it.
GRID_OF = {
    "tag": ("tageditor.py", "acts", "tageditor.py"),
    "collection": ("collections.py", "acts", "collections.py"),
    "launcher": ("launchers.py", "acts", "launchers.py"),
    "location": ("locations.py", "acts", "locations.py"),
    "theme": ("themes.py", "acts", "themes.py"),
    "device": ("devices.py", "acts", "devices.py"),
    "player": ("players.py", "acts", "players.py"),
    "game": ("game_acts.py", "game_acts", "games.py"),
    "table": ("game_acts.py", "table_acts", "games.py"),
}

# Direct `ui.button(` calls outside `panel.py`. A count that only comes down: lower it
# when one moves to a constructor, never raise it.
BUTTON_CEILING = 77


def _tree(path: pathlib.Path) -> ast.Module:
    return trees.tree_for(path)


def _is_ui_call(node: ast.AST, attr: str) -> bool:
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == attr and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "ui")


# What a section's builder draws, read from `ui.` and `panel.` calls. A button is a verb; a
# layout call holds either; anything else is something to read or set.
_BUTTONS = {"action", "icon_action", "remote_action", "browse_button", "link", "link_out",
            "out", "menu_button", "verb_menu", "subject_menu", "button"}
_LAYOUT = {"row", "column", "element", "space", "separator", "tooltip", "menu", "item",
           "card", "timer", "notify", "navigate", "run_javascript", "add_head_html",
           "add_css", "expansion", "tabs", "tab", "tab_panels", "tab_panel", "dialog"}


def _imports(tree: ast.Module) -> dict[str, tuple[str, str | None]]:
    """What each imported console name is: (module, name) for a function, (module, None)
    for a module."""
    found: dict[str, tuple[str, str | None]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or not node.module:
            continue
        for alias in node.names:
            bound = alias.asname or alias.name
            if node.module == "console":
                found[bound] = (alias.name, None)
            elif node.module.startswith("console."):
                found[bound] = (node.module.removeprefix("console."), alias.name)
    return found


def draws(trees_by_module: dict[str, ast.Module], module: str, name: str) -> set[str]:
    """`button` and `content` for what `module.name` draws, through the console functions
    it calls. A call that resolves to nothing here is a library call, and is not read."""
    defs = {mod: {node.name: node for node in tree.body
                  if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
            for mod, tree in trees_by_module.items()}
    imports = {mod: _imports(tree) for mod, tree in trees_by_module.items()}
    seen: set[tuple[str, str]] = set()
    found: set[str] = set()
    stack = [(module, name)]
    while stack:
        mod, fn = stack.pop()
        node = defs.get(mod, {}).get(fn)
        if node is None or (mod, fn) in seen:
            continue
        seen.add((mod, fn))
        for call in ast.walk(node):
            if not isinstance(call, ast.Call):
                continue
            func = call.func
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                owner, attr = func.value.id, func.attr
                if owner in ("ui", "panel"):
                    found.add("button" if attr in _BUTTONS else
                              "layout" if attr in _LAYOUT and owner == "ui" else "content")
                elif owner in imports[mod] and imports[mod][owner][1] is None:
                    stack.append((imports[mod][owner][0], attr))
            elif isinstance(func, ast.Name):
                if func.id in defs.get(mod, {}):
                    stack.append((mod, func.id))
                elif func.id in imports[mod] and imports[mod][func.id][1] is not None:
                    stack.append((imports[mod][func.id][0], imports[mod][func.id][1] or ""))
    return found - {"layout"}


def _builders(trees_by_module: dict[str, ast.Module]) -> dict[str, list[tuple[str, str]]]:
    """Each rail section's key, with the functions that build it. The workbench's `SECTIONS`
    names them; an account section is built by `players._account`, outside that list."""
    imports = _imports(trees_by_module["workbench"])
    built: dict[str, list[tuple[str, str]]] = {}
    for node in ast.walk(trees_by_module["workbench"]):
        if not (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "Section"
                and len(node.args) > 2):
            continue
        refs: list[tuple[str, str]] = []
        for ref in ast.walk(node.args[2]):
            if isinstance(ref, ast.Name):
                refs.append(("workbench", ref.id))
            elif (isinstance(ref, ast.Attribute) and isinstance(ref.value, ast.Name)
                  and ref.value.id in imports and imports[ref.value.id][1] is None):
                refs.append((imports[ref.value.id][0], ref.attr))
        built[ast.unparse(node.args[0])] = refs
    built["player_account"] = [("players", "_account")]
    return built


def _console_trees() -> dict[str, ast.Module]:
    return {path.stem: _tree(path) for path in CONSOLE.glob("*.py")}


def _subject_verbs() -> set[str]:
    for node in _tree(CONSOLE / "workbench.py").body:
        target = getattr(node, "target", None)
        if isinstance(target, ast.Name) and target.id == "SUBJECT_VERBS" \
                and isinstance(node.value, ast.Dict):
            return {key.value for key in node.value.keys
                    if isinstance(key, ast.Constant)}
    return set()


class TestActionsSitWithTheirSubject(unittest.TestCase):
    def test_no_heading_or_section_is_called_actions(self) -> None:
        catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
        spelled = sorted(key for key, value in catalog.items() if value == "Actions")
        self.assertEqual(spelled, ["word.actions"],
                         "name the section for what it holds, or put the verbs in a strip")
        offenders = sorted(path.name for path in CONSOLE.rglob("*.py")
                           if '"word.actions"' in path.read_text(encoding="utf-8")
                           and path.name not in ACTIONS_WORD_AT)
        self.assertEqual(offenders, [])

    def test_no_section_key_is_an_actions_bucket(self) -> None:
        keys = [node.args[0].value
                for node in ast.walk(_tree(CONSOLE / "workbench.py"))
                if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "Section"
                and node.args and isinstance(node.args[0], ast.Constant)]
        self.assertTrue(keys)
        self.assertEqual([key for key in keys if key.endswith("_actions")], [])

    def test_a_subject_menu_and_its_row_menu_share_one_list(self) -> None:
        self.assertEqual(_subject_verbs(), set(GRID_OF))
        for subject, (written, function, drawn) in GRID_OF.items():
            defined = {node.name for node in _tree(CONSOLE / written).body
                       if isinstance(node, ast.FunctionDef)}
            tree = _tree(CONSOLE / drawn)
            called = {node.func.attr for node in ast.walk(tree)
                      if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                      and isinstance(node.func.value, ast.Name)
                      and node.func.value.id == "panel"}
            with self.subTest(subject=subject):
                self.assertIn(function, defined)
                self.assertIn("verb_menu", called)

    def test_no_section_is_only_buttons(self) -> None:
        read = _console_trees()
        sections = _builders(read)
        self.assertGreater(len(sections), 25)
        drawn = {key: set().union(*(draws(read, *ref) for ref in refs))
                 for key, refs in sections.items()}
        self.assertEqual([key for key, found in drawn.items() if not found], [],
                         "a section's builder was not followed to anything it draws")
        only_buttons = sorted(key for key, found in drawn.items() if found == {"button"})
        self.assertEqual(only_buttons, [],
                         "a verb sits in the menu of what it acts on; a section holds "
                         "something to read or set")

    def test_a_builder_of_only_buttons_is_found_and_a_mixed_one_is_not(self) -> None:
        source = trees.parse_snippet(
            "def bare(): panel.action('Go', go)()\n"
            "def mixed(): panel.action('Go', go)(); panel.facts(ui, [])\n"
            "def through(): bare()\n")
        found = {"snippet": source}
        self.assertEqual(draws(found, "snippet", "bare"), {"button"})
        self.assertEqual(draws(found, "snippet", "mixed"), {"button", "content"})
        self.assertEqual(draws(found, "snippet", "through"), {"button"})

    def test_hand_built_buttons_only_come_down(self) -> None:
        count = sum(1 for path in CONSOLE.rglob("*.py") if path.name != "panel.py"
                    for node in ast.walk(_tree(path)) if _is_ui_call(node, "button"))
        self.assertLessEqual(count, BUTTON_CEILING,
                             "build it with panel.action, panel.verb_menu or dialog.footer")
        if count < BUTTON_CEILING:
            self.fail(f"{count} now: lower BUTTON_CEILING to match")


if __name__ == "__main__":
    unittest.main()
