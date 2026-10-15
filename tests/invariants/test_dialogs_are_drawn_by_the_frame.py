"""Every Console dialog is made by `console/dialog.py`, so they all share one design."""

from __future__ import annotations

import ast
import pathlib
import unittest

from tests.support import trees

CONSOLE = pathlib.Path(__file__).resolve().parents[2] / "console"
FRAME = "dialog.py"
OPENS_ONE = "ui.dialog("

# Not questions, so they draw their own card: nothing in them is answered or committed.
NOT_ASKING = {
    "mediaview.py": "an enlarged picture or text, with nothing to answer",
    "remote.py": "the phone remote's own sheets, drawn for a touch screen",
}


# `persistent` blocks Escape as well as a click outside, so it is for a run that cannot be
# left half-way or an answer that cannot be left unsaid. Anything typed into takes
# `ignore_outside_click` and Escape still cancels. Each file below holds the number of
# places it says `persistent`, so a further one is a decision made here: a run puts it on
# and takes it off again, and a request still waiting is drawn with it.
PERSISTENT = {
    "mediasource.py": 2,
    "sign_in_notice.py": 1,
    "wizard.py": 2,
}


def _persistent(path: pathlib.Path) -> list[ast.AST]:
    """Where `path` asks for a `persistent` dialog, as a keyword or among the props."""
    return [one for one in ast.walk(trees.tree_for(path))
            if (isinstance(one, ast.keyword) and one.arg == "persistent")
            or (isinstance(one, ast.Constant) and isinstance(one.value, str)
                and "persistent" in one.value.split())]


def _called(path: pathlib.Path) -> set[str]:
    """What `path` calls on `console.dialog`, by name."""
    tree = trees.tree_for(path)
    names = {alias.asname or alias.name for one in ast.walk(tree)
             if isinstance(one, ast.ImportFrom) and one.module == "console"
             for alias in one.names if alias.name == "dialog"}
    return {one.func.attr for one in ast.walk(tree)
            if isinstance(one, ast.Call) and isinstance(one.func, ast.Attribute)
            and isinstance(one.func.value, ast.Name) and one.func.value.id in names}


TYPED_SECRET = ("token", "code")


def _can_be_clicked_away(call: ast.expr) -> bool:
    """Whether `call` is `dialog.opened(...)` with neither way to keep a click outside out."""
    return (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
            and call.func.attr == "opened"
            and not {"ignore_outside_click", "persistent"} & {key.arg for key in call.keywords})


def _takes_a_typed_secret(body: list[ast.stmt]) -> bool:
    """Whether a field in `body` is labelled by a catalog key that names a token or a code."""
    return any(isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
               and call.func.attr == "field"
               and any(isinstance(one, ast.Constant) and isinstance(one.value, str)
                       and one.value.startswith("console.")
                       and any(word in one.value.rsplit(".", 1)[-1] for word in TYPED_SECRET)
                       for one in ast.walk(call))
               for statement in body for call in ast.walk(statement))


def _secret_dialogs_that_close_on_a_click(path: pathlib.Path) -> list[int]:
    """Lines where `path` opens a dialog with a typed token or code and no way to ignore the
    click outside."""
    return [one.lineno for one in ast.walk(trees.tree_for(path)) if isinstance(one, ast.With)
            for item in one.items if _can_be_clicked_away(item.context_expr)
            and _takes_a_typed_secret(one.body)]


class DialogsAreDrawnByTheFrame(unittest.TestCase):
    def test_no_dialog_is_drawn_by_hand(self) -> None:
        by_hand = sorted(path.name for path in CONSOLE.glob("*.py")
                         if path.name != FRAME
                         and OPENS_ONE in path.read_text(encoding="utf-8"))
        self.assertEqual([], by_hand)

    def test_only_an_exception_draws_its_own_card(self) -> None:
        own = sorted(path.name for path in CONSOLE.glob("*.py") if "made" in _called(path))
        self.assertEqual(sorted(NOT_ASKING), own)

    def test_an_exception_asks_nothing(self) -> None:
        for name in NOT_ASKING:
            with self.subTest(name=name):
                self.assertNotIn("opened", _called(CONSOLE / name))

    def test_only_a_run_or_a_required_answer_blocks_escape(self) -> None:
        blocking = {path.name: len(_persistent(path)) for path in sorted(CONSOLE.glob("*.py"))
                    if path.name != FRAME and _persistent(path)}
        self.assertEqual(PERSISTENT, blocking)

    def test_a_typed_token_or_code_is_not_lost_to_a_click_outside(self) -> None:
        loses = {path.name: lines for path in sorted(CONSOLE.glob("*.py"))
                 if (lines := _secret_dialogs_that_close_on_a_click(path))}
        self.assertEqual({}, loses)

    def test_no_dialog_is_persistent_whatever_happens(self) -> None:
        always = sorted(path.name for path in CONSOLE.glob("*.py")
                        for one in _persistent(path)
                        if isinstance(one, ast.keyword) and isinstance(one.value, ast.Constant)
                        and one.value.value is True)
        self.assertEqual([], always)


if __name__ == "__main__":
    unittest.main()
