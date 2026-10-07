"""Browsing this machine for a folder, over the wire."""

from __future__ import annotations

import contextlib
import sys
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import httpapi
from httpapi import auth
from tests.support.library import TempTree

# One non-dot private folder per platform, to prove a parent listing omits a private
# child that dot-folder filtering alone would not catch.
_NON_DOT_PRIVATE = {
    "darwin": ("Library", "Keychains"),
    "linux": (".config", "google-chrome"),
    "win32": ("AppData/Roaming/Microsoft", "Credentials"),
}


def _client() -> TestClient:
    return TestClient(httpapi.create_api_app(), raise_server_exceptions=False)


class FolderApiTests(TempTree):
    def setUp(self) -> None:
        super().setUp()
        self.client = _client()

    def _get(self, path: str = "", *, kind: str = "", suffix: list[str] | None = None,
             hidden: bool = False):
        params: dict[str, str | list[str]] = {}
        if path:
            params["path"] = path
        if kind:
            params["kind"] = kind
        if suffix:
            params["suffix"] = suffix
        if hidden:
            params["hidden"] = "true"
        return self.client.get("/folders", params=params)

    def test_only_subfolders_are_listed_sorted_by_name(self) -> None:
        (self.root / "bravo").mkdir()
        (self.root / "Alpha").mkdir()
        (self.root / ".hidden").mkdir()
        (self.root / "a file.txt").write_text("not a folder")

        body = self._get(str(self.root)).json()

        self.assertEqual([f["name"] for f in body["folders"]], ["Alpha", "bravo"])

    def test_a_subfolders_parent_is_its_parent(self) -> None:
        child = self.root / "child"
        child.mkdir()

        body = self._get(str(child)).json()

        self.assertEqual(body["parent"], str(self.root))

    def test_a_missing_path_is_not_found(self) -> None:
        response = self._get(str(self.root / "nowhere"))

        self.assertEqual(response.status_code, 404)

    def test_an_empty_path_answers_the_home_folder(self) -> None:
        with patch("common.folder_browse.Path.home", return_value=self.root):
            body = self._get("").json()

        self.assertEqual(body["path"], str(self.root))

    def test_roots_is_never_empty(self) -> None:
        body = self._get(str(self.root)).json()

        self.assertTrue(body["roots"])

    def test_the_folders_above_a_path_come_nearest_first_to_the_top(self) -> None:
        deep = self.root / "one" / "two"
        deep.mkdir(parents=True)

        above = self._get(str(deep)).json()["above"]

        self.assertEqual([one["path"] for one in above][:2],
                         [str(self.root / "one"), str(self.root)])
        self.assertEqual(above[0]["name"], "one")
        self.assertEqual(above[-1]["path"], str(deep.resolve().anchor))
        self.assertEqual(above[-1]["name"], deep.resolve().anchor)

    def test_the_top_of_the_disk_has_nothing_above_it(self) -> None:
        anchor = self.root.resolve().anchor

        body = self._get(anchor).json()

        self.assertEqual(body["above"], [])
        self.assertEqual(body["parent"], "")

    def test_home_is_named_home_among_the_places(self) -> None:
        with patch("common.folder_browse.Path.home", return_value=self.root):
            body = self._get(str(self.root)).json()

        names = {one["path"]: one["name"] for one in body["roots"]}
        self.assertEqual(names[str(self.root)], "Home")

    def test_a_program_pickers_places_name_home_too(self) -> None:
        with patch("common.folder_browse.Path.home", return_value=self.root):
            body = self._get(str(self.root), kind="exe").json()

        names = {one["path"]: one["name"] for one in body["roots"]}
        self.assertEqual(names[str(self.root)], "Home")

    def test_a_network_caller_is_refused(self) -> None:
        with patch("httpapi.folders.caller_is_local", return_value=False):
            response = self._get(str(self.root))

        self.assertEqual(response.status_code, 403)

    def test_a_private_folder_cannot_be_listed(self) -> None:
        (self.root / ".ssh").mkdir()

        with patch("common.folder_browse.Path.home", return_value=self.root):
            response = self._get(str(self.root / ".ssh"))

        self.assertEqual(response.status_code, 400)

    def test_a_private_folder_is_omitted_from_its_parent(self) -> None:
        case = _NON_DOT_PRIVATE.get(sys.platform)
        if case is None:
            self.skipTest(f"no non-dot private-folder case recorded for {sys.platform}")
        parent_rel, child_name = case
        parent = self.root / parent_rel
        parent.mkdir(parents=True)
        (parent / child_name).mkdir()
        (parent / "visible").mkdir()

        with patch("common.folder_browse.Path.home", return_value=self.root):
            body = self._get(str(parent)).json()

        self.assertEqual([f["name"] for f in body["folders"]], ["visible"])

    def test_kind_exe_lists_an_executable_and_omits_a_non_executable_file(self) -> None:
        if sys.platform == "win32":
            self.skipTest("Windows decides this by PATHEXT, not os.access")
        runnable = self.root / "runme"
        runnable.write_text("#!/bin/sh\n")
        runnable.chmod(0o755)
        (self.root / "notes.txt").write_text("not executable")

        body = self._get(str(self.root), kind="exe").json()

        self.assertEqual([f["name"] for f in body["files"]], ["runme"])

    def test_kind_file_with_a_suffix_lists_only_that_suffix(self) -> None:
        (self.root / "a.ini").write_text("")
        (self.root / "b.txt").write_text("")

        body = self._get(str(self.root), kind="file", suffix=[".ini"]).json()

        self.assertEqual([f["name"] for f in body["files"]], ["a.ini"])

    def test_kind_file_with_no_suffix_lists_every_file(self) -> None:
        (self.root / "a.ini").write_text("")
        (self.root / "b.txt").write_text("")

        body = self._get(str(self.root), kind="file").json()

        self.assertEqual(sorted(f["name"] for f in body["files"]), ["a.ini", "b.txt"])

    def test_hidden_files_are_omitted(self) -> None:
        (self.root / ".hidden").write_text("")
        (self.root / "visible.txt").write_text("")

        body = self._get(str(self.root), kind="file").json()

        self.assertEqual([f["name"] for f in body["files"]], ["visible.txt"])

    def test_hidden_lists_dot_named_folders_and_files(self) -> None:
        (self.root / ".local").mkdir()
        (self.root / ".hidden").write_text("")
        (self.root / "visible.txt").write_text("")

        body = self._get(str(self.root), kind="file", hidden=True).json()

        self.assertEqual([f["name"] for f in body["folders"]], [".local"])
        self.assertEqual([f["name"] for f in body["files"]], [".hidden", "visible.txt"])

    def test_hidden_still_omits_a_private_folder(self) -> None:
        (self.root / ".ssh").mkdir()
        (self.root / ".local").mkdir()

        with patch("common.folder_browse.Path.home", return_value=self.root):
            body = self._get(str(self.root), hidden=True).json()

        self.assertEqual([f["name"] for f in body["folders"]], [".local"])

    def test_a_private_folders_files_are_never_listed(self) -> None:
        private = self.root / ".ssh"
        private.mkdir()
        (private / "id_ed25519").write_text("not a real key")

        with patch("common.folder_browse.Path.home", return_value=self.root):
            response = self._get(str(private), kind="file")

        self.assertEqual(response.status_code, 400)

    def test_a_file_path_lists_its_folder(self) -> None:
        child = self.root / "child"
        child.mkdir()
        (child / "table.vpx").write_text("")

        body = self._get(str(child / "table.vpx"), kind="file").json()

        self.assertEqual(body["path"], str(child))
        self.assertEqual([f["name"] for f in body["files"]], ["table.vpx"])

    def test_kind_exe_with_an_empty_path_starts_at_one_of_its_roots(self) -> None:
        body = self._get(kind="exe").json()

        self.assertIn(body["path"], [root["path"] for root in body["roots"]])

    def test_an_unknown_kind_is_refused(self) -> None:
        response = self._get(str(self.root), kind="folder")

        self.assertEqual(response.status_code, 400)

    def test_a_network_caller_is_refused_for_any_kind(self) -> None:
        with patch("httpapi.folders.caller_is_local", return_value=False):
            response = self._get(str(self.root), kind="exe")

        self.assertEqual(response.status_code, 403)

    def test_an_app_bundle_lands_in_files_under_exe(self) -> None:
        if sys.platform != "darwin":
            self.skipTest("`.app` bundles are a macOS thing")
        (self.root / "Pinball.app" / "Contents" / "MacOS").mkdir(parents=True)

        body = self._get(str(self.root), kind="exe").json()

        self.assertEqual([f["name"] for f in body["folders"]], [])
        self.assertEqual([f["name"] for f in body["files"]], ["Pinball.app"])


class MakeFolderApiTests(TempTree):
    def setUp(self) -> None:
        super().setUp()
        self.client = _client()

    def _post(self, parent: str, name: str):
        return self.client.post("/folders", json={"parent": parent, "name": name})

    def test_the_folder_is_made_and_its_own_listing_comes_back(self) -> None:
        response = self._post(str(self.root), "Games")

        self.assertEqual(response.status_code, 200)
        self.assertTrue((self.root / "Games").is_dir())
        self.assertEqual(response.json()["path"], str(self.root / "Games"))
        self.assertEqual(response.json()["parent"], str(self.root))
        self.assertEqual(response.json()["folders"], [])

    def test_the_name_is_trimmed(self) -> None:
        self._post(str(self.root), "  Games  ")

        self.assertTrue((self.root / "Games").is_dir())

    def test_a_name_is_not_a_path(self) -> None:
        """A separator would make folders the picker never showed."""
        for name in ("a/b", "a\\b", "..", "."):
            with self.subTest(name=name):
                self.assertEqual(self._post(str(self.root), name).status_code, 400)

        self.assertEqual(list(self.root.iterdir()), [])

    def test_a_name_is_needed(self) -> None:
        self.assertEqual(self._post(str(self.root), "   ").status_code, 400)

    def test_a_name_with_a_control_character_is_refused_rather_than_failing(self) -> None:
        """A NUL reaches the filesystem call as a ValueError, which is a 500."""
        for name in ("a\x00b", "a\nb", "a\tb"):
            with self.subTest(name=repr(name)):
                self.assertEqual(self._post(str(self.root), name).status_code, 400)

        self.assertEqual(list(self.root.iterdir()), [])

    def test_a_parent_is_needed_or_it_would_be_made_where_the_server_runs(self) -> None:
        with contextlib.chdir(self.root):
            for parent in ("", "   "):
                with self.subTest(parent=parent):
                    self.assertEqual(self._post(parent, "Games").status_code, 400)

        self.assertEqual(list(self.root.iterdir()), [])

    def test_a_folder_already_there_is_never_reused(self) -> None:
        (self.root / "Games").mkdir()
        (self.root / "Games" / "kept.txt").write_text("mine")

        response = self._post(str(self.root), "Games")

        self.assertEqual(response.status_code, 400)
        self.assertTrue((self.root / "Games" / "kept.txt").exists())

    def test_a_folder_to_make_it_in_must_be_there(self) -> None:
        self.assertEqual(self._post(str(self.root / "nowhere"), "Games").status_code, 404)

    def test_a_private_folder_is_not_written_to(self) -> None:
        (self.root / ".ssh").mkdir()

        with patch("common.folder_browse.Path.home", return_value=self.root):
            response = self._post(str(self.root / ".ssh"), "Games")

        self.assertEqual(response.status_code, 400)
        self.assertFalse((self.root / ".ssh" / "Games").exists())

    def test_a_network_caller_is_refused_and_nothing_is_made(self) -> None:
        with patch("httpapi.folders.caller_is_local", return_value=False):
            response = self._post(str(self.root), "Games")

        self.assertEqual(response.status_code, 403)
        self.assertFalse((self.root / "Games").exists())

    def test_it_takes_the_scope_adding_a_library_folder_takes(self) -> None:
        """Making a folder is writing to the disk for the same reason adding one is."""
        scopes = {(route.methods and sorted(route.methods)[0], path): auth.route_scope(route)
                  for path, route in auth.iter_api_routes(httpapi.create_api_app())}

        self.assertEqual(scopes[("POST", "/folders")],
                         scopes[("PUT", "/config/{list_key}/{item_id}")])


if __name__ == "__main__":
    unittest.main()
