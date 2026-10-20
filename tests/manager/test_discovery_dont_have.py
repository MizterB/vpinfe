"""Games You Don't Have on Discovery's front page: the shelf drawn from one read, what a
tile says, and the menu on it."""

from __future__ import annotations

import asyncio
import unittest
from typing import Any
from unittest import mock

from nicegui import core, run, ui

from common.online import vps_home, vps_marks
from manager.kit.data import Library
from manager.library import discovery, discovery_marks
from manager.library import discovery_home as home

# Made at import, outside any task, where NiceGUI still hands out the script's own page.
_PAGE = ui.element()

KEPT = ["tableFiles", "b2sFiles"]


def _table(rid: str, by: int, fmt: str = "VPX") -> dict[str, Any]:
    return {"id": rid, "by": [by], "added": "2020-01-01T00:00:00Z", "held": False,
            "mod": False, "version": "", "format": fmt}


def _entry(vps_id: str, name: str, tables: list[dict[str, Any]], *, in_library: bool = False,
           manufacturer: str = "", year: int | None = None) -> dict[str, Any]:
    return {"vps_id": vps_id, "name": name, "in_library": in_library, "img_url": "",
            "manufacturer": manufacturer, "year": year, "type": "", "themes": [], "url": "",
            "listed": ["tableFiles"], "held": [], "releases": {"tableFiles": tables}}


PEOPLE: list[dict[str, Any]] = [{"name": name, "aliases": [], "releases": 4}
                                for name in ("Ann", "Bo", "Cy")]
FOUND: dict[str, Any] = {"counted": "2026-10-01T10:00:00Z", "people": PEOPLE, "rows": [
    _entry("g1", "Alien", [_table("t1", 0)], in_library=True),
    _entry("g2", "Batman", [_table("t2", 0), _table("t3", 1), _table("t4", 2)],
           manufacturer="Williams", year=1997),
    _entry("g3", "Cactus", [_table("t5", 0)], manufacturer="Bally"),
    _entry("g4", "Dune", [_table("t6", 0, "FP")]),
]}


def _words(body: ui.element) -> list[str]:
    return [str(one.text) for one in body.descendants()
            if isinstance(one, ui.label) and not one.is_deleted]


async def _settle() -> None:
    for _ in range(8):
        await asyncio.sleep(0)


class DrivenShelf(unittest.IsolatedAsyncioTestCase):
    """Home drawn by `_fill_home`, through the Library and a client that answers."""

    def setUp(self) -> None:
        self.client = mock.Mock()
        self.client.library_policy.return_value = {"hidden_asset_kinds": [],
                                                   "hidden_media_kinds": []}
        self.client.catalog_discovery.return_value = FOUND
        self.client.discovery_marks.return_value = []
        self.client.preferences.return_value = {}
        self.client.discovery_home.side_effect = self._answer
        self.library = Library(self.client)
        self.library.load_kept_kinds()
        self.found = FOUND
        self.state: dict[str, Any] = {}
        self.selected: list[Any] = []

        async def inline(call: Any, *args: Any, **more: Any) -> Any:
            return call(*args, **more)

        for patcher in (
                mock.patch.object(run, "io_bound", inline),
                mock.patch.object(vps_home.arrivals, "was", return_value=""),
                mock.patch.object(home.remembered, "get", return_value=None),
                mock.patch.object(discovery.deeplink, "sync")):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _answer(self, days: int) -> dict[str, Any]:
        return vps_home.home(self.found, KEPT, days,
                             marks=vps_marks.Marks(self.client.discovery_marks()))

    async def asyncSetUp(self) -> None:
        was = core.loop
        core.loop = asyncio.get_running_loop()
        self.addCleanup(setattr, core, "loop", was)

    async def _select(self, row: Any) -> None:
        self.selected.append(row)

    async def _draw(self) -> ui.element:
        with _PAGE:
            body = ui.column()
            await discovery._fill_home(self.library, body, self.state, self._select, mock.Mock())
        await _settle()
        return body

    async def test_the_shelf_lists_the_games_the_library_lacks_with_the_most_authors_first(
            self) -> None:
        words = _words(await self._draw())

        self.assertIn("Games You Don't Have", words)
        self.assertIn("Most authors first", words)
        self.assertLess(words.index("Batman"), words.index("Cactus"))
        self.assertIn("Tables by 3 authors", words)
        self.assertIn("Tables by 1 author", words)

    async def test_a_tile_says_who_made_the_game_and_when(self) -> None:
        words = _words(await self._draw())

        self.assertIn("Williams 1997", words)
        self.assertIn("Bally", words)

    async def test_a_game_the_library_holds_or_without_a_table_it_plays_is_not_on_it(
            self) -> None:
        words = _words(await self._draw())

        self.assertNotIn("Dune", words)
        # Alien is on the New shelf at most: its table is dated 2020, outside the window.
        self.assertNotIn("Alien", words)

    async def test_the_shelf_follows_the_missing_shelf_and_comes_before_the_authors(
            self) -> None:
        self.found = {**FOUND, "rows": [
            *FOUND["rows"],
            {**_entry("g5", "Eden", [_table("t7", 0)], in_library=True),
             "listed": ["tableFiles", "b2sFiles"],
             "releases": {"tableFiles": [{**_table("t7", 0), "held": True}],
                          "b2sFiles": [_table("b7", 1)]}}]}

        words = _words(await self._draw())

        self.assertLess(words.index("Missing from Your Games"),
                        words.index("Games You Don't Have"))
        self.assertLess(words.index("Games You Don't Have"), words.index("Authors You Collect"))

    async def test_nothing_to_have_draws_no_shelf(self) -> None:
        self.found = {**FOUND, "rows": [FOUND["rows"][0]]}

        self.assertNotIn("Games You Don't Have", _words(await self._draw()))

    async def test_a_library_never_compared_draws_no_shelf(self) -> None:
        self.found = {**FOUND, "counted": "", "rows": [
            {**row, "in_library": None} for row in FOUND["rows"]]}

        self.assertNotIn("Games You Don't Have", _words(await self._draw()))

    async def test_an_ignored_game_leaves_the_shelf(self) -> None:
        self.client.discovery_marks.return_value = [
            {"state": "ignored", "scope": "game", "id": "g2", "detail": "", "since": "x"}]

        words = _words(await self._draw())

        self.assertNotIn("Batman", words)
        self.assertIn("Cactus", words)

    async def test_a_wanted_game_stays_on_the_shelf_and_the_wanted_one(self) -> None:
        self.client.discovery_marks.return_value = [
            {"state": "wanted", "scope": "game", "id": "g2", "detail": "", "since": "x"}]

        words = _words(await self._draw())

        self.assertEqual(words.count("Batman"), 2)

    async def test_each_tile_has_a_menu(self) -> None:
        body = await self._draw()

        tiles = [one for one in body.descendants()
                 if not one.is_deleted and "manager-shelf-tile" in one.classes
                 and any(isinstance(child, ui.label) and child.text == "Tables by 1 author"
                         for child in one.descendants())]

        self.assertEqual(len(tiles), 1)
        self.assertEqual(sum(isinstance(child, ui.context_menu)
                             for child in tiles[0].descendants()), 1)


def _labels(entries: list[Any]) -> list[str]:
    return [one.label for one in entries]


def _mark(state: str, scope: str, one: str) -> dict[str, str]:
    return {"state": state, "scope": scope, "id": one, "detail": "", "since": "x"}


class MenuTests(unittest.TestCase):
    ITEM = {"vps_id": "g2", "game": "Batman", "authors": 3, "manufacturer": "", "year": ""}

    def _verbs(self, *marked: dict[str, str]) -> list[str]:
        library = mock.Mock(spec=Library)
        library.marks.return_value = list(marked)
        return _labels(discovery_marks.Marking(library, mock.AsyncMock()).verbs(
            discovery_marks.DONT_HAVE, self.ITEM, "", ""))

    def test_a_game_can_be_wanted_or_ignored(self) -> None:
        self.assertEqual(self._verbs(), ["Add to Wanted", "Ignore Game"])

    def test_a_wanted_game_can_be_taken_off(self) -> None:
        self.assertEqual(self._verbs(_mark("wanted", "game", "g2")),
                         ["Remove from Wanted", "Ignore Game"])

    def test_an_ignored_game_can_be_stopped(self) -> None:
        self.assertEqual(self._verbs(_mark("ignored", "game", "g2")),
                         ["Add to Wanted", "Stop Ignoring"])

    def test_the_menu_is_titled_with_the_game(self) -> None:
        marking = discovery_marks.Marking(mock.Mock(spec=Library), mock.AsyncMock())

        self.assertEqual(marking.title(discovery_marks.DONT_HAVE, self.ITEM), "Batman")

    def test_a_game_is_wanted_by_its_own_mark(self) -> None:
        library = mock.Mock(spec=Library)
        library.marks.return_value = [_mark("wanted", "game", "g2"),
                                      _mark("wanted", "release", "g3")]
        marking = discovery_marks.Marking(library, mock.AsyncMock())

        self.assertTrue(marking.wanted_game("g2"))
        self.assertFalse(marking.wanted_game("g3"))


if __name__ == "__main__":
    unittest.main()
