"""One control grammar, and what is allowed to sit outside it.

The Console had two answers to "what control does this type want": `settings.control_for`
for a config option, and a copy of it in the themes page for a theme's own options. Two
answers drift the moment either gains a type, which is what these pin.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from console import panel, settings, themes


class ThemeOptionsUseTheSharedGrammar(unittest.TestCase):
    """A theme's settings are settings, drawn the way every other setting is."""

    def test_every_declared_type_maps_onto_a_control(self) -> None:
        cases = {
            "boolean": "bool",
            "number": "number",
            "select": "choice",
            "textarea": "text",
            "json": "text",
            "": "text",
            "something-new": "text",
        }
        for declared, expected in cases.items():
            with self.subTest(declared=declared):
                found = themes._as_option({"key": "k", "type": declared,
                                           "options": ["a", "b"]})
                self.assertEqual(found["type"], expected)

    def test_a_number_keeps_its_bounds_and_its_fraction(self) -> None:
        """`int` was the nearest existing type and it is the wrong one: a theme declares
        scale factors, and formatting one as a whole number shows a value that is not
        the one stored."""
        found = themes._as_option({"key": "k", "type": "number", "min": 0.5, "max": 2,
                                   "step": 0.1})

        self.assertEqual(found["type"], "number")
        self.assertEqual((found["min"], found["max"], found["step"]), (0.5, 2, 0.1))

    def test_choices_reach_the_control_as_a_mapping(self) -> None:
        """A theme names its choices `{value: label}`. Flattened to a list, the stored
        value goes on screen where the label belongs."""
        found = themes._as_option({
            "key": "k", "type": "select",
            "options": [{"value": "hi", "label": "High"}, {"value": "lo", "label": "Low"}]})

        self.assertEqual(found["choices"], {"hi": "High", "lo": "Low"})


class WhatTheDialogHolds(unittest.TestCase):
    """Nothing is written until Save, so editing a control changes the dialog's own
    pending values. Driven here because a synthetic click on a Quasar control does not
    reach the server, so a browser cannot answer this one."""

    def setUp(self) -> None:
        self.captured: dict = {}
        self.real = panel.switch

        def fake(value, on_change, **kw):
            self.captured["value"] = value
            self.captured["on_change"] = on_change
            return lambda: None

        settings.panel.switch = fake

    def tearDown(self) -> None:
        settings.panel.switch = self.real

    def test_changing_a_control_changes_the_pending_value(self) -> None:
        wanted = {"k": False}

        rows = themes._rows([{"key": "k", "name": "Start", "type": "boolean"}], wanted)

        self.assertEqual(rows[0][0], "Start")
        self.assertIs(self.captured["value"], False)
        self.captured["on_change"](SimpleNamespace(value=True))
        self.assertEqual(wanted, {"k": True})

    def test_json_is_parsed_where_it_is_typed(self) -> None:
        """While the dialog is open and beside the field that has it, rather than as a
        string the theme's own code cannot read."""
        wanted: dict = {"k": None}
        save = themes._saver({"key": "k", "type": "json"}, wanted)

        self.assertTrue(save('{"a": 1}'))
        self.assertEqual(wanted["k"], {"a": 1})
        self.assertFalse(save("{not json"))
        self.assertEqual(wanted["k"], {"a": 1}, "a refused value must not be stored")
        self.assertTrue(save("  "))
        self.assertIsNone(wanted["k"])

    def test_a_json_value_reaches_the_field_as_json(self) -> None:
        """A field handed an object renders Python's idea of it - single quotes and
        all - which is not what the theme would read back."""
        shown = themes._shown({"key": "k", "type": "json"}, {"k": {"a": 1}})

        self.assertIn('"a"', shown)


if __name__ == "__main__":
    unittest.main()
