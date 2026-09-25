"""What type each Visual Pinball setting is, and the script that reads it from the source."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType

from apps.vpx.setting_types import TYPES

ROOT = Path(__file__).resolve().parents[2]


def _script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "fetch_vpx_setting_types", ROOT / "scripts" / "fetch_vpx_setting_types.py")
    assert spec is not None and spec.loader is not None, "the generator is gone"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


script = _script()

DECLARED = """\
PropBoolBase(Player, PlaySound, "Enable Playfield"s, "Mechanical sounds, on or off"s,
   false, true);
PropBoolBase(Player, Held, "Held"s, "Kept, even at the same value"s, true, false);
PropEnum1(DefaultPropsGate, GateType, "GateType"s, ""s, GateType, GateWireW,
   "GateWireW"s, "GatePlate"s);
PropFloatStepped(Player, Rotation, "Rotation"s, ""s, 0.f, 360.f, 90.f, 0.f);
PropEnum(Player, SyncMode, "Synchronization"s,
   "No Sync: nothing waits.\\nVertical Sync: waits, "
   "for the display."s,
   int, 3, "No Sync"s, "Vertical Sync"s);
PropArray(Window, Mode, int, Enum, Int, m_propInvalid, m_propBackglass_BackglassOutput);
"""


class ParseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.types, self.contextual = script.parsed(DECLARED)

    def test_every_form_of_declaration_is_typed(self) -> None:
        self.assertEqual(self.types, {
            "Player.PlaySound": "bool",
            "Player.Held": "bool",
            "DefaultProps\\Gate.GateType": "choice",
            "Player.Rotation": "number",
            "Player.SyncMode": "choice",
        })

    def test_a_base_form_says_for_itself_whether_it_is_contextual(self) -> None:
        self.assertIn("Player.Held", self.contextual)
        self.assertNotIn("Player.PlaySound", self.contextual)

    def test_a_form_it_does_not_know_stops_the_run(self) -> None:
        with self.assertRaisesRegex(ValueError, "PropColor"):
            script.parsed('PropColor(Player, Tint, "Tint"s, ""s, 0x000000);')


class PluginTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        plugin = self.root / "pinmame"
        plugin.mkdir()
        (plugin / "plugin.cfg").write_text('[configuration]\nid = "PinMAME"\n')
        (plugin / "plugin.cpp").write_text(
            'MSGPI_STRING_VAL_SETTING(pathProp, "PinMAMEPath", "PinMAME Path",\n'
            '   "Folder that contains PinMAME subfolders", true, "", 1024);\n'
            'MSGPI_BOOL_VAL_SETTING(zeProp, "ZeDMD", "ZeDMD", "", true, false);\n'
            'MSGPI_INT_VAL_SETTING(portProp, "Port", PORT_LABEL, "", true, 0, 9, 0);\n')

    def test_each_setting_lands_in_its_plugin_s_section(self) -> None:
        types, _labels = script.from_plugins(self.root)

        self.assertEqual(types, {"Plugin.PinMAME.Enable": "bool",
                                 "Plugin.PinMAME.PinMAMEPath": "string",
                                 "Plugin.PinMAME.ZeDMD": "bool",
                                 "Plugin.PinMAME.Port": "int"})

    def test_a_label_is_kept_where_it_is_not_the_key(self) -> None:
        _types, labels = script.from_plugins(self.root)

        self.assertEqual(labels, {"Plugin.PinMAME.PinMAMEPath": "PinMAME Path"})


class CombinedTests(unittest.TestCase):
    def test_the_later_build_answers_for_a_setting_both_declare(self) -> None:
        types, contextual, _labels = script.combined([
            ({"DefaultProps\\Flasher.AddBlend": "bool", "Player.PlayMusic": "bool"},
             {"DefaultProps\\Flasher.AddBlend"}, {}),
            ({"DefaultProps\\Flasher.AddBlend": "choice"}, set(), {}),
        ])

        self.assertEqual(types, {"DefaultProps\\Flasher.AddBlend": "choice",
                                 "Player.PlayMusic": "bool"})
        self.assertEqual(contextual, set())

    def test_a_label_the_later_build_no_longer_gives_is_gone(self) -> None:
        _types, _contextual, labels = script.combined([
            ({"Plugin.B2S.ShowGrill": "bool", "Plugin.B2S.Old": "bool"}, set(),
             {"Plugin.B2S.ShowGrill": "Show Grill", "Plugin.B2S.Old": "Old Switch"}),
            ({"Plugin.B2S.ShowGrill": "bool"}, set(), {}),
        ])

        self.assertEqual(labels, {"Plugin.B2S.Old": "Old Switch"})


class MapTests(unittest.TestCase):
    def test_the_sound_switches_the_installed_build_writes_are_switches(self) -> None:
        for qualified in ("Player.PlaySound", "Player.PlayMusic", "Plugin.PinMAME.Sound"):
            with self.subTest(qualified=qualified):
                self.assertEqual(TYPES.get(qualified), "bool")


if __name__ == "__main__":
    unittest.main()
