from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest import mock

from common import events, jobs
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
        fake.cpu_count.return_value = 4
        fake.process_iter.return_value = []
        fake.sensors_temperatures.return_value = {}
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
        self.assertEqual(metrics.psutil.process_iter.call_count, 1)

    def test_the_sample_carries_the_temperature_and_the_busiest_programs(self) -> None:
        metrics.psutil.sensors_temperatures.return_value = {"coretemp": [_reading("Package", 60)]}
        metrics.psutil.process_iter.return_value = [_process(5, "vpx", 40.0, 7)]
        metrics.sample()
        self.clock[0] += 2
        found = metrics.sample()
        self.assertEqual(found["cpu_temperature"], 60.0)
        self.assertEqual(found["busiest"], [{"name": "vpx", "cpu_percent": 10.0, "memory": 7}])

    def test_graphics_joins_the_sample_and_only_a_busy_reading_the_history(self) -> None:
        found = metrics.sample()
        self.assertEqual(found["graphics"], self.graphics)
        self.assertEqual(metrics.history()[-1]["gpus"], {"1": 30.0})


def _reading(label: str, current: float | None) -> mock.Mock:
    return mock.Mock(label=label, current=current)


def _process(pid: int, name: str | None, cpu: float | None, rss: int | None) -> mock.Mock:
    memory = None if rss is None else mock.Mock(rss=rss)
    return mock.Mock(info={"pid": pid, "name": name, "cpu_percent": cpu, "memory_info": memory})


class MarksTests(unittest.TestCase):
    def setUp(self) -> None:
        metrics.reset_for_tests()
        jobs.reset_for_tests()
        events.clear()
        self.addCleanup(metrics.reset_for_tests)
        self.addCleanup(jobs.reset_for_tests)
        self.addCleanup(events.clear)
        self.clock = [1000.0]
        patch = mock.patch.object(metrics.time, "time", side_effect=lambda: self.clock[0])
        patch.start()
        self.addCleanup(patch.stop)

    def _job(self, kind: str, started: float) -> None:
        with jobs.track(kind):
            pass
        jobs.recent(1)[0].started_at = started

    def test_a_launch_is_marked_with_the_games_title(self) -> None:
        metrics.register()
        with mock.patch("common.games.game_metadata.game_title", return_value="Attack"):
            events.emit(events.TABLE_LAUNCHED, game=object(), private=False)

        self.assertEqual([{"at": 1000.0, "kind": "table", "name": "Attack"}], metrics.marks())

    def test_a_private_game_is_marked_without_its_name(self) -> None:
        metrics.register()
        with mock.patch("common.games.game_metadata.game_title",
                        return_value="Attack") as named:
            events.emit(events.TABLE_LAUNCHED, game=object(), private=True)

        self.assertEqual([{"at": 1000.0, "kind": "table", "name": ""}], metrics.marks())
        named.assert_not_called()

    def test_a_game_that_cannot_be_named_is_still_marked(self) -> None:
        metrics.register()
        with mock.patch("common.games.game_metadata.game_title", side_effect=ValueError):
            events.emit(events.TABLE_LAUNCHED, game=object(), private=False)

        self.assertEqual([""], [one["name"] for one in metrics.marks()])

    def test_registering_twice_marks_a_launch_once(self) -> None:
        metrics.register()
        metrics.register()
        events.emit(events.TABLE_LAUNCHED, game=None, private=False)

        self.assertEqual(1, len(metrics.marks()))

    def test_a_job_is_marked_when_it_started_by_its_kind(self) -> None:
        self._job("library_scan", 990.0)

        self.assertEqual([{"at": 990.0, "kind": "job", "name": "library_scan"}],
                         metrics.marks())

    def test_jobs_and_launches_come_oldest_first_and_only_from_inside_the_window(self) -> None:
        metrics.register()
        self._job("old", 100.0)
        self._job("library_scan", 900.0)
        self.clock[0] = 950.0
        events.emit(events.TABLE_LAUNCHED, game=None, private=False)
        self.clock[0] = 1000.0

        found = metrics.marks(200)

        self.assertEqual(["library_scan", ""], [one["name"] for one in found])
        self.assertEqual([900.0, 950.0], [one["at"] for one in found])
        self.assertEqual(3, len(metrics.marks()))

    def test_the_launches_kept_are_bounded(self) -> None:
        for _ in range(metrics.LAUNCHES + 5):
            metrics.on_launched(game=None)

        self.assertEqual(metrics.LAUNCHES, len(metrics.marks()))


class CpuTemperatureTests(unittest.TestCase):
    def _on(self, chips: dict | None) -> float | None:
        fake = mock.Mock()
        fake.sensors_temperatures.return_value = chips
        with mock.patch.object(metrics, "psutil", fake):
            return metrics.cpu_temperature()

    def test_an_intel_package_wins_over_its_cores(self) -> None:
        self.assertEqual(self._on({"coretemp": [_reading("Core 0", 50.0),
                                                _reading("Package id 0", 64.0)]}), 64.0)

    def test_amd_reads_its_control_temperature(self) -> None:
        self.assertEqual(self._on({"k10temp": [_reading("Tccd1", 40.0),
                                               _reading("Tctl", 55.0)]}), 55.0)

    def test_a_known_chip_with_no_preferred_label_answers_with_its_first_reading(self) -> None:
        self.assertEqual(self._on({"cpu_thermal": [_reading("", 48.5)]}), 48.5)

    def test_the_processors_chip_is_preferred_to_another_listed_first(self) -> None:
        self.assertEqual(self._on({"nvme": [_reading("Composite", 33.0)],
                                   "coretemp": [_reading("Package id 0", 61.0)]}), 61.0)

    def test_a_thermal_zone_is_the_last_resort_and_no_other_chip_is_the_processor(
            self) -> None:
        self.assertEqual(self._on({"acpitz": [_reading("", 41.0)]}), 41.0)
        self.assertEqual(self._on({"nvme": [_reading("Composite", 33.0)],
                                   "soc_thermal": [_reading("", 47.0)]}), 47.0)
        for chip in ("nvme", "mt7921_phy0", "spd5118", "nct6798", "BAT0"):
            self.assertIsNone(self._on({chip: [_reading("", 33.0)]}), chip)

    def test_a_label_earlier_in_the_list_wins_whatever_order_the_sensors_come_in(self) -> None:
        self.assertEqual(self._on({"zenpower": [_reading("Tctl", 70.0), _reading("Tdie", 60.0)]}),
                         60.0)

    def test_a_platform_without_sensors_has_no_temperature(self) -> None:
        self.assertIsNone(self._on({}))
        with mock.patch.object(metrics, "psutil", mock.Mock(spec=["cpu_percent"])):
            self.assertIsNone(metrics.cpu_temperature())


class BusiestTests(unittest.TestCase):
    def setUp(self) -> None:
        metrics.reset_for_tests()
        self.addCleanup(metrics.reset_for_tests)
        self.fake = mock.Mock()
        self.fake.cpu_count.return_value = 4
        patch = mock.patch.object(metrics, "psutil", self.fake)
        patch.start()
        self.addCleanup(patch.stop)

    def _list(self, *processes: mock.Mock) -> list[dict] | None:
        self.fake.process_iter.return_value = list(processes)
        return metrics.busiest()

    def test_the_first_listing_is_nothing_because_every_process_reads_zero_once(self) -> None:
        self.assertIsNone(self._list(_process(10, "chrome", 0.0, 100)))
        self.assertEqual(self._list(_process(10, "chrome", 80.0, 100)),
                         [{"name": "chrome", "cpu_percent": 20.0, "memory": 100}])

    def test_processes_with_one_name_are_one_row_and_the_share_is_of_the_machine(self) -> None:
        self._list()
        found = self._list(_process(10, "chrome", 40.0, 100), _process(11, "chrome", 20.0, 50),
                           _process(12, "vpx", 20.0, 500))
        self.assertEqual(found, [{"name": "chrome", "cpu_percent": 15.0, "memory": 150},
                                 {"name": "vpx", "cpu_percent": 5.0, "memory": 500}])

    def test_the_busiest_five_are_listed_and_the_ties_by_size(self) -> None:
        self._list()
        found = self._list(*(_process(10 + n, f"p{n}", float(n), n) for n in range(8)),
                           _process(30, "big", 0.0, 10 ** 9))
        self.assertEqual([one["name"] for one in found], ["p7", "p6", "p5", "p4", "p3"])
        self.assertEqual(self._list(_process(31, "small", 0.0, 1), _process(32, "big", 0.0, 9))[0]
                         ["name"], "big")

    def test_this_process_is_named_for_the_app_and_not_the_interpreter(self) -> None:
        self._list()
        found = self._list(_process(os.getpid(), "python3.12", 40.0, 100))
        self.assertEqual(found[0]["name"], metrics.OWN)

    def test_a_process_the_os_will_not_let_us_read_is_skipped(self) -> None:
        self._list()
        found = self._list(_process(10, "root-owned", None, 100), _process(11, "also", 8.0, None),
                           _process(0, "System Idle Process", 400.0, 0),
                           _process(12, "mine", 8.0, 5))
        self.assertEqual([one["name"] for one in found], ["mine"])

    def test_a_listing_that_fails_is_no_list(self) -> None:
        self.fake.process_iter.side_effect = OSError
        self.assertIsNone(metrics.busiest())


if __name__ == "__main__":
    unittest.main()
