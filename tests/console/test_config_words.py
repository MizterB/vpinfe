"""What a settings row says about where its value came from.

The program's file is 98% untouched keys, so most of what this surface shows is a value
nobody chose. Saying that in the wire's word - `unset` - would put a term on screen that
nobody outside this project uses, and putting it on almost every row would say nothing
either way.
"""

from __future__ import annotations

import unittest

from common.i18n import t
from console import app_settings, workbench


class _Bool:
    type = "bool"
    choices = ()
    default = "1"
    key = "Backglass.ShowGrill"


class _Choice:
    type = "choice"
    choices = (("0", "Disabled"), ("1", "Floating"))
    default = "0"
    key = "Backglass.BackglassOutput"


class ValueWordTests(unittest.TestCase):
    def test_a_switch_reads_on_and_off_rather_than_one_and_zero(self) -> None:
        self.assertEqual(workbench._said_value(_Bool, "1"), "On")
        self.assertEqual(workbench._said_value(_Bool, "0"), "Off")

    def test_a_choice_reads_its_own_label(self) -> None:
        self.assertEqual(workbench._said_value(_Choice, "1"), "Floating")

    def test_a_value_with_no_label_is_shown_as_it_is(self) -> None:
        self.assertEqual(workbench._said_value(_Choice, "7"), "7")


class ClearHintTests(unittest.TestCase):
    def test_clearing_names_the_value_it_goes_back_to_and_whose(self) -> None:
        """So nobody has to change a value to find out what it was following."""
        said = workbench._clear_hint(
            {"fallback_scope": "launcher", "fallback": "0"}, _Bool, "Visual Pinball X")

        self.assertEqual(said, "Back to Off - All Tables")

    def test_whose_is_said_in_the_scope_words(self) -> None:
        said = workbench._clear_hint(
            {"fallback_scope": "folder", "fallback": "1"}, _Choice, "Visual Pinball X")

        self.assertEqual(said, "Back to Floating - This Game")

    def test_with_nothing_under_it_the_program_answers(self) -> None:
        self.assertEqual(workbench._clear_hint({}, _Bool, "Visual Pinball X"),
                         "Back to On - Visual Pinball X's default")

    def test_a_default_with_no_value_names_only_whose(self) -> None:
        class _Text:
            type = "text"
            choices = ()
            default = ""

        self.assertEqual(workbench._clear_hint({}, _Text, "Visual Pinball X"),
                         "Back to Visual Pinball X's default")


class SwitchedOffTests(unittest.TestCase):
    ONE = {"launcher_id": "a", "app": "vpx", "enabled": True, "display_name": "Wide"}
    TWO = {"launcher_id": "b", "app": "vpx", "enabled": True, "display_name": "Narrow"}

    def test_it_names_where_the_tables_go(self) -> None:
        self.assertEqual(workbench._switched_off_goes_to(self.ONE, [self.ONE, self.TWO]),
                         "Narrow")

    def test_nothing_is_said_where_nothing_could_take_them(self) -> None:
        other_app = dict(self.TWO, app="fp")
        switched_off = dict(self.TWO, enabled=False)
        for held in ([self.ONE], [self.ONE, other_app], [self.ONE, switched_off]):
            with self.subTest(held=held):
                self.assertEqual(workbench._switched_off_goes_to(self.ONE, held), "")


class MarkTests(unittest.TestCase):
    def test_a_value_nobody_has_touched_is_not_marked(self) -> None:
        """Unmarked is the untouched one, so a mark always means somebody did
        something. On 98% of rows a mark would say nothing."""
        self.assertIsNone(workbench._config_mark(
            {"set_here": False, "in_effect": True, "scope": ""}, "launcher"))

    def test_a_value_set_at_this_scope_says_so(self) -> None:
        self.assertIsNotNone(workbench._config_mark(
            {"set_here": True, "in_effect": True, "scope": "launcher"}, "launcher"))

    def test_a_value_from_another_layer_names_that_layer(self) -> None:
        self.assertIn("folder", workbench.CAME_FROM["folder"].lower())
        self.assertIsNotNone(workbench._config_mark(
            {"set_here": False, "in_effect": True, "scope": "folder"}, "entry"))

    def test_a_shadowed_value_is_the_loud_one(self) -> None:
        """Somebody wrote it and another layer answers over it. Invisible on the row
        otherwise, and the bug report we would get."""
        mark = workbench._config_mark(
            {"set_here": True, "in_effect": False, "scope": "launcher"}, "folder")

        self.assertIsNotNone(mark)

    def test_no_word_on_screen_is_the_wire_s(self) -> None:
        said = " ".join(workbench.CAME_FROM.values()).lower()

        self.assertNotIn("unset", said)
        self.assertNotIn("scope", said)


class ScopeWordTests(unittest.TestCase):
    """Where an edit goes and where a value came from, in one set of words."""

    def test_the_picker_says_what_the_marks_say(self) -> None:
        self.assertEqual(app_settings.scope_words(1),
                         {scope: t(key) for scope, key in workbench.CAME_FROM.items()})

    def test_they_are_the_three_a_person_says(self) -> None:
        self.assertEqual(sorted(app_settings.scope_words(1).values()),
                         ["All Tables", "This Game", "This Table"])

    def test_a_game_of_several_tables_says_how_many(self) -> None:
        self.assertEqual(app_settings.scope_words(3)[app_settings.SCOPE_FOLDER],
                         "This Game - 3 tables")


if __name__ == "__main__":
    unittest.main()
