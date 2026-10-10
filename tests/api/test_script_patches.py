"""Fetching the script fixes a check offered, and no others."""

from __future__ import annotations

import unittest
from unittest import mock

from starlette.testclient import TestClient

import httpapi
from common import jobs
from common.games import library_ops, metadata_service


class FetchRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        jobs.reset_for_tests()
        self.addCleanup(jobs.reset_for_tests)
        self.client = TestClient(httpapi.create_api_app(), raise_server_exceptions=False)

    def fetch(self, **kwargs: object) -> tuple[int, mock.Mock]:
        with mock.patch.object(library_ops, "apply_script_patches") as ran:
            ran.return_value = library_ops.start(jobs.KIND_LIBRARY_SCAN, lambda job: None, "x")
            response = self.client.post("/library/patches", **kwargs)
        return response.status_code, ran

    def test_no_body_asks_for_every_game(self) -> None:
        status, ran = self.fetch()
        self.assertEqual(status, 202)
        ran.assert_called_once_with(None)

    def test_the_named_folders_are_handed_on(self) -> None:
        _, ran = self.fetch(json={"games": ["Fathom (Bally 1981)"]})
        ran.assert_called_once_with(["Fathom (Bally 1981)"])

    def test_an_empty_list_names_no_game_and_is_not_every_game(self) -> None:
        _, ran = self.fetch(json={"games": []})
        ran.assert_called_once_with([])

    def test_a_misspelled_key_is_refused_rather_than_read_as_every_game(self) -> None:
        status, ran = self.fetch(json={"game": ["Fathom (Bally 1981)"]})
        self.assertEqual(status, 422)
        ran.assert_not_called()


class NamedFoldersTests(unittest.TestCase):
    def test_an_empty_list_looks_at_no_game(self) -> None:
        game = mock.Mock(game_dir_name="Fathom (Bally 1981)")
        with mock.patch("common.games.game_repository.all_games", return_value=[game]), \
                mock.patch("common.games.library_folders.blocked_games", return_value=[]), \
                mock.patch.object(metadata_service, "StandaloneScripts") as scripts:
            metadata_service.apply_vpx_patches(only=[])
        self.assertEqual(scripts.call_args.args[0], [])


if __name__ == "__main__":
    unittest.main()
