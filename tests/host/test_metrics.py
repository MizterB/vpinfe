from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from common.host import metrics


class OneSampleTests(unittest.TestCase):
    def setUp(self) -> None:
        metrics.reset_for_tests()
        self.addCleanup(metrics.reset_for_tests)
        self.clock = [1000.0]
        patch = mock.patch.object(metrics.time, "time", side_effect=lambda: self.clock[0])
        patch.start()
        self.addCleanup(patch.stop)
        self.cpu = mock.Mock(side_effect=[46.5, 0.0, 12.0])
        fake = mock.Mock(cpu_percent=self.cpu)
        fake.virtual_memory.return_value = mock.Mock(total=100, available=40, percent=60.0)
        patch = mock.patch.object(metrics, "psutil", fake)
        patch.start()
        self.addCleanup(patch.stop)
        self.graphics = {"cards": [{"id": "1", "name": "Card", "busy": 30.0, "source": "x"},
                                   {"id": "2", "name": "Other", "source": "x"}],
                         "reason": "", "detail": ""}
        patch = mock.patch.object(metrics.graphics, "read", return_value=self.graphics)
        patch.start()
        self.addCleanup(patch.stop)

    def test_a_second_caller_gets_the_reading_already_taken(self) -> None:
        first = metrics.sample()
        self.clock[0] += 0.01
        second = metrics.sample()
        self.assertEqual(first["cpu_percent"], 46.5)
        self.assertEqual(second["cpu_percent"], 46.5)
        self.assertEqual(self.cpu.call_count, 1)

    def test_only_the_reading_actually_taken_enters_the_history(self) -> None:
        metrics.sample()
        self.clock[0] += 0.01
        metrics.sample()
        self.clock[0] += 2
        metrics.sample()
        self.assertEqual([one["cpu_percent"] for one in metrics.history()], [46.5, 0.0])

    def test_the_volumes_follow_the_caller_not_the_cache(self) -> None:
        metrics.sample([])
        self.clock[0] += 0.01
        found = metrics.sample([str(Path(__file__).parent)])
        self.assertEqual(len(found["disks"]), 1)
        self.assertEqual(self.cpu.call_count, 1)

    def test_graphics_joins_the_sample_and_only_a_busy_reading_the_history(self) -> None:
        found = metrics.sample()
        self.assertEqual(found["graphics"], self.graphics)
        self.assertEqual(metrics.history()[-1]["gpus"], {"1": 30.0})


if __name__ == "__main__":
    unittest.main()
