"""The setting that says whether adding a game asks where it goes lives on the Folders
page, and Settings does not draw it a second time."""

from __future__ import annotations

import unittest

from common.settings import config_service
from manager.settings import settings_here


class HomeTests(unittest.TestCase):
    def test_the_setting_names_the_folders_page_as_its_home(self) -> None:
        described = {(option["section"], option["key"]): option
                     for block in config_service.schema()["sections"]
                     for option in block["options"]}

        self.assertEqual(described[("updates", "ask_where_new_games_go")]["home"],
                         "library.folders")

    def test_settings_leaves_out_what_another_page_is_the_home_of(self) -> None:
        schema = config_service.schema()["sections"]
        kept = {option["key"] for block in settings_here(schema)
                for option in block["options"]}

        self.assertNotIn("ask_where_new_games_go", kept)
        self.assertIn("download_spreadsheet", kept)


if __name__ == "__main__":
    unittest.main()
