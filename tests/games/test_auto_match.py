"""Matching a game to its VPS entry from its folder name."""

from __future__ import annotations

import unittest

from common.online.vpsdb import VPSdb


def _catalog(*entries: dict) -> VPSdb:
    vps = VPSdb.__new__(VPSdb)
    vps.data = list(entries)
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


if __name__ == "__main__":
    unittest.main()
