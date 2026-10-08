"""What an import would do, before it does any of it.

Two things this holds. Every source is an option with a derived default, so "no ROMs came
across" is something somebody chose and can see they chose. And an import can be run more
than once - a first pass fails partway, or the games come now and the ROMs when the old
machine is back - so what is already here is recognized rather than collided with.
"""

from __future__ import annotations

import tempfile
import unittest
import unittest.mock
from pathlib import Path

from common.extensions import host

host.Registry().load(host.BUNDLED_DIR / "library_importer")

from vpinfe_ext_library_importer import plan as plan_for  # noqa: E402
from vpinfe_ext_library_importer.gamestats import Played  # noqa: E402
from vpinfe_ext_library_importer.source import (  # noqa: E402
    SourceGame,
    SourceLibrary,
    SourceMedia,
    SourceSystem,
)


def _library(*games, tables_dir="/src/tables", roms="/src/roms"):
    return SourceLibrary(source_id="pinballx", root="/src", systems=(
        SourceSystem(name="Visual Pinball X", games=tuple(games),
                     tables_dir=tables_dir, working_path=roms),))


def _game(key, **fields):
    fields.setdefault("display_name", key)
    return SourceGame(key=key, **fields)


class SourceTests(unittest.TestCase):
    def test_what_can_be_worked_out_is_the_default(self) -> None:
        library = _library(_game("Taxi", media=(
            SourceMedia(source_kind="Wheel Images", path="/src/Media/VPX/Wheel/Taxi.png"),)))

        found = {one.key: one for one in plan_for.derive_sources(library)}

        self.assertEqual(found["tables"].path, "/src/tables")
        self.assertTrue(found["tables"].derived)
        self.assertTrue(found["media"].derived)

    def test_the_media_folder_is_the_systems_own_where_there_is_one(self) -> None:
        library = _library(_game("Taxi", media=(
            SourceMedia(source_kind="Instruction Cards",
                        path="/src/Media/Instruction Cards/Taxi 1.png", shared=True),
            SourceMedia(source_kind="Wheel Images", path="/src/Media/VPX/Wheel/Taxi.png"))))

        found = {one.key: one for one in plan_for.derive_sources(library)}

        self.assertEqual(found["media"].path, "/src/Media/VPX")

    def test_a_library_with_only_shared_folders_points_at_media_itself(self) -> None:
        library = _library(_game("Taxi", media=(
            SourceMedia(source_kind="Flyer Images/Front",
                        path="/src/Media/Flyer Images/Front/Taxi.png", shared=True),)))

        found = {one.key: one for one in plan_for.derive_sources(library)}

        self.assertEqual(found["media"].path, "/src/Media")

    def test_a_kind_with_nowhere_to_go_is_not_offered(self) -> None:
        """A field that carries nothing is a promise the code cannot keep. Registry
        settings have no destination on this platform at all - VPinMAME's per-ROM values
        live in memory and nothing persists them - so they are read and not offered."""
        found = {one.key for one in plan_for.derive_sources(_library())}

        self.assertNotIn("registry", found)
        self.assertIn("roms", found)

    def test_what_the_user_said_wins(self) -> None:
        found = {one.key: one for one in
                 plan_for.derive_sources(_library(_game("Taxi")),
                                         {"tables": "/elsewhere"})}

        self.assertEqual(found["tables"].path, "/elsewhere")
        self.assertFalse(found["tables"].derived)

    def test_clearing_one_is_how_somebody_says_not_that(self) -> None:
        """An empty source means that kind is not imported. It has to be reachable, or
        a derived guess cannot be refused."""
        found = {one.key: one for one in
                 plan_for.derive_sources(_library(_game("Taxi")), {"tables": ""})}

        self.assertFalse(found["tables"].active)


class MatchTests(unittest.TestCase):
    HELD = [{"game_id": "g1", "folder_name": "Taxi (Williams 1988)",
             "name": "Taxi", "vps_id": "vps-taxi"}]

    def test_a_game_a_previous_run_made_is_recognized_by_its_folder(self) -> None:
        library = _library(_game("Taxi", display_name="Taxi (Williams 1988)"))

        found = plan_for.match_existing(library, self.HELD)

        self.assertTrue(found[0].existing)
        self.assertEqual(found[0].how, "folder")

    def test_one_renamed_since_is_still_recognized(self) -> None:
        """A rename should not turn one game into two."""
        library = _library(_game("Taxi", display_name="Taxi, the good one",
                                 vps_id="vps-taxi"))

        found = plan_for.match_existing(library, self.HELD)

        self.assertTrue(found[0].existing)
        self.assertEqual(found[0].how, "vps_id")

    def test_a_game_nothing_here_matches_is_new(self) -> None:
        found = plan_for.match_existing(_library(_game("Funhouse")), self.HELD)

        self.assertFalse(found[0].existing)


class LookedTests(unittest.TestCase):
    """What the look found changes which games are copies and which are matched."""

    HELD = [{"game_id": "g1", "folder_name": "Renamed Taxi", "name": "Taxi",
             "vps_id": "vps-taxi", "table_files": ["taxi.vpx"]}]

    def test_a_game_the_look_found_is_a_copy_of_the_one_with_that_entry(self) -> None:
        game = _game("Taxi", display_name="Taxi (Williams 1988)")

        found = plan_for.match_existing(_library(game), self.HELD,
                                        looked={id(game): {"vps_id": "vps-taxi"}})

        self.assertTrue(found[0].existing)
        self.assertEqual(found[0].how, "vps_id")

    def test_a_game_file_name_one_game_holds_is_a_copy(self) -> None:
        game = _game("Taxi", display_name="Taxi (Williams 1988)",
                     table_file="/src/tables/Taxi.VPX")

        found = plan_for.match_existing(_library(game), self.HELD)

        self.assertTrue(found[0].existing)
        self.assertEqual(found[0].how, "table_file")

    def test_a_game_file_name_two_games_hold_says_nothing(self) -> None:
        held = [{**self.HELD[0], "vps_id": ""},
                {"game_id": "g2", "folder_name": "Another", "name": "Another",
                 "vps_id": "", "table_files": ["taxi.vpx"]}]
        game = _game("Taxi", display_name="Taxi (Williams 1988)",
                     table_file="/src/tables/Taxi.vpx")

        found = plan_for.match_existing(_library(game), held)

        self.assertFalse(found[0].existing)

    def test_the_entry_found_and_the_reason_not_are_carried(self) -> None:
        matched, left = _game("Taxi"), _game("Funhouse")
        looked = {id(matched): {"vps_id": "vps-taxi"},
                  id(left): {"vps_id": "", "reason": "not_found"}}

        found = plan_for.match_existing(_library(matched, left), [], looked=looked)

        self.assertEqual((found[0].vps_id, found[0].reason), ("vps-taxi", ""))
        self.assertEqual((found[1].vps_id, found[1].reason), ("", "not_found"))

    def test_only_games_made_new_are_counted_as_matched(self) -> None:
        new, here = _game("Funhouse", table_file="/src/tables/Funhouse.vpx"), _game(
            "Old", display_name="Renamed Taxi", table_file="/src/tables/Old.vpx")
        looked = {id(new): {"vps_id": "vps-new"}, id(here): {"vps_id": "vps-taxi"}}

        made = plan_for.build(_library(new, here), list(self.HELD), on_existing="fill",
                              source_id="pinballx", kinds=(), looked=looked)

        self.assertEqual(plan_for.expected(made)["matched"], 1)

    def test_the_games_not_matched_are_counted_by_why(self) -> None:
        looked = {}
        games = [_game("A"), _game("B"), _game("C")]
        for game, why in zip(games, ("not_found", "not_found", "two_entries"), strict=True):
            looked[id(game)] = {"vps_id": "", "reason": why}

        made = plan_for.build(_library(*games), [], source_id="pinballx", kinds=(),
                              looked=looked)

        self.assertEqual(plan_for.not_matched(made), {"not_found": 2, "two_entries": 1})

    def test_builds_sharing_a_folder_are_one_game_not_matched(self) -> None:
        games = [_game("Kiss (Bally 1979)", table_file=f"/src/{name}.vpx")
                 for name in ("a", "b")]
        looked = {id(game): {"vps_id": "", "reason": "not_found"} for game in games}

        made = plan_for.build(_library(*games), [], source_id="pinballx", kinds=(),
                              looked=looked)

        self.assertEqual(plan_for.not_matched(made), {"not_found": 1})


class NamedByTheEntryTests(unittest.TestCase):
    """A matched game is called what its catalog entry is called."""

    CATALOG = [{"id": "vps-trek", "name": "Star Trek: The Next Generation",
                "manufacturer": "Williams", "year": 1993, "type": "SS"},
               {"id": "vps-taxi", "name": "Taxi", "manufacturer": "Premier", "year": 1989,
                "type": "SS"}]

    def _plan(self, *games, **chosen):
        from common.games import auto_match

        rows = [{"title": game.title, "manufacturer": game.manufacturer,
                 "year": game.year, "folder": game.key} for game in games]
        looked = dict(zip((id(game) for game in games),
                          auto_match.settle(self.CATALOG, rows), strict=True))
        return plan_for.build(_library(*games), [], source_id="pinballx", kinds=(),
                              looked=looked, **chosen)

    def _trek(self):
        return [_game(f"Star Trek {name} (Williams 1993)", title=f"Star Trek {name}",
                      manufacturer="Williams", year="1993",
                      table_file=f"/src/{number}.vpx")
                for number, name in enumerate((": The Next Generation", " The Next Generation"))]

    def test_builds_the_source_spells_two_ways_are_one_game(self) -> None:
        made = self._plan(*self._trek())

        self.assertEqual({one.folder for one in made.matches},
                         {"Star Trek The Next Generation (Williams 1993)"})
        self.assertEqual(plan_for.expected(made)["games"], 1)

    def test_the_source_s_names_are_kept_where_asked(self) -> None:
        made = self._plan(*self._trek(), names="source")

        self.assertEqual(len({one.folder for one in made.matches}), 2)

    def test_a_game_nothing_matched_keeps_the_source_name(self) -> None:
        made = self._plan(_game("Funhouse (Williams 1990)", title="Funhouse",
                                manufacturer="Williams", year="1990"))

        self.assertEqual(made.matches[0].folder, "Funhouse (Williams 1990)")
        self.assertEqual(made.renamed(), (0, []))

    def test_the_renames_are_counted_with_a_few_shown(self) -> None:
        made = self._plan(self._taxi())

        self.assertEqual(made.renamed(), (1, [("Taxi (Premiere 1989)", "Taxi (Premier 1989)")]))

    def _taxi(self):
        return _game("Taxi (Premiere 1989)", title="Taxi", manufacturer="Premiere",
                     year="1989", game_type="EM")

    def test_the_details_that_differ_are_counted_per_detail(self) -> None:
        made = self._plan(self._taxi())

        self.assertEqual(made.differing(), {"title": 0, "manufacturer": 1, "year": 0,
                                            "type": 1})
        self.assertEqual(made.matches[0].differs, ("manufacturer", "type"))

    def test_a_game_found_by_the_name_on_disk_is_called_that(self) -> None:
        held = [{"game_id": "g1", "folder_name": "Taxi (Premiere 1989)", "name": "Taxi",
                 "vps_id": "", "table_files": []}]
        game = self._taxi()
        from common.games import auto_match

        looked = {id(game): auto_match.settle(self.CATALOG, [{
            "title": "Taxi", "manufacturer": "Premiere", "year": "1989", "folder": game.key}])[0]}
        made = plan_for.build(_library(game), held, source_id="pinballx", kinds=(),
                              looked=looked)

        self.assertEqual((made.matches[0].game_id, made.matches[0].folder, made.matches[0].was),
                         ("g1", "Taxi (Premiere 1989)", ""))

    def test_a_detail_the_entry_leaves_blank_is_a_gap_not_a_difference(self) -> None:
        self.CATALOG.append({"id": "bare", "name": "Funhouse", "manufacturer": "Williams"})
        self.addCleanup(self.CATALOG.pop)
        game = _game("Funhouse (Williams 1990)", title="Funhouse", manufacturer="Williams",
                     year="1990")

        looked = {id(game): {"vps_id": "bare", "entry": self.CATALOG[-1]}}
        made = plan_for.build(_library(game), [], source_id="pinballx", kinds=(),
                              looked=looked)

        self.assertEqual((made.matches[0].differs, made.matches[0].gaps), ((), ("year",)))

    def test_the_choices_are_kept_or_fall_back_to_the_default(self) -> None:
        game = _game("Taxi", title="Taxi")

        chosen = self._plan(game, names="source", details="some",
                            detail_fields=["year", "bogus", "title"])
        odd = self._plan(game, names="nope", details="nope")

        self.assertEqual((chosen.names, chosen.details, chosen.detail_fields),
                         ("source", "some", ("title", "year")))
        self.assertEqual((odd.names, odd.details), ("vps", "vps"))


class ExpectedTests(unittest.TestCase):
    KINDS = ("playfield", "wheel")

    def _plan(self, library, held=(), **fields):
        """Built the way the extension builds it: the counts a report compares against
        are worked out while each game is in hand, so the plan needs to know what a
        media kind is."""
        fields.setdefault("source_id", "pinballx")
        fields.setdefault("kinds", self.KINDS)
        return plan_for.build(library, list(held), **fields)

    def test_it_counts_what_the_run_will_act_on(self) -> None:
        library = _library(
            _game("Taxi", table_file="/src/tables/Taxi.vpx", rom="taxi_l4",
                  media=(SourceMedia(source_kind="Wheel Images", path="/w/Taxi.png"),)),
            _game("Funhouse", table_file="/src/tables/Funhouse.vpx"))

        counts = plan_for.expected(self._plan(library))

        self.assertEqual(counts["games"], 2)
        self.assertEqual(counts["tables"], 2)
        self.assertEqual(counts["media"], 1)

    def test_several_builds_of_one_machine_are_one_game(self) -> None:
        """A real library held three of Kiss (Bally 1979) by different authors, and 34
        colliding folder names across 656 games. They are one game with three tables
        here, so the count has to say one - a plan promising three reports a shortfall
        for behaving correctly."""
        library = _library(
            _game("Kiss (Bally 1979)", table_file="/src/a.vpx"),
            _game("Kiss (Bally 1979)", table_file="/src/b.vpx"),
            _game("Kiss (Bally 1979)", table_file="/src/c.vpx"))

        counts = plan_for.expected(self._plan(library))

        self.assertEqual(counts["games"], 1)
        self.assertEqual(counts["tables"], 3)

    def test_only_the_first_build_brings_artwork(self) -> None:
        """The rest are the same table photographed twice, and the run does not place
        them - so counting them promises files that never arrive."""
        art = (SourceMedia(source_kind="Wheel Images", path="/w/Kiss.png"),)
        library = _library(
            _game("Kiss (Bally 1979)", table_file="/src/a.vpx", media=art),
            _game("Kiss (Bally 1979)", table_file="/src/b.vpx", media=art))

        counts = plan_for.expected(self._plan(library))

        self.assertEqual(counts["media"], 1)

    def test_a_later_build_counts_the_slots_the_first_left_empty(self) -> None:
        """The run puts a later build's artwork where nothing is, and never replaces, so
        the plan counts the kinds the game has no file for yet."""
        library = _library(
            _game("Kiss (Bally 1979)", table_file="/src/a.vpx", media=(
                SourceMedia(source_kind="Wheel Images", path="/w/a.png"),)),
            _game("Kiss (Bally 1979)", table_file="/src/b.vpx", media=(
                SourceMedia(source_kind="Wheel Images", path="/w/b.png"),
                SourceMedia(source_kind="Table Images", path="/t/b.png"))))

        counts = plan_for.expected(self._plan(library))

        self.assertEqual(counts["media"], 2)

    def test_two_games_with_the_same_key_are_both_counted(self) -> None:
        """A real source held two entries with byte-identical name attributes. Keyed on
        that, a dict silently keeps one, and the run then does more than the plan said."""
        library = _library(
            _game("Alpha", table_file="/src/a.vpx"),
            _game("Beta", table_file="/src/b.vpx"))
        same = [one for one in library.games]
        self.assertEqual(len({one.key for one in same}), 2)

        counts = plan_for.expected(self._plan(library))

        self.assertEqual(counts["tables"], 2)

    def test_a_quote_a_filesystem_cannot_keep_does_not_make_a_second_game(self) -> None:
        """A real library held `'300' (Gottlieb 1975)` where the source called it
        `"300" (Gottlieb 1975)`. The quote is the only difference, and a filesystem
        substitutes one for the other - matched literally, the machine ends up with the
        game twice."""
        library = _library(_game('"300"', display_name='"300" (Gottlieb 1975)',
                                 table_file="/src/tables/300.vpx"))
        held = [{"game_id": "g1", "folder_name": "'300' (Gottlieb 1975)",
                 "name": "300", "vps_id": ""}]

        made = self._plan(library, held)

        self.assertEqual(len(made.already), 1)
        self.assertEqual(made.new, [])

    def test_two_machines_whose_names_differ_stay_two(self) -> None:
        """The line this stops at: stripping punctuation generally would make Taxi and
        Taxi 2 one game, and merging two machines is worse than holding a duplicate."""
        library = _library(_game("Taxi", display_name="Taxi",
                                 table_file="/src/tables/Taxi.vpx"))
        held = [{"game_id": "g1", "folder_name": "Taxi 2", "name": "Taxi 2",
                 "vps_id": ""}]

        made = self._plan(library, held)

        self.assertEqual(made.already, [])
        self.assertEqual(len(made.new), 1)

    def test_a_source_nobody_set_contributes_nothing(self) -> None:
        """And says zero rather than being left out - an absent row reads as an
        oversight where a zero reads as a decision."""
        library = _library(_game("Taxi", rom="taxi_l4"))

        counts = plan_for.expected(
            self._plan(library, chosen={"media": ""}))

        self.assertEqual(counts["media"], 0)

    def test_a_kind_with_nowhere_to_go_is_not_offered(self) -> None:
        """Registry settings are read and not offered: nothing on this platform reads
        per-ROM VPinMAME values back, so anything written would be consumed by nothing."""
        offered = set(plan_for.SOURCES)

        self.assertNotIn("registry", offered)
        self.assertIn("registry", plan_for.NOT_YET)
        # And what does have somewhere to go is offered.
        self.assertIn("roms", offered)

    def test_games_already_here_are_not_counted_unless_they_are_being_filled(self) -> None:
        library = _library(_game("Taxi", display_name="Taxi (Williams 1988)",
                                 table_file="/src/tables/Taxi.vpx"))
        held = [{"game_id": "g1", "folder_name": "Taxi (Williams 1988)",
                 "name": "Taxi", "vps_id": ""}]

        skipping = plan_for.expected(self._plan(library, held))
        filling = plan_for.expected(self._plan(library, held, on_existing="fill"))

        self.assertEqual(skipping["games"], 0)
        self.assertEqual(filling["games"], 1)

    def _stats(self, *rows: str) -> dict:
        """A GameStats.csv holding these rows, chosen as the play history source."""
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "GameStats.csv"
        path.write_text("".join(f"{row}\n" for row in ("Game,Play Count,Is Favorite",
                                                        *rows)), encoding="utf-8")
        return {"history": str(path)}

    def test_a_game_the_play_history_names_is_counted(self) -> None:
        library = _library(_game("Taxi", display_name="Taxi (Williams 1988)"),
                           _game("Funhouse", display_name="Funhouse (Williams 1990)"))
        chosen = self._stats("Taxi (Williams 1988).Visual Pinball X,33,",
                             "Medieval Madness (Williams 1997).Visual Pinball X,12,")

        counts = plan_for.expected(self._plan(library, chosen=chosen))

        self.assertEqual(counts["history"], 1)

    def test_a_machine_brings_its_play_history_once(self) -> None:
        library = _library(
            _game("Kiss (Bally 1979)", table_file="/src/a.vpx"),
            _game("Kiss (Bally 1979)", table_file="/src/b.vpx"))
        chosen = self._stats("Kiss (Bally 1979).Visual Pinball X,7,")

        counts = plan_for.expected(self._plan(library, chosen=chosen))

        self.assertEqual(counts["history"], 1)

    def test_a_game_left_alone_brings_no_play_history(self) -> None:
        library = _library(_game("Taxi", display_name="Taxi (Williams 1988)"))
        held = [{"game_id": "g1", "folder_name": "Taxi (Williams 1988)",
                 "name": "Taxi", "vps_id": ""}]
        chosen = self._stats("Taxi (Williams 1988).Visual Pinball X,33,")

        skipping = plan_for.expected(self._plan(library, held, chosen=chosen))
        filling = plan_for.expected(self._plan(library, held, chosen=chosen,
                                               on_existing="fill"))

        self.assertEqual(skipping["history"], 0)
        self.assertEqual(filling["history"], 1)

    def test_a_row_holding_only_a_favorite_is_not_counted(self) -> None:
        library = _library(_game("Taxi", display_name="Taxi (Williams 1988)"))
        chosen = self._stats("Taxi (Williams 1988).Visual Pinball X,,1")

        counts = plan_for.expected(self._plan(library, chosen=chosen))

        self.assertEqual(counts["history"], 0)

    def test_leaving_them_alone_is_the_default(self) -> None:
        """Rewriting what somebody has curated since the last run is the worse
        mistake."""
        self.assertEqual(plan_for.build(_library(), []).on_existing, "skip")


class FillTests(unittest.TestCase):
    """A fill counts what it adds, which is what the game is missing."""

    KINDS = ("playfield", "wheel")
    HELD = [{"game_id": "g1", "folder_name": "Taxi", "name": "Taxi", "vps_id": ""}]
    ART = (SourceMedia(source_kind="Wheel Images", path="/w/Taxi.png"),
           SourceMedia(source_kind="Table Images", path="/p/Taxi.png"))

    def _filled(self, **held):
        library = _library(_game("Taxi", table_file="/src/tables/Taxi.vpx", media=self.ART))
        made = plan_for.build(library, self.HELD, on_existing="fill", source_id="pinballx",
                              kinds=self.KINDS)
        made.matches[0].played = Played(name="Taxi", system="Visual Pinball X",
                                        play_count=5, rating=4, tags=("Fav",))
        made.matches[0].history = 1
        if held:
            made.held["g1"] = plan_for.Held(**held)
        return made

    def test_a_game_nobody_measured_is_counted_whole(self) -> None:
        counts = plan_for.expected(self._filled())

        self.assertEqual((counts["tables"], counts["media"], counts["history"]), (1, 2, 1))

    def test_a_game_file_the_game_holds_is_not_promised(self) -> None:
        counts = plan_for.expected(self._filled(tables=frozenset({"taxi.vpx"})))

        self.assertEqual(counts["tables"], 0)

    def test_artwork_the_game_holds_is_not_promised(self) -> None:
        counts = plan_for.expected(self._filled(media=frozenset({"wheel"})))

        self.assertEqual(counts["media"], 1)

    def test_history_the_game_already_has_is_not_promised(self) -> None:
        counts = plan_for.expected(self._filled(
            user={"play_count": 9, "rating": 2, "tags": ["Fav"]}))

        self.assertEqual(counts["history"], 0)

    def test_measuring_reads_only_for_a_fill(self) -> None:
        made = self._filled()
        made.on_existing = "skip"
        read = unittest.mock.Mock()

        plan_for.measure_fill(made, read)

        read.assert_not_called()
        self.assertEqual(made.held, {})

    def test_a_game_that_cannot_be_read_is_counted_whole(self) -> None:
        made = self._filled()

        with self.assertLogs(plan_for.logger, "WARNING"):
            plan_for.measure_fill(made, unittest.mock.Mock(side_effect=OSError("gone")))

        self.assertEqual(plan_for.expected(made)["tables"], 1)


class MissingHistoryTests(unittest.TestCase):
    PLAYED = Played(name="Taxi", system="Visual Pinball X", play_count=5,
                    play_time_seconds=300, last_played=1700000000, favorite=True,
                    rating=4, tags=("Fav", "New"))

    def test_an_empty_game_is_missing_everything(self) -> None:
        found = plan_for.missing_history(self.PLAYED, {})

        self.assertEqual(found.counters, {"play_count": 5, "play_time_seconds": 300,
                                          "last_played": 1700000000})
        self.assertEqual((found.tags, found.rating, found.favorite),
                         (("Fav", "New"), 4, True))

    def test_what_is_held_is_never_replaced(self) -> None:
        found = plan_for.missing_history(self.PLAYED, {
            "play_count": 9, "play_time_seconds": 1, "last_played": 5, "rating": 2,
            "favorite": True, "tags": ["Fav"]})

        self.assertEqual(found.counters, {})
        self.assertEqual((found.tags, found.rating, found.favorite),
                         (("New",), 0, False))

    def test_a_tag_differing_only_in_case_is_the_same_tag(self) -> None:
        found = plan_for.missing_history(self.PLAYED, {"tags": ["fav"]})

        self.assertEqual(found.tags, ("New",))

    def test_a_source_that_remembers_nothing_adds_nothing(self) -> None:
        found = plan_for.missing_history(Played(name="Taxi", system="Visual Pinball X"), {})

        self.assertFalse(found.counts)


class ComparisonTests(unittest.TestCase):
    def test_expected_and_actual_come_back_together(self) -> None:
        rows = {one["key"]: one for one in
                plan_for.against({"games": 8, "media": 20}, {"games": 7, "media": 20})}

        self.assertEqual(rows["games"]["short"], 1)
        self.assertEqual(rows["media"]["short"], 0)

    def test_every_row_is_reported_not_only_the_short_ones(self) -> None:
        """A line that appears only when something went wrong makes a clean import read
        as a report with things missing from it."""
        rows = plan_for.against({"games": 3}, {"games": 3})

        self.assertEqual(len(rows), len(plan_for.COUNTS))


class SpaceTests(unittest.TestCase):
    """What a run writes and whether there is room for it, said before it writes any."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / "Harbor Lights.vpx").write_bytes(b"t" * 1000)
        (self.root / "Harbor Lights.directb2s").write_bytes(b"b" * 500)
        (self.root / "Quarry Run.vpx").write_bytes(b"t" * 2000)
        (self.root / "wheel.png").write_bytes(b"w" * 40)
        self.games = [
            SourceGame(key="Harbor Lights", table_file=str(self.root / "Harbor Lights.vpx"),
                       media=(SourceMedia(source_kind="Wheel Images",
                                          path=str(self.root / "wheel.png")),)),
            SourceGame(key="Quarry Run", table_file=str(self.root / "Quarry Run.vpx"))]

    def _companions(self, table_file: str) -> list[str]:
        stem = Path(table_file).stem
        return sorted(one.name for one in self.root.iterdir()
                      if one.stem == stem and one.suffix != ".vpx")

    def _bytes(self, **more) -> int:
        return plan_for.bytes_to_copy(self.games, "pinballx", ("wheel",),
                                      self._companions, **more)

    def test_a_copy_counts_the_game_file_what_rides_with_it_and_the_artwork(self) -> None:
        self.assertEqual(self._bytes(), 1000 + 500 + 2000 + 40)

    def test_a_move_counts_only_the_artwork(self) -> None:
        """The game files are not written again; they change folders."""
        self.assertEqual(self._bytes(move=True), 40)

    def test_a_file_that_is_gone_counts_for_nothing(self) -> None:
        (self.root / "Quarry Run.vpx").unlink()

        self.assertEqual(self._bytes(), 1000 + 500 + 40)

    def test_a_source_with_no_game_file_counts_its_artwork_alone(self) -> None:
        self.games[0] = SourceGame(key="Harbor Lights", media=self.games[0].media)

        self.assertEqual(self._bytes(), 2000 + 40)

    def test_games_are_made_where_the_game_files_are(self) -> None:
        """A source can name a folder its tables are not in, and moving into that one
        would put the folders somewhere the files never were."""
        library = SourceLibrary(source_id="emulationstation", root=str(self.root), systems=(
            SourceSystem(name="x", games=tuple(self.games), tables_dir="/elsewhere"),))

        self.assertEqual(plan_for.tables_folder(library.systems[0]), str(self.root))

    def test_game_files_in_several_folders_fall_back_to_the_one_the_source_names(self) -> None:
        elsewhere = SourceGame(key="Orchard", table_file="/else/Orchard.vpx")
        system = SourceSystem(name="x", games=(*self.games, elsewhere), tables_dir="/named")

        self.assertEqual(plan_for.tables_folder(system), "/named")

    def test_a_system_with_no_game_files_has_the_folder_it_was_told(self) -> None:
        system = SourceSystem(name="x", games=(SourceGame(key="Orchard"),),
                              tables_dir="/named")

        self.assertEqual(plan_for.tables_folder(system), "/named")

    def test_a_listed_file_that_is_gone_has_nothing_riding_with_it(self) -> None:
        """A frontend's list outlives the files it names."""
        def refusing(path: str) -> list[str]:
            raise FileNotFoundError(path)

        gone = [SourceGame(key="Taxi", table_file=str(self.root / "Taxi.vpx"))]

        self.assertEqual(plan_for.bytes_to_copy(gone, "pinballx", (), refusing), 0)

    def test_sizes_read_in_the_unit_a_person_would_say(self) -> None:
        self.assertEqual(plan_for.size_of(0), "0 B")
        self.assertEqual(plan_for.size_of(1023), "1023 B")
        self.assertEqual(plan_for.size_of(1024), "1.0 KB")
        self.assertEqual(plan_for.size_of(3500), "3.4 KB")
        self.assertEqual(plan_for.size_of(5 * 1024 ** 2), "5.0 MB")
        self.assertEqual(plan_for.size_of(int(2.5 * 1024 ** 3)), "2.5 GB")
        self.assertEqual(plan_for.size_of(3 * 1024 ** 4), "3.0 TB")

    def test_there_is_always_a_unit_to_say_it_in(self) -> None:
        self.assertTrue(plan_for.size_of(5000 * 1024 ** 4).endswith("TB"))

    def test_room_is_asked_of_the_nearest_folder_that_exists(self) -> None:
        free, where = plan_for.room_at(str(self.root / "not" / "made" / "yet"))

        self.assertGreater(free, 0)
        self.assertTrue(where)

    def test_room_that_cannot_be_told_is_minus_one(self) -> None:
        with unittest.mock.patch.object(plan_for.shutil, "disk_usage", side_effect=OSError):
            self.assertEqual(plan_for.room_at(str(self.root)), (-1, ""))


class FoldersFoundTests(unittest.TestCase):
    """Where the emulator keeps its sets, worked out from where the source says it runs."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.install = self.root / "Visual Pinball"
        self.install.mkdir()

    def derived(self) -> dict:
        library = _library(_game("Taxi"), tables_dir=str(self.install / "Tables"),
                           roms=str(self.install))
        return {one.key: one for one in plan_for.derive_sources(library)}

    def test_a_folder_spelled_in_another_case_is_found(self) -> None:
        (self.install / "VPINMAME" / "ROMS").mkdir(parents=True)

        self.assertEqual(self.derived()["roms"].path,
                         str(self.install / "VPINMAME" / "ROMS"))

    def test_the_folders_are_looked_for_up_from_the_working_folder_too(self) -> None:
        (self.root / "Music").mkdir()
        (self.root / "PinUPSystem" / "PUPVideos").mkdir(parents=True)

        found = self.derived()

        self.assertEqual(found["music"].path, str(self.root / "Music"))
        self.assertEqual(found["pups"].path, str(self.root / "PinUPSystem" / "PUPVideos"))
        self.assertTrue(found["music"].derived)

    def test_the_sound_and_color_root_must_hold_one_of_the_three(self) -> None:
        (self.install / "VPinMAME").mkdir()
        self.assertEqual(self.derived()["altdata"].path, "")

        (self.install / "VPinMAME" / "altsound").mkdir()

        self.assertEqual(self.derived()["altdata"].path, str(self.install / "VPinMAME"))

    def test_a_bare_roms_folder_is_not_taken_from_above_the_install(self) -> None:
        (self.root / "roms").mkdir()

        self.assertEqual(self.derived()["roms"].path, "")

    def test_the_persons_own_music_folder_is_not_a_games_music(self) -> None:
        (self.root / "Music").mkdir()

        with unittest.mock.patch("pathlib.Path.home", return_value=self.root):
            self.assertEqual(self.derived()["music"].path, "")

    def test_a_folder_that_was_looked_for_and_is_not_there_says_so(self) -> None:
        found = self.derived()

        self.assertTrue(found["roms"].not_found)
        self.assertFalse(found["roms"].active)

    def test_a_folder_somebody_cleared_was_not_looked_for_in_their_name(self) -> None:
        (self.install / "Music").mkdir()
        library = _library(_game("Taxi"), roms=str(self.install))

        found = {one.key: one for one in plan_for.derive_sources(library, {"music": ""})}

        self.assertFalse(found["music"].not_found)
        self.assertFalse(found["music"].active)


MAP = {"taxi_l1": "taxi_l4"}


class RomsCountTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.roms = self.root / "roms"
        self.roms.mkdir()
        (self.roms / "Taxi_L4.ZIP").write_bytes(b"r" * 700)
        (self.root / "Taxi.vpx").write_bytes(b"t" * 1000)
        self.games = [SourceGame(key="Taxi", table_file=str(self.root / "Taxi.vpx"))]

    def bytes_of(self, **more) -> int:
        return plan_for.bytes_to_copy(self.games, "pinballx", (), lambda path: [], **more)

    def test_the_rom_the_game_file_names_counts_in_any_case(self) -> None:
        names = {self.games[0].table_file: "taxi_l4"}

        self.assertEqual(self.bytes_of(roms=names, roms_dir=str(self.roms)), 1700)

    def test_a_name_the_source_maps_counts_the_set_it_points_to(self) -> None:
        names = {self.games[0].table_file: "taxi_l1"}

        self.assertEqual(self.bytes_of(roms=names, roms_dir=str(self.roms)), 1000)
        self.assertEqual(self.bytes_of(roms=names, roms_dir=str(self.roms),
                                       real=lambda name: MAP.get(name, "")), 1700)

    def test_a_move_still_copies_the_rom(self) -> None:
        names = {self.games[0].table_file: "taxi_l4"}

        self.assertEqual(self.bytes_of(move=True, roms=names, roms_dir=str(self.roms)), 700)

    def test_a_rom_the_folder_does_not_hold_or_a_folder_not_given_counts_for_nothing(
            self) -> None:
        names = {self.games[0].table_file: "afm_113b"}

        self.assertEqual(self.bytes_of(roms=names, roms_dir=str(self.roms)), 1000)
        self.assertEqual(self.bytes_of(roms={self.games[0].table_file: "taxi_l4"}), 1000)


class MissingRomsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.roms = Path(self._tmp.name)
        (self.roms / "taxi_l4.zip").write_bytes(b"r")

    def plan(self, *matches: plan_for.Match, active: bool = True) -> plan_for.Plan:
        found = plan_for.Source(key="roms", label="ROMs", help="",
                                path=str(self.roms) if active else "")
        return plan_for.Plan(sources=[found], matches=list(matches))

    def test_only_a_solid_state_machine_is_said_to_need_its_rom(self) -> None:
        made = self.plan(
            plan_for.Match(key="a", folder="A", machine="SS", rom="afm_113b"),
            plan_for.Match(key="b", folder="B", machine="EM", rom="aladdins_castle"),
            plan_for.Match(key="c", folder="C", machine="", rom="apache_1978"))

        self.assertEqual(plan_for.missing_roms(made), 1)

    def test_a_rom_that_is_there_in_any_case_is_not_missing(self) -> None:
        made = self.plan(plan_for.Match(key="a", folder="A", machine="SS", rom="TAXI_L4"))

        self.assertEqual(plan_for.missing_roms(made), 0)

    def test_a_game_already_in_the_library_is_not_said_to_need_its_rom(self) -> None:
        made = self.plan(plan_for.Match(key="a", folder="A", machine="SS", rom="afm_113b",
                                        game_id="g1"))

        self.assertEqual(plan_for.missing_roms(made), 0)

    def test_builds_of_one_game_count_once(self) -> None:
        made = self.plan(
            plan_for.Match(key="a", folder="A", machine="SS", rom="afm_113b"),
            plan_for.Match(key="a2", folder="a", machine="SS", rom="afm_113b"))

        self.assertEqual(plan_for.missing_roms(made), 1)

    def test_nothing_is_said_where_roms_are_not_being_imported(self) -> None:
        made = self.plan(plan_for.Match(key="a", folder="A", machine="SS", rom="afm_113b"),
                         active=False)

        self.assertEqual(plan_for.missing_roms(made), 0)

    def test_the_rom_a_game_file_names_goes_on_its_match_by_position(self) -> None:
        library = _library(_game("A", table_file="/t/A.vpx"), _game("B"))
        made = self.plan(plan_for.Match(key="A", folder="A"),
                         plan_for.Match(key="B", folder="B"))

        plan_for.attach_roms(made, library, {"/t/A.vpx": "afm_113b"})

        self.assertEqual([one.rom for one in made.matches], ["afm_113b", ""])

    def test_a_name_the_source_maps_is_the_set_the_game_needs(self) -> None:
        library = _library(_game("A", table_file="/t/A.vpx"))
        made = self.plan(plan_for.Match(key="A", folder="A", machine="SS"))

        plan_for.attach_roms(made, library, {"/t/A.vpx": "taxi_l1"},
                             real=lambda name: MAP.get(name, ""))

        self.assertEqual(made.matches[0].rom, "taxi_l4")
        self.assertEqual(plan_for.missing_roms(made), 0)


if __name__ == "__main__":
    unittest.main()
