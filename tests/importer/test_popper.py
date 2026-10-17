"""Reading a PinUP Popper library.

Written after the reader met a real database for the first time. What is pinned is the
schema's shape and the two things that database settled: Popper records the extension
each emulator plays, always, and it records a game's media key separately from its name.

The fixture is built here rather than copied. The schema is a fact about Popper; a
library is somebody's own.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import time
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

from common.extensions import host

host.Registry().load(host.BUNDLED_DIR / "library_importer")

from vpinfe_ext_library_importer import plan as plan_for  # noqa: E402
from vpinfe_ext_library_importer import popper  # noqa: E402

EMULATORS = ("EMUID integer primary key, EmuName text, Description text, DirGames text, "
             "DirMedia text, EmuDisplay text, Visible integer, DirRoms text, "
             "GamesExt text")
GAMES = ("GameID integer primary key, EMUID integer, GameName text, GameFileName text, "
         "GameDisplay text, Visible integer, GameYear text, ROM text, Manufact text, "
         "GameType text, GameTheme text, GameRating text, IPDBNum text, "
         "MediaSearch text")


class PopperCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def _library(self, emulators, games) -> Path:
        db = sqlite3.connect(self.root / popper.DATABASE)
        db.execute(f"create table Emulators ({EMULATORS})")
        db.execute(f"create table Games ({GAMES})")
        db.executemany(
            "insert into Emulators (EMUID, EmuName, DirGames, DirRoms, Visible, "
            "GamesExt) values (?, ?, ?, ?, ?, ?)", emulators)
        db.executemany(
            "insert into Games (GameID, EMUID, GameName, GameFileName, GameDisplay, "
            "Visible, GameYear, ROM, Manufact) values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            games)
        db.commit()
        db.close()
        return self.root


class ReadTests(PopperCase):
    def test_a_folder_with_the_database_is_claimed(self) -> None:
        self.assertTrue(popper.detect(self._library([], [])))

    def test_a_folder_without_one_is_not(self) -> None:
        self.assertFalse(popper.detect(self.root))

    def test_the_games_of_an_emulator_are_read(self) -> None:
        root = self._library(
            [(1, "Visual Pinball X", "", "", 1, "vpx")],
            [(1, 1, "Taxi (Williams 1988)", "Taxi (Williams 1988).vpx", "Taxi", 1,
              "1988", "taxi_l4", "Williams")])

        library = popper.read(root)

        self.assertEqual(len(library.games), 1)
        self.assertEqual(library.games[0].rom, "taxi_l4")

    def test_the_long_name_is_the_display_name_and_not_the_short_one(self) -> None:
        """Counter-intuitive, and worth pinning because it reads backwards: `GameName`
        holds the whole "Title (Manufacturer Year) version" a person sees, and
        `GameDisplay` holds the shorter title. A real library had "The Addams Family
        (Bally 1992) 2.4.41" in the first and "Leprechaun King" in the second."""
        root = self._library(
            [(1, "Visual Pinball X", "", "", 1, "vpx")],
            [(1, 1, "Leprechaun King (Orbital 2020)",
              "Leprechaun King (Orbital 2020).vpx", "Leprechaun King", 1, "", "", "")])

        found = popper.read(root).games[0]

        self.assertEqual(found.display_name, "Leprechaun King (Orbital 2020)")
        self.assertEqual(found.title, "Leprechaun King")

    def test_a_row_with_no_name_is_reported_rather_than_dropped(self) -> None:
        root = self._library(
            [(1, "Visual Pinball X", "", "", 1, "vpx")],
            [(1, 1, "", "", "", 1, "", "", "")])

        library = popper.read(root)

        self.assertEqual(library.games, ())
        self.assertTrue(any("no name" in note for note in library.notes))


class PlayableTests(PopperCase):
    """Which emulators are imported.

    Popper records the extension per emulator and always fills it in, which neither of
    the other sources does - so this filter is one column here rather than three guesses.
    """

    def _read(self, plays=None):
        root = self._library(
            [(1, "Visual Pinball X", "", "", 1, "vpx"),
             (2, "Future Pinball", "", "", 1, "fpt"),
             (3, "PC Games", "", "", 1, "lnk")],
            [(1, 1, "Taxi", "Taxi.vpx", "Taxi", 1, "", "", ""),
             (2, 2, "BBB", "BBB.fpt", "BBB", 1, "", "", "")])
        return popper.read(root, plays)

    def test_only_what_this_build_plays_comes_across(self) -> None:
        found = self._read()

        self.assertEqual([one.name for one in found.systems], ["Visual Pinball X"])

    def test_what_was_left_is_named(self) -> None:
        said = [one for one in self._read().notes if "does not play" in one]

        self.assertTrue(said)
        self.assertIn("Future Pinball", said[0])
        self.assertIn("PC Games", said[0])

    def test_an_extension_providing_an_app_changes_the_answer(self) -> None:
        found = self._read(plays=lambda suffix: suffix in (".vpx", ".fpt"))

        self.assertEqual(sorted(one.name for one in found.systems),
                         ["Future Pinball", "Visual Pinball X"])

    def test_an_emulator_that_records_no_extension_is_kept(self) -> None:
        """Saying nothing is not saying no, and a blank column should not drop a
        library."""
        root = self._library([(1, "Something", "", "", 1, "")],
                             [(1, 1, "A", "A.vpx", "A", 1, "", "", "")])

        self.assertEqual([one.name for one in popper.read(root).systems], ["Something"])


STATS = ("UniqueID integer primary key, GameID integer, LastPlayed datetime, "
         "NumberPlays integer default 0, TimePlayedSecs integer, HighScores text")


class StatsTests(PopperCase):
    """What Popper remembers about playing, which lives in the database itself."""

    def _stats(self, *rows) -> Path:
        root = self._library(
            [(1, "Visual Pinball X", "", "", 1, "vpx")],
            [(1, 1, "Leprechaun King (Orbital 2020)", "a.vpx", "Leprechaun King", 1,
              "", "", ""),
             (2, 1, "2 in 1 (Bally 1964)", "b.vpx", "2 in 1", 1, "", "", ""),
             (3, 1, "Joust (Bally 1969)", "c.vpx", "Joust", 1, "", "", "")])
        db = sqlite3.connect(root / popper.DATABASE)
        db.execute(f"create table GamesStats ({STATS})")
        db.executemany("insert into GamesStats (GameID, LastPlayed, NumberPlays, "
                       "TimePlayedSecs) values (?, ?, ?, ?)", rows)
        db.commit()
        db.close()
        return root / popper.DATABASE

    def test_a_played_game_brings_its_count_time_and_date(self) -> None:
        found, notes = popper.read_stats(
            self._stats((1, "2021-02-26 22:26:43.645", 7, 386)))

        self.assertEqual(notes, [])
        self.assertEqual(found[0].name, "Leprechaun King (Orbital 2020)")
        self.assertEqual(found[0].play_count, 7)
        self.assertEqual(found[0].play_time_seconds, 386)

    @unittest.skipUnless(hasattr(time, "tzset"), "no tzset on this platform")
    def test_the_date_is_read_as_the_time_somebody_was_standing_there(self) -> None:
        """No zone is written beside it, so it is local - reading it as UTC moves every
        date by however far the machine is from Greenwich."""
        path = self._stats((1, "2021-02-26 22:26:43.645", 7, 386))
        with mock.patch.dict(os.environ, {"TZ": "America/New_York"}):
            time.tzset()
            self.addCleanup(time.tzset)
            found, _ = popper.read_stats(path)

        self.assertEqual(found[0].last_played,
                         int(datetime(2021, 2, 27, 3, 26, 43, tzinfo=UTC).timestamp()))

    def test_a_date_without_milliseconds_is_read_too(self) -> None:
        with_ms, _ = popper.read_stats(self._stats((1, "2021-02-26 22:26:43.000", 7, 386)))
        self.root.joinpath(popper.DATABASE).unlink()
        without, _ = popper.read_stats(self._stats((1, "2021-02-26 22:26:43", 7, 386)))

        self.assertEqual(without[0].last_played, with_ms[0].last_played)

    def test_a_date_before_1970_does_not_stop_the_read(self) -> None:
        found, notes = popper.read_stats(self._stats((1, "1900-01-01 00:00:00", 7, 386)))

        self.assertEqual(notes, [])
        self.assertEqual(found[0].play_count, 7)

    def test_a_rating_comes_across_in_whole_stars_even_for_a_game_nobody_played(self) -> None:
        path = self._stats((1, "2021-02-26 22:26:43.645", 7, 386))
        db = sqlite3.connect(path)
        db.executemany("update Games set GameRating = ? where GameID = ?",
                       [("3.5", 1), ("2", 3)])
        db.commit()
        db.close()

        found, _ = popper.read_stats(path)

        self.assertEqual({one.name: one.rating for one in found},
                         {"Leprechaun King (Orbital 2020)": 4, "Joust (Bally 1969)": 2})

    def test_a_rating_of_nothing_or_zero_is_not_carried(self) -> None:
        path = self._stats()
        db = sqlite3.connect(path)
        db.executemany("update Games set GameRating = ? where GameID = ?",
                       [("0", 1), ("", 2), (None, 3)])
        db.commit()
        db.close()

        self.assertEqual(popper.read_stats(path), ([], []))

    def test_a_rated_game_nobody_played_does_not_replace_the_same_name_that_was(self) -> None:
        path = self._stats((1, "2021-02-26 22:26:43.645", 7, 386))
        db = sqlite3.connect(path)
        db.execute("insert into Games (GameID, EMUID, GameName, GameRating) "
                   "values (9, 1, 'Leprechaun King (Orbital 2020)', '4')")
        db.commit()
        db.close()

        found, _ = popper.read_stats(path)

        self.assertEqual([(one.play_count, one.rating) for one in found], [(7, 4)])

    def test_a_database_with_no_rating_column_still_brings_its_play_counts(self) -> None:
        path = self._stats((1, "2021-02-26 22:26:43.645", 7, 386))
        db = sqlite3.connect(path)
        db.execute("alter table Games drop column GameRating")
        db.commit()
        db.close()

        found, notes = popper.read_stats(path)

        self.assertEqual((notes, [(one.play_count, one.rating) for one in found]),
                         ([], [(7, None)]))

    def test_a_rating_is_read_where_the_database_keeps_no_play_statistics(self) -> None:
        root = self._library([(1, "Visual Pinball X", "", "", 1, "vpx")],
                             [(1, 1, "Joust (Bally 1969)", "c.vpx", "Joust", 1, "", "", "")])
        db = sqlite3.connect(root / popper.DATABASE)
        db.execute("update Games set GameRating = '5'")
        db.commit()
        db.close()

        found, notes = popper.read_stats(root / popper.DATABASE)

        self.assertEqual((notes, [one.rating for one in found]), ([], [5]))

    def test_a_game_nobody_played_is_left_out_and_not_zeroed(self) -> None:
        """A row Popper made without a play has no count and no date. Carrying it would
        overwrite what is already here with nothing."""
        found, _ = popper.read_stats(self._stats((1, None, 0, None), (2, "", 0, 0),
                                                 (3, "2026-09-28 20:11:00.000", 1, 95)))

        self.assertEqual([one.name for one in found], ["Joust (Bally 1969)"])

    def test_a_database_with_no_statistics_says_nothing(self) -> None:
        root = self._library([], [])

        self.assertEqual(popper.read_stats(root / popper.DATABASE), ([], []))

    def test_a_file_that_is_not_a_database_is_reported(self) -> None:
        path = self.root / popper.DATABASE
        path.write_bytes(b"not a database, and long enough to be read as one" * 8)

        found, notes = popper.read_stats(path)

        self.assertEqual(found, [])
        self.assertEqual(len(notes), 1)

    def test_the_plan_takes_the_history_from_the_database_it_reads_the_games_from(
            self) -> None:
        path = self._stats((1, "2021-02-26 22:26:43.645", 7, 386),
                           (3, "2026-09-28 20:11:00.000", 1, 95))
        library = popper.read(path.parent)

        made = plan_for.build(library, [])

        self.assertEqual(next(one.path for one in made.sources if one.key == "history"),
                         str(path))
        self.assertEqual(plan_for.expected(made)["history"], 2)


if __name__ == "__main__":
    unittest.main()
