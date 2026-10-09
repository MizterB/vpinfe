"""A label takes title case, the way `common/labels.py` writes one. A heading is the
same thing; a sentence or a phrase stays in sentence case.

Core's Settings and Console labels are held to it. An extension's step titles and
questions are phrases and an app's labels are its own, so neither is in this."""

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


def _off_the_rule(keys: list[str]) -> dict[str, tuple[str, str]]:
    return {key: (CATALOG[key], field_label(CATALOG[key])) for key in keys
            if isinstance(CATALOG[key], str) and CATALOG[key] != field_label(CATALOG[key])}


class LabelsAreTitleCase(unittest.TestCase):

    def test_every_settings_and_console_label_is_in_the_case_field_label_writes(self) -> None:
        keys = [key for key in CATALOG
                if key.endswith(".label") and key.startswith(("config.", "console."))
                and key not in _NAMED_AS_THE_PROGRAM]
        self.assertGreater(len(keys), 100, "the catalog held more labels than this found")
        self.assertEqual(_off_the_rule(keys), {})

    def test_the_headings_that_name_a_section_are_title_case(self) -> None:
        self.assertEqual(_off_the_rule(sorted(_HEADINGS)), {})


if __name__ == "__main__":
    unittest.main()
