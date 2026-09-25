"""Which sections a launcher's rail offers, and when.

Offering a settings editor for a program that is not on this machine is a form of
lying: there is nothing to read it out of and nothing a write could mean. Details
stays, because pointing the launcher somewhere else is how it gets fixed.
"""

from __future__ import annotations

import asyncio
import unittest
from collections import Counter
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock, patch
from urllib.parse import parse_qs

from common import path_checks
from common.i18n import t
from console import app_settings, data, deeplink, games, page, panel, renderers, settings, workbench


def _launcher(state: str, *, has_config: bool = True) -> dict:
    return {"app_name": "Visual Pinball X", "has_config": has_config,
            "fields": [{"key": "bin_path", "path": "exe"}],
            "checks": {"bin_path": {"state": state}}}


def _context(state: str, groups=("displays",), *, has_config: bool = True) -> dict:
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

        self.assertIn("launcher_displays", shown)
        self.assertIn("launcher_details", shown)
        self.assertIn("launcher_backups", shown)

    def test_every_setting_is_in_all_settings_after_the_areas(self) -> None:
        shown = _shown(_context(path_checks.OK, groups=("displays", "plugins", "more")))

        self.assertEqual(shown, ["launcher_details", "launcher_displays", "launcher_plugins",
                                 "launcher_all", "launcher_backups"])

    def test_a_program_that_is_not_there_leaves_only_what_can_fix_it(self) -> None:
        shown = _shown(_context(path_checks.MISSING))

        self.assertEqual(shown, ["launcher_details", "launcher_backups"])

    def test_a_group_the_app_does_not_declare_is_absent_rather_than_empty(self) -> None:
        """An install without the plugin architecture shows fewer sections, not empty
        ones - and that follows from what the app answered rather than a version test."""
        shown = _shown(_context(path_checks.OK, groups=("displays",)))

        self.assertNotIn("launcher_plugins", shown)
        self.assertNotIn("launcher_sound", shown)

    def test_a_group_declared_with_nothing_in_it_is_also_absent(self) -> None:
        context = _context(path_checks.OK)
        context["config_groups"] = [SimpleNamespace(key="displays", label="Displays",
                                                    settings=[])]

        self.assertNotIn("launcher_displays", _shown(context))

    def test_an_app_with_no_settings_of_its_own_offers_no_copies(self) -> None:
        shown = _shown(_context(path_checks.OK, groups=(), has_config=False))

        self.assertEqual(shown, ["launcher_details"])


def _setting(key: str, label: str = "", *, default: str = "",
             description: str = "") -> SimpleNamespace:
    return SimpleNamespace(key=key, label=label or key.rsplit(".", 1)[-1],
                           default=default, description=description, help="")


def _group(key: str, *settings: SimpleNamespace, curated=(),
           summarized: bool = False) -> SimpleNamespace:
    return SimpleNamespace(key=key, label=key.title(), settings=list(settings),
                           curated=list(curated), summarized=summarized)


class AllSettingsTests(unittest.TestCase):
    GROUPS = [
        _group("displays", _setting("Player.PlayfieldFullScreen", "Display Mode"),
               _setting("Backglass.BackglassOutput", "Output Mode", default="0")),
        _group("plugins", _setting("Plugin.PinMAME.Enable", "Enable"),
               _setting("Plugin.PinMAME.PinMAMEPath", "PinMAME Path",
                        description="Where the ROMs live")),
        _group("more", _setting("Player.BallTrail", "Ball Trail", default="1"),
               _setting("DMD.Profile1Legacy", "Legacy")),
    ]

    def _found(self, values: dict | None = None, **wanted) -> list[tuple[str, list[str]]]:
        return [(section, [f.key for f in fields]) for section, fields in
                workbench.found_settings(self.GROUPS, values or {}, wanted)]

    def test_everything_under_its_section_in_the_order_the_areas_reach_it(self) -> None:
        self.assertEqual(self._found(), [
            ("Player", ["Player.PlayfieldFullScreen", "Player.BallTrail"]),
            ("Backglass", ["Backglass.BackglassOutput"]),
            ("Plugin.PinMAME", ["Plugin.PinMAME.Enable", "Plugin.PinMAME.PinMAMEPath"]),
            ("DMD", ["DMD.Profile1Legacy"]),
        ])

    def test_the_key_typed_from_the_file_finds_its_row(self) -> None:
        self.assertEqual(self._found(query="fullscreen"),
                         [("Player", ["Player.PlayfieldFullScreen"])])

    def test_every_word_has_to_be_somewhere_in_label_key_or_description(self) -> None:
        self.assertEqual(self._found(query="pinmame roms"),
                         [("Plugin.PinMAME", ["Plugin.PinMAME.PinMAMEPath"])])
        self.assertEqual(self._found(query="pinmame trail"), [])

    def test_one_area(self) -> None:
        self.assertEqual(self._found(area="more"), [
            ("Player", ["Player.BallTrail"]), ("DMD", ["DMD.Profile1Legacy"])])

    def test_set_here_is_what_this_launcher_s_file_holds(self) -> None:
        values = {"Player.BallTrail": {"value": "1", "set_here": True},
                  "Backglass.BackglassOutput": {"value": "1", "set_here": False}}

        self.assertEqual(self._found(values, set_here=True),
                         [("Player", ["Player.BallTrail"])])

    def test_different_from_default_is_about_the_value_not_where_it_is_set(self) -> None:
        values = {"Player.BallTrail": {"value": "1.0", "set_here": True},
                  "Backglass.BackglassOutput": {"value": "1", "set_here": False},
                  "Player.PlayfieldFullScreen": {"value": "", "set_here": False}}

        self.assertEqual(self._found(values, differs=True),
                         [("Backglass", ["Backglass.BackglassOutput"])])

    def test_a_section_reads_as_words(self) -> None:
        self.assertEqual(workbench.section_title("ScoreView", {}), "Score View")
        self.assertEqual(workbench.section_title("DMD", {}), "DMD")

    def test_a_plugin_takes_the_name_its_area_gives_it(self) -> None:
        names = workbench._plugin_names([_group("plugins", curated=[
            SimpleNamespace(key="PUP", label="Pin Up Player",
                            keys=("Plugin.PUP.Enable",)),
            SimpleNamespace(key="playfield", label="Playfield", keys=("Player.PlaySound",)),
        ])])

        self.assertEqual(names, {"PUP": "Pin Up Player"})
        self.assertEqual(workbench.section_title("Plugin.PUP", names),
                         t("console.workbench.plugin_section", name="Pin Up Player"))
        self.assertEqual(workbench.section_title("Plugin.HelloWorld", names),
                         t("console.workbench.plugin_section", name="Hello World"))


def _heading(key: str, *keys: str, enabled_by: str = "",
             rivals: tuple[str, ...] = (), label: str = "") -> SimpleNamespace:
    return SimpleNamespace(key=key, label=label or key.title(), note="", keys=keys,
                           enabled_by=enabled_by, rivals=rivals)


class ConflictTests(unittest.TestCase):
    RENDERERS = [_group(
        "plugins",
        _setting("Plugin.B2S.Enable", "Enable", default="1"),
        _setting("Plugin.B2SLegacy.Enable", "Enable", default="0"),
        _setting("Plugin.DOF.Enable", "Enable", default="1"),
        curated=[_heading("B2S", "Plugin.B2S.Enable", enabled_by="Plugin.B2S.Enable",
                          rivals=("Plugin.B2SLegacy.Enable",)),
                 _heading("B2SLegacy", "Plugin.B2SLegacy.Enable", label="B2S Legacy",
                          enabled_by="Plugin.B2SLegacy.Enable",
                          rivals=("Plugin.B2S.Enable",)),
                 _heading("DOF", "Plugin.DOF.Enable", enabled_by="Plugin.DOF.Enable")])]

    def test_two_rivals_on_each_name_the_other(self) -> None:
        both = workbench.conflicts(self.RENDERERS, {"Plugin.B2SLegacy.Enable": {"value": "1"}})

        self.assertEqual(both, {"Plugin.B2S.Enable": "B2S Legacy",
                                "Plugin.B2SLegacy.Enable": "B2S"})

    def test_a_rival_off_is_no_conflict(self) -> None:
        self.assertEqual(workbench.conflicts(self.RENDERERS, {}), {})
        self.assertEqual(workbench.conflicts(self.RENDERERS, {
            "Plugin.B2S.Enable": {"value": "0"},
            "Plugin.B2SLegacy.Enable": {"value": "1"}}), {})

    def test_either_switch_redraws_the_other(self) -> None:
        self.assertEqual(workbench.rival_switches(self.RENDERERS),
                         {"Plugin.B2S.Enable", "Plugin.B2SLegacy.Enable"})

    def test_rivals_travel_with_their_heading(self) -> None:
        groups = data.config_groups({"groups": [{
            "key": "plugins", "label": "Plugins", "settings": [], "curated": [
                {"key": "B2S", "label": "B2S", "keys": ["Plugin.B2S.Enable"],
                 "enabled_by": "Plugin.B2S.Enable", "rivals": ["Plugin.B2SLegacy.Enable"]},
                {"key": "DOF", "label": "DOF", "keys": ["Plugin.DOF.Enable"]}]}]})

        self.assertEqual([h.rivals for h in groups[0].curated],
                         [("Plugin.B2SLegacy.Enable",), ()])


class CuratedAreaTests(unittest.TestCase):
    PLUGINS = _group(
        "plugins",
        _setting("Plugin.PinMAME.Enable", "Enable", default="0"),
        _setting("Plugin.PinMAME.PinMAMEPath", "PinMAME Path"),
        _setting("Plugin.PinMAME.Cheat", "Cheat"),
        _setting("Plugin.DOF.Enable", "Enable", default="1"),
        curated=[_heading("PinMAME", "Plugin.PinMAME.Enable", "Plugin.PinMAME.PinMAMEPath",
                          enabled_by="Plugin.PinMAME.Enable"),
                 _heading("DOF", "Plugin.DOF.Enable", enabled_by="Plugin.DOF.Enable"),
                 _heading("Serum", "Plugin.Serum.Enable", enabled_by="Plugin.Serum.Enable")])

    def _drawn(self, values: dict) -> list[tuple[str, list[str]]]:
        return [(heading.key, [f.key for f in fields])
                for heading, fields in workbench.curated_blocks(self.PLUGINS, values)]

    def test_a_switch_that_is_off_draws_alone(self) -> None:
        self.assertEqual(self._drawn({}), [("PinMAME", ["Plugin.PinMAME.Enable"]),
                                           ("DOF", ["Plugin.DOF.Enable"])])

    def test_switched_on_its_rows_follow_it_in_the_heading_s_order(self) -> None:
        drawn = self._drawn({"Plugin.PinMAME.Enable": {"value": "1"}})

        self.assertEqual(drawn[0], ("PinMAME", ["Plugin.PinMAME.Enable",
                                                "Plugin.PinMAME.PinMAMEPath"]))

    def test_a_value_turned_off_over_a_default_of_on_hides_the_rest(self) -> None:
        group = _group("plugins", _setting("Plugin.B2S.Enable", default="1"),
                       _setting("Plugin.B2S.ShowGrill"),
                       curated=[_heading("B2S", "Plugin.B2S.Enable", "Plugin.B2S.ShowGrill",
                                         enabled_by="Plugin.B2S.Enable")])

        on = workbench.curated_blocks(group, {})
        off = workbench.curated_blocks(group, {"Plugin.B2S.Enable": {"value": "0"}})

        self.assertEqual([f.key for f in on[0][1]], ["Plugin.B2S.Enable",
                                                     "Plugin.B2S.ShowGrill"])
        self.assertEqual([f.key for f in off[0][1]], ["Plugin.B2S.Enable"])

    def test_a_heading_whose_settings_the_file_does_not_have_is_left_out(self) -> None:
        self.assertNotIn("Serum", [key for key, _ in self._drawn({})])

    def test_a_heading_vpinfe_says_nothing_about_has_the_program_s_line(self) -> None:
        groups = data.config_groups({"groups": [{
            "key": "plugins", "label": "Plugins", "settings": [], "curated": [
                {"key": "WMP", "label": "WMP", "note": "", "description": "WMP audio",
                 "keys": ["Plugin.WMP.Enable"]},
                {"key": "DOF", "label": "DOF", "note": "Drives toys",
                 "description": "Direct Output Framework", "keys": ["Plugin.DOF.Enable"]}]}]})

        self.assertEqual([h.note for h in groups[0].curated], ["WMP audio", "Drives toys"])

    def test_a_row_a_switch_hides_is_still_curated_and_not_one_of_the_rest(self) -> None:
        self.assertEqual(workbench.curated_keys(self.PLUGINS),
                         {"Plugin.PinMAME.Enable", "Plugin.PinMAME.PinMAMEPath",
                          "Plugin.DOF.Enable"})


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
        self.assertIn("rewrites this file", t(workbench.PLAYING_WHY))


class BlankValueTests(unittest.TestCase):
    def _placeholder(self, option: dict) -> str:
        with patch.object(settings.panel, "number") as number:
            settings.control_for(option, settings.value_for(option, ""), lambda _v: True)
        return number.call_args.kwargs.get("placeholder", "")

    def test_a_blank_its_app_works_out_says_so_in_the_control(self) -> None:
        field = SimpleNamespace(key="Player.PlayfieldWidth", type="int", label="Width",
                                default="", choices=(), blank="From the screen")

        self.assertEqual(self._placeholder(workbench._as_option(field)), "From the screen")

    def test_a_choice_s_blank_is_an_option_named_by_it(self) -> None:
        field = SimpleNamespace(key="TableOverride.ViewCabMode", type="int",
                                label="View mode", default="", blank="The table's own",
                                choices=(("0", "Legacy"), ("2", "Window")),
                                choice_help={"2": "The screen as a window"})

        option = workbench._as_option(field)

        self.assertEqual(option["choices"],
                         {"": "The table's own", "0": "Legacy", "2": "Window"})
        self.assertEqual(option["describes"], {"Window": "The screen as a window"})

    def test_a_field_as_the_wire_sends_it_says_so_too(self) -> None:
        field = {"key": "Player.PlayfieldWidth", "type": "int", "label": "Width",
                 "default": "", "blank": "From the screen"}

        self.assertEqual(self._placeholder(dict(field)), "From the screen")


class ColorControlTests(unittest.TestCase):
    OPTION = {"key": "Alpha.Profile4Color", "type": "color", "label": "Color",
              "default": "#FF2315"}

    def test_a_color_is_a_swatch_of_itself_that_saves_what_is_picked(self) -> None:
        save = Mock()
        with patch.object(settings.panel, "swatch") as swatch:
            settings.control_for(self.OPTION, "#E34236", save)

        self.assertEqual(swatch.call_args.args, ("#E34236", save))
        self.assertFalse(swatch.call_args.kwargs["disabled"])

    def test_a_color_that_cannot_be_written_here_cannot_be_picked(self) -> None:
        with patch.object(settings.panel, "swatch") as swatch:
            settings.control_for(self.OPTION, "#E34236", lambda _v: True, writable=False)

        self.assertTrue(swatch.call_args.kwargs["disabled"])


class NamedNumberTests(unittest.TestCase):
    FIELD = SimpleNamespace(key="Player.MaxFramerate", type="number", label="Limit Framerate",
                            default="-1.0", choices=(),
                            named=(("-1", "Match the Display"), ("0", "No Limit")))

    def test_a_number_with_named_values_picks_among_them(self) -> None:
        save = Mock()
        option = workbench._as_option(self.FIELD)
        with patch.object(settings.panel, "named_number") as named:
            settings.control_for(option, settings.value_for(option, ""), save)

        self.assertEqual(named.call_args.args,
                         (-1.0, {"-1": "Match the Display", "0": "No Limit"}, save))
        self.assertFalse(named.call_args.kwargs["whole"])

    def test_a_stored_value_is_named_by_its_number_not_its_spelling(self) -> None:
        named = dict(self.FIELD.named)

        self.assertEqual([panel.named_as(one, named) for one in (-1.0, "-1", "0.0", 0)],
                         ["-1", "-1", "0", "0"])

    def test_any_other_value_is_custom(self) -> None:
        named = dict(self.FIELD.named)

        self.assertEqual([panel.named_as(one, named) for one in (60.0, "", None, "x")],
                         ["", "", "", ""])


class TableSettingsTitleTests(unittest.TestCase):
    """Every setting at one table, in the dialog Show Every Setting opens."""

    def test_it_is_titled_for_the_table_not_the_launcher(self) -> None:
        said = app_settings.title_for("Medieval Madness", "VPW 1.2", "Visual Pinball X", 1)

        self.assertEqual(said, "Medieval Madness: Visual Pinball X Settings")

    def test_a_game_of_several_tables_says_which(self) -> None:
        said = app_settings.title_for("Medieval Madness", "VPW 1.2", "Visual Pinball X", 2)

        self.assertEqual(said, "Medieval Madness - VPW 1.2: Visual Pinball X Settings")

    def test_a_file_shared_with_the_game_says_who_else_reads_it(self) -> None:
        note = app_settings.shared_note({"shared_with_game": True}, 3)

        self.assertIsNotNone(note)
        self.assertIn("the other 2 tables", _said(note))

    def test_nothing_is_said_where_the_file_is_the_table_s_alone(self) -> None:
        self.assertIsNone(app_settings.shared_note({"shared_with_game": False}, 3))

    def test_nor_where_the_game_has_no_other_table(self) -> None:
        self.assertIsNone(app_settings.shared_note({"shared_with_game": True}, 1))


class TableRailTests(unittest.TestCase):
    def test_a_table_s_settings_follow_the_table(self) -> None:
        keys = [s.key for s in workbench.sections_for("table")]

        self.assertEqual(keys[keys.index("table_details") + 1], "table_settings")

    def test_a_game_has_none(self) -> None:
        self.assertNotIn("table_settings", [s.key for s in workbench.sections_for("game")])


class LaunchReportTests(unittest.TestCase):
    """The Launch group's one line about the launcher, which leads to Settings."""

    TABLE = {"launcher_name": "Visual Pinball X", "launcher_app_configurable": True}

    def _report(self, **table: object) -> tuple[str, str]:
        context = {"state": {"view": "games", "game": "g1", "table": "t1"}}
        with patch.object(workbench.panel, "link") as link:
            label, _draw = workbench._launcher_report(context, {**self.TABLE, **table})
        self.assertEqual(label, "Launcher")
        return str(link.call_args.args[0]), str(link.call_args.kwargs["to"])

    def test_its_own_settings_are_counted(self) -> None:
        self.assertEqual(self._report(launcher_settings_here=3)[0],
                         "Visual Pinball X · 3 settings of its own")

    def test_one_is_said_as_one(self) -> None:
        self.assertEqual(self._report(launcher_settings_here=1)[0],
                         "Visual Pinball X · 1 setting of its own")

    def test_values_the_game_s_file_gives_it_are_counted(self) -> None:
        self.assertEqual(self._report(launcher_settings_from_folder=2)[0],
                         "Visual Pinball X · 2 settings from This Game")

    def test_with_none_it_is_the_launcher_alone(self) -> None:
        self.assertEqual(self._report()[0], "Visual Pinball X")

    def test_a_program_that_keeps_no_settings_counts_none(self) -> None:
        self.assertEqual(self._report(launcher_app_configurable=False,
                                      launcher_settings_here=3)[0], "Visual Pinball X")

    def test_it_leads_to_the_table_s_settings(self) -> None:
        address = parse_qs(self._report()[1].split("?", 1)[1])

        self.assertEqual(address["section"], ["table_settings"])
        self.assertEqual(address["table"], ["t1"])


class SettingsColumnTests(unittest.TestCase):
    """The Tables grid's Settings column, which says of every table what Launch says of
    one."""

    ROW = {"id": "t", "launcher_name": "Visual Pinball X", "launcher_app_configurable": True}

    def _cell(self, **row: object) -> tuple[str, str, int]:
        (built,) = games.table_rows([{**self.ROW, **row}])
        return built["settings"], built["settings_said"], built["settings_count"]

    def test_a_camera_alone_is_named(self) -> None:
        self.assertEqual(self._cell(launcher_settings_here=1, launcher_point_of_view=True),
                         ("point_of_view", "Point of View", 1))

    def test_beside_other_settings_it_counts_as_one(self) -> None:
        self.assertEqual(self._cell(launcher_settings_here=3, launcher_point_of_view=True),
                         ("own", "3 of its own", 3))

    def test_one_is_said_as_one(self) -> None:
        self.assertEqual(self._cell(launcher_settings_here=1), ("own", "1 of its own", 1))

    def test_values_from_the_game_s_file_say_so(self) -> None:
        self.assertEqual(self._cell(launcher_settings_from_folder=2),
                         ("from_game", "2 from This Game", 2))

    def test_a_table_as_all_tables_play_is_blank(self) -> None:
        self.assertEqual(self._cell(), ("", "", 0))

    def test_a_program_that_keeps_no_settings_counts_none(self) -> None:
        self.assertEqual(self._cell(launcher_app_configurable=False,
                                    launcher_settings_here=3), ("", "", 0))

    def test_its_filter_offers_each_kind_a_cell_holds(self) -> None:
        column = next(one for one in games.TABLE_COLUMNS if one["field"] == "settings")
        choices = column["filterParams"]["choices"]

        self.assertEqual([one["value"] for one in choices],
                         ["own", "point_of_view", "from_game", ""])
        self.assertEqual(choices[0]["label"], "Has Settings of Its Own")

    def test_the_launch_view_shows_it_after_the_launcher(self) -> None:
        shown = games.TABLE_VIEWS["console.game_tables.launch"].columns

        self.assertEqual(shown[shown.index("launcher") + 1], "settings")

    def test_focusing_it_opens_the_table_s_settings(self) -> None:
        section = games.TABLE_COLUMN_SECTIONS["settings"]

        self.assertIn(section, [s.key for s in workbench.sections_for("table")])


def _field(key: str, label: str = "", *, per_table: bool = False,
           scopes: tuple[str, ...] = ("entry",)) -> SimpleNamespace:
    return SimpleNamespace(key=key, label=label or key.rsplit(".", 1)[-1], type="text",
                           default="", description="", choices=(), scopes=scopes,
                           per_table=per_table)


class DifferencesTests(unittest.TestCase):
    """What a table's Settings list under the program: its differences and nothing else."""

    SET = {"set_here": True, "in_effect": True, "scope": "entry", "value": "1"}
    GAME = {"set_here": False, "in_effect": True, "scope": "folder", "value": "1"}
    ALL = {"set_here": False, "in_effect": True, "scope": "launcher", "value": "1"}

    def test_only_its_own_values_and_the_game_s_are_listed(self) -> None:
        groups = [_group("sound", _field("Player.A"), _field("Player.B"),
                         _field("Player.C"), _field("Player.D"))]
        values = {"Player.A": self.SET, "Player.B": self.GAME, "Player.C": self.ALL}

        found = app_settings.differences(groups, values)

        self.assertEqual([(area, [f.key for f in fields]) for area, fields in found],
                         [("Sound", ["Player.A", "Player.B"])])

    def test_an_area_s_curated_rows_come_first(self) -> None:
        fields = [_field("Player.A"), _field("Player.B"), _field("Player.C")]
        curated = (SimpleNamespace(key="", label="", keys=("Player.C", "Player.B")),)
        values = {key: self.SET for key in ("Player.A", "Player.B", "Player.C")}

        found = app_settings.differences([_group("sound", *fields, curated=curated)], values)

        self.assertEqual([f.key for f in found[0][1]], ["Player.C", "Player.B", "Player.A"])

    def test_a_plugin_s_row_leads_with_the_plugin_s_name(self) -> None:
        enable = _field("Plugin.B2SLegacy.Enable", "Enable")
        curated = (SimpleNamespace(key="B2SLegacy", label="B2S Legacy",
                                   keys=("Plugin.B2SLegacy.Enable",)),)

        found = app_settings.differences([_group("plugins", enable, curated=curated)],
                                         {enable.key: self.SET})

        self.assertEqual(found[0][1][0].label, "B2S Legacy: Enable")

    DISPLAYS = _group(
        "displays",
        _field("Player.PlayfieldFullScreen", "Display Mode"),
        _field("Player.PlayfieldWidth", "Width"),
        _field("Backglass.BackglassFullScreen", "Display Mode"),
        _field("Backglass.BackglassWidth", "Width"),
        _field("Backglass.BackglassFSWidth", "Width"),
        _field("Player.BGSet", "View Mode"),
        curated=(SimpleNamespace(key="playfield", label="Playfield",
                                 keys=("Player.PlayfieldFullScreen", "Player.PlayfieldWidth")),
                 SimpleNamespace(key="backglass", label="Backglass",
                                 keys=("Backglass.BackglassFullScreen",
                                       "Backglass.BackglassWidth")),
                 SimpleNamespace(key="cabinet", label="Cabinet", keys=("Player.BGSet",))))

    def _labels(self, *keys: str) -> list[str]:
        found = app_settings.differences([self.DISPLAYS], dict.fromkeys(keys, self.SET))
        return [field.label for field in found[0][1]]

    def test_a_row_several_windows_share_names_its_window(self) -> None:
        """Even alone: under Displays, Display Mode on its own says nothing about which
        window."""
        self.assertEqual(self._labels("Backglass.BackglassFullScreen"),
                         ["Backglass Display Mode"])

    def test_a_label_nothing_else_in_the_area_shares_is_the_program_s(self) -> None:
        self.assertEqual(self._labels("Player.BGSet"), ["View Mode"])

    def test_a_window_s_row_it_does_not_curate_goes_with_its_window(self) -> None:
        self.assertEqual(self._labels("Backglass.BackglassFSWidth"), ["Backglass Width"])

    def test_the_camera_is_not_listed_setting_by_setting(self) -> None:
        view = _field("TableOverride.ViewCabMode")

        self.assertEqual(app_settings.differences(
            [_group("point_of_view", view, summarized=True)], {view.key: self.SET}), [])


class PointOfViewTests(unittest.TestCase):
    MODE = _field("TableOverride.ViewCabMode", "View mode")
    DESKTOP_MODE = _field("TableOverride.ViewDTMode", "View mode")
    CAB = _field("TableOverride.ViewCabPlayerX")
    DESKTOP = _field("TableOverride.ViewDTPlayerX")
    GROUP = SimpleNamespace(
        key="point_of_view", label="Point of View", summarized=True, read_only=False,
        settings=[MODE, DESKTOP_MODE, CAB, DESKTOP], rows=(MODE.key, DESKTOP_MODE.key),
        curated=[SimpleNamespace(key="cabinet", label="Cabinet", keys=(MODE.key, CAB.key)),
                 SimpleNamespace(key="desktop", label="Desktop",
                                 keys=(DESKTOP_MODE.key, DESKTOP.key))])

    def _view(self, **values: dict) -> SimpleNamespace | None:
        return app_settings.point_of_view([self.GROUP], values)

    def test_its_rows_are_each_named_by_their_view(self) -> None:
        view = self._view(**{self.CAB.key: DifferencesTests.SET})

        self.assertEqual([row.label for row in view.rows],
                         ["Cabinet View mode", "Desktop View mode"])

    def test_the_camera_is_named_by_the_views_it_is_saved_in(self) -> None:
        view = self._view(**{self.CAB.key: DifferencesTests.SET})

        self.assertEqual((view.views, view.own), (["Cabinet"], [self.CAB.key]))
        self.assertEqual(app_settings.camera_said(view), "Saved for this table (Cabinet)")

    def test_one_from_the_game_says_so_and_is_not_the_table_s_to_reset(self) -> None:
        view = self._view(**{self.DESKTOP.key: DifferencesTests.GAME})

        self.assertEqual(view.own, [])
        self.assertEqual(app_settings.camera_said(view), "Saved for this game (Desktop)")

    def test_a_view_mode_alone_leaves_the_camera_the_table_s_own(self) -> None:
        view = self._view(**{self.MODE.key: DifferencesTests.SET})

        self.assertEqual((view.views, view.own, view.reaching), ([], [], False))
        self.assertEqual(app_settings.camera_said(view), "The table's own")

    def test_and_absent_when_nothing_in_it_differs(self) -> None:
        self.assertIsNone(self._view(**{self.CAB.key: DifferencesTests.ALL}))

    def test_reset_takes_the_camera_off_and_leaves_the_view_modes(self) -> None:
        view = self._view(**{self.CAB.key: DifferencesTests.SET,
                             self.MODE.key: DifferencesTests.SET})
        remove = Mock()

        with patch.object(app_settings.panel, "action") as action:
            entries = app_settings._camera_entries(view, remove, playing=False)
        action.call_args.args[1]()

        self.assertIn(app_settings.panel.ASIDE, [label for label, _draw in entries])
        remove.assert_called_once_with([self.CAB.key])

    def test_no_reset_where_the_table_does_not_hold_it(self) -> None:
        view = self._view(**{self.DESKTOP.key: DifferencesTests.GAME})

        with patch.object(app_settings.panel, "action") as action:
            app_settings._camera_entries(view, Mock(), playing=False)

        action.assert_not_called()


class TableOptionsTests(unittest.TestCase):
    SPEED = _field("TableOption.Ball_Speed", "Ball Speed")
    LIGHTS = _field("TableOption.Lights", "Lights")
    GROUP = SimpleNamespace(key="table_options", label="Table Options", summarized=False,
                            read_only=True, settings=[SPEED, LIGHTS], curated=[], rows=())

    def _resets(self, values: dict) -> list[str]:
        options = app_settings.table_options([self.GROUP], values)
        with patch.object(app_settings.panel, "action") as action:
            app_settings._option_entries(options, values, Mock(), playing=False)
        return [call.args[0] for call in action.call_args_list]

    def test_each_one_the_table_holds_has_reset_and_two_have_reset_all(self) -> None:
        values = {self.SPEED.key: DifferencesTests.SET, self.LIGHTS.key: DifferencesTests.SET}

        self.assertEqual(self._resets(values), ["Reset", "Reset", "Reset All"])

    def test_one_alone_has_no_reset_all(self) -> None:
        self.assertEqual(self._resets({self.SPEED.key: DifferencesTests.SET}), ["Reset"])

    def test_they_are_not_listed_among_the_differences(self) -> None:
        values = {self.SPEED.key: DifferencesTests.SET}

        self.assertEqual(app_settings.differences([self.GROUP], values), [])

    def test_and_absent_without_one(self) -> None:
        self.assertIsNone(app_settings.table_options([self.GROUP], {}))


class AddASettingTests(unittest.TestCase):
    SET = DifferencesTests.SET
    SOUND = _group("sound", _field("Player.A"), _field("Player.B", per_table=True))
    GRAPHICS = _group("graphics", _field("Player.C", per_table=True), _field("Player.D"))

    def _offered(self, groups, values=None, added=()) -> list[tuple[str, str]]:
        return [(str(field.label), area)
                for field, area in app_settings.addable(groups, values or {}, added)]

    def test_those_commonly_set_per_table_come_first_each_with_its_area(self) -> None:
        self.assertEqual(self._offered([self.SOUND, self.GRAPHICS]),
                         [("B", "Sound"), ("C", "Graphics"), ("A", "Sound"),
                          ("D", "Graphics")])

    def test_one_the_table_already_shows_is_not_offered(self) -> None:
        offered = self._offered([self.SOUND, self.GRAPHICS],
                                {"Player.A": self.SET, "Player.B": DifferencesTests.GAME},
                                added=["Player.C"])

        self.assertEqual(offered, [("D", "Graphics")])

    def test_one_kept_for_all_tables_alone_is_not_offered(self) -> None:
        group = _group("sound", _field("Player.A"),
                       _field("Player.ShowFPS", scopes=("launcher",)))

        self.assertEqual(self._offered([group]), [("A", "Sound")])

    def test_nor_are_the_table_s_options(self) -> None:
        self.assertEqual(self._offered([TableOptionsTests.GROUP]), [])

    def test_of_the_point_of_view_only_the_view_modes_it_draws(self) -> None:
        group = SimpleNamespace(**{**vars(PointOfViewTests.GROUP),
                                   "rows": (PointOfViewTests.MODE.key,)})

        self.assertEqual(self._offered([group]), [("Cabinet View mode", "Point of View")])

    def test_and_none_of_it_once_its_rows_are_drawn(self) -> None:
        values = {PointOfViewTests.CAB.key: self.SET}

        self.assertEqual(self._offered([PointOfViewTests.GROUP], values), [])

    def test_an_added_setting_is_listed_among_the_differences(self) -> None:
        found = app_settings.differences([self.SOUND], {}, added=["Player.B"])

        self.assertEqual([(area, [f.key for f in fields]) for area, fields in found],
                         [("Sound", ["Player.B"])])

    def test_an_added_view_mode_draws_the_point_of_view(self) -> None:
        view = app_settings.point_of_view([PointOfViewTests.GROUP], {},
                                          added=[PointOfViewTests.MODE.key])

        assert view is not None
        self.assertEqual((len(view.rows), view.views, view.own), (2, [], []))

    def test_what_was_added_is_forgotten_when_another_table_is_open(self) -> None:
        state: dict[str, Any] = {}
        app_settings._added(state, "t1")
        state[app_settings.ADDED]["keys"] = ["Player.A"]

        self.assertEqual(app_settings._added(state, "t1"), ["Player.A"])
        self.assertEqual(app_settings._added(state, "t2"), [])

    def _headings(self, offered: list) -> list[str]:
        with patch.object(app_settings.panel, "SettingPicker") as picker, \
                patch.object(app_settings.ui, "run_javascript"):
            app_settings._add_picker({"state": {}}, [], offered)
        return list(picker.call_args.kwargs["headings"].values())

    def test_a_heading_starts_each_run(self) -> None:
        offered = app_settings.addable([self.SOUND, self.GRAPHICS], {}, ())

        self.assertEqual(self._headings(offered),
                         ["Commonly Set per Table", "Everything Else"])

    def test_and_none_where_nothing_is_commonly_set_per_table(self) -> None:
        offered = app_settings.addable([_group("sound", _field("Player.A"))], {}, ())

        self.assertEqual(self._headings(offered), [])


def _other(table_id: str, value: str = "1", *, scope: str = "entry",
           shares: bool = False) -> dict:
    return {"table": {"id": table_id}, "launcher_id": "l1", "shares": shares,
            "reads_game": scope == "folder",
            "values": {"Player.X": {"value": value, "scope": scope}}}


class _Game:
    """The game's tables as the API answers for them. A write lands in the written
    table's own file, and where that file is also the game's, in what the tables reading
    it get."""

    def __init__(self, *others: dict) -> None:
        self.held = {one["table"]["id"]: dict(one) for one in others}
        self.written: list[str] = []

    def launcher_config(self, _launcher: str, table: str, _scope: str) -> dict:
        one = self.held[table]
        return {"values": one["values"], "shared_with_game": one["shares"]}

    def write_launcher_config(self, _launcher: str, values: dict, *, table: str,
                              scope: str) -> dict:
        self.written.append(f"{table}@{scope}")
        self.held[table]["values"] = {"Player.X": {"value": values["Player.X"],
                                                   "scope": "entry"}}
        if self.held[table]["shares"]:
            for one in self.held.values():
                if one["values"]["Player.X"]["scope"] == "folder":
                    one["values"] = {"Player.X": {"value": values["Player.X"],
                                                  "scope": "folder"}}
        return {}


class SetForAllTests(unittest.TestCase):
    """Set for All N Tables, beside a value one of a game's tables sets itself."""

    SET = {"set_here": True, "in_effect": True, "scope": "entry", "value": "2"}
    FIELD = _field("Player.X")

    def _verb(self, *others: dict, offered=frozenset({"Player.X"})):
        return app_settings._for_all({"playing": False}, list(others), False, [], offered)

    def test_it_is_offered_where_another_table_does_not_use_the_value(self) -> None:
        self.assertIsNotNone(self._verb(_other("b", "2"), _other("c", "1"))(
            self.SET, self.FIELD))

    def test_and_not_where_every_other_table_does(self) -> None:
        self.assertIsNone(self._verb(_other("b", "2"))(self.SET, self.FIELD))

    def test_nor_beside_a_value_the_table_does_not_set_itself(self) -> None:
        held = {**self.SET, "set_here": False, "scope": "launcher"}

        self.assertIsNone(self._verb(_other("b", "1"))(held, self.FIELD))

    def test_nor_on_the_camera(self) -> None:
        camera = _field("TableOverride.ViewCabFOV")

        self.assertIsNone(self._verb(_other("b", "1"))(self.SET, camera))

    def test_the_camera_and_the_table_options_are_one_table_s_own(self) -> None:
        view = SimpleNamespace(summarized=True, rows=["TableOverride.ViewCabMode"],
                               settings=[_field("TableOverride.ViewCabMode"),
                                         _field("TableOverride.ViewCabFOV")])
        options = SimpleNamespace(summarized=False, read_only=True,
                                  settings=[_field("TableOption.Volume")])
        sound = SimpleNamespace(summarized=False, settings=[
            _field("Player.X"), _field("Player.Stereo3D", scopes=("launcher",))])

        self.assertEqual(app_settings._for_every_table([sound, view, options]),
                         {"Player.X", "TableOverride.ViewCabMode"})

    def test_a_table_reading_this_table_s_file_uses_what_it_sets(self) -> None:
        other = _other("b", "1", scope="folder")

        self.assertTrue(app_settings.already_uses(other, self.FIELD, "2", True))
        self.assertFalse(app_settings.already_uses(other, self.FIELD, "2", False))

    def test_each_table_not_using_it_gets_it_in_its_own_file(self) -> None:
        game = _Game(_other("b", "1"), _other("c", "2"))

        cut = app_settings.write_for_all(game, [_other("b", "1"), _other("c", "2")],
                                         self.FIELD, "2", False)

        self.assertEqual((game.written, cut), (["b@entry"], []))

    def test_the_table_whose_file_is_the_game_s_goes_first(self) -> None:
        """So a table reading that file has the value from it, not a file of its own."""
        others = [_other("b", "1", scope="folder"), _other("a", "1", shares=True)]
        game = _Game(*others)

        cut = app_settings.write_for_all(game, others, self.FIELD, "2", False)

        self.assertEqual((game.written, cut), (["a@entry"], []))

    def test_a_table_that_stops_reading_the_game_s_file_is_named(self) -> None:
        others = [_other("b", "1", scope="folder")]

        cut = app_settings.write_for_all(_Game(*others), others, self.FIELD, "2", False)

        self.assertEqual(cut, [{"id": "b"}])

    def test_a_row_draws_it_beside_clear(self) -> None:
        verb = Mock()
        more = Mock(return_value=verb)
        with patch.object(workbench, "ui"), \
                patch.object(workbench.panel, "action", return_value=Mock()):
            workbench._beside(lambda: None, dict(self.SET), self.FIELD, Mock(), "VPX",
                              more=more)()

        more.assert_called_once()
        verb.assert_called_once_with()


class CopyFromGameTests(unittest.IsolatedAsyncioTestCase):
    """Where a table's own file keeps the game's from reaching it."""

    REACH = {"Player.X": "1", "Player.Y": "2"}

    def test_it_says_how_many_do_not_reach_the_table(self) -> None:
        entries = app_settings._from_game_entries({"playing": False}, self.REACH)

        self.assertEqual(_said(entries[0]), "2 of this game's settings do not reach "
                                            "this table, which has its own file")

    async def test_copying_writes_them_at_the_table_s_own_scope(self) -> None:
        inner = {"library": Mock(), "launcher": {"launcher_id": "l1"},
                 "config_table": "t1", "rebuild": AsyncMock()}
        io = self.enterContext(patch.object(app_settings.offload, "io",
                                            new=AsyncMock(return_value={})))
        self.enterContext(patch.object(app_settings, "ui"))

        await app_settings._copy_from_game(inner, self.REACH)

        io.assert_awaited_once_with(inner["library"].write_launcher_config, "l1",
                                    self.REACH, table="t1", scope="entry")
        inner["rebuild"].assert_awaited_once()


class RedrawTests(unittest.TestCase):
    """Whether a write can be marked in place or the panel has to be drawn again."""

    GAME_CAMERA = {"TableOverride.ViewCabFOV": {"value": "30", "scope": "folder"},
                   "Player.SoundVolume": {"value": "40", "scope": "folder"}}

    def test_a_write_that_changes_only_itself_is_marked_in_place(self) -> None:
        after = {**self.GAME_CAMERA, "Player.SoundVolume": {"value": "45", "scope": "entry"}}

        self.assertFalse(workbench._moved(self.GAME_CAMERA, after, "Player.SoundVolume"))

    def test_a_table_s_first_file_takes_the_game_s_values_off_every_setting(self) -> None:
        """The camera is not a row, and it stops reaching the table all the same."""
        after = {"TableOverride.ViewCabFOV": {"value": "", "scope": ""},
                 "Player.SoundVolume": {"value": "45", "scope": "entry"}}

        self.assertTrue(workbench._moved(self.GAME_CAMERA, after, "Player.SoundVolume"))


class TypedRedrawTests(unittest.IsolatedAsyncioTestCase):
    """A number writes on every key, so the redraw its first write calls for waits until
    focus leaves it: drawn between two keys, the second has nowhere to go."""

    AFTER = {"TableOverride.ViewCabFOV": {"value": "", "scope": ""},
             "Player.SoundVolume": {"value": "4", "scope": "entry"},
             "Player.PlayMusic": {"value": "1", "scope": ""}}

    async def _drawn(self, kind: str) -> tuple[list, AsyncMock, Any, Any]:
        key = "Player.SoundVolume" if kind == "int" else "Player.PlayMusic"
        field = SimpleNamespace(key=key, type=kind, label="Row", default="", choices=(),
                                blank="", scopes=("launcher", "entry"), help="",
                                description="")
        rebuild = AsyncMock()
        context = {"library": Mock(), "launcher": {"launcher_id": "probe"},
                   "config_scope": "entry", "config_table": "table", "rebuild": rebuild}
        values = AsyncMock(side_effect=[dict(RedrawTests.GAME_CAMERA), dict(self.AFTER)])
        ui = self.enterContext(patch.object(workbench, "ui"))
        self.enterContext(patch.object(workbench, "_config_values", new=values))
        self.enterContext(patch.object(workbench.run, "io_bound",
                                       new=AsyncMock(return_value={})))
        control_for = self.enterContext(patch.object(workbench.settings_page, "control_for"))
        entries = await workbench._setting_entries(context, [("", "", [field])])
        return entries, rebuild, control_for.call_args.args[2], ui

    async def test_a_number_is_drawn_again_once_focus_leaves_it(self) -> None:
        entries, rebuild, save, ui = await self._drawn("int")
        entries[0][1]()
        row = ui.row.return_value.classes.return_value.__enter__.return_value
        event, leave = row.on.call_args.args

        await save(4)
        await asyncio.sleep(0)
        rebuild.assert_not_awaited()
        await leave()

        self.assertEqual(event, "focusout")
        rebuild.assert_awaited_once()

    async def test_a_number_s_writes_land_in_the_order_it_was_typed(self) -> None:
        landed: list[str] = []

        async def slower_first(_write, _launcher, values, **_kw) -> dict:
            said = values["Player.SoundVolume"]
            await asyncio.sleep(0.03 / len(said))
            landed.append(said)
            return {}

        _, _, save, _ = await self._drawn("int")
        with patch.object(workbench.run, "io_bound", new=slower_first):
            await asyncio.gather(save(4), save(40), save(409))

        self.assertEqual(landed, ["4", "40", "409"])

    async def test_a_switch_is_drawn_again_at_once(self) -> None:
        _, rebuild, save, _ = await self._drawn("bool")

        await save(True)
        await asyncio.sleep(0)

        rebuild.assert_awaited_once()


class GridBehindTests(unittest.IsolatedAsyncioTestCase):
    """The grid behind a table counts the settings it has of its own, and a write marked
    in place puts its row right where that count moved."""

    async def _saved_after(self, before: dict, after: dict) -> AsyncMock:
        field = SimpleNamespace(key="Player.PlayMusic", type="bool", label="Row", default="",
                                choices=(), blank="", scopes=("launcher", "entry"), help="",
                                description="")
        saved, rebuild = AsyncMock(), AsyncMock()
        context = {"library": Mock(), "launcher": {"launcher_id": "probe"},
                   "config_scope": "entry", "config_table": "table",
                   "rebuild": rebuild, "saved": saved}
        self.enterContext(patch.object(workbench, "ui"))
        self.enterContext(patch.object(workbench, "_config_values",
                                       new=AsyncMock(side_effect=[before, after])))
        self.enterContext(patch.object(workbench.run, "io_bound",
                                       new=AsyncMock(return_value={})))
        control_for = self.enterContext(patch.object(workbench.settings_page, "control_for"))
        await workbench._setting_entries(context, [("", "", [field])])

        await control_for.call_args.args[2](True)
        await asyncio.sleep(0)

        rebuild.assert_not_awaited()
        return saved

    async def test_a_setting_that_becomes_the_table_s_own(self) -> None:
        saved = await self._saved_after(
            {"Player.PlayMusic": {"value": "0", "scope": ""}},
            {"Player.PlayMusic": {"value": "1", "scope": "entry"}})

        saved.assert_awaited_once()

    async def test_one_that_stops_being_it(self) -> None:
        saved = await self._saved_after(
            {"Player.PlayMusic": {"value": "0", "scope": "entry"}},
            {"Player.PlayMusic": {"value": "1", "scope": "launcher"}})

        saved.assert_awaited_once()

    async def test_a_value_changed_where_the_table_already_sets_it_leaves_the_row(
            self) -> None:
        saved = await self._saved_after(
            {"Player.PlayMusic": {"value": "0", "scope": "entry"}},
            {"Player.PlayMusic": {"value": "1", "scope": "entry"}})

        saved.assert_not_awaited()


class TableWriteReadsAgainTests(unittest.TestCase):
    """Each table the Console read carries how many settings it has of its own."""

    def _library(self) -> tuple[data.Library, Mock]:
        client = Mock()
        client.all_tables.return_value = []
        client.tables.return_value = []
        library = data.Library(client)
        library.load_tables()
        library.tables_for("game")
        return library, client

    def test_a_write_at_a_table_reads_them_again(self) -> None:
        library, client = self._library()

        library.write_launcher_config("probe", {"Player.PlayMusic": "1"}, table="t1",
                                      scope="entry")
        library.load_tables()
        library.tables_for("game")

        self.assertEqual(2, client.all_tables.call_count)
        self.assertEqual(2, client.tables.call_count)

    def test_a_write_for_all_tables_does_not(self) -> None:
        library, client = self._library()

        library.write_launcher_config("probe", {"Player.PlayMusic": "1"})
        library.load_tables()
        library.tables_for("game")

        self.assertEqual(1, client.all_tables.call_count)
        self.assertEqual(1, client.tables.call_count)


def _said(entry) -> str:
    with patch("console.panel.ui") as ui:
        entry[1]()
    return str(ui.label.call_args.args[0])


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

    def test_the_tables_grid_carries_a_launcher_and_a_setting(self) -> None:
        address = parse_qs(deeplink.query({"view": "tables", "launcher": "vpx",
                                           "sets": "Player.PlayMusic"}))

        self.assertEqual((address["launcher"], address["sets"]),
                         (["vpx"], ["Player.PlayMusic"]))

    def test_a_setting_is_read_back_as_written(self) -> None:
        state: dict = {"view": "tables"}

        deeplink.apply(state, {"view": "tables", "launcher": "vpx",
                               "sets": "Player.PlayMusic"}, views=["tables"], sections=[])

        self.assertEqual((state["launcher"], state["sets"]), ("vpx", "Player.PlayMusic"))

    def test_a_setting_is_noise_anywhere_else(self) -> None:
        address = parse_qs(deeplink.query({"view": "games", "sets": "Player.PlayMusic"}))

        self.assertNotIn("sets", address)

    def test_leaving_the_grid_lets_go_of_a_setting(self) -> None:
        state = {"view": "tables", "sets": "Player.PlayMusic", "game": "", "table": ""}

        with patch.object(page.remembered, "put"):
            page.leave_for(state, "games")

        self.assertFalse(state["sets"])


class OwnSettingsColumnTests(unittest.TestCase):
    """Which settings a table sets differently, and the grid arriving on the tables of one
    launcher that set one."""

    ROW = {"id": "t", "launcher": "vpx", "launcher_name": "Visual Pinball X",
           "launcher_app_configurable": True}

    def _own(self, **row: object) -> list[str]:
        (built,) = games.table_rows([{**self.ROW, **row}])
        return built[games.OWN_SETTINGS_COLUMN]

    def test_a_row_holds_the_settings_by_key(self) -> None:
        self.assertEqual(self._own(launcher_settings_keys=["Player.PlayMusic"]),
                         ["Player.PlayMusic"])

    def test_a_program_that_keeps_no_settings_holds_none(self) -> None:
        self.assertEqual(self._own(launcher_app_configurable=False,
                                   launcher_settings_keys=["Player.PlayMusic"]), [])

    def test_it_is_a_list_column_named_by_setting_in_no_view(self) -> None:
        column = next(one for one in games.TABLE_COLUMNS
                      if one["field"] == games.OWN_SETTINGS_COLUMN)

        self.assertEqual(column["filterParams"]["looks"], renderers.SETTING_LOOKS)
        self.assertIn(renderers.SETTING_LOOKS, renderers.LOOKS)
        for name, preset in games.TABLE_VIEWS.items():
            with self.subTest(view=name):
                self.assertNotIn(games.OWN_SETTINGS_COLUMN,
                                 getattr(preset, "columns", preset))

    def test_an_address_arrives_on_the_launcher_s_tables_that_set_it(self) -> None:
        self.assertEqual(
            games.setting_their_own([self.ROW], "vpx", "Player.PlayMusic"),
            {"launcher": {"filterType": "text", "operator": "OR", "conditions": [
                {"filterType": "text", "type": "equals", "filter": "Visual Pinball X"},
                {"filterType": "text", "type": "equals",
                 "filter": f"{games.SET_HERE_MARK}Visual Pinball X"}]},
             games.OWN_SETTINGS_COLUMN: {"values": ["Player.PlayMusic"]}})

    def test_one_naming_no_launcher_a_table_uses_or_no_setting_asks_for_nothing(
            self) -> None:
        for launcher, key in (("other", "Player.PlayMusic"), ("vpx", ""),
                              ("", "Player.PlayMusic")):
            with self.subTest(launcher=launcher, key=key):
                self.assertIsNone(games.setting_their_own([self.ROW], launcher, key))


class SettingNamesTests(unittest.TestCase):
    """What a setting is called on a grid, away from the area that explains it."""

    def test_a_label_no_other_setting_has_is_its_name(self) -> None:
        self.assertEqual(
            workbench.setting_names([_group("sound", _setting("Player.MusicVolume",
                                                              "Volume"))]),
            {"Player.MusicVolume": "Volume"})

    def test_a_shared_label_is_led_by_its_heading(self) -> None:
        names = workbench.setting_names([_group(
            "displays", _setting("Player.PlayfieldWidth", "Width"),
            _setting("Backglass.BackglassWidth", "Width"),
            curated=[_heading("playfield", "Player.PlayfieldWidth"),
                     _heading("backglass", "Backglass.BackglassWidth")])])

        self.assertEqual(names, {"Player.PlayfieldWidth": "Playfield Width",
                                 "Backglass.BackglassWidth": "Backglass Width"})

    def test_or_by_its_section_where_no_heading_holds_it(self) -> None:
        names = workbench.setting_names([_group(
            "displays", _setting("Player.PlayfieldWidth", "Width"),
            _setting("Backglass.BackglassWidth", "Width"))])

        self.assertEqual(names, {"Player.PlayfieldWidth": "Player Width",
                                 "Backglass.BackglassWidth": "Backglass Width"})

    def test_a_plugin_s_setting_is_led_by_its_plugin_as_a_table_s_settings_lead_it(
            self) -> None:
        names = workbench.setting_names([_group(
            "plugins", _setting("Plugin.PUP.Enable", "Enable"),
            _setting("Plugin.PUP.MainVol", "Main Volume"),
            _setting("Plugin.DOF.Enable", "Enable"),
            curated=[SimpleNamespace(key="PUP", label="Pin Up Player", note="",
                                     keys=("Plugin.PUP.Enable", "Plugin.PUP.MainVol"),
                                     enabled_by="Plugin.PUP.Enable")])])

        self.assertEqual(names, {
            "Plugin.PUP.Enable": t("console.app_settings.plugin_row",
                                   plugin="Pin Up Player", label="Enable"),
            "Plugin.PUP.MainVol": t("console.app_settings.plugin_row",
                                    plugin="Pin Up Player", label="Main Volume"),
            "Plugin.DOF.Enable": t("console.app_settings.plugin_row", plugin="DOF",
                                   label="Enable")})


class TablesSetTheirOwnTests(unittest.IsolatedAsyncioTestCase):
    """A launcher's row says how many of its tables answer over it, and goes to them."""

    async def test_it_counts_the_launcher_s_tables_by_setting(self) -> None:
        library = Mock()
        library.load_tables.return_value = [
            {"launcher": "vpx", "launcher_settings_keys": ["Player.PlayMusic", "Player.FXAA"]},
            {"launcher": "vpx", "launcher_settings_keys": ["Player.PlayMusic"]},
            {"launcher": "other", "launcher_settings_keys": ["Player.PlayMusic"]},
            {"launcher": "vpx"}]
        self.enterContext(patch.object(workbench.offload, "io",
                                       new=AsyncMock(side_effect=lambda call: call())))

        counted = await workbench._set_by_tables(
            {"library": library, "launcher": {"launcher_id": "vpx"}})

        self.assertEqual(counted, {"Player.PlayMusic": 2, "Player.FXAA": 1})

    def test_its_link_goes_to_the_tables_grid_on_them(self) -> None:
        for count, said in ((1, "1 table sets its own"), (4, "4 tables set their own")):
            with self.subTest(count=count), patch("console.panel.ui") as ui:
                workbench._tables_of_their_own({"launcher_id": "vpx"}, "Player.PlayMusic",
                                               count)()
                address = parse_qs(ui.link.call_args.kwargs["target"].split("?", 1)[1])

                self.assertEqual(ui.link.call_args.args[0], said)
                self.assertEqual(address, {"view": ["tables"], "launcher": ["vpx"],
                                           "sets": ["Player.PlayMusic"]})

    async def _beyond(self, scope: str, table: str = "") -> list[object]:
        context = {"library": Mock(), "launcher": {"launcher_id": "vpx"},
                   "config_scope": scope, "config_table": table, "rebuild": AsyncMock()}
        self.enterContext(patch.object(workbench, "ui"))
        self.enterContext(patch.object(workbench, "_config_values",
                                       new=AsyncMock(return_value={})))
        self.enterContext(patch.object(workbench.settings_page, "control_for"))
        self.counted = self.enterContext(patch.object(
            workbench, "_set_by_tables",
            new=AsyncMock(return_value=Counter({"Player.PlayMusic": 2}))))
        beside = self.enterContext(patch.object(workbench, "_beside"))
        await workbench._setting_entries(
            context, [("", "", [_field("Player.PlayMusic", scopes=("launcher", "entry")),
                                _field("Player.FXAA", scopes=("launcher", "entry"))])])
        return [call.args[8] for call in beside.call_args_list]

    async def test_a_row_for_all_tables_carries_it_where_a_table_sets_its_own(
            self) -> None:
        link, none = await self._beyond("launcher")

        self.assertIsNotNone(link)
        self.assertIsNone(none)

    async def test_a_table_s_rows_do_not_ask(self) -> None:
        self.assertEqual(await self._beyond("entry", "t1"), [None, None])
        self.counted.assert_not_awaited()


class SettingGroupsTests(unittest.TestCase):
    """The names a grid gives settings come from one read per launcher that plays a table."""

    GROUPS = {"groups": [{"key": "sound", "label": "Sound", "settings": [
        {"key": "Player.PlayMusic", "label": "Music", "type": "bool", "default": "",
         "description": ""}]}]}

    def _library(self, *answers: object) -> tuple[data.Library, Mock]:
        client = Mock()
        client.all_tables.return_value = [
            {"app": "vpx", "launcher": "a", "launcher_app_configurable": True},
            {"app": "vpx", "launcher": "b", "launcher_app_configurable": True},
            {"app": "other", "launcher": "c", "launcher_app_configurable": False}]
        client.launcher_config.side_effect = answers
        return data.Library(client), client

    def _read(self, client: Mock) -> list[str]:
        return [call.args[0] for call in client.launcher_config.call_args_list]

    def test_one_read_per_launcher_of_a_program_that_keeps_settings(self) -> None:
        library, client = self._library(self.GROUPS, self.GROUPS)

        library.load_tables()

        self.assertEqual(self._read(client), ["a", "b"])
        self.assertEqual([one.key for one in library.setting_groups()["b"]], ["sound"])

    def test_a_launcher_that_cannot_say_leaves_the_others_named(self) -> None:
        library, client = self._library(RuntimeError("gone"), self.GROUPS)

        library.load_tables()

        self.assertEqual(library.setting_groups()["a"], [])
        self.assertEqual([one.key for one in library.setting_groups()["b"]], ["sound"])

    def test_the_table_list_read_again_does_not_read_them_again(self) -> None:
        library, client = self._library(RuntimeError("gone"), self.GROUPS)
        library.load_tables()

        library.write_launcher_config("a", {"Player.PlayMusic": "1"}, table="t1",
                                      scope="entry")
        library.load_tables()

        self.assertEqual(client.all_tables.call_count, 2)
        self.assertEqual(self._read(client), ["a", "b"])


if __name__ == "__main__":
    unittest.main()
