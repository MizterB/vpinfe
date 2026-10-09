"""A label takes title case, the way `common/labels.py` writes one. A heading is the
same thing; a sentence or a phrase stays in sentence case.

Every owner's labels are held to it - core, the extensions and the apps. A button's text
is a command and stays in sentence case, as the Console's buttons do."""

from __future__ import annotations

import unittest

from common.labels import field_label
from tests.support.catalogs import served

CATALOG = served()

# A label that names a program is written as that program writes itself.
_NAMED_AS_THE_PROGRAM = frozenset({
    f"config.tools.{name}_path.label"
    for name in ("grim", "nvidia_smi", "nvtop", "wf_recorder", "wtype", "ydotool")
})

_HEADINGS = frozenset({"console.placement.heading"})

# The names down the left of the import summary, which sit beside the field labels.
_SUMMARY_ROWS = frozenset(
    {f"ext.library_importer.wizard.summary.{name}" for name in (
        "reads_as", "folder", "roms_missing", "matching", "not_matched", "already_here",
        "left_out", "how", "going_into", "space", "comes_across", "left_behind", "names",
        "details", "wheel_images")}
    | {f"ext.library_importer.count.{name}" for name in (
        "games", "tables", "media", "companions", "history", "matched")}
    | {f"ext.library_importer.kind.{name}.none" for name in (
        "tables", "media", "roms", "altdata", "music", "pups", "user", "history")}
    | {"ext.library_importer.wizard.art.wheels_as.label_plain"})


def _off_the_rule(keys: list[str]) -> dict[str, tuple[str, str]]:
    return {key: (CATALOG[key], field_label(CATALOG[key])) for key in keys
            if isinstance(CATALOG[key], str) and CATALOG[key] != field_label(CATALOG[key])}


class LabelsAreTitleCase(unittest.TestCase):

    def test_every_label_is_in_the_case_field_label_writes(self) -> None:
        keys = [key for key in CATALOG
                if key.endswith(".label") and ".action." not in key
                and key not in _NAMED_AS_THE_PROGRAM]
        self.assertGreater(len(keys), 300, "the catalog held more labels than this found")
        self.assertEqual(_off_the_rule(keys), {})

    def test_the_headings_that_name_a_section_are_title_case(self) -> None:
        self.assertEqual(_off_the_rule(sorted(_HEADINGS)), {})

    def test_the_names_down_the_import_summary_are_title_case(self) -> None:
        self.assertEqual(_off_the_rule(sorted(_SUMMARY_ROWS)), {})

    def test_a_placeholder_is_left_as_written_and_is_not_a_word_of_the_title(self) -> None:
        self.assertEqual(field_label("your {source} wheel images are"),
                         "Your {source} Wheel Images Are")
        self.assertEqual(field_label("{source}'s wheel"), "{source}'s Wheel")
        self.assertEqual(field_label("keep {source_name} for"), "Keep {source_name} For")


if __name__ == "__main__":
    unittest.main()
