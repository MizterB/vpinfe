"""The record of the draw order this install wrote into tables' own settings."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from common.games import order_record
from tests.support.library import TempTree

PAIR = {"ScoreView.Priority.B2S": "2", "ScoreView.Priority.Nixie": "1"}
OTHER = {"ScoreView.Priority.B2S": "5", "ScoreView.Priority.Nixie": "1"}


class Recording(TempTree):
    def setUp(self) -> None:
        super().setUp()
        patcher = patch.object(order_record, "PATH", self.root / "state" / "draw_order.json")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_nothing_recorded_holds_nothing(self) -> None:
        self.assertEqual(order_record.held(), {})

    def test_a_pair_kept_is_held_by_its_table_and_survives_a_reread(self) -> None:
        order_record.keep({"t1": PAIR, "t2": OTHER})

        self.assertEqual(order_record.held(), {"t1": PAIR, "t2": OTHER})

    def test_a_pair_kept_again_replaces_the_one_before(self) -> None:
        order_record.keep({"t1": PAIR})

        order_record.keep({"t1": OTHER})

        self.assertEqual(order_record.held(), {"t1": OTHER})

    def test_an_empty_pair_takes_the_table_out_and_leaves_the_others(self) -> None:
        order_record.keep({"t1": PAIR, "t2": OTHER})

        order_record.keep({"t1": {}})

        self.assertEqual(order_record.held(), {"t2": OTHER})

    def test_no_change_writes_no_file(self) -> None:
        order_record.keep({})

        self.assertFalse(order_record.PATH.exists())

    def test_a_file_that_cannot_be_read_is_an_empty_record(self) -> None:
        order_record.PATH.parent.mkdir(parents=True)
        for text in ("{not json", json.dumps({"schema": 99, "tables": {"t1": PAIR}}), "[]"):
            with self.subTest(text=text):
                order_record.PATH.write_text(text, encoding="utf-8")

                self.assertEqual(order_record.held(), {})


if __name__ == "__main__":
    unittest.main()
