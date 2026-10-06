"""When a saved change reaches what it governs, and the helpers that act on it as it is saved."""

from __future__ import annotations

import threading
import unittest
from pathlib import Path
from unittest import mock

from common import config_schema, config_service, events
from common.host import launch_state, peripherals, real_dmd
from common.i18n import t
from console import panel
from console import settings as settings_page


class Store:
    """Enough ConfigStore for the service: typed reads, staged writes, one save."""

    def __init__(self) -> None:
        self.written: dict[tuple[str, str], object] = {}

    def value(self, section, key):
        entry = config_schema.option(section, key)
        return self.written.get((section, key), entry.default if entry else "")

    def set_value(self, section, key, value):
        self.written[(section, key)] = value

    def save(self) -> None:
        pass


def _applies(section: str, key: str) -> str:
    option = config_schema.option(section, key)
    assert option is not None, f"{section}.{key}"
    return option.applies


class DeclaredTests(unittest.TestCase):
    def test_every_setting_declares_a_known_moment(self) -> None:
        for option in config_schema.CONFIG_OPTIONS:
            with self.subTest(option=f"{option.section}.{option.key}"):
                self.assertIn(option.applies, config_schema.APPLIES)

    def test_a_setting_read_when_something_starts_says_which(self) -> None:
        expected = {
            "restart": [("network", "http_port"), ("network", "ws_port"),
                        ("logger", "level"), ("install", "language"),
                        ("behavior", "startup_collection"), ("commands", "on_vpinfe_start"),
                        ("updates", "refresh_minutes"),
                        ("windows.backglass", "screen_id"), ("themes", "active")],
            "windows": [("windows.playfield", "screen_id"), ("windows.backglass", "override"),
                        ("chromium", "path"), ("presentation", "cab_mode"),
                        ("behavior", "splashscreen"), ("media", "wheelset"),
                        ("input", "select")],
            "table": [("table_commands", "on_start"), ("table_commands", "on_exit")],
            "now": [("dof", "enabled"), ("real_dmd", "enabled"), ("behavior", "confirm"),
                    ("commands", "timeout"), ("commands", "on_vpinfe_exit"),
                    ("presentation", "real_dmd_media_priority")],
        }
        for applies, keys in expected.items():
            for section, key in keys:
                with self.subTest(setting=f"{section}.{key}"):
                    self.assertEqual(_applies(section, key), applies)

    def test_a_screen_for_a_window_that_may_not_exist_yet_waits_for_a_restart(self) -> None:
        """A window gets its API at startup, and only if it had a screen then."""
        self.assertEqual(config_schema.window_screen("topper").applies, "restart")

    def test_the_schema_serves_it(self) -> None:
        described = {(o["section"], o["key"]): o["applies"]
                     for s in config_service.schema()["sections"] for o in s["options"]}

        self.assertEqual(described[("network", "http_port")], "restart")
        self.assertEqual(described[("table_commands", "on_start")], "table")
        self.assertEqual(described[("dof", "enabled")], "now")

    def test_a_description_does_not_say_when_the_setting_takes_effect(self) -> None:
        for option in config_schema.CONFIG_OPTIONS:
            said = option.description.lower()
            with self.subTest(option=f"{option.section}.{option.key}"):
                self.assertNotIn("takes effect", said)
                self.assertNotIn("after a restart", said)


class SettingsChangedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = Store()
        self.heard: list[dict] = []
        events.clear()
        self.addCleanup(events.clear)
        events.subscribe(events.SETTINGS_CHANGED, lambda **payload: self.heard.append(payload))
        patched = mock.patch.object(config_service, "get_ini_config", lambda: self.store)
        patched.start()
        self.addCleanup(patched.stop)

    def test_a_save_announces_the_keys_it_changed_and_the_store(self) -> None:
        config_service.set_values({"dof": {"enabled": True}, "logger": {"terminal": False}})

        [payload] = self.heard
        self.assertEqual(sorted(payload["keys"]), ["dof.enabled", "logger.terminal"])
        self.assertIs(payload["ini_config"], self.store)

    def test_a_key_saved_at_the_value_it_has_is_not_announced(self) -> None:
        config_service.set_values({"dof": {"enabled": True}})
        self.heard.clear()

        config_service.set_values({"dof": {"enabled": True}, "real_dmd": {"enabled": True}})

        [payload] = self.heard
        self.assertEqual(payload["keys"], ["real_dmd.enabled"])

    def test_a_save_that_changes_nothing_announces_nothing(self) -> None:
        config_service.set_values({"logger": {"terminal": "true"}})

        self.assertEqual(self.heard, [])

    def test_a_refused_save_announces_nothing(self) -> None:
        with self.assertRaises(config_service.UnknownSettingsError):
            config_service.set_values({"dof": {"enabled": True}, "x": {"y": "z"}})

        self.assertEqual(self.heard, [])


class PeripheralSettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        events.clear()
        peripherals.reset_for_tests()
        self.addCleanup(events.clear)
        self.addCleanup(peripherals.reset_for_tests)
        self.calls: list[tuple[str, object]] = []
        for name, label in (("restart_dof_service_if_enabled", "dof"),
                            ("restart_libdmdutil_service_if_enabled", "dmd")):
            patched = mock.patch.object(
                peripherals, name,
                side_effect=lambda cfg, label=label: self.calls.append((label, cfg)))
            patched.start()
            self.addCleanup(patched.stop)
        patched = mock.patch.object(real_dmd.RealDmdUpdater, "show_again",
                                    lambda one: self.calls.append(("art", one)))
        patched.start()
        self.addCleanup(patched.stop)
        peripherals._realdmd_updater = real_dmd.RealDmdUpdater(
            object(), "t", lambda *_: True)  # type: ignore[arg-type]
        patched = mock.patch.object(launch_state, "current",
                                    lambda: launch_state.LaunchState(launching=self.playing))
        patched.start()
        self.addCleanup(patched.stop)
        self.playing = False

    def test_a_dof_setting_restarts_dof_alone(self) -> None:
        peripherals.apply_settings(["dof.enabled"], "store")

        self.assertEqual(self.calls, [("dof", "store")])

    def test_a_real_dmd_setting_restarts_the_panel_and_puts_the_table_back_on_it(self) -> None:
        peripherals.apply_settings(["real_dmd.zedmd_serial_port"], "store")

        self.assertEqual([label for label, _ in self.calls], ["dmd", "art"])
        self.assertEqual(self.calls[0], ("dmd", "store"))

    def test_a_panel_nobody_has_shown_art_on_has_nothing_to_put_back(self) -> None:
        peripherals._realdmd_updater = None

        peripherals.apply_settings(["real_dmd.enabled"], "store")

        self.assertEqual(self.calls, [("dmd", "store")])

    def test_the_dof_key_the_helper_does_not_read_restarts_nothing(self) -> None:
        peripherals.apply_settings(["dof.config_tool_api_key"], "store")

        self.assertEqual(self.calls, [])

    def test_nothing_restarts_while_a_table_plays(self) -> None:
        """VPX holds the hardware; `reacquire_after_exit` starts both again afterwards."""
        self.playing = True

        peripherals.apply_settings(["dof.enabled", "real_dmd.enabled"], "store")

        self.assertEqual(self.calls, [])

    def test_other_settings_touch_neither_helper(self) -> None:
        peripherals.apply_settings(["logger.level", "behavior.confirm"], "store")

        self.assertEqual(self.calls, [])

    def test_a_save_reaches_the_helpers_through_the_bus_off_the_saving_thread(self) -> None:
        ran: list[str] = []
        done = threading.Event()

        def restart(cfg):
            ran.append(threading.current_thread().name)
            done.set()

        peripherals.register()
        with mock.patch.object(peripherals, "restart_dof_service_if_enabled", restart):
            events.emit(events.SETTINGS_CHANGED, keys=["dof.enabled"], ini_config="store")
            self.assertTrue(done.wait(5))

        self.assertEqual(ran, ["peripherals-settings"])

    def test_a_save_touching_neither_peripheral_starts_no_thread(self) -> None:
        with mock.patch.object(threading, "Thread") as thread:
            peripherals.on_settings_changed(keys=["logger.level"], ini_config="store")

        thread.assert_not_called()


class RealDmdShowAgainTests(unittest.TestCase):
    def _updater(self) -> tuple[real_dmd.RealDmdUpdater, list[Path | None]]:
        shown: list[Path | None] = []
        done = threading.Event()

        def show(_config, image) -> bool:
            shown.append(image)
            done.set()
            return True

        updater = real_dmd.RealDmdUpdater(object(), "t", show)  # type: ignore[arg-type]
        updater.done = done  # type: ignore[attr-defined]
        return updater, shown

    def test_the_last_image_is_sent_again(self) -> None:
        updater, shown = self._updater()
        updater.queue_image_update("Game", Path("/art/game.png"))
        self.assertTrue(updater.done.wait(5))  # type: ignore[attr-defined]
        updater.done.clear()  # type: ignore[attr-defined]

        updater.show_again()
        self.assertTrue(updater.done.wait(5))  # type: ignore[attr-defined]

        self.assertEqual(shown, [Path("/art/game.png")] * 2)

    def test_nothing_is_sent_before_a_table_has_been_selected(self) -> None:
        updater, shown = self._updater()

        updater.show_again()

        self.assertEqual(shown, [])


class HelpLineTests(unittest.TestCase):
    def _line(self, **option) -> str:
        base = {"key": "x", "type": "string", "default": "", "description": ""}
        with mock.patch.object(panel, "note", side_effect=lambda text: text):
            _, note = settings_page._noted({**base, **option}, "", mock.Mock(), "")
        return note or ""

    def test_a_setting_that_applies_now_says_nothing_more(self) -> None:
        self.assertEqual(self._line(description="What it does", applies="now"),
                         "What it does")

    def test_a_setting_read_at_startup_says_so_after_what_it_does(self) -> None:
        self.assertEqual(
            self._line(description="What it does", applies="restart"),
            t("console.settings.described_default", description="What it does",
              default=t("console.settings.applies.restart")))

    def test_a_setting_with_no_description_says_only_when(self) -> None:
        for applies in ("restart", "windows", "table"):
            with self.subTest(applies=applies):
                self.assertEqual(self._line(applies=applies),
                                 t(f"console.settings.applies.{applies}"))

    def test_the_language_note_says_when_too(self) -> None:
        language = config_schema.option("install", "language")
        assert language is not None

        said = settings_page.with_when(language.description, language.applies)

        self.assertTrue(said.endswith(t("console.settings.applies.restart")))
        self.assertTrue(said.startswith(language.description))

    def test_a_wait_the_page_has_said_is_left_off_the_row(self) -> None:
        said = self._line(description="What it does", applies="windows")
        with mock.patch.object(panel, "note", side_effect=lambda text: text):
            _, note = settings_page._noted(
                {"key": "x", "type": "string", "default": "", "description": "What it does",
                 "applies": "windows"}, "", mock.Mock(), "", True)

        self.assertIn(t("console.settings.applies.windows"), said)
        self.assertEqual(note, "What it does")

    def test_the_three_moments_are_worded(self) -> None:
        self.assertEqual(t("console.settings.applies.restart"),
                         "Takes effect after VPinFE restarts")
        self.assertEqual(t("console.settings.applies.windows"),
                         "Takes effect when the windows reopen")
        self.assertEqual(t("console.settings.applies.table"),
                         "Takes effect the next time a table starts")


class PageWaitsTests(unittest.TestCase):
    """A page whose settings all wait for the same thing says it once, in its head."""

    def _waits(self, page: str) -> str:
        schema = config_service.schema()["sections"]
        sections = next(one[3] for _group, pages in settings_page.DEVICE_INDEX
                        for one in pages if one[0] == page)
        return settings_page.page_waits(schema, settings_page._with_windows(sections, schema))

    def test_a_page_of_settings_that_all_wait_says_what_for(self) -> None:
        for page, waits in (("frontend.chromium", "windows"), ("hardware.input", "windows"),
                            ("vpinfe.network", "restart"), ("vpinfe.logger", "restart"),
                            ("frontend.table_commands", "table")):
            with self.subTest(page=page):
                self.assertEqual(self._waits(page), waits)

    def test_a_page_whose_settings_differ_says_nothing(self) -> None:
        for page in ("hardware.displays", "frontend.behavior", "library.updates"):
            with self.subTest(page=page):
                self.assertEqual(self._waits(page), "")

    def test_a_page_of_settings_that_apply_now_says_nothing(self) -> None:
        self.assertEqual(self._waits("vpinfe.console"), "")

    def test_the_head_says_it_after_what_the_page_is_for(self) -> None:
        with mock.patch.object(panel, "header") as header:
            settings_page.page_head("frontend.chromium", waits="windows")

        note = header.call_args.args[1]
        self.assertTrue(note.startswith(t("console.settings.note_chromium")))
        self.assertTrue(note.endswith(t("console.settings.applies_once.windows")))

    def test_a_page_with_no_note_of_its_own_has_only_the_wait(self) -> None:
        with mock.patch.object(panel, "header") as header:
            settings_page.page_head("vpinfe.network", waits="restart")

        self.assertEqual(header.call_args.args[1], t("console.settings.applies_once.restart"))

    def test_every_wait_is_worded(self) -> None:
        for waits in config_schema.APPLIES:
            if waits == config_schema.APPLIES_NOW:
                continue
            with self.subTest(waits=waits):
                key = f"console.settings.applies_once.{waits}"
                self.assertNotEqual(t(key), key)
