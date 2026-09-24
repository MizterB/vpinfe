"""Which sections a launcher's rail offers, and when.

Offering a settings editor for a program that is not on this machine is a form of
lying: there is nothing to read it out of and nothing a write could mean. Setup
stays, because pointing the launcher somewhere else is how it gets fixed.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs

from common import path_checks
from common.i18n import t
from console import deeplink, page, settings, workbench


def _launcher(state: str, *, has_config: bool = True) -> dict:
    return {"app_name": "Visual Pinball X", "has_config": has_config,
            "fields": [{"key": "bin_path", "path": "exe"}],
            "checks": {"bin_path": {"state": state}}}


def _context(state: str, groups=("backglass",), *, has_config: bool = True) -> dict:
    return {
        "launcher": _launcher(state, has_config=has_config),
        "config_groups": [SimpleNamespace(key=key, label=key.title(), settings=[1])
                          for key in groups],
    }


def _shown(context: dict) -> list[str]:
    return [s.key for s in workbench.sections_for("launcher")
            if s.shown is None or s.shown(context)]


class RailTests(unittest.TestCase):
    def test_a_working_launcher_offers_the_groups_its_app_declares(self) -> None:
        shown = _shown(_context(path_checks.OK))

        self.assertIn("launcher_backglass", shown)
        self.assertIn("launcher_setup", shown)
        self.assertIn("launcher_backups", shown)

    def test_a_program_that_is_not_there_leaves_only_what_can_fix_it(self) -> None:
        shown = _shown(_context(path_checks.MISSING))

        self.assertEqual(shown, ["launcher_setup", "launcher_backups"])

    def test_a_group_the_app_does_not_declare_is_absent_rather_than_empty(self) -> None:
        """An install without the plugin architecture shows fewer sections, not empty
        ones - and that follows from what the app answered rather than a version test."""
        shown = _shown(_context(path_checks.OK, groups=("backglass",)))

        self.assertNotIn("launcher_rom", shown)
        self.assertNotIn("launcher_scoreview", shown)

    def test_a_group_declared_with_nothing_in_it_is_also_absent(self) -> None:
        context = _context(path_checks.OK)
        context["config_groups"] = [SimpleNamespace(key="backglass", label="Backglass",
                                                    settings=[])]

        self.assertNotIn("launcher_backglass", _shown(context))

    def test_an_app_with_no_settings_of_its_own_offers_no_copies(self) -> None:
        shown = _shown(_context(path_checks.OK, groups=(), has_config=False))

        self.assertEqual(shown, ["launcher_setup"])


class ProgramNoteTests(unittest.TestCase):
    def test_no_program_set_says_to_set_one(self) -> None:
        self.assertEqual(workbench._program_note(_launcher(path_checks.UNSET)),
                         t("console.workbench.set_program_see_settings",
                           app="Visual Pinball X"))

    def test_a_path_that_finds_nothing_says_so(self) -> None:
        self.assertEqual(workbench._program_note(_launcher(path_checks.MISSING)),
                         t("console.workbench.not_at_that_path", app="Visual Pinball X"))

    def test_a_program_that_is_there_needs_no_note(self) -> None:
        self.assertEqual(workbench._program_note(_launcher(path_checks.OK)), "")

    def test_an_app_with_no_settings_of_its_own_gets_none(self) -> None:
        for state in (path_checks.UNSET, path_checks.MISSING):
            with self.subTest(state=state):
                self.assertEqual(
                    workbench._program_note(_launcher(state, has_config=False)), "")


class PlayingTests(unittest.TestCase):
    def test_not_knowing_is_not_a_reason_to_refuse_to_draw(self) -> None:
        class Broken:
            def play_state(self):
                raise RuntimeError("no answer")

        self.assertFalse(workbench._playing(Broken()))

    def test_a_table_playing_is_reported(self) -> None:
        class Playing:
            def play_state(self):
                return {"launching": True}

        self.assertTrue(workbench._playing(Playing()))

    def test_the_reason_says_who_the_other_writer_is(self) -> None:
        """The program rewrites this file itself when a table exits, so an edit made now
        is one of two writers and the last one wins."""
        self.assertIn("writes this file itself", t(workbench.PLAYING_NOTE))


class BlankValueTests(unittest.TestCase):
    def _placeholder(self, option: dict) -> str:
        with patch.object(settings.panel, "number") as number:
            settings.control_for(option, settings.value_for(option, ""), lambda _v: True)
        return number.call_args.kwargs.get("placeholder", "")

    def test_a_blank_its_app_works_out_says_so_in_the_control(self) -> None:
        field = SimpleNamespace(key="Player.PlayfieldWidth", type="int", label="Width",
                                default="", choices=(), blank="From the screen")

        self.assertEqual(self._placeholder(workbench._as_option(field)), "From the screen")

    def test_the_table_dialog_s_field_says_so_too(self) -> None:
        field = {"key": "Player.PlayfieldWidth", "type": "int", "label": "Width",
                 "default": "", "blank": "From the screen"}

        self.assertEqual(self._placeholder(dict(field)), "From the screen")


class AddressTests(unittest.TestCase):
    """A reload lands on the launcher that was open, not on the empty panel."""

    def test_the_open_launcher_is_in_the_address(self) -> None:
        address = parse_qs(deeplink.query({"view": "launchers", "launcher": "second-vpx"}))

        self.assertEqual(address["launcher"], ["second-vpx"])

    def test_it_is_read_back_from_one(self) -> None:
        state: dict = {"view": "launchers"}

        deeplink.apply(state, {"view": "launchers", "launcher": "second-vpx"},
                       views=["launchers"], sections=[])

        self.assertEqual(state["launcher"], "second-vpx")

    def test_it_is_noise_anywhere_else(self) -> None:
        address = parse_qs(deeplink.query({"view": "games", "launcher": "second-vpx"}))

        self.assertNotIn("launcher", address)

    def test_leaving_the_page_lets_go_of_it(self) -> None:
        state = {"view": "launchers", "launcher": "second-vpx", "game": "", "table": ""}

        with patch.object(page.remembered, "put"):
            page.leave_for(state, "games")

        self.assertFalse(state["launcher"])


if __name__ == "__main__":
    unittest.main()
