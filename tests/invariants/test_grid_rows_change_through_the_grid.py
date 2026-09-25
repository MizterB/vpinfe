"""A Console grid's rows change through `grid.transact` and nowhere else.

A selection is resolved against the rows the grid was built from. A transaction sent
past `transact` changes the screen and leaves those rows as they were, so a bulk action
acts on a row as it was before the edit.
"""

from __future__ import annotations

import pathlib
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
CONSOLE = REPO / "console"
HELPER = CONSOLE / "grid.py"
CALL = "applyTransaction"


def _sends(path: pathlib.Path) -> list[str]:
    return [f"{path.relative_to(REPO)}:{number}"
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
            if CALL in line]


class GridRowsChangeThroughTheGridTests(unittest.TestCase):
    def test_no_other_module_sends_a_transaction(self) -> None:
        offenders = []
        for path in sorted([*CONSOLE.rglob("*.py"), *CONSOLE.rglob("*.js")]):
            if path != HELPER:
                offenders += _sends(path)
        self.assertEqual(offenders, [], "change a grid's rows with grid.transact")

    def test_the_scan_finds_the_helper_s_own(self) -> None:
        """Or a scan that matches nothing would pass the test above as well."""
        self.assertEqual(len(_sends(HELPER)), 1)


if __name__ == "__main__":
    unittest.main()
