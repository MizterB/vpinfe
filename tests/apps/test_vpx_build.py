"""Which settings the build that wrote an ini has."""

from __future__ import annotations

import unittest
from unittest import mock

from apps.vpx import build
from apps.vpx.setting_types import Span

LINE = "1081"


class RevTests(unittest.TestCase):
    def setUp(self) -> None:
        patch = mock.patch.object(build, "LINE", LINE)
        patch.start()
        self.addCleanup(patch.stop)

    def test_the_rev_is_what_follows_the_line(self) -> None:
        self.assertEqual(build.rev_of("10815985"), 5985)

    def test_a_build_of_another_line_has_no_rev_to_compare(self) -> None:
        self.assertIsNone(build.rev_of("10800000"))
        self.assertIsNone(build.rev_of("1090123"))

    def test_nothing_or_nonsense_has_none(self) -> None:
        for said in (None, "", "   ", "1081", "1081x", "10.8.1", "1081\u00b2", "1081\u0665"):
            with self.subTest(said=said):
                self.assertIsNone(build.rev_of(said))

    def test_surrounding_space_is_ignored(self) -> None:
        self.assertEqual(build.rev_of(" 10815353\n"), 5353)


class DeclaresTests(unittest.TestCase):
    def setUp(self) -> None:
        patch = mock.patch.dict(build.SPANS, {
            "A.added": Span(100, None),
            "A.removed": Span(0, 200),
            "A.between": Span(100, 200),
        }, clear=True)
        patch.start()
        self.addCleanup(patch.stop)

    def test_a_setting_with_no_span_is_in_every_build(self) -> None:
        self.assertTrue(build.declares("A.plain", 1))

    def test_an_added_setting_starts_at_its_first_rev(self) -> None:
        self.assertFalse(build.declares("A.added", 99))
        self.assertTrue(build.declares("A.added", 100))

    def test_a_removed_setting_is_gone_from_the_rev_that_took_it_out(self) -> None:
        self.assertTrue(build.declares("A.removed", 199))
        self.assertFalse(build.declares("A.removed", 200))

    def test_a_setting_present_for_a_while_is_in_between_only(self) -> None:
        self.assertEqual([build.declares("A.between", rev) for rev in (99, 100, 199, 200)],
                         [False, True, True, False])

    def test_a_plugin_the_program_has_is_offered_its_new_setting_to_an_older_ini(self) -> None:
        self.assertFalse(build.declares("A.added", 99))
        self.assertTrue(build.declares("A.added", 99, plugin_present=True))

    def test_a_plugin_the_program_has_is_not_offered_a_setting_it_dropped(self) -> None:
        self.assertFalse(build.declares("A.removed", 200, plugin_present=True))

    def test_a_build_with_no_known_rev_is_shown_everything(self) -> None:
        for key in ("A.added", "A.removed", "A.between"):
            with self.subTest(key=key):
                self.assertTrue(build.declares(key, None))


if __name__ == "__main__":
    unittest.main()
