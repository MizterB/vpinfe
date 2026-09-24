"""Matching a game to its VPS entry from its folder name, and leaving a person's alone."""

from __future__ import annotations

import configparser
import json
import unittest
from unittest.mock import MagicMock, patch

from common.games import game_service, metadata_service
from common.games.game_metadata import (
    MATCHED_BY_USER,
    MATCHED_ON_IMPORT,
    VPS_MATCHED_BY_KEY,
    vps_matched_by,
)
from common.online.vpsdb import VPSdb
from tests.support.library import TempTree, fake_game, game_info, write_game

FOLDER = "Fathom (Bally 1981)"


def _catalog(*entries: dict) -> VPSdb:
    vps = VPSdb.__new__(VPSdb)
    vps.data = list(entries)
    vps.download_media_for_game = MagicMock()
    return vps


def _entry(vps_id: str, name: str, manufacturer: str = "Bally", year: int = 1981) -> dict:
    return {"id": vps_id, "name": name, "manufacturer": manufacturer, "year": year}


class LookupTests(unittest.TestCase):
    def test_the_closest_name_wins_over_the_first_that_passes(self) -> None:
        vps = _catalog(_entry("plural", "Fathoms"), _entry("exact", "Fathom"))

        self.assertEqual(vps.lookup_name("Fathom", "Bally", 1981)["id"], "exact")

    def test_a_tie_keeps_the_first_in_the_catalog(self) -> None:
        vps = _catalog(_entry("first", "Fathom"), _entry("second", "Fathom"))

        self.assertEqual(vps.lookup_name("Fathom", "Bally", 1981)["id"], "first")

    def test_a_different_year_is_no_match(self) -> None:
        vps = _catalog(_entry("other", "Fathom", year=1986))

        self.assertIsNone(vps.lookup_name("Fathom", "Bally", 1981))


class MatchedByTests(unittest.TestCase):
    def test_an_import_pick_reads_as_one(self) -> None:
        meta = game_info(vpinfe={VPS_MATCHED_BY_KEY: MATCHED_ON_IMPORT})

        self.assertEqual(vps_matched_by(meta), MATCHED_ON_IMPORT)

    def test_no_record_is_a_guess(self) -> None:
        self.assertEqual(vps_matched_by(game_info()), "")

    def test_an_override_is_a_persons_whatever_the_record_says(self) -> None:
        meta = game_info(vpinfe={"alt_vpsid": "chosen"})

        self.assertEqual(vps_matched_by(meta), MATCHED_BY_USER)

    def test_a_declared_no_match_is_a_persons(self) -> None:
        meta = game_info(vps_id="", vpinfe={"alt_vpsid": None})

        self.assertEqual(vps_matched_by(meta), MATCHED_BY_USER)

    def test_a_record_with_no_entry_to_describe_says_nothing(self) -> None:
        meta = game_info(vps_id="", vpinfe={VPS_MATCHED_BY_KEY: MATCHED_BY_USER})

        self.assertEqual(vps_matched_by(meta), "")


class RebuildTests(TempTree):
    """`--update-all` over one game whose folder name guesses `fathom`."""

    def setUp(self) -> None:
        super().setUp()
        self.vps = _catalog(_entry("fathom", "Fathom"),
                            _entry("chosen", "Fathom Deluxe", year=1983))

    def rebuild(self, info: dict | None) -> dict:
        folder = write_game(self.root, FOLDER, info=info)
        config = configparser.ConfigParser()
        config["Settings"] = {"gamerootdir": str(self.root)}
        parser = MagicMock()
        parser.single_file_extract.return_value = {"filename": f"{FOLDER}.vpx"}
        with patch.object(metadata_service, "games_under",
                          return_value=[fake_game(folder, FOLDER)]), \
                patch.object(metadata_service, "VPSdb", return_value=self.vps), \
                patch.object(metadata_service, "VPXParser", return_value=parser):
            metadata_service.build_metadata(update_all=True, iniconfig=config)
        return json.loads((folder / f"{FOLDER}.info").read_text(encoding="utf-8"))

    def art_fetched_for(self) -> list[str]:
        return [call.args[1] for call in self.vps.download_media_for_game.call_args_list]

    def test_an_import_pick_survives_a_rebuild(self) -> None:
        saved = self.rebuild(game_info("Fathom Deluxe", vps_id="chosen",
                                       vpinfe={VPS_MATCHED_BY_KEY: MATCHED_ON_IMPORT}))

        self.assertEqual(saved["Info"]["VPSId"], "chosen")
        self.assertEqual(saved["vpinfe"][VPS_MATCHED_BY_KEY], MATCHED_ON_IMPORT)
        self.assertEqual(self.art_fetched_for(), ["chosen"])

    def test_an_override_keeps_its_details_and_gets_its_own_art(self) -> None:
        saved = self.rebuild(game_info("Fathom Deluxe", vps_id="fathom",
                                       vpinfe={"alt_vpsid": "chosen"}))

        self.assertEqual(saved["vpinfe"]["alt_vpsid"], "chosen")
        self.assertEqual(saved["Info"], {"Title": "Fathom Deluxe", "VPSId": "fathom"})
        self.assertEqual(self.art_fetched_for(), ["chosen"])

    def test_a_declared_no_match_stays_and_fetches_nothing(self) -> None:
        saved = self.rebuild(game_info("Homebrew", vps_id="", vpinfe={"alt_vpsid": None}))

        self.assertIsNone(saved["vpinfe"]["alt_vpsid"])
        self.assertEqual(saved["Info"]["VPSId"], "")
        self.assertEqual(self.art_fetched_for(), [])

    def test_a_guess_is_guessed_again(self) -> None:
        saved = self.rebuild(game_info("Fathom Deluxe", vps_id="chosen"))

        self.assertEqual(saved["Info"]["VPSId"], "fathom")
        self.assertNotIn(VPS_MATCHED_BY_KEY, saved["vpinfe"])
        self.assertEqual(self.art_fetched_for(), ["fathom"])

    def test_a_game_with_no_record_is_guessed(self) -> None:
        saved = self.rebuild(None)

        self.assertEqual(saved["Info"]["VPSId"], "fathom")
        self.assertEqual(self.art_fetched_for(), ["fathom"])


class AssociateTests(TempTree):
    def associate(self, info: dict, **kwargs) -> dict:
        folder = write_game(self.root, FOLDER, info=info)
        parser = MagicMock()
        parser.single_file_extract.return_value = {"filename": f"{FOLDER}.vpx"}
        with patch.object(game_service, "VPXParser", return_value=parser), \
                patch.object(game_service, "refresh_game"):
            game_service.associate_vps_to_folder(
                folder, _entry("chosen", "Fathom Deluxe", year=1983), **kwargs)
        return json.loads((folder / f"{FOLDER}.info").read_text(encoding="utf-8"))

    def test_a_pick_is_recorded_and_puts_an_override_aside(self) -> None:
        saved = self.associate(game_info(vps_id="fathom", vpinfe={"alt_vpsid": "other"}))

        self.assertEqual(saved["Info"]["VPSId"], "chosen")
        self.assertEqual(saved["vpinfe"]["alt_vpsid"], "")
        self.assertEqual(saved["vpinfe"][VPS_MATCHED_BY_KEY], MATCHED_BY_USER)

    def test_an_import_says_so(self) -> None:
        saved = self.associate(game_info(vps_id=""), matched_by=MATCHED_ON_IMPORT)

        self.assertEqual(saved["vpinfe"][VPS_MATCHED_BY_KEY], MATCHED_ON_IMPORT)

    def test_a_pick_replaces_a_declared_no_match(self) -> None:
        saved = self.associate(game_info(vps_id="", vpinfe={"alt_vpsid": None}))

        self.assertEqual(vps_matched_by(saved), MATCHED_BY_USER)
        self.assertEqual(saved["vpinfe"]["alt_vpsid"], "")


if __name__ == "__main__":
    unittest.main()
