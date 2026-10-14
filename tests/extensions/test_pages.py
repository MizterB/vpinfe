"""A page an extension puts in the rail: what it may declare, what it answers, what the
routes do with it, and how it may be titled."""

from __future__ import annotations

import json
import logging
import tempfile
import unittest
from pathlib import Path
from typing import Any

from common import i18n
from common.extensions import contract, host, pictures, store
from common.extensions.context import ExtensionUI, check_references
from common.i18n import t
from tests.support.served import client_for

MODULE = "tests.extensions.test_pages"
NAME = "paged"

STATE: dict[str, Any] = {}

ANSWER = {"title": "Weekly", "under": "Since Monday",
          "sections": [{"key": "now", "label": "",
                        "facts": [{"label": "Plays", "value": 4, "kind": "number"}],
                        "fields": [{"key": "note", "type": "string", "label": "Note",
                                    "value": "hi"},
                                   {"key": "token", "type": "secret", "label": "Token",
                                    "value": "hunter2"}],
                        "rows": [{"label": "Bally", "under": "1990"}]}]}


def fresh_state() -> None:
    STATE.clear()
    STATE.update(saved=[], answer=ANSWER, raises=None, pressed=[], title="This week",
                 list_title="")


def paged(ctx: Any) -> None:
    def read() -> Any:
        return STATE["answer"]

    def save(changes: dict) -> None:
        if STATE["raises"] is not None:
            raise STATE["raises"]
        STATE["saved"].append(dict(changes))

    def refresh() -> str:
        STATE["pressed"].append("refresh")
        return "Read"

    ctx.ui.page("week", read, title=STATE["title"], save=save,
                acts={"refresh": refresh, "site": "https://example.org"})
    if STATE["list_title"]:
        ctx.ui.list("plays", lambda: [], columns=[{"field": "name"}],
                    title=STATE["list_title"])


def _installed(root: Path, *, capabilities: list[str], titles: dict | None = None) -> Path:
    directory = root / NAME
    (directory / "i18n").mkdir(parents=True)
    (directory / "extension.json").write_text(json.dumps({
        "name": NAME, "display_name": "Paged", "version": "1.0.0",
        "description": "Puts a page in the rail, for the tests that ask for it.",
        "requires_platform": contract.PLATFORM_ABI,
        "capabilities": capabilities, "scopes": []}), encoding="utf-8")
    (directory / "i18n" / "en.json").write_text(
        json.dumps({"page.week.act.refresh.label": "Read again", **(titles or {})}),
        encoding="utf-8")
    (directory / "__init__.py").write_text(
        f"from {MODULE} import paged as register\n", encoding="utf-8")
    return directory


class Declaring(unittest.TestCase):
    def ui(self, *, allowed: bool = True) -> ExtensionUI:
        return ExtensionUI(NAME, allowed)

    def test_a_page_is_declared_with_its_area_and_where_it_is_served(self) -> None:
        ui = self.ui()

        ui.page("week", lambda: {}, area="system", title="Week",
                save=lambda values: None, acts={"x": lambda: None})

        self.assertEqual(ui.declared_pages, [{
            "key": "week", "area": "system", "title": "Week", "base": "/pages/week",
            "about": "/pages/week/about", "save": True}])

    def test_a_page_goes_in_community_unless_it_says_otherwise(self) -> None:
        ui = self.ui()

        ui.page("week", lambda: {})

        self.assertEqual(ui.declared_pages[0]["area"], "community")

    def test_a_page_needs_the_ui_capability(self) -> None:
        with self.assertRaisesRegex(contract.ContractError, "ui:mount"):
            self.ui(allowed=False).page("week", lambda: {})

    def test_a_page_has_a_key_that_is_its_own_and_an_area_core_has(self) -> None:
        ui = self.ui()
        ui.page("week", lambda: {})

        with self.assertRaisesRegex(contract.ContractError, "no key"):
            ui.page(" ", lambda: {})
        with self.assertRaisesRegex(contract.ContractError, "twice"):
            ui.page("week", lambda: {})
        with self.assertRaisesRegex(contract.ContractError, "not one of"):
            ui.page("other", lambda: {}, area="attic")

    def test_a_read_a_save_and_acts_are_what_they_should_be(self) -> None:
        ui = self.ui()

        with self.assertRaisesRegex(contract.ContractError, "not a function"):
            ui.page("a", "read")  # type: ignore[arg-type]
        with self.assertRaisesRegex(contract.ContractError, "not a function"):
            ui.page("b", lambda: {}, save="save")  # type: ignore[arg-type]
        with self.assertRaisesRegex(contract.ContractError, "neither a dict nor a function"):
            ui.page("c", lambda: {}, acts=["x"])
        self.assertEqual(ui.declared_pages, [])

    def test_an_act_that_opens_a_dialog_the_extension_never_offers_is_refused(self) -> None:
        ui = self.ui()
        ui.page("week", lambda: {}, acts={"add": {"action": "add_one"}})

        with self.assertRaisesRegex(contract.ContractError, "page 'week'.*add_one"):
            check_references(ui)


class Served(unittest.TestCase):
    capabilities = ["ui:mount"]

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = store.ExtensionStore(Path(tmp.name))
        self.registry = host.Registry(self.store)
        self.addCleanup(self.registry.clear)
        self.addCleanup(i18n.disown, f"ext.{NAME}")
        fresh_state()
        self.record = self.registry.load(
            _installed(Path(tmp.name) / "installed", capabilities=self.capabilities))
        self.assertEqual(self.record.state, host.LOADED, self.record.error)
        self.client = client_for(self, self.registry, self.record)
        self.base = f"/ext/{NAME}/pages/week"

    def ok(self, response: Any) -> Any:
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def put(self, **values: Any) -> Any:
        return self.client.put(self.base, json={"values": values})


class Reading(Served):
    def test_a_page_answers_what_the_extension_read(self) -> None:
        answer = self.ok(self.client.get(self.base))

        self.assertEqual((answer["title"], answer["under"]), ("Weekly", "Since Monday"))
        (section,) = answer["sections"]
        self.assertEqual([one["label"] for one in section["facts"]], ["Plays"])
        self.assertEqual(section["rows"], [{"label": "Bally", "under": "1990"}])
        self.assertNotIn("hunter2", json.dumps(answer))

    def test_an_answer_core_cannot_draw_is_the_extensions_failure(self) -> None:
        for answer in ({"under": "no title"}, {"title": "T", "color": "red"}):
            with self.subTest(answer=answer):
                STATE["answer"] = answer

                self.assertEqual(self.client.get(self.base).status_code, 400)

    def test_a_page_the_extension_did_not_declare_is_not_there(self) -> None:
        response = self.client.get(f"/ext/{NAME}/pages/other")

        self.assertEqual(response.status_code, 404, response.text)
        self.assertEqual(response.json()["error"]["message"],
                         t("error.extensions.no_page", display=self.record.display_name,
                           key="other"))

    def test_the_menu_lists_the_acts_with_the_extensions_words(self) -> None:
        offered = self.ok(self.client.get(f"{self.base}/about"))["acts"]

        self.assertEqual(offered, [{"key": "refresh", "label": "Read again"},
                                   {"key": "site", "label": "site",
                                    "url": "https://example.org"}])

    def test_an_act_runs_and_says_what_it_answered(self) -> None:
        said = self.ok(self.client.post(f"{self.base}/about/acts/refresh"))

        self.assertEqual(said, {"message": "Read"})
        self.assertEqual(STATE["pressed"], ["refresh"])

    def test_an_address_is_opened_and_never_run(self) -> None:
        response = self.client.post(f"{self.base}/about/acts/site")

        self.assertEqual(response.status_code, 404, response.text)


class Saving(Served):
    def test_changed_fields_are_written_and_the_page_comes_back(self) -> None:
        answer = self.ok(self.put(note="there"))

        self.assertEqual(STATE["saved"], [{"note": "there"}])
        self.assertEqual(answer["title"], "Weekly")

    def test_a_key_the_page_does_not_offer_is_refused_and_nothing_is_saved(self) -> None:
        response = self.put(other="x")

        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(STATE["saved"], [])

    def test_a_save_that_raises_is_a_refusal_in_its_words_with_the_field_named(self) -> None:
        STATE["raises"] = ValueError("That note is too long")

        response = self.put(note="x")

        error = response.json()["error"]
        self.assertEqual((response.status_code, error["message"], error["details"]),
                         (400, "That note is too long", {"field": "note"}))

    def test_a_page_with_no_save_cannot_be_written(self) -> None:
        self.record.context.ui.page_functions["week"].save = None

        response = self.put(note="x")

        self.assertEqual(response.status_code, 404, response.text)
        self.assertEqual(response.json()["error"]["message"],
                         t("error.extensions.no_page_save", display=self.record.display_name,
                           key="week"))

    def test_writing_wants_the_write_scope_and_not_the_read_one(self) -> None:
        self.client = client_for(self, self.registry, self.record,
                                 allowed=lambda scope: scope.endswith(":read"))

        self.assertEqual(self.client.get(self.base).status_code, 200)
        self.assertEqual(self.put(note="x").status_code, 403)
        self.assertEqual(STATE["saved"], [])


class Declared(Served):
    def test_the_record_lists_its_pages_with_the_title_resolved(self) -> None:
        self.assertEqual([(one["key"], one["title"], one["area"])
                          for one in self.record.as_dict()["pages"]],
                         [("week", "This week", "community")])

    def test_a_page_with_no_title_is_named_for_its_extension_unless_the_catalog_says(self) -> None:
        self.record.declared_pages[0]["title"] = ""
        self.assertEqual(self.record.pages()[0]["title"], "Paged")

    def test_a_switched_off_extension_lists_no_pages(self) -> None:
        self.record.state = host.DISABLED

        self.assertEqual(self.record.as_dict()["pages"], [])


class Pictured(Served):
    capabilities = ["ui:mount", "net:outbound"]
    WEB = "https://pictures.example/week.png"

    def setUp(self) -> None:
        super().setUp()
        pictures._sources.clear()

    def test_a_web_picture_is_an_address_of_cores_own(self) -> None:
        STATE["answer"] = {**ANSWER, "picture": self.WEB}

        answer = self.ok(self.client.get(self.base))

        self.assertRegex(answer["picture"], rf"^/api/v1/ext/{NAME}/pictures/[0-9a-f]{{20}}$")

    def test_a_picture_fact_is_an_address_of_cores_own(self) -> None:
        section = {**ANSWER["sections"][0],
                   "facts": [{"label": "Cover", "value": self.WEB, "kind": "picture"}]}
        STATE["answer"] = {**ANSWER, "sections": [section]}

        answer = self.ok(self.client.get(self.base))

        self.assertRegex(answer["sections"][0]["facts"][0]["value"],
                         rf"^/api/v1/ext/{NAME}/pictures/[0-9a-f]{{20}}$")

    def test_a_game_fact_s_picture_is_an_address_of_cores_own(self) -> None:
        section = {**ANSWER["sections"][0],
                   "facts": [{"label": "Machine", "value": "v1", "kind": "game", "keys": "vps",
                              "picture": self.WEB}]}
        STATE["answer"] = {**ANSWER, "sections": [section]}

        fact = self.ok(self.client.get(self.base))["sections"][0]["facts"][0]

        self.assertRegex(fact["picture"], rf"^/api/v1/ext/{NAME}/pictures/[0-9a-f]{{20}}$")
        self.assertEqual("v1", fact["value"])


class PicturedWithoutOutbound(Served):
    def test_a_web_picture_is_refused_and_says_which_page(self) -> None:
        STATE["answer"] = {**ANSWER, "picture": "https://pictures.example/week.png"}

        response = self.client.get(self.base)

        self.assertEqual(response.status_code, 400)
        self.assertIn(t("error.extensions.picture_outbound", display="Paged",
                        key="page week"), response.text)


class Titled(unittest.TestCase):
    def load(self, titles: dict | None = None, **state: Any) -> host.Record:
        logging.disable(logging.ERROR)
        self.addCleanup(logging.disable, logging.NOTSET)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        registry = host.Registry(store.ExtensionStore(Path(tmp.name)))
        self.addCleanup(registry.clear)
        self.addCleanup(i18n.disown, f"ext.{NAME}")
        fresh_state()
        STATE.update(state)
        return registry.load(_installed(Path(tmp.name) / "installed",
                                        capabilities=["ui:mount"], titles=titles))

    def test_a_page_with_no_title_takes_the_one_in_the_catalog(self) -> None:
        record = self.load(titles={"page.week.title": "Weekly plays"}, title="")

        self.assertEqual(record.state, host.LOADED, record.error)
        self.assertEqual(record.pages()[0]["title"], "Weekly plays")

    def test_a_page_may_not_be_named_for_a_core_page(self) -> None:
        record = self.load(title=t("console.section.games"))

        self.assertEqual(record.state, host.FAILED)
        self.assertIn("a page", record.error)

    def test_a_page_may_not_share_a_title_with_a_list_in_its_area(self) -> None:
        record = self.load(list_title="This week")

        self.assertEqual(record.state, host.FAILED)
        self.assertIn("a page 'This week'", record.error)


if __name__ == "__main__":
    unittest.main()
