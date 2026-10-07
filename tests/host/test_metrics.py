from __future__ import annotations

import contextlib
import json
import subprocess
import unittest
from collections.abc import Iterator
from pathlib import Path
from unittest import mock

from common.host import about, metrics


@contextlib.contextmanager
def _nvtop(cards: list) -> Iterator[None]:
    done = subprocess.CompletedProcess(["nvtop", "-s"], 0, stdout=json.dumps(cards),
                                       stderr="")
    with mock.patch.object(metrics.platform, "system", return_value="Linux"), \
            mock.patch.object(metrics.shutil, "which", return_value="/usr/bin/nvtop"), \
            mock.patch.object(metrics.subprocess, "run", return_value=done):
        yield


def _names(cards: list) -> list[str]:
    with _nvtop(cards):
        return [card["name"] for card in metrics.gpu()["gpus"]]


class UnnamedCardTests(unittest.TestCase):
    def test_two_unnamed_cards_read_apart(self) -> None:
        self.assertEqual(_names([{"gpu_util": "10%"}, {"device_name": None}]),
                         ["Card 1", "Card 2"])

    def test_a_named_card_keeps_its_name_beside_an_unnamed_one(self) -> None:
        self.assertEqual(_names([{"device_name": "Radeon Pro 5500M"}, {"device_name": ""}]),
                         ["Radeon Pro 5500M", "Card 2"])

    def test_a_lone_unnamed_card_is_unknown(self) -> None:
        self.assertEqual(_names([{"temp": "40C"}]), ["Unknown"])

    def test_about_names_each_card(self) -> None:
        with _nvtop([{}, {}]):
            self.assertEqual(about._graphics(), "Card 1, Card 2")


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


if __name__ == "__main__":
    unittest.main()
