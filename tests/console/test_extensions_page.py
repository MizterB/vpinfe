"""One extension's page in Settings, and the rows that lead to it.

What is worth pinning is that every state the host can reach is shown, by a word or by
the switch, that a switch somebody set does not read as something that broke, and that
the index marks only what is wrong or off.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

from nicegui import ui

from common import feature_checks, i18n, install_identity
from common.extensions import host
from console import ext_page, settings, wizard
from tests.support import lines


class StateWordTests(unittest.TestCase):
    def test_every_state_the_switch_cannot_show_has_a_word(self) -> None:
        """A state with no word draws no finding, so a stopped extension would look fine."""
        states = {value for name, value in vars(host).items()
                  if name.isupper() and isinstance(value, str)
                  and value in {"loaded", "failed", "disabled", "off"}}

        self.assertEqual(states - {host.LOADED, host.OFF}, set(ext_page.STATE_WORDS))

    def test_running_draws_no_finding(self) -> None:
        self.assertNotIn(host.LOADED, ext_page.STATE_WORDS)

    def test_off_draws_no_finding_beside_the_switch_that_says_it(self) -> None:
        self.assertNotIn(host.OFF, ext_page.STATE_WORDS)


RUNNING = {"name": "sample", "display_name": "Sample", "version": "1.2.0",
           "description": "Does a thing", "state": host.LOADED, "enabled": True,
           "reason": "", "reason_key": "", "actions": [], "surfaces": {}, "scopes": [],
           "capabilities": []}
SWITCHED_OFF = {**RUNNING, "state": host.OFF, "enabled": False, "reason": "Switched off",
                "reason_key": host.SWITCHED_OFF}
WAITING = {**SWITCHED_OFF, "enabled": True, "reason": "Starts at the next restart",
           "reason_key": host.STARTS_AT_RESTART}
WRONG_PLATFORM = {**RUNNING, "state": host.OFF, "reason": "It does not run on macOS",
                  "reason_key": host.WRONG_PLATFORM}
LACKS = {**RUNNING, "state": host.OFF, "reason": "It needs the frontend feature",
         "reason_key": host.LACKS_FEATURES}
BROKE = {**RUNNING, "state": host.FAILED, "reason": "It threw"}
STOPPED = {**RUNNING, "state": host.DISABLED, "reason": "It stopped answering"}


class Page:
    """One extension's page drawn, and what is on it."""

    def __init__(self, found: dict, settings_read: dict | None = None,
                 open_this_device: Any = None) -> None:
        self.redraw = mock.Mock()
        self.open_this_device = open_this_device or mock.Mock()
        with ui.column() as self.body:
            with mock.patch.object(ext_page, "ApiClient"):
                ext_page.build(found, settings_read or {}, self.redraw,
                               self.open_this_device)

    def labels(self, *classes: str) -> list[str]:
        return [one.text for one in self.body.descendants()
                if isinstance(one, ui.label) and all(c in one.classes for c in classes)]

    @property
    def headings(self) -> list[str]:
        return self.labels("console-fact-heading")

    @property
    def rows(self) -> list[str]:
        return self.labels("console-fact-label")

    @property
    def buttons(self) -> list[str]:
        return [one.text for one in self.body.descendants() if isinstance(one, ui.button)]

    @property
    def switches(self) -> list[bool]:
        return [bool(one.value) for one in self.body.descendants()
                if isinstance(one, ui.switch)]


class HeaderTests(unittest.TestCase):
    def test_the_name_is_the_display_name_with_the_version_under_it(self) -> None:
        page = Page(RUNNING)

        self.assertEqual(page.labels("console-workbench-title"), ["Sample"])
        self.assertEqual(page.labels("console-workbench-label"), ["Version 1.2.0"])

    def test_no_version_draws_no_caption(self) -> None:
        page = Page({**RUNNING, "version": ""})

        self.assertEqual(page.labels("console-workbench-label"), [])

    def test_its_description_is_under_the_name(self) -> None:
        self.assertEqual(Page(RUNNING).labels("console-panel-note"), ["Does a thing"])


class FindingTests(unittest.TestCase):
    def finding(self, found: dict) -> list[str]:
        return Page(found).labels("console-attention-line")

    def test_one_running_or_only_switched_off_says_nothing_under_its_name(self) -> None:
        self.assertEqual(self.finding(RUNNING), [])
        self.assertEqual(self.finding(SWITCHED_OFF), [])
        self.assertEqual(self.finding(WAITING), [])

    def test_one_that_broke_is_failed_and_says_why(self) -> None:
        page = Page(BROKE)

        self.assertEqual(page.labels("console-attention-line"),
                         [i18n.t("console.ext_page.failed")])
        self.assertEqual(page.labels("console-member-table"), ["It threw"])

    def test_one_that_stopped_is_stopped(self) -> None:
        self.assertEqual(self.finding(STOPPED), [i18n.t("console.ext_page.stopped")])

    def test_one_that_cannot_run_here_says_so_with_nothing_to_press(self) -> None:
        page = Page(WRONG_PLATFORM)

        self.assertEqual(page.labels("console-attention-line"),
                         [i18n.t("console.ext_page.cannot_run")])
        self.assertEqual(page.labels("console-member-table"), ["It does not run on macOS"])
        self.assertEqual(page.buttons, [])

    def test_one_missing_a_feature_offers_this_device(self) -> None:
        opened = mock.Mock()
        with mock.patch.object(ext_page.panel, "action",
                               wraps=ext_page.panel.action) as action:
            page = Page(LACKS, open_this_device=opened)

        self.assertEqual(page.buttons, [i18n.t("console.ext_page.open_device")])
        action.call_args.args[1]()
        opened.assert_called_once_with()


class SettingsGroupTests(unittest.TestCase):
    def test_enabled_is_the_first_row_under_a_headed_settings_group(self) -> None:
        page = Page(RUNNING)

        self.assertEqual(page.headings[0], i18n.t("console.ext_page.settings"))
        self.assertEqual(page.rows[0], i18n.t("console.ext_page.enabled"))

    def test_the_switch_shows_what_was_chosen_not_what_is_running(self) -> None:
        """Switched on and waiting for a restart is on, though the state is off."""
        self.assertEqual(Page(WAITING).switches, [True])
        self.assertEqual(Page(SWITCHED_OFF).switches, [False])
        self.assertEqual(Page(LACKS).switches, [True])

    def test_one_waiting_for_a_restart_says_so_under_the_switch(self) -> None:
        self.assertIn(i18n.t(host.STARTS_AT_RESTART), Page(WAITING).labels("console-help"))
        self.assertNotIn(i18n.t(host.STARTS_AT_RESTART),
                         Page(SWITCHED_OFF).labels("console-help"))

    def test_its_own_settings_are_rows_beside_enabled(self) -> None:
        page = Page({**RUNNING, "surfaces": {"settings": "/settings"}},
                    {"fields": [{"key": "endpoint", "label": "Server", "value": "x"}]})

        self.assertEqual(page.rows[:2], [i18n.t("console.ext_page.enabled"), "Server"])

    def test_a_setting_that_would_not_read_says_why(self) -> None:
        page = Page({**RUNNING, "surfaces": {"settings": "/settings"}},
                    {"error": "No answer"})

        self.assertIn(i18n.t("console.ext_page.list_failed"), page.labels("console-intro"))


class StoppedSettingsLineTests(unittest.TestCase):
    LINE = i18n.t("console.ext_page.settings_when_running")

    def says(self, found: dict) -> bool:
        return self.LINE in Page({**found, "has_settings": True}).labels("console-help")

    def test_one_that_is_not_running_says_where_its_settings_will_be(self) -> None:
        for found in (SWITCHED_OFF, WAITING, BROKE, STOPPED):
            with self.subTest(state=found["state"]):
                self.assertTrue(self.says(found))

    def test_one_that_is_running_draws_its_settings_instead(self) -> None:
        self.assertFalse(self.says(RUNNING))

    def test_one_that_cannot_run_here_makes_no_promise(self) -> None:
        for found in (WRONG_PLATFORM, LACKS):
            with self.subTest(reason=found["reason_key"]):
                self.assertFalse(self.says(found))

    def test_one_that_declares_no_settings_says_nothing(self) -> None:
        self.assertNotIn(self.LINE, Page(SWITCHED_OFF).labels("console-help"))


class ActionsGroupTests(unittest.TestCase):
    ACTIONS = [{"key": "run", "label": "Import a Library", "description": "Brings one in"}]

    def test_a_running_extension_offers_its_actions_under_a_heading(self) -> None:
        page = Page({**RUNNING, "actions": self.ACTIONS})

        self.assertIn(i18n.t("word.actions"), page.headings)
        self.assertIn("Import a Library", page.buttons)

    def test_one_that_is_not_running_offers_none(self) -> None:
        page = Page({**SWITCHED_OFF, "actions": self.ACTIONS})

        self.assertNotIn(i18n.t("word.actions"), page.headings)
        self.assertNotIn("Import a Library", page.buttons)

    def test_one_with_none_draws_no_empty_heading(self) -> None:
        self.assertNotIn(i18n.t("word.actions"), Page(RUNNING).headings)


class ReachGroupTests(unittest.TestCase):
    def test_what_it_can_reach_is_two_rows_of_chips(self) -> None:
        page = Page({**RUNNING, "scopes": ["games:read"],
                     "capabilities": ["net:outbound"]})

        self.assertIn(i18n.t("console.ext_page.reach_title"), page.headings)
        self.assertEqual(page.rows[-2:], [i18n.t("console.ext_page.library"),
                                          i18n.t("console.ext_page.this_device")])
        self.assertEqual(page.labels("console-tier", "console-tier--on"),
                         [i18n.t("console.ext_page.read_library"),
                          i18n.t("console.ext_page.reach_internet")])

    def test_it_is_read_from_the_manifest_whatever_the_state(self) -> None:
        page = Page({**SWITCHED_OFF, "scopes": ["games:read"]})

        self.assertEqual(page.rows[-1], i18n.t("console.ext_page.library"))

    def test_one_that_reaches_nothing_draws_no_heading(self) -> None:
        self.assertNotIn(i18n.t("console.ext_page.reach_title"), Page(RUNNING).headings)

    def test_a_row_with_nothing_in_it_is_not_drawn(self) -> None:
        page = Page({**RUNNING, "scopes": ["games:read"]})

        self.assertNotIn(i18n.t("console.ext_page.this_device"), page.rows)


class SwitchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        # Outside the test's task, which has no page to draw into.
        self.body = ui.column()

    def draw(self, found: dict, answer: object) -> tuple[mock.Mock, mock.AsyncMock,
                                                         mock.Mock]:
        switch = self.enterContext(mock.patch.object(ext_page.panel, "switch"))
        io = self.enterContext(mock.patch.object(
            ext_page.offload, "io",
            new=mock.AsyncMock(**({"side_effect": answer} if isinstance(answer, Exception)
                                  else {"return_value": answer}))))
        self.client = self.enterContext(mock.patch.object(ext_page, "ApiClient")).return_value
        redraw = mock.Mock()
        with self.body:
            ext_page.build(found, {}, redraw, mock.Mock())
        return switch, io, redraw

    async def press(self, switch: mock.Mock, value: bool = False) -> None:
        with self.body:
            await switch.call_args.args[1](SimpleNamespace(value=value))

    async def test_it_asks_the_api_and_draws_the_page_again(self) -> None:
        switch, io, redraw = self.draw(RUNNING, None)

        await self.press(switch)

        [asked] = io.await_args_list
        self.assertIs(asked.args[0], self.client.set_extension_enabled)
        self.assertEqual(asked.args[1:], ("sample", False))
        redraw.assert_called_once_with()

    async def test_a_refused_switch_says_so_and_draws_the_page_as_it_is(self) -> None:
        notify = self.enterContext(mock.patch.object(ext_page.ui, "notify"))
        switch, _io, redraw = self.draw(RUNNING, RuntimeError("Not allowed"))

        await self.press(switch)

        notify.assert_called_once_with(i18n.t("said.off_failed"), caption="Not allowed",
                                       type="negative")
        redraw.assert_called_once_with()

    async def test_a_refusal_to_turn_it_on_says_that(self) -> None:
        notify = self.enterContext(mock.patch.object(ext_page.ui, "notify"))
        switch, _io, _redraw = self.draw(SWITCHED_OFF, RuntimeError("Not allowed"))

        await self.press(switch, True)

        notify.assert_called_once_with(i18n.t("said.on_failed"), caption="Not allowed",
                                       type="negative")


class IndexTests(unittest.TestCase):
    def test_the_group_is_last_and_lists_each_by_name(self) -> None:
        pages = settings.system_pages(install_identity.FEATURES, [
            {"name": "zed", "display_name": "Zed"}, {"name": "ant", "display_name": "ant"},
            {"name": "mid", "display_name": "Mid"}])
        tail = [(page[0], page[1]) for group, page in pages
                if group == settings.EXTENSIONS_GROUP]

        self.assertEqual(tail, [("extensions.ant", "ant"), ("extensions.mid", "Mid"),
                                ("extensions.zed", "Zed")])
        self.assertEqual(pages[-1][0], settings.EXTENSIONS_GROUP)

    def test_a_page_key_survives_the_address_lowercasing_the_page(self) -> None:
        self.assertEqual(ext_page.key("My_Ext"), "extensions.my_ext")

    def test_none_installed_has_no_group(self) -> None:
        pages = settings.system_pages(install_identity.FEATURES, [])

        self.assertNotIn(settings.EXTENSIONS_GROUP, [group for group, _page in pages])

    def test_the_group_is_there_for_an_install_with_nothing_switched_on(self) -> None:
        pages = settings.system_pages([], [{"name": "ant", "display_name": "Ant"}])

        self.assertIn(settings.EXTENSIONS_GROUP, [group for group, _page in pages])

    def test_an_extension_that_broke_marks_its_page(self) -> None:
        item = feature_checks.Unmet(feature=install_identity.CORE,
                                    section=feature_checks.EXTENSIONS, key="sample",
                                    state="failed", reason="It threw")

        self.assertEqual(settings.pages_in_trouble([item]), {"extensions.sample": [item]})


class TroubleTests(unittest.TestCase):
    def trouble(self, records: list) -> list[Any]:
        with mock.patch.object(settings.extensions, "records", return_value=records):
            return settings._extension_trouble()

    def record(self, state: str) -> Any:
        return SimpleNamespace(name="sample", state=state, reason="said")

    def test_failed_and_stopped_are_trouble(self) -> None:
        for state in (host.FAILED, host.DISABLED):
            [item] = self.trouble([self.record(state)])
            self.assertEqual((item.section, item.key, item.reason),
                             (feature_checks.EXTENSIONS, "sample", "said"))

    def test_running_and_off_are_not(self) -> None:
        self.assertEqual(self.trouble([self.record(host.LOADED),
                                       self.record(host.OFF)]), [])


class IndexMarkTests(unittest.TestCase):
    def marks(self, installed: list, trouble: list) -> dict[str, Any]:
        entries: list = []

        def sections(given: list, *_args: Any, **_kwargs: Any) -> Any:
            entries.extend(given)
            return ui.column()

        state = {"extensions": installed, "trouble": trouble,
                 "settings_page": "extensions.sample"}
        with mock.patch.object(settings.panel, "sections", sections), \
                mock.patch.object(settings.busy, "fill"):
            settings.build_system(mock.Mock(), state, mock.Mock(),
                                  {"features": list(install_identity.FEATURES)})
        return {entry[1]: entry[3] for entry in entries if len(entry) > 3}

    def test_off_is_said_at_the_end_of_its_row_and_nowhere_else(self) -> None:
        marks = self.marks([SWITCHED_OFF, {**RUNNING, "name": "other",
                                           "display_name": "Other"}], [])

        self.assertIsNotNone(marks["Sample"])
        self.assertIsNone(marks["Other"])
        self.assertIsNone(marks[settings.EXTENSIONS_GROUP])

    def test_one_that_broke_wears_the_trouble_mark_and_so_does_its_group(self) -> None:
        item = feature_checks.Unmet(feature=install_identity.CORE,
                                    section=feature_checks.EXTENSIONS, key="sample",
                                    state="failed", reason="It threw")
        marks = self.marks([BROKE], [item])

        self.assertIsNotNone(marks["Sample"])
        self.assertIsNotNone(marks[settings.EXTENSIONS_GROUP])

    def test_one_running_is_marked_with_nothing(self) -> None:
        self.assertIsNone(self.marks([RUNNING], [])["Sample"])


class SecretSettingTests(unittest.TestCase):
    """A secret is drawn empty whatever it holds, and leaving it empty keeps it."""

    def _drawn(self, field: dict) -> tuple[str, Callable[[str], Any], str]:
        given: dict[str, Any] = {}

        def fake(value, on_save, *, placeholder="", refuses=False):
            given.update(value=value, on_save=on_save, placeholder=placeholder)
            return lambda: None

        client = mock.Mock()
        with mock.patch.object(ext_page.panel, "field", fake):
            ext_page._control(client, "/ext/sample/settings", "token", field, mock.Mock())
        self.client = client
        return given["value"], given["on_save"], given["placeholder"]

    def test_a_value_that_arrived_anyway_is_not_drawn(self) -> None:
        value, _, placeholder = self._drawn({"key": "token", "type": "secret",
                                             "value": "leaked", "set": True})

        self.assertEqual((value, placeholder), ("", i18n.t("console.ext_page.secret_set")))

    def test_one_not_set_says_so(self) -> None:
        _, _, placeholder = self._drawn({"key": "token", "type": "secret", "set": False})

        self.assertEqual(placeholder, i18n.t("console.ext_page.secret_not_set"))

    def test_leaving_it_empty_writes_nothing(self) -> None:
        _, on_save, _ = self._drawn({"key": "token", "type": "secret", "set": True})

        self.assertIsNone(on_save(""))
        self.client.ext_put.assert_not_called()


class LanguageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.addCleanup(i18n.set_language, i18n.language())

    def test_what_a_scope_allows_is_read_in_the_language_set(self) -> None:
        english = ext_page._plainly("games:read")
        i18n.set_language("qps")

        self.assertNotEqual(english, ext_page._plainly("games:read"))

    def test_a_scope_nobody_described_is_shown_as_it_is(self) -> None:
        self.assertEqual("games:teleport", ext_page._plainly("games:teleport"))


def _said(job: dict, under: str = "ext.sample.action.run") -> list[str]:
    with ui.column() as body:
        wizard.report(body, job, under)
    return [one.text for one in body.descendants() if isinstance(one, ui.label)]


def _reported(job: dict) -> dict[str, str]:
    with ui.column() as body:
        wizard.report(body, job, "ext.sample.action.run")
    return lines.details(body)


def _noted(notes: list) -> dict[str, str]:
    with ui.column() as body:
        wizard._lines(notes, "")
    return lines.details(body)


class NoteTests(unittest.TestCase):
    def test_a_plain_note_hovers_nothing(self) -> None:
        self.assertEqual({"Kiss.pov was left behind": ""},
                         _noted(["Kiss.pov was left behind"]))

    def test_a_note_with_a_detail_hovers_it(self) -> None:
        self.assertEqual(
            {"Settings.xml could not be read": "Nothing is at /pbx/Config/Settings.xml"},
            _noted([{"text": "Settings.xml could not be read",
                     "detail": "Nothing is at /pbx/Config/Settings.xml"}]))

    def test_a_note_with_only_a_detail_says_the_detail(self) -> None:
        self.assertEqual({"Nothing answers at example.org": ""},
                         _noted([{"detail": "Nothing answers at example.org"}]))


class ReportTests(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        (Path(folder.name) / "en.json").write_text(
            json.dumps({"action.run.result.games": "Games made"}), encoding="utf-8")
        i18n.own("ext.sample", Path(folder.name))
        self.addCleanup(i18n.disown, "ext.sample")
        self.addCleanup(i18n.set_language, i18n.language())

    def test_a_count_is_titled_by_its_extension(self) -> None:
        self.assertIn("Games made", _said({"state": "done", "result": {"games": 3}}))

    def test_a_count_with_no_word_is_titled_by_its_field(self) -> None:
        self.assertIn("games_skipped",
                      _said({"state": "done", "result": {"games_skipped": 1}}))

    def test_a_row_that_does_not_say_how_it_matched_is_named_alone(self) -> None:
        said = _said({"state": "done",
                      "result": {"already_here": [{"key": "k", "name": "Kiss"}]}})

        self.assertIn("Kiss", said)

    def test_a_row_that_did_not_come_across_is_worded_by_the_catalog(self) -> None:
        with mock.patch.object(wizard, "t", side_effect=lambda key, **_values: key):
            said = _said({"state": "done",
                          "result": {"rows": [{"name": "Kiss", "error": "no table"}]}})

        self.assertIn("console.ext_action.missed", said)

    def test_a_row_error_with_a_detail_hovers_it(self) -> None:
        drawn = _reported({"state": "done", "result": {"rows": [
            {"name": "Kiss", "error": {"text": "the game file did not come across",
                                       "detail": "Something is already at Kiss.vpx"}}]}})

        self.assertEqual("Something is already at Kiss.vpx",
                         drawn["Kiss - the game file did not come across"])

    def test_a_row_error_as_a_string_hovers_nothing(self) -> None:
        drawn = _reported({"state": "done", "result": {"rows": [
            {"name": "Kiss", "error": "the game file did not come across"}]}})

        self.assertEqual("", drawn["Kiss - the game file did not come across"])


if __name__ == "__main__":
    unittest.main()
