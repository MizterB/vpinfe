"""Which VPS releases a table's app can be matched to."""

from __future__ import annotations

import unittest

from common import apps
from common.extensions import provided_apps
from common.games.game_service import release_fits


class ReleaseFitsTests(unittest.TestCase):
    def setUp(self) -> None:
        apps.withdraw_all()
        self.addCleanup(apps.withdraw_all)

    def test_a_release_in_the_apps_format_fits(self) -> None:
        self.assertTrue(release_fits({"tableFormat": "VPX"}, {"filename": "a.vpx"}))

    def test_a_release_in_another_format_does_not(self) -> None:
        self.assertFalse(release_fits({"tableFormat": "FP"}, {"filename": "a.vpx"}))

    def test_vps_spelling_is_not_case_sensitive(self) -> None:
        self.assertTrue(release_fits({"tableFormat": "vpx"}, {"filename": "a.vpx"}))

    def test_a_release_filed_under_no_format_fits_any_app(self) -> None:
        self.assertTrue(release_fits({}, {"filename": "a.vpx"}))
        self.assertTrue(release_fits({"tableFormat": ""}, {"filename": "a.vpx"}))

    def test_an_entry_no_app_claims_is_matched_as_the_default_apps(self) -> None:
        self.assertTrue(release_fits({"tableFormat": "VPX"}, {"filename": "a.unknown"}))
        self.assertFalse(release_fits({"tableFormat": "FP"}, {"filename": "a.unknown"}))

    def test_an_app_declaring_several_formats_fits_each(self) -> None:
        apps.contribute(provided_apps.build("pfx", {
            "id": "pfx", "name": "Pinball FX", "suffixes": (".pfx",),
            "vps_formats": ("fx", "FX2", "fx3")}))
        entry = {"filename": "a.pfx"}

        self.assertTrue(all(release_fits({"tableFormat": one}, entry)
                            for one in ("FX", "FX2", "FX3")))
        self.assertFalse(release_fits({"tableFormat": "VPX"}, entry))

    def test_an_app_declaring_none_fits_every_release(self) -> None:
        apps.contribute(provided_apps.build("other", {
            "id": "other", "name": "Other", "suffixes": (".oth",)}))

        self.assertTrue(release_fits({"tableFormat": "FP"}, {"filename": "a.oth"}))


if __name__ == "__main__":
    unittest.main()
