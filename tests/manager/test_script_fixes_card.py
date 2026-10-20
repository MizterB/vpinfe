"""Fetching the published script fixes, as a click runs them."""

from __future__ import annotations

import asyncio
import unittest
from unittest import mock

from nicegui import ui

from common.i18n import t
from manager.kit.data import Library
from manager.settings import sections

OFFERED = {"reachable": True, "offered": ["Sample Game (Original 2024)"], "checked": 1,
           "already": 0}


async def _now(callback, *args, **kwargs):
    return callback(*args, **kwargs)


class FetchTests(unittest.TestCase):
    def fetch(self, library: mock.Mock, client: mock.Mock, after: mock.Mock) -> None:
        with mock.patch("manager.kit.confirm.ask", mock.AsyncMock(return_value=True)), \
                mock.patch("manager.kit.api.ApiClient", return_value=client), \
                mock.patch.object(sections.run, "io_bound", new=_now), \
                mock.patch.object(sections, "_ended", mock.AsyncMock(return_value={})), \
                mock.patch.object(sections.ui, "notify", wraps=ui.notify) as notify:
            with ui.column() as page:
                pass
            client.apply_script_patches.side_effect = lambda *_: (page.clear(), {"id": "job-1"})[1]

            asyncio.run(sections.fetch_script_fixes(library, after))
        self.notify = notify

    def test_how_it_went_is_said_after_the_page_is_left(self) -> None:
        library = mock.Mock()
        library.script_patches.return_value = OFFERED
        client = mock.Mock()
        after = mock.Mock()

        self.fetch(library, client, after)

        client.apply_script_patches.assert_called_once_with(OFFERED["offered"])
        self.notify.assert_called_once_with(t("manager.sections.fetching_way"), type="positive")

    def test_the_folders_it_is_given_are_the_ones_fetched_and_the_check_is_not_asked(
            self) -> None:
        library = mock.Mock()
        library.script_patches.return_value = OFFERED
        client = mock.Mock()
        with mock.patch("manager.kit.confirm.ask", mock.AsyncMock(return_value=True)) as ask, \
                mock.patch("manager.kit.api.ApiClient", return_value=client), \
                mock.patch.object(sections.run, "io_bound", new=_now), \
                mock.patch.object(sections, "_ended", mock.AsyncMock(return_value={})), \
                mock.patch.object(sections.ui, "notify"):
            client.apply_script_patches.return_value = {"id": "job-1"}
            with ui.column():
                asyncio.run(sections.fetch_script_fixes(
                    library, mock.Mock(), only=["Folder One", "Folder Two"]))

        client.apply_script_patches.assert_called_once_with(["Folder One", "Folder Two"])
        library.script_patches.assert_not_called()
        self.assertEqual(t("manager.sections.fetch_confirm", count=2), ask.call_args.args[0])

    def test_what_showed_the_fixes_is_drawn_when_it_begins_and_again_when_the_job_ends(
            self) -> None:
        library = mock.Mock()
        library.script_patches.return_value = OFFERED
        events = mock.Mock()
        events.attach_mock(library.begin_script_fetch, "begin")
        events.attach_mock(library.end_script_fetch, "end")
        events.attach_mock(library.read_script_patches, "read")
        after = mock.Mock()
        events.attach_mock(after, "draw")

        self.fetch(library, mock.Mock(), after)

        self.assertEqual([mock.call.begin(), mock.call.draw(), mock.call.end(),
                          mock.call.read(), mock.call.draw()], events.mock_calls)

    def test_declining_the_confirm_fetches_nothing(self) -> None:
        library = mock.Mock()
        library.script_patches.return_value = OFFERED
        client = mock.Mock()
        with mock.patch("manager.kit.confirm.ask", mock.AsyncMock(return_value=False)), \
                mock.patch("manager.kit.api.ApiClient", return_value=client):
            with ui.column():
                asyncio.run(sections.fetch_script_fixes(library, mock.Mock()))

        client.apply_script_patches.assert_not_called()
        library.begin_script_fetch.assert_not_called()

    def test_a_fetch_that_could_not_start_leaves_the_page_as_it_was(self) -> None:
        library = mock.Mock()
        library.script_patches.return_value = OFFERED
        client = mock.Mock()
        client.apply_script_patches.side_effect = OSError("down")
        after = mock.Mock()
        with mock.patch("manager.kit.confirm.ask", mock.AsyncMock(return_value=True)), \
                mock.patch("manager.kit.api.ApiClient", return_value=client), \
                mock.patch.object(sections.run, "io_bound", new=_now), \
                mock.patch.object(sections.ui, "notify"):
            with ui.column():
                asyncio.run(sections.fetch_script_fixes(library, after))

        library.begin_script_fetch.assert_not_called()
        after.assert_not_called()


class TheKeptAnswer(unittest.TestCase):
    def library(self) -> tuple[Library, mock.Mock]:
        client = mock.Mock()
        client.all_tables.return_value = []
        client.library_policy.return_value = {}
        client.script_patches.return_value = OFFERED
        library = Library(client)
        library.load_kept_kinds()
        return library, client

    def test_the_tables_page_reads_it_with_its_rows_and_a_fetch_makes_it_read_again(self) -> None:
        library, client = self.library()
        self.assertFalse(library.has_tables_view())

        library.load_tables_view()

        self.assertTrue(library.has_tables_view())
        self.assertEqual(OFFERED, library.script_patches())
        library.begin_script_fetch()
        self.assertFalse(library.has_tables_view())
        self.assertEqual({}, library.script_patches())
        library.end_script_fetch()
        library.load_tables_view()
        self.assertEqual(2, client.script_patches.call_count)

    def test_a_visit_while_the_job_runs_sees_nothing_offered_and_one_after_it_sees_the_count(
            self) -> None:
        """The server still answers with the old count until the job has written the files
        and counted again, so a visit in between must not read that as fixes to fetch."""
        library, client = self.library()
        library.load_tables_view()
        self.assertEqual(["Sample Game (Original 2024)"], library.script_patches()["offered"])

        library.begin_script_fetch()
        library.load_tables_view()
        self.assertTrue(library.has_tables_view())
        self.assertEqual([], library.script_patches()["offered"])
        self.assertEqual(1, library.script_patches()["checked"])

        client.script_patches.return_value = {**OFFERED, "offered": [], "already": 1}
        library.end_script_fetch()
        self.assertFalse(library.has_tables_view())
        library.read_script_patches()
        self.assertTrue(library.has_tables_view())
        self.assertEqual(([], 1), (library.script_patches()["offered"],
                                   library.script_patches()["already"]))

    def test_an_answer_that_could_not_be_read_is_nothing_found_and_not_a_page_that_never_loads(
            self) -> None:
        library, client = self.library()
        client.script_patches.side_effect = OSError("down")

        library.load_tables_view()

        self.assertEqual({}, library.script_patches())
        self.assertTrue(library.has_tables_view())


class TheClient(unittest.TestCase):
    def test_the_offered_folders_are_what_is_posted(self) -> None:
        from manager.kit.api import ApiClient
        with mock.patch.object(ApiClient, "_post", return_value={}) as post:
            ApiClient().apply_script_patches(["Fathom (Bally 1981)"])
            ApiClient().apply_script_patches()

        self.assertEqual([mock.call("/library/patches", {"games": ["Fathom (Bally 1981)"]}),
                          mock.call("/library/patches", {})], post.call_args_list)
