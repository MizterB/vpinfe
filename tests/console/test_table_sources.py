"""How a table reaches a game from Add a Table, and from a drop on the game's panel."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

from console import mediasource, uploads


async def _now(callback: Any, *args: Any, **kwargs: Any) -> Any:
    return callback(*args, **kwargs)


def _context(library: Any) -> dict[str, Any]:
    return {"library": library, "game_id": "g-1",
            "game": {"name": "Some Game", "folder": "/games/Some Game"}}


class CopyOrUseWhereItIs(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.library = Mock()
        self.done = AsyncMock()
        self.sources = mediasource._Table(_context(self.library), self.done)
        for patched in (patch("console.offload.run.io_bound", new=_now),
                        patch.object(mediasource.ui, "notify")):
            patched.start()
            self.addCleanup(patched.stop)

    async def test_a_copy_is_the_tables_import(self) -> None:
        await self.sources._chosen("/share/Other.vpx")

        self.library.import_table_file.assert_called_once_with("g-1", "/share/Other.vpx")
        self.library.add_referenced_table.assert_not_called()
        self.done.assert_awaited_once()

    async def test_use_it_where_it_is_points_at_it(self) -> None:
        self.sources.copies = False

        await self.sources._chosen("/share/Other.vpx")

        self.library.add_referenced_table.assert_called_once_with("g-1", "/share/Other.vpx")
        self.library.import_table_file.assert_not_called()

    async def test_a_refusal_adds_nothing(self) -> None:
        self.library.import_table_file.side_effect = RuntimeError("not readable")

        await self.sources._chosen("/elsewhere/Other.vpx")

        self.done.assert_not_awaited()


class Uploaded(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.done = AsyncMock()
        self.confirmed = AsyncMock()
        for patched in (patch.object(uploads, "analyzed", new=AsyncMock(return_value={})),
                        patch.object(uploads, "confirmed_import", new=self.confirmed)):
            patched.start()
            self.addCleanup(patched.stop)

    async def _dropped(self) -> dict[str, Any]:
        sources = mediasource._Table(_context(Mock()), self.done)
        await sources.arrived(uploads.Drop(upload_id="u-1", name="Other.vpx"))
        return self.confirmed.await_args.kwargs

    async def test_it_joins_the_game_rather_than_replacing_its_table(self) -> None:
        asked = await self._dropped()

        self.assertTrue(asked["add_table"])
        self.assertEqual(asked["game_dir"], "/games/Some Game")

    async def test_a_drop_on_the_panel_finishes_with_no_dialog_to_close(self) -> None:
        asked = await self._dropped()

        await asked["on_done"]()

        self.done.assert_awaited_once()


class ThePanelTakesTheDrop(unittest.TestCase):
    def test_it_is_marked_so_the_page_leaves_it_alone(self) -> None:
        element = Mock(_props={})

        with patch.object(uploads, "listener"):
            mediasource.take_table_drops(element, _context(Mock()), AsyncMock())

        self.assertIn(uploads.OWN_DROP, element._props)
        self.assertEqual({"dragover", "dragleave", "drop"},
                         {one.args[0] for one in element.on.call_args_list})

    def test_the_page_script_names_the_same_mark(self) -> None:
        self.assertIn(f"[{uploads.OWN_DROP}]", uploads._DND_SCRIPT)


if __name__ == "__main__":
    unittest.main()
