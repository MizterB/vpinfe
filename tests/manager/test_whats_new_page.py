"""The page an update opens: which parts it has, how they walk, and when the bare address
opens it."""

from __future__ import annotations

import asyncio
import unittest
from collections.abc import Callable

from nicegui import ui

from common.release import migration_ledger, release_notes, upgrade_needs, whats_new
from manager import page
from manager import whats_new as page_whats_new

_PAGE = ui.element()


def _labels(draw: Callable[[], None]) -> list[str]:
    with _PAGE:
        holder = ui.element("div")
        with holder:
            draw()
    return [one.text for one in holder.descendants() if isinstance(one, ui.label)]


def _review(*, releases: bool = True, files: bool = False,
            needs: bool = False) -> whats_new.Review:
    section = release_notes.Section("Summary", [release_notes.Entry("Faster scans.")])
    return whats_new.Review(
        since="v3.0.0",
        releases=[release_notes.Release("v3.1.0", [section])] if releases else [],
        files=[migration_ledger.Entry("info_upgrade", "v3.1.0", 2)] if files else [],
        needs=[upgrade_needs.Need("pick", "v3.1.0", lambda config: False)]
        if needs else [])


class ArrivalTests(unittest.TestCase):
    def test_a_bare_address_after_an_update_opens_it(self) -> None:
        self.assertTrue(page.arrives_in_whats_new(True, "", window=False))

    def test_a_link_naming_a_place_shows_that_place(self) -> None:
        self.assertFalse(page.arrives_in_whats_new(True, "tables", window=False))

    def test_the_frontends_own_window_never_opens_it(self) -> None:
        self.assertFalse(page.arrives_in_whats_new(True, "", window=True))

    def test_nothing_waiting_opens_nothing(self) -> None:
        self.assertFalse(page.arrives_in_whats_new(False, "", window=False))


class PartsTests(unittest.TestCase):
    def keys(self, found: whats_new.Review) -> list[str]:
        return [one.key for one in page_whats_new.parts(found)]

    def test_a_part_with_nothing_in_it_is_not_a_step(self) -> None:
        self.assertEqual(self.keys(_review(releases=False)), [])
        self.assertEqual(self.keys(_review()), ["changed"])

    def test_the_parts_are_read_in_the_order_a_person_asks_about_them(self) -> None:
        self.assertEqual(self.keys(_review(files=True, needs=True)),
                         ["changed", "files", "needs"])


class WalkTests(unittest.TestCase):
    def calls(self, found: whats_new.Review):
        return page_whats_new.calls(found, page_whats_new.parts(found))

    def test_it_opens_on_what_changed_and_says_where_it_starts(self) -> None:
        step = asyncio.run(self.calls(_review(files=True)).first(None))

        self.assertEqual(step["step"], "changed")
        self.assertEqual(step["help"], "Everything since v3.0.0")
        self.assertNotIn("confirm", step)
        self.assertEqual([entry["label"] for entry in step["steps"]],
                         ["What changed", "Your files"])

    def test_next_goes_on_and_the_last_part_ends_it(self) -> None:
        calls = self.calls(_review(files=True))

        step = asyncio.run(calls.check({}, "changed"))

        self.assertEqual(step["step"], "files")
        self.assertEqual(step["confirm"], "Done")
        self.assertTrue(step["steps"][0]["done"])

    def test_one_part_has_no_step_row_and_ends_at_once(self) -> None:
        step = asyncio.run(self.calls(_review()).first(None))

        self.assertNotIn("steps", step)
        self.assertEqual(step["confirm"], "Done")

    def test_a_done_part_reopens_where_it_was(self) -> None:
        step = asyncio.run(self.calls(_review(files=True)).first("files"))

        self.assertEqual(step["step"], "files")


class DrawingTests(unittest.TestCase):
    def test_what_changed_shows_the_version_and_what_it_says(self) -> None:
        (part,) = page_whats_new.parts(_review())

        words = _labels(part.draw)

        self.assertIn("v3.1.0", words)
        self.assertIn("Faster scans.", words)

    def test_a_file_row_says_what_was_done_with_its_count(self) -> None:
        part = page_whats_new.parts(_review(files=True))[1]

        words = _labels(part.draw)

        self.assertIn("Game Metadata", words)
        self.assertIn("2 games' metadata brought onto the current format", words)

    def test_a_migration_with_no_words_still_names_itself(self) -> None:
        found = whats_new.Review(since="", files=[migration_ledger.Entry("unnamed", "v3.1.0", 1)])
        (part,) = page_whats_new.parts(found)

        self.assertIn("unnamed", _labels(part.draw))


if __name__ == "__main__":
    unittest.main()
