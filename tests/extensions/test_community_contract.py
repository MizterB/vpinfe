"""A list an extension declares for Community, and the ones it may not."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from starlette.testclient import TestClient

import httpapi
from common import extensions
from common.extensions import host, store
from common.extensions.context import ContractError, ExtensionUI

ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "community"
WEEK = "https://challenge.example/week"

COLUMNS = [{"field": "name", "header": "Table"},
           {"field": "plays", "header": "Plays", "kind": "number"},
           {"field": "vpsId", "header": "VPS"}]


def _rows() -> list[dict]:
    return []


def _mark(rows: list) -> None:
    return None


class TheDeclaration(unittest.TestCase):
    def setUp(self) -> None:
        self.ui = ExtensionUI("site", allowed=True)

    def test_a_list_is_recorded_as_data(self) -> None:
        self.ui.list("tables", _rows, title="Site", columns=COLUMNS,
                     views=[{"key": "plays", "name": "Most played",
                             "columns": ["name", "plays"],
                             "sort": [{"field": "plays", "desc": True}]}],
                     relation={"field": "vpsId", "keys": "vps_entry"})

        (said,) = self.ui.declared_lists
        self.assertEqual(("tables", ["text", "number", "text"],
                          [{"field": "plays", "desc": True}], "vps_entry"),
                         (said["key"], [one["kind"] for one in said["columns"]],
                          said["views"][0]["sort"], said["relation"]["keys"]))

    def test_a_kind_core_does_not_draw_is_refused(self) -> None:
        with self.assertRaises(ContractError):
            self.ui.list("tables", _rows, title="Site",
                         columns=[{"field": "art", "header": "Art", "kind": "html"}])

    def test_a_view_on_a_column_it_does_not_have_is_refused(self) -> None:
        with self.assertRaises(ContractError):
            self.ui.list("tables", _rows, title="Site", columns=COLUMNS,
                         views=[{"key": "top", "sort": [{"field": "rating"}]}])

    def test_a_view_with_no_key_is_refused(self) -> None:
        """The key is what its words are found by, in the extension's catalog."""
        with self.assertRaises(ContractError):
            self.ui.list("tables", _rows, columns=COLUMNS,
                         views=[{"name": "Top", "sort": [{"field": "plays"}]}])

    def test_a_line_under_the_first_column_is_kept(self) -> None:
        self.ui.list("tables", _rows, title="Site",
                     columns=[{**COLUMNS[0], "under": ["maker", "year"]}, *COLUMNS[1:]])

        self.assertEqual(["maker", "year"],
                         self.ui.declared_lists[0]["columns"][0]["under"])

    def test_a_line_under_any_other_column_is_refused(self) -> None:
        with self.assertRaises(ContractError):
            self.ui.list("tables", _rows, title="Site",
                         columns=[COLUMNS[0], {**COLUMNS[1], "under": ["year"]}])

    def test_a_relation_by_anything_but_a_vps_id_is_refused(self) -> None:
        with self.assertRaises(ContractError):
            self.ui.list("tables", _rows, title="Site", columns=COLUMNS,
                         relation={"field": "name", "keys": "rom"})

    def test_a_tag_is_recorded_as_a_tag_would_be_stored(self) -> None:
        self.ui.list("tables", _rows, title="Site", columns=COLUMNS,
                     relation={"field": "vpsId", "keys": "vps_release"},
                     tag=" Weekly   Challenge ")

        self.assertEqual("Weekly Challenge", self.ui.declared_lists[0]["tag"])

    def test_a_tag_on_a_list_that_relates_to_nothing_is_refused(self) -> None:
        """The tag lands on what the list relates to, so without a relation it would
        land nowhere and say nothing about why."""
        with self.assertRaises(ContractError):
            self.ui.list("tables", _rows, title="Site", columns=COLUMNS, tag="Challenge")

    def test_a_view_ranks_by_numbers_and_dates(self) -> None:
        self.ui.list("scores", _rows, title="Site",
                     columns=[*COLUMNS, {"field": "set", "kind": "date"}],
                     views=[{"key": "top", "ranks": True,
                             "sort": [{"field": "plays", "desc": True},
                                      {"field": "set"}]},
                            {"key": "all", "sort": [{"field": "name"}]}],
                     relation={"field": "vpsId", "keys": "vps_release"})

        self.assertEqual([True, False],
                         [one["ranks"] for one in self.ui.declared_lists[0]["views"]])

    def test_a_ranked_view_sorting_on_text_is_refused(self) -> None:
        """A ranking is a number a game has; a name sorts but ranks nothing."""
        with self.assertRaises(ContractError):
            self.ui.list("tables", _rows, title="Site", columns=COLUMNS,
                         views=[{"key": "top", "ranks": True,
                                 "sort": [{"field": "plays", "desc": True},
                                          {"field": "name"}]}],
                         relation={"field": "vpsId", "keys": "vps_entry"})

    def test_a_ranked_view_with_no_sort_is_refused(self) -> None:
        with self.assertRaises(ContractError):
            self.ui.list("tables", _rows, title="Site", columns=COLUMNS,
                         views=[{"key": "top", "ranks": True}],
                         relation={"field": "vpsId", "keys": "vps_entry"})

    def test_a_ranked_view_of_a_list_that_relates_to_nothing_is_refused(self) -> None:
        with self.assertRaises(ContractError):
            self.ui.list("tables", _rows, title="Site", columns=COLUMNS,
                         views=[{"key": "top", "ranks": True,
                                 "sort": [{"field": "plays", "desc": True}]}])

    def test_it_needs_the_capability_to_draw(self) -> None:
        with self.assertRaises(ContractError):
            ExtensionUI("site", allowed=False).list("tables", _rows, columns=COLUMNS)

    def test_the_routes_core_serves_it_on_are_recorded(self) -> None:
        self.ui.list("tables", _rows, title="Site", columns=COLUMNS)

        (said,) = self.ui.declared_lists
        self.assertEqual(("/lists/tables", "/lists/tables/about"),
                         (said["base"], said["about"]))

    def test_a_list_is_in_community_unless_it_says_otherwise(self) -> None:
        self.ui.list("tables", _rows, columns=COLUMNS)
        self.ui.list("scores", _rows, columns=COLUMNS, area="library")

        self.assertEqual(["community", "library"],
                         [one["area"] for one in self.ui.declared_lists])

    def test_an_area_core_does_not_draw_is_refused(self) -> None:
        for area in ("Community", "sidebar", "provides"):
            with self.subTest(area=area), self.assertRaises(ContractError):
                self.ui.list("tables", _rows, columns=COLUMNS, area=area)
        self.assertEqual([], self.ui.declared_lists)

    def test_rows_that_are_not_a_function_are_refused(self) -> None:
        for rows in ("/community/tables", None, [{"name": "AFM"}]):
            with self.subTest(rows=rows), self.assertRaises(ContractError):
                self.ui.list("tables", rows, columns=COLUMNS)

    def test_a_status_or_acts_that_are_not_what_core_calls_are_refused(self) -> None:
        with self.assertRaises(ContractError):
            self.ui.list("tables", _rows, columns=COLUMNS, status="/tables/about")
        with self.assertRaises(ContractError):
            self.ui.list("scores", _rows, columns=COLUMNS, acts=["post"])

    def test_a_key_declared_twice_is_refused(self) -> None:
        self.ui.list("tables", _rows, columns=COLUMNS)

        with self.assertRaises(ContractError):
            self.ui.list("tables", _rows, columns=COLUMNS)

    def test_verbs_are_recorded_as_data_without_their_functions(self) -> None:
        self.ui.list("tables", _rows, columns=COLUMNS, verbs=[
            {"key": "mark", "run": _mark, "danger": True, "needs": "ok", "one": True,
             "label": "Mark"},
            {"key": "open", "link": "page"}])

        (said,) = self.ui.declared_lists
        self.assertEqual(
            [{"key": "mark", "label": "Mark", "link": "", "danger": True, "needs": "ok",
              "one": True},
             {"key": "open", "label": "", "link": "page", "danger": False, "needs": "",
              "one": True}], said["verbs"])
        self.assertIs(self.ui.list_functions["tables"].verbs["mark"]["run"], _mark)

    def test_a_verb_core_cannot_read_is_refused_with_what_it_reads(self) -> None:
        with self.assertRaises(ContractError) as raised:
            self.ui.list("tables", _rows, columns=COLUMNS,
                         verbs=[{"key": "mark", "run": _mark, "confirm": "Sure?"}])

        self.assertIn("confirm", str(raised.exception))
        self.assertIn("danger", str(raised.exception))
        self.assertEqual([], self.ui.declared_lists)

    def test_a_verb_wrongly_given_is_refused(self) -> None:
        wrong = {
            "not a dict": ["mark"],
            "no key": {"run": _mark},
            "neither run nor link": {"key": "mark"},
            "both run and link": {"key": "mark", "run": _mark, "link": "page"},
            "run that is not a function": {"key": "mark", "run": "mark"},
            "danger on a link": {"key": "open", "link": "page", "danger": True},
            "needs on a link": {"key": "open", "link": "page", "needs": "ok"},
        }
        for what, verb in wrong.items():
            with self.subTest(what), self.assertRaises(ContractError):
                self.ui.list("tables", _rows, columns=COLUMNS, verbs=[verb])
        self.assertEqual([], self.ui.declared_lists)

    def test_two_verbs_with_one_key_are_refused(self) -> None:
        with self.assertRaises(ContractError):
            self.ui.list("tables", _rows, columns=COLUMNS,
                         verbs=[{"key": "mark", "run": _mark}, {"key": "mark", "run": _mark}])


class HowTheListStands(unittest.TestCase):
    """The fixture's Ratings list answers a line and its acts from its settings, through
    the routes core writes."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = store.ExtensionStore(Path(tmp.name))
        self.registry = host.Registry(self.store)
        extensions.set_registry(self.registry)
        self.addCleanup(extensions.set_registry, host.Registry())
        self.addCleanup(self.registry.clear)
        self.registry.load_from(ROOT)
        self.client = TestClient(httpapi.create_api_app(), raise_server_exceptions=False)

    def about(self) -> dict:
        answer = self.client.get("/ext/challenge/lists/ratings/about")
        answer.raise_for_status()
        return answer.json()

    def test_the_declaration_names_the_route_for_core(self) -> None:
        (found,) = [one for one in self.client.get("/extensions").json()["extensions"]
                    if one["name"] == "challenge"]

        self.assertEqual({"machines": "/lists/machines/about",
                          "releases": "/lists/releases/about",
                          "ratings": "/lists/ratings/about",
                          "builds": "/lists/builds/about"},
                         {one["key"]: one["about"] for one in found["lists"]})
        self.assertEqual({"community"}, {one["area"] for one in found["lists"]})

    def test_a_line_and_the_acts_that_can_work_now(self) -> None:
        self.store.set_setting("challenge", "status", "Ends Sunday")
        self.store.set_setting("challenge", "status_to", "settings")
        self.store.set_setting("challenge", "waiting", "afm,mm")

        self.assertEqual({"status": {"text": "Ends Sunday", "to": "settings"},
                          "acts": [{"key": "post", "label": "Post Now"},
                                   {"key": "week", "label": "This Week", "url": WEEK}]},
                         self.about())

    def test_an_act_is_pressed_on_the_route_under_it(self) -> None:
        self.store.set_setting("challenge", "waiting", "afm,mm")

        said = self.client.post("/ext/challenge/lists/ratings/about/acts/post")

        self.assertEqual((200, {"message": "Posted 2"}), (said.status_code, said.json()))
        self.assertEqual(["week"], [one["key"] for one in self.about()["acts"]])

    def test_an_act_the_list_does_not_offer_now_is_not_found(self) -> None:
        said = self.client.post("/ext/challenge/lists/ratings/about/acts/post")

        self.assertEqual(404, said.status_code)

    def test_a_stopped_extension_answers_neither(self) -> None:
        self.registry.disable("challenge", "switched off")

        self.assertEqual(
            (501, 501),
            (self.client.get("/ext/challenge/lists/ratings/about").status_code,
             self.client.post("/ext/challenge/lists/ratings/about/acts/post").status_code))


def _extension(root: Path, name: str, *titles: tuple[str, str]) -> Path:
    """A folder holding an extension whose lists are `(area, title)`, titled as written."""
    folder = root / name
    folder.mkdir()
    (folder / "extension.json").write_text(json.dumps({
        "name": name, "display_name": name.title(), "version": "1.0.0",
        "requires_platform": 1, "capabilities": ["ui:mount"]}))
    declared = "".join(
        f"    ctx.ui.list('l{n}', lambda: [], area={area!r}, title={title!r},"
        " columns=[{'field': 'name', 'header': 'Name'}])\n"
        for n, (area, title) in enumerate(titles))
    (folder / "__init__.py").write_text(f"def register(ctx):\n{declared}")
    return folder


class WhatAListMayBeTitled(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        state = self.root / "state"
        state.mkdir()
        self.registry = host.Registry(store.ExtensionStore(state))
        self.addCleanup(self.registry.clear)

    def load(self, name: str, *titles: tuple[str, str]) -> host.Record:
        return self.registry.load(_extension(self.root, name, *titles))

    def test_a_list_titled_as_a_core_page_does_not_load(self) -> None:
        record = self.load("site", ("community", "Games"))

        self.assertEqual(host.FAILED, record.state)
        self.assertIn("Games", record.error)

    def test_the_comparison_ignores_case(self) -> None:
        self.assertEqual(host.FAILED, self.load("site", ("system", "ABOUT")).state)

    def test_two_lists_with_one_title_in_one_area_do_not_both_load(self) -> None:
        self.assertEqual(host.LOADED, self.load("one", ("community", "Scores")).state)
        self.assertEqual(host.FAILED, self.load("two", ("community", "scores")).state)

    def test_one_title_in_two_areas_is_two_lists(self) -> None:
        self.assertEqual(host.LOADED, self.load("one", ("community", "Scores")).state)
        self.assertEqual(host.LOADED, self.load("two", ("library", "Scores")).state)

    def test_the_failed_one_leaves_nothing_declared(self) -> None:
        record = self.load("site", ("community", "Games"))

        self.assertEqual([], record.declared_lists)


if __name__ == "__main__":
    unittest.main()
