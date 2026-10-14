"""A group an extension puts on a game's or a table's panel: what it may declare, what the
routes ask it, and what a Private game keeps from it."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from common import i18n
from common.extensions import contract, host, pane, store
from common.extensions.context import ExtensionUI
from common.i18n import t
from tests.support.served import client_for

MODULE = "tests.extensions.test_panel_groups"
NAME = "grouped"

STATE: dict[str, Any] = {}

SECTION = {"facts": [{"label": "Plays", "value": 4, "kind": "number"}],
           "fields": [{"key": "note", "type": "string", "label": "Note", "value": "hi"},
                      {"key": "token", "type": "secret", "label": "Token", "value": "hunter2"}],
           "rows": [{"label": "Bally", "under": "1990"}]}

PUBLIC = {"private": False, "vps_id": "vps-1", "name": "Taxi"}
HIDDEN = {"private": True, "vps_id": "vps-2", "name": "Secret"}


def fresh_state() -> None:
    STATE.clear()
    STATE.update(asked=[], saved=[], answer=SECTION, raises=None)


def grouped(ctx: Any) -> None:
    def read_game(who: dict) -> Any:
        STATE["asked"].append(("game", dict(who)))
        return STATE["answer"]

    def read_table(who: dict) -> Any:
        STATE["asked"].append(("table", dict(who)))
        return STATE["answer"]

    def save(who: dict, changes: dict) -> None:
        if STATE["raises"] is not None:
            raise STATE["raises"]
        STATE["saved"].append((dict(who), dict(changes)))

    ctx.ui.panel_group("game", read_game, title="Taxi notes", save=save)
    ctx.ui.panel_group("table", read_table)


def _installed(root: Path, scopes: list[str]) -> Path:
    directory = root / NAME
    (directory / "i18n").mkdir(parents=True)
    (directory / "extension.json").write_text(json.dumps({
        "name": NAME, "display_name": "Grouped", "version": "1.0.0",
        "description": "Puts a group on a panel, for the tests that ask for it.",
        "requires_platform": contract.PLATFORM_ABI,
        "capabilities": ["ui:mount"], "scopes": scopes}), encoding="utf-8")
    (directory / "i18n" / "en.json").write_text(
        json.dumps({"group.table.title": "On this table"}), encoding="utf-8")
    (directory / "__init__.py").write_text(
        f"from {MODULE} import grouped as register\n", encoding="utf-8")
    return directory


class Declaring(unittest.TestCase):
    def ui(self, *, allowed: bool = True, scopes: tuple[str, ...] = ("games:read",)
           ) -> ExtensionUI:
        return ExtensionUI(NAME, allowed, scopes)

    def test_a_group_is_declared_for_a_game_and_for_a_table(self) -> None:
        ui = self.ui()

        ui.panel_group("game", lambda who: None, save=lambda who, values: None)
        ui.panel_group("table", lambda who: None, title="Here")

        self.assertEqual(
            ui.declared_groups,
            [{"subject": "game", "title": "", "base": "/groups/game", "save": True},
             {"subject": "table", "title": "Here", "base": "/groups/table", "save": False}])

    def test_a_group_needs_the_ui_capability_and_the_scope_to_read_games(self) -> None:
        with self.assertRaisesRegex(contract.ContractError, "ui:mount"):
            self.ui(allowed=False).panel_group("game", lambda who: None)
        with self.assertRaisesRegex(contract.ContractError, "games:read"):
            self.ui(scopes=()).panel_group("game", lambda who: None)

    def test_a_subject_is_a_game_or_a_table_and_is_declared_once(self) -> None:
        ui = self.ui()
        ui.panel_group("game", lambda who: None)

        with self.assertRaisesRegex(contract.ContractError, "not one of"):
            ui.panel_group("player", lambda who: None)
        with self.assertRaisesRegex(contract.ContractError, "twice"):
            ui.panel_group("game", lambda who: None)

    def test_a_read_and_a_save_are_functions(self) -> None:
        ui = self.ui()

        with self.assertRaisesRegex(contract.ContractError, "not a function"):
            ui.panel_group("game", "read")  # type: ignore[arg-type]
        with self.assertRaisesRegex(contract.ContractError, "not a function"):
            ui.panel_group("table", lambda who: None, save="save")  # type: ignore[arg-type]
        self.assertEqual(ui.declared_groups, [])


class Grouped(unittest.TestCase):
    def test_nothing_or_an_empty_section_is_no_group(self) -> None:
        for answer in (None, {}, {"facts": [], "fields": [], "rows": []}):
            with self.subTest(answer=answer):
                self.assertIsNone(pane.grouped(answer))

    def test_a_section_comes_back_shaped(self) -> None:
        section = pane.grouped(SECTION)

        assert section is not None
        self.assertEqual([one["kind"] for one in section["facts"]], ["number"])
        self.assertEqual(section["rows"], [{"label": "Bally", "under": "1990"}])
        token = next(one for one in section["fields"] if one["key"] == "token")
        self.assertEqual(token["set"], True)
        self.assertNotIn("value", token)

    def test_a_group_answers_a_section_and_nothing_else(self) -> None:
        wrong = {"a title": {"title": "T", "facts": [{"label": "L", "value": "v"}]},
                 "sections": {"sections": []},
                 "not a dict": ["facts"],
                 "two fields of one key": {"fields": [{"key": "f"}, {"key": "f"}]},
                 "a fact kind with no drawing": {"facts": [
                     {"label": "L", "value": "v", "kind": "rating"}]}}
        for what, answer in wrong.items():
            with self.subTest(what), self.assertRaises(pane.PaneError):
                pane.grouped(answer)


class Served(unittest.TestCase):
    scopes = ["games:read"]

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = store.ExtensionStore(Path(tmp.name))
        self.registry = host.Registry(self.store)
        self.addCleanup(self.registry.clear)
        self.addCleanup(i18n.disown, f"ext.{NAME}")
        fresh_state()
        self.record = self.registry.load(_installed(Path(tmp.name) / "installed", self.scopes))
        self.assertEqual(self.record.state, host.LOADED, self.record.error)
        self.client = client_for(self, self.registry, self.record)
        self.base = f"/ext/{NAME}/groups"
        self.game = {"game_dir_name": "g1"}
        self.resource = PUBLIC
        for target, replacement in (
                ("httpapi.extensions_served.game_lens.resource_of", self._resource),
                ("httpapi.extensions_served.game_lens.game_or_refuse", lambda _id: self.game),
                ("httpapi.extensions_served.table_ops.row_or_refuse", self._table)):
            patch = mock.patch(target, replacement)
            patch.start()
            self.addCleanup(patch.stop)

    def _resource(self, game_id: str) -> dict:
        return dict(self.resource)

    def _table(self, game: Any, table_id: str) -> dict:
        return {"id": table_id, "version": "1.2", "source": {"vps_file_id": "file-9"}}

    def ok(self, response: Any) -> Any:
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def put(self, path: str, **values: Any) -> Any:
        return self.client.put(f"{self.base}{path}", json={"values": values})


class Reading(Served):
    def test_a_game_group_is_asked_about_the_game_and_answers_a_section(self) -> None:
        answer = self.ok(self.client.get(f"{self.base}/game/g1"))

        self.assertEqual(STATE["asked"], [("game", {
            "game_id": "g1", "vps_id": "vps-1", "name": "Taxi"})])
        self.assertEqual(answer["title"], "Taxi notes")
        self.assertEqual([one["label"] for one in answer["section"]["facts"]], ["Plays"])
        self.assertNotIn("hunter2", json.dumps(answer))

    def test_a_table_group_is_told_the_table_too_and_is_headed_from_the_catalog(self) -> None:
        answer = self.ok(self.client.get(f"{self.base}/table/g1/t1"))

        self.assertEqual(STATE["asked"], [("table", {
            "game_id": "g1", "vps_id": "vps-1", "name": "Taxi", "table_id": "t1",
            "vps_file_id": "file-9", "version": "1.2"})])
        self.assertEqual(answer["title"], "On this table")

    def test_a_group_with_nothing_to_say_answers_no_section(self) -> None:
        STATE["answer"] = None

        self.assertEqual(self.ok(self.client.get(f"{self.base}/game/g1"))["section"], None)

    def test_a_private_game_is_never_asked_about(self) -> None:
        self.resource = HIDDEN

        for path in ("/game/g1", "/table/g1/t1"):
            with self.subTest(path):
                answer = self.ok(self.client.get(f"{self.base}{path}"))
                self.assertEqual(answer, {"title": "", "section": None})
        self.assertEqual(STATE["asked"], [])

    def test_an_answer_core_cannot_draw_is_the_extensions_failure(self) -> None:
        STATE["answer"] = {"color": "red"}

        response = self.client.get(f"{self.base}/game/g1")

        self.assertEqual(response.status_code, 400, response.text)

    def test_a_group_the_extension_did_not_declare_is_not_there(self) -> None:
        self.record.context.ui.group_functions.pop("table")

        response = self.client.get(f"{self.base}/table/g1/t1")

        self.assertEqual(response.status_code, 404, response.text)
        self.assertEqual(
            response.json()["error"]["message"],
            t("error.extensions.no_group", display=self.record.display_name,
              subject="table"))


class Saving(Served):
    def test_changed_fields_are_written_for_the_game_and_the_group_comes_back(self) -> None:
        answer = self.ok(self.put("/game/g1", note="there"))

        self.assertEqual(STATE["saved"], [({"game_id": "g1", "vps_id": "vps-1",
                                            "name": "Taxi"}, {"note": "there"})])
        self.assertEqual(answer["title"], "Taxi notes")

    def test_a_key_the_group_does_not_offer_is_refused_and_nothing_is_saved(self) -> None:
        response = self.put("/game/g1", other="x")

        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(STATE["saved"], [])

    def test_a_save_that_raises_is_a_refusal_in_its_words_with_the_field_named(self) -> None:
        STATE["raises"] = ValueError("That note is too long")

        response = self.put("/game/g1", note="x")

        self.assertEqual(response.status_code, 400, response.text)
        error = response.json()["error"]
        self.assertEqual((error["message"], error["details"]),
                         ("That note is too long", {"field": "note"}))

    def test_a_group_with_no_save_cannot_be_written(self) -> None:
        response = self.put("/table/g1/t1", note="x")

        self.assertEqual(response.status_code, 404, response.text)
        self.assertEqual(
            response.json()["error"]["message"],
            t("error.extensions.no_group_save", display=self.record.display_name,
              subject="table"))

    def test_a_private_game_is_not_written_to(self) -> None:
        self.resource = HIDDEN

        response = self.put("/game/g1", note="x")

        self.assertEqual(response.status_code, 404, response.text)
        self.assertEqual((STATE["asked"], STATE["saved"]), ([], []))

    def test_a_private_games_table_is_not_written_to(self) -> None:
        self.resource = HIDDEN

        response = self.put("/table/g1/t1", note="x")

        self.assertEqual(response.status_code, 404, response.text)
        self.assertEqual((STATE["asked"], STATE["saved"]), ([], []))

    def test_writing_wants_the_write_scope_and_not_the_read_one(self) -> None:
        self.client = client_for(self, self.registry, self.record,
                                 allowed=lambda scope: scope.endswith(":read"))

        self.assertEqual(self.client.get(f"{self.base}/game/g1").status_code, 200)
        self.assertEqual(self.put("/game/g1", note="x").status_code, 403)
        self.assertEqual(STATE["saved"], [])


class Declared(Served):
    def test_a_switched_off_extension_lists_no_groups(self) -> None:
        self.record.state = host.DISABLED

        self.assertEqual(self.record.as_dict()["groups"], [])

    def test_the_record_lists_its_groups_with_the_title_resolved(self) -> None:
        self.assertEqual(
            [(one["subject"], one["title"], one["save"]) for one in self.record.groups()],
            [("game", "Taxi notes", True), ("table", "On this table", False)])

    def test_the_record_says_so_in_what_the_console_reads(self) -> None:
        self.assertEqual([one["subject"] for one in self.record.as_dict()["groups"]],
                         ["game", "table"])


class NotAllowed(unittest.TestCase):
    def test_an_extension_that_declares_a_group_without_the_scope_fails_to_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry = host.Registry(store.ExtensionStore(Path(tmp)))
            self.addCleanup(registry.clear)
            self.addCleanup(i18n.disown, f"ext.{NAME}")
            fresh_state()

            record = registry.load(_installed(Path(tmp) / "installed", []))

        self.assertNotEqual(record.state, host.LOADED)
        self.assertEqual(record.groups(), [])


if __name__ == "__main__":
    unittest.main()
