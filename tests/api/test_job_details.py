"""A finished job's counts, as the one line the Jobs view shows."""

from __future__ import annotations

import unittest

from common import job_details, jobs
from common.i18n import t


class Describers(unittest.TestCase):
    def test_a_library_read_counts_its_games(self) -> None:
        said = job_details.of(jobs.KIND_LIBRARY_SCAN, {"games": 1, "new_games": 0})

        self.assertEqual(t("said.job_library_read", count=1), said)

    def test_a_library_read_with_new_games_says_how_many_matched(self) -> None:
        said = job_details.of(jobs.KIND_LIBRARY_SCAN,
                              {"games": 40, "new_games": 3, "new_matched": 2})

        self.assertEqual(t("said.job_library_new", count=40, new=3, matched=2), said)

    def test_a_scan_counts_found_and_not_found(self) -> None:
        said = job_details.of(jobs.KIND_LIBRARY_SCAN, {"found": 9, "not_found": 2})

        self.assertEqual(t("said.job_scan_found", found=9, missing=2), said)

    def test_a_media_fill_counts_what_it_did(self) -> None:
        said = job_details.of(jobs.KIND_MEDIA_FILL,
                              {"games": 5, "filled": 3, "unmatched": 1, "failed": 1})

        self.assertEqual(t("said.job_media_filled", count=5, filled=3, unmatched=1, failed=1), said)

    def test_a_settings_write_counts_the_tables_changed_and_not(self) -> None:
        said = job_details.of(jobs.KIND_TABLE_SETTINGS,
                              {"tables": 5, "written": ["a", "b", "c"], "failed": [{}, {}]})

        self.assertEqual(t("said.job_table_settings", count=3, failed=2), said)

    def test_a_recording_says_how_many_it_made(self) -> None:
        said = job_details.of(jobs.KIND_MEDIA_CAPTURE, {"run": {"done": 2, "of": 5}})

        self.assertEqual(t("said.job_recorded", done=2, total=5), said)

    def test_a_tool_download_says_the_version(self) -> None:
        self.assertEqual(t("said.job_tool_version", version="7"),
                         job_details.of(jobs.KIND_TOOL_GET, {"version": "7"}))

    def test_a_result_of_a_shape_not_named_has_no_line(self) -> None:
        for result in (None, "text", 3, [], {}, {"unrelated": 1}):
            for kind in (jobs.KIND_LIBRARY_SCAN, jobs.KIND_MEDIA_FILL,
                         jobs.KIND_MEDIA_CAPTURE, jobs.KIND_TOOL_GET):
                self.assertEqual("", job_details.of(kind, result), (kind, result))

    def test_a_kind_nobody_describes_has_no_line(self) -> None:
        self.assertEqual("", job_details.of("acme.sync", {"games": 1, "new_games": 0}))


if __name__ == "__main__":
    unittest.main()
