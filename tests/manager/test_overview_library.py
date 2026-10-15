"""The Library card and Recent Jobs on Overview: what each kind's bar counts, which kinds fold
into one line, how the jobs are listed and what hiding the empty kinds writes.

The readers are apart from the page, so this runs without one.
"""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from manager import sections
from manager.data import Library


def library(games: dict[str, dict[str, bool]], *, hidden: tuple[str, ...] = (),
            listed: list[dict] | None = None) -> Library:
    client = Mock()
    client.library_policy.return_value = {"hidden_media_kinds": list(hidden)}
    client.put_library_policy.side_effect = lambda changes: {"hidden_media_kinds":
                                                              changes["hidden_media_kinds"]}
    lib = Library(client)
    lib.load_kept_kinds()
    lib.games = [{"id": game_id} for game_id in games]
    lib.media = {game_id: {kind: {"present": present} for kind, present in kinds.items()}
                 for game_id, kinds in games.items()}
    lib._front = {"listed": listed}
    return lib


class WhatEachBarCounts(unittest.TestCase):
    def test_a_kind_counts_the_games_that_hold_it_fewest_first(self):
        lib = library({"a": {"wheel": True, "backglass": True},
                       "b": {"wheel": True, "backglass": False},
                       "c": {"wheel": True, "backglass": False}})

        self.assertEqual([("backglass", 1), ("wheel", 3)], sections.kind_holdings(lib))

    def test_a_kind_no_game_holds_is_listed_at_zero_for_the_fold(self):
        lib = library({"a": {"wheel": True, "topper": False}})

        self.assertEqual([("topper", 0), ("wheel", 1)], sections.kind_holdings(lib))

    def test_a_game_no_longer_in_the_library_is_not_counted(self):
        lib = library({"a": {"wheel": True}, "gone": {"wheel": True}})
        lib.games = [{"id": "a"}]

        self.assertEqual([("wheel", 1)], sections.kind_holdings(lib))

    def test_a_kind_the_library_does_not_collect_has_no_bar(self):
        lib = library({"a": {"wheel": True, "topper": True}}, hidden=("topper",))

        self.assertEqual([("wheel", 1)], sections.kind_holdings(lib))


class HidingTheEmptyKinds(unittest.TestCase):
    def test_the_kinds_are_added_to_the_ones_already_hidden(self):
        lib = library({"a": {"wheel": True}}, hidden=("topper",))

        lib.hide_media_kinds(["launch_audio", "instruction_card"])

        lib._client.put_library_policy.assert_called_once_with(
            {"hidden_media_kinds": ["instruction_card", "launch_audio", "topper"]})

    def test_the_kinds_the_library_keeps_follow_the_write(self):
        lib = library({"a": {"wheel": True, "topper": False}})

        lib.hide_media_kinds(["topper"])

        self.assertNotIn("topper", lib.kept_kinds()["media"])


class TheHideButton(unittest.TestCase):
    def press(self, lib: Library, state: dict, *, writes: AsyncMock) -> None:
        with patch("manager.on_page.ui", MagicMock()), \
                patch.object(sections.run, "io_bound", writes):
            asyncio.run(sections._hide_kinds(lib, state, ["topper"])())

    def test_it_writes_the_kinds_then_opens_the_media_settings(self):
        opened = AsyncMock()
        writes = AsyncMock()

        self.press(library({}), {"open_on": opened}, writes=writes)

        writes.assert_awaited_once()
        opened.assert_awaited_once()
        self.assertEqual("library.media", opened.await_args.args[0].keys["settings_page"])

    def test_a_failed_write_opens_nothing(self):
        opened = AsyncMock()

        with patch.object(sections.ui, "notify") as notify:
            self.press(library({}), {"open_on": opened}, writes=AsyncMock(side_effect=OSError()))

        opened.assert_not_called()
        notify.assert_called_once()


class TheLatestJobs(unittest.TestCase):
    def job(self, job_id: str, started: float, **fields) -> dict:
        return {"id": job_id, "kind": "media.fill", "state": "done", "started_at": started,
                "finished_at": started + 5, **fields}

    def test_newest_first_and_no_more_than_the_card_holds(self):
        listed = [self.job(str(n), 1000.0 + n) for n in range(sections.RECENT_JOBS + 3)]

        shown = sections._latest_jobs(library({}, listed=listed))

        self.assertEqual(sections.RECENT_JOBS, len(shown))
        self.assertEqual(str(sections.RECENT_JOBS + 2), shown[0]["id"])

    def test_a_job_that_finished_with_problems_reads_as_done_with_errors(self):
        shown = sections._latest_jobs(library({}, listed=[self.job("1", 1.0, problems=2)]))

        self.assertEqual("with_errors", shown[0]["outcome"])

    def test_a_running_job_carries_how_far_it_has_got(self):
        running = self.job("1", 1.0, state="running", pct=40)

        shown = sections._latest_jobs(library({}, listed=[running]))

        self.assertEqual(40.0, shown[0]["pct"])

    def test_jobs_that_could_not_be_read_are_not_an_empty_list(self):
        self.assertIsNone(sections._latest_jobs(library({}, listed=None)))
        self.assertEqual([], sections._latest_jobs(library({}, listed=[])))


class TheFrontKeepsTheList(unittest.TestCase):
    def test_a_refresh_carries_the_list_and_the_running_ones(self):
        lib = library({})
        lib._front = {"play": {}, "jobs": [], "listed": []}
        running = {"id": "1", "state": "running"}
        done = {"id": "2", "state": "done"}

        lib.refresh_front({}, [running, done])

        self.assertEqual([running, done], lib.front()["listed"])
        self.assertEqual([running], lib.front()["jobs"])

    def test_a_failed_read_leaves_none_not_an_empty_list(self):
        lib = Library.__new__(Library)
        lib._client = SimpleNamespace(
            players=lambda: [], play_state=lambda: {}, high_scores=lambda *a, **k: {},
            player_record=lambda player_id: [],
            jobs=Mock(side_effect=OSError("down")))
        lib.games = []
        lib._front_player = ""

        self.assertIsNone(lib._read_front()["listed"])


if __name__ == "__main__":
    unittest.main()
