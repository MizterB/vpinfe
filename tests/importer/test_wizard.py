"""The guided task the importer offers, as core sees it.

Core draws the wizard from what the extension declares, so what is pinned here is the
declaration and the three calls behind it - not the drawing, which is core's and is the
same for every task.
"""

from __future__ import annotations

import tempfile
import unittest
import unittest.mock
from pathlib import Path

from fastapi.testclient import TestClient

import httpapi
from common import extensions
from common.extensions import host, store
from common.extensions.contract import ContractError

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests" / "fixtures" / "pinballx"
BASE = "/ext/library_importer"


class WizardCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.store = store.ExtensionStore(self.root / "extensions.json")
        self.registry = host.Registry(self.store)
        extensions.set_registry(self.registry)
        self.addCleanup(extensions.set_registry, host.Registry())
        self.addCleanup(self.registry.clear)
        self.record = self.registry.load(host.BUNDLED_DIR / "library_importer")
        self.assertEqual(self.record.state, host.LOADED, self.record.reason)
        self.client = TestClient(httpapi.create_api_app(), raise_server_exceptions=False)


class DeclarationTests(WizardCase):
    def test_the_action_is_listed_with_the_extension(self) -> None:
        found = self.client.get("/extensions").json()["extensions"][0]

        action = found["actions"][0]
        self.assertEqual(action["key"], "import")
        self.assertEqual(action["base"], "/wizard")
        self.assertTrue(action["label"])

    def test_an_action_declares_no_mode(self) -> None:
        """How many steps it has is read off what it answers - the fields it asks
        for and the confirm it names. A declared mode would be a second statement
        of the same thing, and the two come apart."""
        found = self.client.get("/extensions").json()["extensions"][0]
        action = found["actions"][0]

        self.assertEqual(sorted(action), ["base", "description", "key", "label"])

    def test_an_extension_that_is_not_running_offers_nothing(self) -> None:
        """A button that refuses is worse than no button."""
        with self.assertLogs("vpinfe.common.extensions", "ERROR"):
            self.registry.disable("library_importer", "asked to")

        found = self.client.get("/extensions").json()["extensions"][0]

        self.assertEqual(found["actions"], [])

    def test_offering_one_without_the_capability_is_refused(self) -> None:
        from common.extensions.context import ExtensionUI

        with self.assertRaises(ContractError):
            ExtensionUI("quiet", allowed=False).action("go", "Go", "/x")


class FormTests(WizardCase):
    def test_the_first_step_asks_where_the_library_is(self) -> None:
        found = self.client.get(f"{BASE}/wizard").json()

        self.assertTrue(found["title"])
        self.assertEqual([one["key"] for one in found["fields"]], ["path"])
        self.assertEqual(found["fields"][0]["type"], "path")


class CheckTests(WizardCase):
    def _check(self, path) -> dict:
        return self.client.post(f"{BASE}/wizard/check",
                                json={"values": {"path": str(path)}}).json()

    def test_it_says_what_would_come_across(self) -> None:
        found = self._check(FIXTURE)

        self.assertTrue(found["ready"])
        summary = dict(found["summary"])
        self.assertEqual(summary["Games"], "4")
        self.assertEqual(summary["Already matched"], "1")

    def test_the_notes_travel_with_the_counts(self) -> None:
        """A summary that said four games and stayed quiet about their tables being on a
        machine that is not here would describe an import that will not happen."""
        found = self._check(FIXTURE)

        self.assertTrue(any("not reachable from here" in note
                            for note in found["notes"]))

    def test_the_confirm_says_what_it_will_do(self) -> None:
        self.assertEqual(self._check(FIXTURE)["confirm"], "Bring in 4 games")

    def test_several_systems_are_a_choice_and_one_is_not(self) -> None:
        found = self._check(FIXTURE)

        self.assertEqual([one["key"] for one in found["fields"]], ["systems"])
        self.assertEqual(len(found["fields"][0]["choices"]), 2)

    def test_a_folder_holding_nothing_readable_is_not_ready(self) -> None:
        empty = self.root / "empty"
        empty.mkdir()

        found = self._check(empty)

        self.assertFalse(found["ready"])
        self.assertTrue(found["reason"])

    def test_choosing_the_folder_here_is_what_lets_core_read_it(self) -> None:
        """It is set at the check rather than at the end, because there is nothing to
        summarize until core may read the folder at all."""
        from httpapi import filesystem

        self._check(FIXTURE)

        self.assertEqual(filesystem.within_roots(str(FIXTURE / "Config")).name, "Config")


if __name__ == "__main__":
    unittest.main()
