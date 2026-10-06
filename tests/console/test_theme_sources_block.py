"""Settings > Themes, the sources block: what a change writes, and what it leaves alone."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

import httpapi
from common import paths
from common.online import theme_source_checks as checks
from console import offload, panel, theme_sources

LISTS, THEMES = theme_sources.LISTS, theme_sources.THEMES

ONE = "https://example.test/one/themes.json"
TWO = "https://example.test/two/themes.json"
THREE = "https://example.test/three/themes.json"
THEME = "https://github.com/owner/neon"


def source(address: str, **fields: Any) -> dict[str, Any]:
    return {"address": address, "name": address, "state": "ready", "level": "", **fields}


class Written:
    """A Library that only records what the block asked of it."""

    def __init__(self, sources: dict[str, list[dict[str, Any]]]) -> None:
        self.sources = sources
        self.writes: list[dict[str, Any]] = []
        self.reads = 0

    def put_config(self, changes: dict[str, Any]) -> dict[str, Any]:
        self.writes.append(changes)
        for group, addresses in changes["themes"].items():
            self.sources[group] = [source(one) for one in addresses]
        return {}

    def theme_sources(self) -> dict[str, Any]:
        return self.sources

    def themes(self, refresh: bool = False) -> dict[str, Any]:
        self.reads += 1
        return {}


class BlockTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.library = Written({LISTS: [source(ONE), source(TWO), source(THREE)],
                                THEMES: []})
        self.rerender = MagicMock()
        self.block = theme_sources.Block(self.library, self.library.sources,  # type: ignore[arg-type]
                                         self.rerender)
        self.enterContext(patch.object(
            offload, "io", new=AsyncMock(side_effect=lambda call, *args: call(*args))))
        self.enterContext(patch("console.on_page.ui"))
        self.enterContext(patch.object(theme_sources, "ui"))
        self.offered = self.enterContext(patch.object(theme_sources.undo, "offer"))

    async def test_a_drop_writes_the_order_it_made_and_reads_the_themes_again(self) -> None:
        await self.block.moved(LISTS, {"from": 0, "to": 2})

        self.assertEqual(self.library.writes, [{"themes": {LISTS: [TWO, THREE, ONE]}}])
        self.assertEqual(self.library.reads, 1)
        self.rerender.assert_called_once()

    async def test_a_step_off_either_end_writes_nothing(self) -> None:
        await self.block.step(LISTS, ONE, -1)
        await self.block.step(LISTS, THREE, 1)

        self.assertEqual(self.library.writes, [])

    async def test_a_drop_that_names_no_row_writes_nothing(self) -> None:
        for event in ({}, {"from": "x", "to": 1}, {"from": 5, "to": 0}, {"from": 1, "to": 1}):
            await self.block.moved(LISTS, event)

        self.assertEqual(self.library.writes, [])

    async def test_removing_the_last_list_leaves_none_and_offers_it_back(self) -> None:
        for one in (ONE, TWO, THREE):
            block = theme_sources.Block(self.library, self.library.sources,  # type: ignore[arg-type]
                                        self.rerender)
            await block.remove(LISTS, source(one, name=one))

        self.assertEqual(self.library.writes[-1], {"themes": {LISTS: []}})
        self.assertEqual(self.offered.call_count, 3)

        self.library.sources[LISTS] = []
        self.library.writes.clear()
        await self.offered.call_args.args[1]()

        self.assertEqual(self.library.writes, [{"themes": {LISTS: [THREE]}}])

    async def test_the_stock_list_is_put_back_once(self) -> None:
        self.library.sources[LISTS] = []

        await theme_sources.add_default(self.library, self.rerender)  # type: ignore[arg-type]
        await theme_sources.add_default(self.library, self.rerender)  # type: ignore[arg-type]

        self.assertEqual(self.library.writes,
                         [{"themes": {LISTS: [theme_sources.default_list()]}}])
        self.rerender.assert_called_once()


    async def test_two_removals_in_one_window_both_stand(self) -> None:
        await asyncio.gather(self.block.remove(LISTS, source(ONE, name="one")),
                             self.block.remove(LISTS, source(TWO, name="two")))

        self.assertEqual(self.library.writes[-1], {"themes": {LISTS: [THREE]}})

    async def test_a_drop_after_a_write_waits_for_the_page_to_be_drawn_again(self) -> None:
        await self.block.remove(LISTS, source(ONE, name="one"))
        self.library.writes.clear()

        await self.block.moved(LISTS, {"from": 0, "to": 1})

        self.assertEqual(self.library.writes, [])

    async def test_a_drop_whose_write_fails_draws_the_rows_again(self) -> None:
        self.library.put_config = MagicMock(side_effect=OSError("read-only"))  # type: ignore[method-assign]

        await self.block.moved(LISTS, {"from": 0, "to": 2})

        self.rerender.assert_called_once()
        self.assertEqual(self.block.addresses[LISTS], [ONE, TWO, THREE])

    async def test_undo_puts_back_only_the_one_removed_at_its_place(self) -> None:
        await self.block.remove(LISTS, source(ONE, name="one"))
        self.library.sources[LISTS] = [source(TWO), source(THREE), source(THEME)]
        self.library.writes.clear()

        await self.offered.call_args.args[1]()

        self.assertEqual(self.library.writes,
                         [{"themes": {LISTS: [ONE, TWO, THREE, THEME]}}])

    async def test_undo_that_cannot_write_says_so_instead_of_undone(self) -> None:
        await self.block.remove(LISTS, source(ONE, name="one"))
        self.library.put_config = MagicMock(side_effect=OSError("read-only"))  # type: ignore[method-assign]

        with self.assertRaises(OSError):
            await self.offered.call_args.args[1]()


class RowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.block = theme_sources.Block(
            Written({}), {}, MagicMock())  # type: ignore[arg-type]
        self.enterContext(patch.object(panel, "action", side_effect=lambda *a, **k: "action"))

    def test_the_group_of_single_themes_is_drawn_only_when_it_holds_one(self) -> None:
        bare = theme_sources.rows(self.block, {LISTS: [source(ONE)], THEMES: []})
        both = theme_sources.rows(self.block, {LISTS: [source(ONE)], THEMES: [source(THEME)]})

        labels = [label for label, _value in bare if isinstance(label, str)]
        self.assertEqual(labels, [theme_sources.t("console.theme_sources.lists")])
        self.assertEqual(len(both), len(bare) + 2)

    def test_a_group_with_nothing_in_it_still_draws_its_row(self) -> None:
        rows = theme_sources.rows(self.block, {LISTS: [], THEMES: []})

        self.assertEqual(len([label for label, _value in rows if isinstance(label, str)]), 1)


class ChipTests(unittest.TestCase):
    def test_every_state_that_carries_a_level_has_its_word(self) -> None:
        for state in (checks.NOT_CHECKED, checks.NOT_ANSWERING, checks.NOT_FOUND,
                      checks.NOT_A_THEME, checks.SOME_UNREADABLE, checks.NOT_USED,
                      checks.NEEDS_VPINFE):
            if checks.level(state):
                word = theme_sources._word({"state": state})
                self.assertFalse(word.startswith("console."), state)


class EmptiedListTests(unittest.TestCase):
    """An emptied `registries` is stored as empty, not read back as the default."""

    def setUp(self) -> None:
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(paths, "VPINFE_INI_PATH", root / "vpinfe.ini"))
        self.client = TestClient(httpapi.create_api_app(), raise_server_exceptions=False)

    def _lists(self) -> list[str]:
        found = self.client.get("/themes/sources").json()
        return [one["address"] for one in found[LISTS]]

    def test_an_emptied_list_stays_empty(self) -> None:
        self.assertEqual(self._lists(), [theme_sources.default_list()])

        put = self.client.put("/config", json={"themes": {LISTS: []}})

        self.assertFalse(put.is_error, put.text)
        self.assertEqual(self._lists(), [])

        put = self.client.put("/config", json={"themes": {LISTS: [theme_sources.default_list()]}})

        self.assertFalse(put.is_error, put.text)
        self.assertEqual(self._lists(), [theme_sources.default_list()])


if __name__ == "__main__":
    unittest.main()
