"""Which sections a launcher's rail offers, and when.

Offering a settings editor for a program that is not on this machine is a form of
lying: there is nothing to read it out of and nothing a write could mean. Details
stays, because pointing the launcher somewhere else is how it gets fixed.
"""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock, patch
from urllib.parse import parse_qs

from common import path_checks
from common.i18n import t
from console import app_settings, deeplink, page, settings, workbench


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
                         t("console.workbench.plugin_section", name="HelloWorld"))


def _heading(key: str, *keys: str, enabled_by: str = "") -> SimpleNamespace:
    return SimpleNamespace(key=key, label=key.title(), note="", keys=keys,
                           enabled_by=enabled_by)


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

    def test_a_field_as_the_wire_sends_it_says_so_too(self) -> None:
        field = {"key": "Player.PlayfieldWidth", "type": "int", "label": "Width",
                 "default": "", "blank": "From the screen"}

        self.assertEqual(self._placeholder(dict(field)), "From the screen")


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


def _field(key: str, label: str = "") -> SimpleNamespace:
    return SimpleNamespace(key=key, label=label or key.rsplit(".", 1)[-1], type="text",
                           default="", description="", choices=(), scopes=("entry",))


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


class CameraTests(unittest.TestCase):
    VIEW = _field("TableOverride.ViewCabMode")
    GROUPS = [_group("point_of_view", VIEW, summarized=True)]

    def test_one_saved_for_the_table_is_one_row(self) -> None:
        rows = app_settings._camera(self.GROUPS, {self.VIEW.key: DifferencesTests.SET})

        self.assertEqual(rows[1], ("Camera", "Saved for this table"))
        self.assertEqual(len(rows), 2)

    def test_one_from_the_game_says_so(self) -> None:
        rows = app_settings._camera(self.GROUPS, {self.VIEW.key: DifferencesTests.GAME})

        self.assertEqual(rows[1:], [("Camera", "Saved for this game")])

    def test_and_absent_without_one(self) -> None:
        self.assertEqual(app_settings._camera(self.GROUPS, {}), [])


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

    async def test_a_switch_is_drawn_again_at_once(self) -> None:
        _, rebuild, save, _ = await self._drawn("bool")

        await save(True)
        await asyncio.sleep(0)

        rebuild.assert_awaited_once()


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


if __name__ == "__main__":
    unittest.main()
