"""What the Extensions page says about an extension that is not running.

The words are the whole of this page: the list itself is one card per row. What is worth
pinning is that every state the host can reach has a word, and that the word for a switch
somebody set is not the word for something that broke.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from nicegui import ui

from common import i18n
from common.extensions import host
from console import ext_action, ext_page, sections


class StateWordTests(unittest.TestCase):
    def test_every_state_that_is_not_running_has_a_word(self) -> None:
        """A state with no word draws no chip, so a stopped extension would look fine."""
        states = {value for name, value in vars(host).items()
                  if name.isupper() and isinstance(value, str)
                  and value in {"loaded", "failed", "disabled", "off"}}

        self.assertEqual(states - {host.LOADED}, set(sections.STATE_WORDS))

    def test_running_draws_no_chip(self) -> None:
        """A badge on every row says nothing."""
        self.assertNotIn(host.LOADED, sections.STATE_WORDS)

    def test_a_switch_somebody_set_reads_differently_from_a_fault(self) -> None:
        self.assertNotEqual(sections.STATE_WORDS[host.OFF],
                            sections.STATE_WORDS[host.DISABLED])

    def test_only_a_state_that_costs_something_wears_the_warn_tone(self) -> None:
        self.assertEqual(sections.QUIET_STATES, {host.OFF})


class FrontDoorTests(unittest.TestCase):
    """What a person browsing what is installed is shown.

    Not what an extension may reach. A scope is what somebody agrees to when installing
    something; on a list of what is already installed it is jargon in front of everybody
    who is not auditing, and it belongs on the extension's own page.
    """

    def test_the_card_does_not_name_scopes_or_capabilities(self) -> None:
        source = Path(sections.__file__).read_text(encoding="utf-8")
        card = source[source.index("def _extension_card"):source.index("def _actions")]

        self.assertNotIn("scopes", card)
        self.assertNotIn("capabilities", card)

    def test_an_action_is_drawn_from_its_label_alone(self) -> None:
        """The description is already the line under the extension's name."""
        source = Path(sections.__file__).read_text(encoding="utf-8")
        actions = source[source.index("def _actions"):]

        self.assertIn("tooltip", actions)


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
        ext_action._report(body, job, under)
    return [one.text for one in body.descendants() if isinstance(one, ui.label)]


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
        with mock.patch.object(ext_action, "t", side_effect=lambda key, **_values: key):
            said = _said({"state": "done",
                          "result": {"rows": [{"name": "Kiss", "error": "no table"}]}})

        self.assertIn("console.ext_action.missed", said)


if __name__ == "__main__":
    unittest.main()
