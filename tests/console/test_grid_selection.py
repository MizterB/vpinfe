"""What a grid's checkboxes select."""

from __future__ import annotations

import unittest

from console import grid


class SelectAll(unittest.TestCase):

    def test_the_header_checkbox_takes_only_the_rows_on_screen(self):
        self.assertEqual(grid.ROW_SELECTION["selectAll"], "filtered")

    def test_a_cell_click_leaves_the_checkboxes_alone(self):
        self.assertFalse(grid.ROW_SELECTION["enableClickSelection"])


if __name__ == "__main__":
    unittest.main()
