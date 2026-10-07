"""Settings > Library > Folders, the folders the person adds from: what a change writes,
what a row shows, and which settings the page is the home of."""

from __future__ import annotations

import asyncio
import unittest
from functools import partial
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from nicegui import ui

from common import config_service, path_state
from common.i18n import t
from console import browse_folders, folders, offload, panel
from console import settings as settings_page
from console.settings import settings_here

ONE, TWO, THREE, FOUR = "/mnt/one", "/mnt/two", "/mnt/three", "/mnt/four"
_PAGE = ui.element()


class Written:
    """A Library that only records what the block asked of it."""

    def __init__(self, held: list[str]) -> None:
        self.held = held
        self.writes: list[dict[str, Any]] = []

    def put_config(self, changes: dict[str, Any]) -> dict[str, Any]:
        self.writes.append(changes)
        self.held = list(changes[browse_folders.SECTION][browse_folders.KEY])
        return {}

    def config_values(self) -> dict[str, Any]:
        return {browse_folders.SECTION: {browse_folders.KEY: list(self.held)}}


class BlockTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.library = Written([ONE, TWO, THREE])
        self.rerender = MagicMock()
        self.block = browse_folders.Block(self.library, list(self.library.held),  # type: ignore[arg-type]
                                          {}, self.rerender)
        self.enterContext(patch.object(
            offload, "io", new=AsyncMock(side_effect=lambda call, *args: call(*args))))
        self.enterContext(patch("console.on_page.ui"))
        self.enterContext(patch.object(browse_folders, "ui"))
        self.offered = self.enterContext(patch.object(browse_folders.undo, "offer"))

    def _written(self) -> list[list[str]]:
        return [write[browse_folders.SECTION][browse_folders.KEY] for write in self.library.writes]

    async def test_adding_a_folder_writes_the_list_with_it_at_the_end(self) -> None:
        await self.block.add(FOUR)

        self.assertEqual(self._written(), [[ONE, TWO, THREE, FOUR]])
        self.rerender.assert_called_once()

    async def test_adding_a_folder_that_is_listed_writes_nothing(self) -> None:
        await self.block.add(TWO)

        self.assertEqual(self.library.writes, [])
        self.rerender.assert_not_called()

    async def test_removing_a_folder_writes_the_rest_and_offers_it_back(self) -> None:
        await self.block.remove(TWO)

        self.assertEqual(self._written(), [[ONE, THREE]])
        self.offered.assert_called_once()
        self.assertIn(TWO, self.offered.call_args.args[0])

    async def test_removing_a_folder_that_is_not_listed_writes_nothing(self) -> None:
        await self.block.remove(FOUR)

        self.assertEqual(self.library.writes, [])
        self.offered.assert_not_called()

    async def test_two_removals_in_one_window_both_stand(self) -> None:
        await asyncio.gather(self.block.remove(ONE), self.block.remove(TWO))

        self.assertEqual(self._written()[-1], [THREE])

    async def test_undo_puts_back_only_the_one_removed_at_its_place(self) -> None:
        await self.block.remove(ONE)
        self.library.held = [TWO, THREE, FOUR]
        self.library.writes.clear()

        await self.offered.call_args.args[1]()

        self.assertEqual(self._written(), [[ONE, TWO, THREE, FOUR]])

    async def test_undo_of_a_folder_added_back_by_hand_writes_nothing(self) -> None:
        await self.block.remove(ONE)
        self.library.held = [TWO, ONE]
        self.library.writes.clear()

        await self.offered.call_args.args[1]()

        self.assertEqual(self.library.writes, [])

    async def test_undo_that_cannot_write_raises_so_undone_is_not_said(self) -> None:
        await self.block.remove(ONE)
        self.library.put_config = MagicMock(side_effect=OSError("read-only"))  # type: ignore[method-assign]

        with self.assertRaises(OSError):
            await self.offered.call_args.args[1]()

    async def test_a_write_that_fails_leaves_the_list_as_it_was(self) -> None:
        self.library.put_config = MagicMock(side_effect=OSError("read-only"))  # type: ignore[method-assign]

        await self.block.add(FOUR)

        self.assertEqual(self.block.held, [ONE, TWO, THREE])
        self.rerender.assert_not_called()


class ListedTests(unittest.TestCase):
    def test_a_list_is_kept_as_it_came(self) -> None:
        self.assertEqual(browse_folders.listed([ONE, TWO]), [ONE, TWO])

    def test_a_config_line_is_split_and_trimmed(self) -> None:
        self.assertEqual(browse_folders.listed(f"{ONE}, {TWO} ,"), [ONE, TWO])

    def test_nothing_is_no_folders(self) -> None:
        self.assertEqual(browse_folders.listed(None), [])
        self.assertEqual(browse_folders.listed(""), [])


class ChipTests(unittest.TestCase):
    def test_a_folder_that_is_ready_carries_no_chip(self) -> None:
        self.assertIsNone(browse_folders.state_chip(path_state.PathState(path_state.OK)))

    def test_a_folder_that_is_not_there_says_so(self) -> None:
        chip = browse_folders.state_chip(
            path_state.PathState(path_state.MISSING, "No such folder"))

        assert chip is not None
        self.assertEqual(chip[2], "No such folder")

    def test_a_folder_that_files_are_only_taken_from_need_not_be_writable(self) -> None:
        self.assertIsNone(browse_folders.state_chip(path_state.PathState(path_state.READ_ONLY)))

    def test_a_folder_nothing_was_asked_of_carries_no_chip(self) -> None:
        self.assertIsNone(browse_folders.state_chip(None))


class RowTests(unittest.TestCase):
    def _block(self, held: list[str]) -> browse_folders.Block:
        return browse_folders.Block(Written(held), held, {}, MagicMock())  # type: ignore[arg-type]

    def test_the_setting_is_replaced_by_its_line_the_folders_and_the_way_to_add_one(self) -> None:
        found = browse_folders.rows(self._block([ONE]))

        self.assertIs(found[0][0], panel.LEDE)
        self.assertEqual([one[0] for one in found[1:]], [panel.FULL, panel.FULL])

    def test_with_no_folders_there_is_no_list_to_draw(self) -> None:
        found = browse_folders.rows(self._block([]))

        self.assertEqual([one[0] for one in found[1:]], [panel.FULL])


class HomeTests(unittest.TestCase):
    def test_both_settings_name_the_folders_page_as_their_home(self) -> None:
        described = {(option["section"], option["key"]): option
                     for block in config_service.schema()["sections"]
                     for option in block["options"]}

        for key in ("browse_dirs", "manufacturer_logos_dir"):
            self.assertEqual(described[("media", key)]["home"], "library.folders", key)

    def test_settings_leaves_out_what_another_page_is_the_home_of(self) -> None:
        schema = config_service.schema()["sections"]
        kept = {option["key"] for block in settings_here(schema)
                for option in block["options"]}

        self.assertNotIn("browse_dirs", kept)
        self.assertNotIn("manufacturer_logos_dir", kept)
        self.assertIn("playfield_variant", kept)

    def test_each_has_a_heading_of_its_own_on_the_page(self) -> None:
        described = {(option["section"], option["key"]): option
                     for block in config_service.schema()["sections"]
                     for option in block["options"]}

        self.assertEqual(described[("media", "browse_dirs")]["group_label"],
                         "Folders to Add From")
        self.assertEqual(described[("media", "manufacturer_logos_dir")]["group_label"],
                         "Logos")


class ReadTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.enterContext(patch.object(
            offload, "io", new=AsyncMock(side_effect=lambda call, *args: call(*args))))
        self.look = self.enterContext(patch.object(
            path_state, "look_all",
            side_effect=lambda asks: [path_state.PathState(path_state.OK) for _ in asks]))

    async def test_each_folder_is_kept_with_what_the_disk_says_of_it(self) -> None:
        block = await browse_folders.read(MagicMock(), {"media": {"browse_dirs": [ONE, TWO]}})

        self.assertEqual(block.held, [ONE, TWO])
        self.assertEqual(list(block.states), [ONE, TWO])

    async def test_no_folders_ask_nothing_of_the_disk(self) -> None:
        block = await browse_folders.read(MagicMock(), {"media": {"browse_dirs": []}})

        self.assertEqual((block.held, block.states), ([], {}))
        self.look.assert_not_called()


class RefusalTests(unittest.TestCase):
    def test_nothing_typed_is_refused(self) -> None:
        self.assertEqual(browse_folders.refusal("", [ONE]), t("console.folders.needs_name"))

    def test_a_folder_already_listed_is_refused(self) -> None:
        self.assertEqual(browse_folders.refusal(ONE, [ONE]), t("console.browse_folders.already"))

    def test_a_folder_not_yet_listed_is_not(self) -> None:
        self.assertIsNone(browse_folders.refusal(TWO, [ONE]))


class DialogTests(unittest.TestCase):
    def test_the_dialog_says_which_list_the_folder_joins(self) -> None:
        before = {one for one in _PAGE.client.layout.descendants() if isinstance(one, ui.dialog)}
        with _PAGE, patch.object(ui, "run_javascript"):
            browse_folders.add_dialog(browse_folders.Block(MagicMock(), [], {}))
        box = next(one for one in _PAGE.client.layout.descendants()
                   if isinstance(one, ui.dialog) and one not in before)
        self.addCleanup(box.delete)
        said = [one.text for one in box.descendants()
                if isinstance(one, (ui.label, ui.button)) and one.text]

        self.assertIn(t("console.browse_folders.add_title"), said)
        self.assertIn(t("word.add"), said)
        self.assertNotIn(t("console.folders.add_folder"), said)


class PageTests(unittest.IsolatedAsyncioTestCase):
    """What Settings hands the Folders page to draw under the library's folders."""

    def setUp(self) -> None:
        self.enterContext(patch.object(
            offload, "io", new=AsyncMock(side_effect=lambda call, *args: call(*args))))
        self.enterContext(patch.object(
            path_state, "look_all",
            side_effect=lambda asks: [path_state.PathState(path_state.OK) for _ in asks]))
        self.enterContext(patch.object(settings_page, "_waiting", new=AsyncMock(return_value=[])))
        self.page = self.enterContext(patch.object(
            folders, "page", new=AsyncMock(return_value=lambda: None)))
        self.redraw = MagicMock()
        self.library = MagicMock()
        self.library.config_schema.side_effect = lambda: config_service.schema()["sections"]
        self.library.config_values.return_value = {
            "media": {"browse_dirs": [ONE], "manufacturer_logos_dir": ""}}
        self.library.config_path_checks.return_value = []

    async def _below(self) -> list[tuple[Any, ...]]:
        await settings_page._folders_page(self.library, self.redraw, {})
        return await self.page.await_args.args[3]()  # type: ignore[union-attr]

    async def test_each_setting_is_under_a_heading_of_its_own(self) -> None:
        found = await self._below()

        self.assertEqual([one[1] for one in found if one[0] is panel.HEADING],
                         ["Folders to Add From", "Logos"])

    async def test_the_list_redraws_the_page_when_it_changes(self) -> None:
        found = await self._below()

        listing = next(one[1] for one in found
                       if isinstance(one[1], partial) and one[1].func is browse_folders._list)
        self.assertIs(listing.args[0].rerender, self.redraw)
        self.assertEqual(listing.args[0].held, [ONE])

    async def test_a_settings_read_that_fails_says_so_in_place_of_them(self) -> None:
        self.library.config_values.side_effect = OSError("disk")

        found = await self._below()

        self.assertEqual(len(found), 1)
        self.assertIs(found[0][0], panel.FULL)


if __name__ == "__main__":
    unittest.main()
