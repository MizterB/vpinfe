"""Fetching the published script fixes and checking for them, as a click runs them."""

from __future__ import annotations

import asyncio
import unittest
from unittest import mock

from nicegui import ui

from common.i18n import t
from manager import sections

OFFERED = {"reachable": True, "offered": ["Sample Game (Original 2024)"], "checked": 1,
           "already": 0}


async def _now(callback, *args, **kwargs):
    return callback(*args, **kwargs)


class FetchTests(unittest.TestCase):
    def test_how_it_went_is_said_after_the_page_is_left(self) -> None:
        library = mock.Mock()
        library.script_patches.return_value = OFFERED
        client = mock.Mock()
        after = mock.Mock()
        with mock.patch("manager.kit.confirm.ask", mock.AsyncMock(return_value=True)), \
                mock.patch("manager.kit.api.ApiClient", return_value=client), \
                mock.patch.object(sections.run, "io_bound", new=_now), \
                mock.patch.object(sections.ui, "notify", wraps=ui.notify) as notify:
            with ui.column() as page:
                pass
            client.apply_script_patches.side_effect = lambda *_: page.clear()

            asyncio.run(sections.fetch_script_fixes(library, after))

        client.apply_script_patches.assert_called_once_with(OFFERED["offered"])
        notify.assert_called_once_with(t("manager.sections.fetching_way"), type="positive")
        library.forget_script_patches.assert_called_once_with()
        after.assert_called_once_with()

    def test_declining_the_confirm_fetches_nothing(self) -> None:
        library = mock.Mock()
        library.script_patches.return_value = OFFERED
        client = mock.Mock()
        with mock.patch("manager.kit.confirm.ask", mock.AsyncMock(return_value=False)), \
                mock.patch("manager.kit.api.ApiClient", return_value=client):
            with ui.column():
                asyncio.run(sections.fetch_script_fixes(library, mock.Mock()))

        client.apply_script_patches.assert_not_called()
        library.forget_script_patches.assert_not_called()


class CheckTests(unittest.TestCase):
    def check(self, found: dict) -> mock.Mock:
        library = mock.Mock()
        library.script_patches.return_value = found
        with mock.patch.object(sections.run, "io_bound", new=_now), \
                mock.patch.object(sections.ui, "notify") as notify:
            with ui.column():
                check = sections.script_fixes_line(library, {})
                asyncio.run(check())
        return notify

    def test_fixes_found_are_a_notice_and_not_a_toast(self) -> None:
        self.check(OFFERED).assert_not_called()

    def test_show_with_no_table_left_to_show_says_so_and_opens_nothing(self) -> None:
        library = mock.Mock()
        library.script_patches.return_value = OFFERED
        library.script_fix_tables.return_value = ()
        state = {"open_on": mock.Mock()}
        shown = []
        with mock.patch.object(sections.panel, "action",
                               side_effect=lambda text, call, **kw: lambda: shown.append(call)), \
                mock.patch.object(sections.ui, "notify") as notify:
            with ui.column():
                sections.script_fixes_line(library, state)
            shown[0]()

        state["open_on"].assert_not_called()
        notify.assert_called_once_with(t("manager.sections.fix_tables_gone"))

    def test_nothing_published_is_said(self) -> None:
        found = {"reachable": True, "offered": [], "checked": 4, "already": 1}
        [call] = self.check(found).call_args_list
        self.assertIn("4 checked", call.args[0])

    def test_an_index_that_could_not_be_reached_is_not_nothing_to_do(self) -> None:
        for found in ({}, {"reachable": False, "offered": []}):
            [call] = self.check(found).call_args_list
            self.assertEqual(t("manager.sections.index_unreachable"), call.args[0])


class TheClient(unittest.TestCase):
    def test_the_offered_folders_are_what_is_posted(self) -> None:
        from manager.kit.api import ApiClient
        with mock.patch.object(ApiClient, "_post", return_value={}) as post:
            ApiClient().apply_script_patches(["Fathom (Bally 1981)"])
            ApiClient().apply_script_patches()

        self.assertEqual([mock.call("/library/patches", {"games": ["Fathom (Bally 1981)"]}),
                          mock.call("/library/patches", {})], post.call_args_list)
