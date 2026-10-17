"""An extension's Online source: what the contract accepts, and what core serves of it."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from starlette.testclient import TestClient

import httpapi
from common import i18n
from common.extensions import contract, host, reach, sources, store
from common.extensions.context import ContractError, ExtensionSources
from common.extensions.contract import Unavailable
from common.i18n import t
from tests.support.accepted import owner_accepts
from tests.support.identity import IDENTITY
from tests.support.served import client_for

MODULE = "tests.extensions.test_online_sources"
NAME = "sourced"
KINDS = ["playfield_video", "pup_pack", "table"]
WEB = "https://pictures.example/cover.png"

PUBLIC = {"private": False, "vps_id": "vps-1", "name": "Taxi"}
HIDDEN = {"private": True, "vps_id": "vps-2", "name": "Secret"}

STATE: dict[str, Any] = {}


def fresh_state() -> None:
    STATE.clear()
    STATE.update(offers={"rows": []}, take={"message": "Done"}, asked=[], taken=[], off=[])


def sourced(ctx: Any) -> None:
    class Dialog:
        def ask(self, step: str) -> dict:
            return {"fields": []}

    def offers(who: dict, kind: str) -> Any:
        STATE["asked"].append((dict(who), kind))
        if isinstance(STATE["offers"], Exception):
            raise STATE["offers"]
        return STATE["offers"]

    def take(who: dict, kind: str, key: str) -> Any:
        STATE["taken"].append((dict(who), kind, key))
        if isinstance(STATE["take"], Exception):
            raise STATE["take"]
        return STATE["take"]

    ctx.ui.action("get", Dialog())
    ctx.sources.contribute("files", "Example Files", KINDS, offers=offers, take=take)


def _installed(root: Path, capabilities: list[str]) -> Path:
    directory = root / NAME
    (directory / "i18n").mkdir(parents=True)
    (directory / "extension.json").write_text(json.dumps({
        "name": NAME, "display_name": "Sourced", "version": "1.0.0",
        "description": "Offers files from a place online, for the tests that ask.",
        "requires_platform": contract.PLATFORM_ABI, **IDENTITY,
        "capabilities": capabilities, "scopes": ["games:read"]}), encoding="utf-8")
    (directory / "i18n" / "en.json").write_text(
        json.dumps({"action.get.label": "Get a file"}), encoding="utf-8")
    (directory / "__init__.py").write_text(
        f"from {MODULE} import sourced as register\n", encoding="utf-8")
    return directory


def _policy(test: unittest.TestCase) -> None:
    """The sources this install has switched off are whatever STATE says."""
    patch = mock.patch("common.games.library_policy.get_library_policy",
                       lambda: mock.Mock(get=lambda key: list(STATE["off"])))
    patch.start()
    test.addCleanup(patch.stop)


class Registry(unittest.TestCase):
    def setUp(self) -> None:
        fresh_state()
        sources.clear()
        self.addCleanup(sources.clear)
        _policy(self)

    def put(self, extension: str = "ext", key: str = "files",
            kinds: frozenset[str] = frozenset({"wheel"})) -> sources.Source:
        sources.register(extension, key, "Files", kinds, lambda who, kind: {},
                         lambda who, kind, row: {})
        held = sources.named(extension, key)
        assert held is not None
        return held

    def test_a_source_is_stored_under_its_extension_and_key(self) -> None:
        self.assertEqual("ext.files", self.put().id)

    def test_two_extensions_may_name_a_source_alike(self) -> None:
        self.put("one")
        self.put("two")

        self.assertEqual(["one.files", "two.files"], [one.id for one in sources.all_sources()])

    def test_a_key_is_lower_case_words_joined_by_underscores(self) -> None:
        for key in ("Files", "a b", "a.b", "1up", ""):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "lower-case words"):
                self.put(key=key)

    def test_a_source_that_offers_nothing_is_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "offers no kind"):
            self.put(kinds=frozenset())

    def test_a_kind_core_has_no_slot_for_is_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "no slot for"):
            self.put(kinds=frozenset({"wheel", "bogus"}))

    def test_a_kind_no_dialog_is_opened_for_is_refused(self) -> None:
        for kind in ("game_info", "patch", "media"):
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, "no slot for"):
                self.put(kinds=frozenset({kind}))

    def test_taking_an_extension_out_takes_its_sources(self) -> None:
        self.put("one")
        self.put("two")

        sources.forget("one")

        self.assertEqual(["two.files"], [one.id for one in sources.all_sources()])

    def test_switching_a_source_off_in_settings_is_read_by_its_id(self) -> None:
        held = self.put()
        self.assertTrue(sources.enabled(held))

        STATE["off"] = ["EXT.FILES"]
        self.assertFalse(sources.enabled(held))

        STATE["off"] = ["vpinmediadb"]
        self.assertTrue(sources.enabled(held))


class Names(unittest.TestCase):
    def test_a_kind_is_known_by_every_name_its_slot_may_be_opened_under(self) -> None:
        self.assertEqual({"alt_color", "altcolor_serum", "altcolor_vni"},
                         sources.names_for("alt_color"))
        self.assertEqual({"wheel"}, sources.names_for("wheel"))

    def test_a_table_is_not_the_playfield_picture(self) -> None:
        self.assertEqual({"table"}, sources.names_for("table"))
        self.assertNotIn("table", sources.names_for("playfield"))

    def test_the_backglass_file_is_not_the_backglass_picture(self) -> None:
        self.assertEqual({"backglass_file"}, sources.names_for("backglass_file"))
        self.assertNotIn("backglass_file", sources.names_for("backglass"))
        self.assertEqual("backglass_file", sources.file_kind("backglass"))
        self.assertEqual("pov", sources.file_kind("pov"))
        self.assertIn("backglass_file", sources.slot_kinds())

    def test_an_old_spelling_of_a_media_kind_means_the_kind_it_became(self) -> None:
        self.assertIn("backglass", sources.names_for("bg"))


class TheContract(unittest.TestCase):
    def setUp(self) -> None:
        fresh_state()
        sources.clear()
        self.addCleanup(sources.clear)

    def ctx(self, scopes: tuple[str, ...] = ("games:read",),
            reaches: tuple[str, ...] = (reach.PLAY, reach.LIBRARY)) -> ExtensionSources:
        return ExtensionSources("ext", scopes, reaches)

    def contribute(self, ctx: ExtensionSources, key: str = "files", name: str = "Files",
                   kinds: Any = ("wheel",), offers: Any = lambda who, kind: {},
                   take: Any = lambda who, kind, row: {}) -> None:
        ctx.contribute(key, name, kinds, offers=offers, take=take)

    def test_a_source_is_registered_for_the_kinds_it_names(self) -> None:
        self.contribute(self.ctx(), kinds=["wheel", "table"])

        held = sources.named("ext", "files")
        assert held is not None
        self.assertEqual((frozenset({"wheel", "table"}), "Files"), (held.kinds, held.name))

    def test_it_needs_to_read_games(self) -> None:
        with self.assertRaisesRegex(ContractError, "games:read"):
            self.contribute(self.ctx(scopes=()))

    def test_it_needs_the_library_tier(self) -> None:
        with self.assertRaisesRegex(ContractError, "tiers"):
            self.contribute(self.ctx(reaches=(reach.PLAY,)))

    def test_a_key_and_a_name_are_both_needed(self) -> None:
        for key, name in (("", "Files"), (" ", "Files"), ("files", ""), ("files", " ")):
            with self.subTest(key=key, name=name), self.assertRaisesRegex(
                    ContractError, "no key or name"):
                self.contribute(self.ctx(), key=key, name=name)

    def test_a_key_used_twice_is_refused(self) -> None:
        ctx = self.ctx()
        self.contribute(ctx)

        with self.assertRaisesRegex(ContractError, "twice"):
            self.contribute(ctx)

    def test_kinds_are_a_list_of_names(self) -> None:
        for kinds in ("wheel", 5, None):
            with self.subTest(kinds=kinds), self.assertRaisesRegex(
                    ContractError, "not a list of names"):
                self.contribute(self.ctx(), kinds=kinds)

    def test_offers_and_take_are_functions(self) -> None:
        with self.assertRaisesRegex(ContractError, "not a function"):
            self.contribute(self.ctx(), offers="no")
        with self.assertRaisesRegex(ContractError, "not a function"):
            self.contribute(self.ctx(), take=None)

    def test_a_refusal_from_the_registry_is_the_contracts_own_error(self) -> None:
        for key, kinds in (("Files", ["wheel"]), ("files", []), ("files", ["bogus"])):
            with self.subTest(key=key, kinds=kinds), self.assertRaises(ContractError):
                self.contribute(self.ctx(), key=key, kinds=kinds)

        self.assertEqual([], sources.all_sources())


class Served(unittest.TestCase):
    capabilities = ["ui:mount", "net:outbound"]

    def setUp(self) -> None:
        owner_accepts(self)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        fresh_state()
        sources.clear()
        self.addCleanup(sources.clear)
        _policy(self)
        self.store = store.ExtensionStore(self.root)
        self.registry = host.Registry(self.store)
        self.addCleanup(self.registry.clear)
        self.addCleanup(i18n.disown, f"ext.{NAME}")
        self.record = self.registry.load(_installed(self.root / "installed", self.capabilities))
        self.assertEqual(self.record.state, host.LOADED, self.record.error)
        self.client = client_for(self, self.registry, self.record)
        self.resources = {"g1": PUBLIC, "hidden": HIDDEN}
        patch = mock.patch("httpapi.extensions_served.game_lens.resource_of",
                           lambda game_id: dict(self.resources[game_id]))
        patch.start()
        self.addCleanup(patch.stop)

    def offers(self, kind: str = "playfield_video", game_id: str = "g1", key: str = "files",
               **who: str) -> Any:
        who = who or {"vps_id": "vps-9", "name": "Other"}
        return self.client.get(f"/ext/{NAME}/sources/{key}/offers",
                               params={"kind": kind, "game_id": game_id, **who})

    def take(self, row: str = "a", kind: str = "playfield_video", game_id: str = "g1",
             key: str = "files", table_id: str = "") -> Any:
        return self.client.post(f"/ext/{NAME}/sources/{key}/take", json={
            "kind": kind, "row": row,
            "who": {"game_id": game_id, "vps_id": "vps-9", "name": "Other",
                    "table_id": table_id}})

    def refused(self, response: Any, status: int, message: str = "") -> dict:
        self.assertEqual(status, response.status_code, response.text)
        error = response.json()["error"]
        if message:
            self.assertEqual(message, error["message"])
        return error

    def display(self) -> str:
        return self.record.display_name


class Withdrawn(Served):
    def test_a_loaded_extension_has_its_source_registered(self) -> None:
        held = sources.named(NAME, "files")
        assert held is not None
        self.assertEqual(frozenset(KINDS), held.kinds)

    def test_switching_the_extension_off_takes_its_source_with_it(self) -> None:
        with self.assertLogs(level="ERROR"):
            self.registry.disable(NAME, "switched off")

        self.assertIsNone(sources.named(NAME, "files"))


class Offering(Served):
    def test_it_is_asked_for_the_entry_the_slot_looks_up_and_the_kind_it_is_open_for(
            self) -> None:
        self.assertEqual(200, self.offers().status_code)

        self.assertEqual([({"game_id": "g1", "vps_id": "vps-9", "name": "Other", "table_id": ""},
                           "playfield_video")], STATE["asked"])

    def test_what_it_has_comes_back_checked(self) -> None:
        STATE["offers"] = {
            "rows": [{"key": "a", "name": " A table video ", "site": "example.com",
                      "page": "https://example.com/a", "note": "30 MB", "tag": "FSS",
                      "current": True, "picture": WEB},
                     {"key": "b", "name": "Another"}],
            "note": "More on the site",
            "link": {"text": "Open the site", "to": "https://example.com/"}}

        answer = self.offers().json()

        first, second = answer["rows"]
        self.assertRegex(first.pop("picture"), rf"^/api/v1/ext/{NAME}/pictures/.+")
        self.assertEqual({"key": "a", "name": "A table video", "site": "example.com",
                          "page": "https://example.com/a", "note": "30 MB", "tag": "FSS",
                          "current": True}, first)
        self.assertEqual({"key": "b", "name": "Another", "site": "", "page": "", "note": "",
                          "tag": "", "picture": "", "current": False}, second)
        self.assertEqual("More on the site", answer["note"])
        self.assertEqual({"text": "Open the site", "to": "https://example.com/"},
                         answer["link"])

    def test_an_answer_with_nothing_in_it_is_no_rows(self) -> None:
        for answer in (None, {}, {"rows": None}):
            STATE["offers"] = answer
            with self.subTest(answer=answer):
                self.assertEqual({"rows": [], "note": "", "link": None},
                                 self.offers().json())

    def test_a_link_to_the_extensions_settings_is_kept(self) -> None:
        STATE["offers"] = {"link": {"text": "Open Settings", "settings": True}}

        self.assertEqual({"text": "Open Settings", "settings": True},
                         self.offers().json()["link"])

    def test_a_private_game_is_not_asked_about(self) -> None:
        answer = self.offers(game_id="hidden")

        self.assertEqual({"rows": [], "note": "", "link": None}, answer.json())
        self.assertEqual([], STATE["asked"])

    def test_a_kind_the_source_does_not_offer_is_not_found(self) -> None:
        self.refused(self.offers(kind="wheel"), 404, t(
            "error.extensions.source_kind", display=self.display(), key="files",
            kind="wheel"))
        self.assertEqual([], STATE["asked"])

    def test_a_source_that_is_not_there_is_not_found(self) -> None:
        self.refused(self.offers(key="nope"), 404, t(
            "error.extensions.no_source", display=self.display(), key="nope"))

    def test_a_source_switched_off_in_settings_is_not_asked(self) -> None:
        STATE["off"] = [f"{NAME}.files"]

        self.refused(self.offers(), 400, t(
            "error.extensions.source_off", display=self.display(), key="files"))
        self.assertEqual([], STATE["asked"])

    def test_an_answer_of_a_shape_that_is_not_this_one_is_refused(self) -> None:
        wrong = {
            "an answer that is not an object": ["x"],
            "a key the answer does not have": {"rowz": []},
            "rows that are not a list": {"rows": "x"},
            "a row that is not an object": {"rows": ["x"]},
            "a row with no key": {"rows": [{"name": "A"}]},
            "a row with no name": {"rows": [{"key": "a"}]},
            "a field a row does not have": {"rows": [{"key": "a", "name": "A", "size": 3}]},
            "a field that is not text": {"rows": [{"key": "a", "name": "A", "tag": 5}]},
            "two rows with one key": {"rows": [{"key": "a", "name": "A"},
                                               {"key": "a", "name": "B"}]},
            "a page that is not a web address": {"rows": [
                {"key": "a", "name": "A", "page": "javascript:alert(1)"}]},
            "a note that is not text": {"note": 5},
            "a link that is not an object": {"link": "https://example.com/"},
            "a link with no text": {"link": {"to": "https://example.com/"}},
            "a link with two places to go": {"link": {
                "text": "x", "to": "https://example.com/", "settings": True}},
            "a link to something that is not a web address": {"link": {
                "text": "x", "to": "ftp://example.com/"}},
            "a link to a page nothing declared": {"link": {"text": "x", "page": "nope"}},
            "a link to a page that is not text": {"link": {"text": "x", "page": 5}},
            "a link to a page that is a list": {"link": {"text": "x", "page": ["a"]}},
            "a current that is not true or false": {"rows": [
                {"key": "a", "name": "A", "current": "yes"}]},
        }
        for what, answer in wrong.items():
            STATE["offers"] = answer
            with self.subTest(what):
                self.assertEqual(400, self.offers().status_code)

    def test_a_source_that_raises_is_said_and_costs_nothing_else(self) -> None:
        STATE["offers"] = ValueError("The host said no")
        said = self.refused(self.offers(), 400)
        self.assertIn("The host said no", said["message"])

        STATE["offers"] = Unavailable("The host did not answer")
        self.assertEqual(502, self.offers().status_code)

        STATE["offers"] = {"rows": []}
        self.assertEqual(200, self.offers().status_code)


class WithoutOutbound(Served):
    capabilities = ["ui:mount"]

    def test_a_picture_from_the_web_needs_the_capability_to_reach_it(self) -> None:
        STATE["offers"] = {"rows": [{"key": "a", "name": "A", "picture": WEB}]}

        self.refused(self.offers(), 400, t(
            "error.extensions.picture_outbound", display=self.display(),
            key="source files offers"))

    def test_a_picture_in_the_extension_is_fine(self) -> None:
        STATE["offers"] = {"rows": [{"key": "a", "name": "A", "picture": "art/a.png"}]}

        self.assertEqual(200, self.offers().status_code)


class Taking(Served):
    def test_a_pick_is_called_with_the_row_the_kind_and_the_game(self) -> None:
        self.assertEqual(200, self.take(row="a").status_code)

        self.assertEqual([({"game_id": "g1", "vps_id": "vps-9", "name": "Other", "table_id": ""},
                           "playfield_video", "a")], STATE["taken"])

    def test_a_pick_is_told_the_table_the_file_is_saved_for(self) -> None:
        self.assertEqual(200, self.take(table_id="t1").status_code)

        self.assertEqual("t1", STATE["taken"][0][0]["table_id"])

    def test_it_answers_a_job_a_dialog_or_a_message(self) -> None:
        for answer in ({"job": "j1", "message": "Started"}, {"job": "j1"}, {"action": "get"},
                       {"message": "Nothing to do"}):
            STATE["take"] = answer
            with self.subTest(answer=answer):
                response = self.take()
                self.assertEqual(200, response.status_code, response.text)
                self.assertEqual(answer, response.json())

    def test_a_dialog_the_extension_never_declared_is_refused(self) -> None:
        STATE["take"] = {"action": "nope"}

        self.assertEqual(400, self.take().status_code)

    def test_an_answer_that_is_not_one_of_the_three_is_refused(self) -> None:
        wrong = {
            "nothing": {},
            "no answer": None,
            "a job and a dialog": {"job": "j1", "action": "get"},
            "a dialog and a message": {"action": "get", "message": "x"},
            "a key it does not have": {"link": "x"},
            "an empty job": {"job": " "},
            "a job that is not text": {"job": ["x"]},
            "a dialog that is not text": {"action": ["get"]},
            "a message that is not text": {"message": 5},
            "a message of nothing but space": {"message": "  "},
            "a list": ["x"],
        }
        for what, answer in wrong.items():
            STATE["take"] = answer
            with self.subTest(what):
                self.assertEqual(400, self.take().status_code)

    def test_a_blank_message_beside_a_job_is_no_message(self) -> None:
        STATE["take"] = {"job": "j1", "message": "  "}

        response = self.take()

        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual({"job": "j1"}, response.json())

    def test_a_source_that_raises_is_said(self) -> None:
        STATE["take"] = ValueError("The host said no")

        self.assertIn("The host said no", self.refused(self.take(), 400)["message"])

    def test_a_private_game_is_never_taken_into(self) -> None:
        self.refused(self.take(game_id="hidden"), 404, t(
            "error.extensions.verb_none", display=NAME, key="files"))
        self.assertEqual([], STATE["taken"])

    def test_a_kind_the_source_does_not_offer_is_not_found(self) -> None:
        self.assertEqual(404, self.take(kind="wheel").status_code)
        self.assertEqual([], STATE["taken"])

    def test_a_source_switched_off_in_settings_is_not_taken_from(self) -> None:
        STATE["off"] = [f"{NAME}.files"]

        self.assertEqual(400, self.take().status_code)
        self.assertEqual([], STATE["taken"])


class Listed(Served):
    def setUp(self) -> None:
        super().setUp()
        self.api = TestClient(httpapi.create_api_app(), raise_server_exceptions=False)

    def listed(self) -> dict:
        response = self.api.get("/media-sources")
        self.assertEqual(200, response.status_code, response.text)
        return next(one for one in response.json()["sources"] if one.get("extension") == NAME)

    def test_settings_lists_it_with_the_kinds_it_offers_and_who_offers_it(self) -> None:
        self.assertEqual({"id": f"{NAME}.files", "name": "Example Files", "url": "",
                          "enabled": True, "kinds": sorted(KINDS), "extension": NAME,
                          "key": "files"}, self.listed())

    def test_its_switch_follows_what_settings_has_switched_off(self) -> None:
        STATE["off"] = [f"{NAME}.files"]

        self.assertFalse(self.listed()["enabled"])


if __name__ == "__main__":
    unittest.main()
