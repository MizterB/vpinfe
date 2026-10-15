"""An extension's own page: where the rail puts it and how a view key finds it."""

from __future__ import annotations

import asyncio
import unittest
from collections.abc import Callable
from typing import Any
from unittest.mock import Mock, patch

from nicegui import ui

from manager import community, deeplink, ext_pages, page

DECLARED = {"key": "week", "title": "This week", "area": "community", "base": "/pages/week",
            "about": "/pages/week/about", "save": False}
LOADED = {"name": "site", "state": "loaded", "display_name": "Site", "pages": [DECLARED]}
VIEW = "page:site:week"


class TheNav(unittest.TestCase):
    def test_a_running_extensions_page_sits_under_community(self) -> None:
        items = community.nav_items([LOADED, {**LOADED, "name": "off", "state": "failed"}])
        groups = dict(page.nav_for(None, items))

        self.assertEqual([VIEW], [one[0] for one in groups[page.NAV_COMMUNITY]])

    def test_a_page_in_system_sits_before_about(self) -> None:
        system = {**DECLARED, "area": "system"}
        items = community.nav_items([{**LOADED, "pages": [system]}])
        keys = [one[0] for one in dict(page.nav_for(None, items))[page.NAV_SYSTEM]]

        self.assertEqual([VIEW, "about"], keys[-2:])

    def test_a_page_follows_the_extensions_lists_in_its_area(self) -> None:
        listed = {"key": "plays", "title": "Plays", "area": "community", "columns": [],
                  "views": [], "verbs": [], "add": [], "detail": False}
        items = community.nav_items([{**LOADED, "lists": [listed]}])
        keys = [one[0] for one in dict(page.nav_for(None, items))[page.NAV_COMMUNITY]]

        self.assertEqual(["community:site:plays", VIEW], keys)


class TheAddress(unittest.TestCase):
    def test_a_key_with_capitals_comes_back_from_the_address(self) -> None:
        state: dict = {}
        view = "page:site:WeekOne"

        deeplink.apply(state, {"view": view}, views=["games", view], sections=[])

        self.assertEqual(view, state["view"])
        self.assertIn(view, deeplink.query(state))

    def test_an_address_in_other_case_finds_the_same_view(self) -> None:
        state: dict = {}

        deeplink.apply(state, {"view": "GAMES"}, views=["games"], sections=[])

        self.assertEqual("games", state["view"])


class Finding(unittest.TestCase):
    def test_a_view_finds_the_page_it_names(self) -> None:
        self.assertEqual(ext_pages.find(VIEW, [LOADED]), (LOADED, DECLARED))

    def test_a_list_view_or_an_unknown_one_finds_none(self) -> None:
        self.assertIsNone(ext_pages.find("community:site:week", [LOADED]))
        self.assertIsNone(ext_pages.find("page:site:other", [LOADED]))
        self.assertIsNone(ext_pages.find("page:other:week", [LOADED]))

    def test_an_extension_that_is_not_running_has_no_page(self) -> None:
        self.assertIsNone(ext_pages.find(VIEW, [{**LOADED, "state": "failed"}]))

    def test_is_page_reads_the_view_key(self) -> None:
        self.assertTrue(ext_pages.is_page(VIEW))
        self.assertFalse(ext_pages.is_page("community:site:week"))

    def test_the_route_is_under_the_extension(self) -> None:
        self.assertEqual(ext_pages.route(LOADED, DECLARED), "/ext/site/pages/week")


async def _here(callback: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    return callback(*args, **kwargs)


ANSWER = {"title": "Weekly", "under": "Since Monday", "picture": "",
          "sections": [{"key": "now", "label": "Totals", "rows": [],
                        "fields": [{"key": "note", "type": "string", "label": "Note",
                                    "value": "hi"}],
                        "facts": [{"label": "Dashboard", "value": "Open", "kind": "link",
                                   "to": "http://{host}:9090/"}]}]}


class Drawn(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        # Outside the test's task, which has no page to draw into.
        self.body = ui.column()
        self.subject = ui.row()
        self.get = Mock(return_value=ANSWER)
        client = Mock()
        client.ext_get = self.get
        self.enterContext(patch.object(ext_pages.offload, "io", new=_here))
        self.enterContext(patch.object(ext_pages, "ApiClient", return_value=client))
        self.enterContext(patch.object(community, "as_it_stands", return_value=LOADED))
        self.enterContext(patch.object(community, "standing", return_value={}))
        self.menu = self.enterContext(patch.object(ext_pages.panel, "subject_menu"))

    async def show(self, answer: dict | None = None, host: str = "cab.lan") -> list[Any]:
        with self.body:
            await ext_pages.show(self.body, LOADED, DECLARED, self.subject, host, answer)
        await asyncio.gather(*(asyncio.all_tasks() - {asyncio.current_task()}))
        return list(self.body.descendants())

    @staticmethod
    def said(drawn: list[Any]) -> list[str]:
        return [str(getattr(one, "text", "")) for one in drawn]

    async def test_it_reads_the_page_from_its_route_and_draws_what_it_says(self) -> None:
        drawn = await self.show()

        self.get.assert_called_once_with("/ext/site/pages/week")
        for word in ("Weekly", "Since Monday", "Totals"):
            self.assertIn(word, self.said(drawn))
        self.menu.assert_called_once()

    async def test_a_link_fact_is_filled_with_the_host_the_manager_was_opened_at(self) -> None:
        drawn = await self.show(host="cab.lan")

        links = [str(one.props.get("href")) for one in drawn if one.props.get("href")]
        self.assertEqual(["http://cab.lan:9090/"], links)

    async def test_an_answer_handed_in_is_drawn_without_a_read(self) -> None:
        drawn = await self.show({**ANSWER, "title": "Kept"})

        self.get.assert_not_called()
        self.assertIn("Kept", self.said(drawn))

    async def test_a_read_that_fails_says_so_and_keeps_the_menu(self) -> None:
        self.get.side_effect = RuntimeError("down")

        drawn = await self.show()

        said = " ".join(self.said(drawn))
        self.assertIn("Site", said)
        self.assertIn("down", said)
        self.menu.assert_called_once()

    async def test_a_page_drawn_again_replaces_what_was_there(self) -> None:
        await self.show()
        drawn = await self.show({**ANSWER, "title": "Later"})

        self.assertIn("Later", self.said(drawn))
        self.assertNotIn("Weekly", self.said(drawn))


if __name__ == "__main__":
    unittest.main()
