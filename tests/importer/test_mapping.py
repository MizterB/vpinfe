"""Turning what a source said into what we store.

One place knows both vocabularies, so this is where a wrong answer would be, and the
title rule is the one that is a judgement rather than a lookup.
"""

from __future__ import annotations

import unittest

from common.extensions import host

# Loaded the way core loads it; the modules are only importable once it has been.
host.Registry().load(host.BUNDLED_DIR / "library_importer")

from vpinfe_ext_library_importer import mapping  # noqa: E402
from vpinfe_ext_library_importer.source import SourceGame, SourceMedia  # noqa: E402

KINDS = ("playfield", "playfield_video", "wheel", "backglass", "audio", "logo")


def _game(**fields) -> SourceGame:
    return SourceGame(key=fields.pop("key", "Taxi"), **fields)


class TitleTests(unittest.TestCase):
    def test_the_machine_name_is_lifted_out_of_the_description(self) -> None:
        found = mapping.details_for(_game(display_name="Attack from Mars (Bally 1995)",
                                          manufacturer="Bally", year="1995"))

        self.assertEqual(found["title"], "Attack from Mars")

    def test_a_title_the_source_gave_is_never_second_guessed(self) -> None:
        found = mapping.details_for(_game(title="Big Bang Bar",
                                          display_name="Big Bang Bar (Capcom 1996)",
                                          manufacturer="Capcom", year="1996"))

        self.assertEqual(found["title"], "Big Bang Bar")

    def test_a_bracket_that_is_not_the_maker_and_year_is_left_alone(self) -> None:
        """A removal of something known, not a guess at what a name ends with."""
        found = mapping.details_for(_game(display_name="Taxi (Redux)",
                                          manufacturer="Williams", year="1988"))

        self.assertNotIn("title", found)

    def test_nothing_is_lifted_without_both_halves_to_match_on(self) -> None:
        found = mapping.details_for(_game(display_name="Taxi (Williams 1988)",
                                          manufacturer="Williams"))

        self.assertNotIn("title", found)


class DetailTests(unittest.TestCase):
    def test_only_what_the_source_actually_said_is_sent(self) -> None:
        """An empty value written over nothing says we examined it and found none, and
        for an unmatched import nobody examined anything."""
        found = mapping.details_for(_game(manufacturer="Williams"))

        self.assertEqual(found, {"manufacturer": "Williams"})

    def test_themes_come_across_as_a_list(self) -> None:
        found = mapping.details_for(_game(themes=("Aliens", "Outer Space")))

        self.assertEqual(found["themes"], ["Aliens", "Outer Space"])


class MediaTests(unittest.TestCase):
    def _with(self, *kinds) -> SourceGame:
        return _game(media=tuple(SourceMedia(source_kind=one, path=f"/s/{one}.png")
                                 for one in kinds))

    def test_a_source_folder_maps_to_one_of_our_kinds(self) -> None:
        found = mapping.media_for("pinballx", self._with("Table Images", "Wheel Images"),
                                  KINDS)

        self.assertEqual(sorted(kind for kind, _p in found), ["playfield", "wheel"])

    def test_the_still_and_the_moving_one_are_different_kinds(self) -> None:
        found = mapping.media_for("pinballx",
                                  self._with("Table Images", "Table Videos"), KINDS)

        self.assertEqual(sorted(kind for kind, _p in found),
                         ["playfield", "playfield_video"])

    def test_a_kind_this_build_has_no_slot_for_is_left_behind(self) -> None:
        """Putting it somewhere approximate would be worse than not carrying it."""
        game = self._with("FullDMD Videos")

        self.assertEqual(mapping.media_for("pinballx", game, KINDS), [])
        self.assertEqual(mapping.unmapped_kinds("pinballx", game, KINDS),
                         ["FullDMD Videos"])

    def test_the_real_dmd_cards_and_front_of_the_flyer_have_slots(self) -> None:
        known = (*KINDS, "real_dmd", "real_dmd_color", "flyer", "instruction_card")
        game = self._with("Real DMD Images", "Real DMD Color Images",
                          "Instruction Cards", "Flyer Images/Front")

        found = mapping.media_for("pinballx", game, known)

        self.assertEqual(sorted(kind for kind, _p in found),
                         ["flyer", "instruction_card", "real_dmd", "real_dmd_color"])
        self.assertEqual(mapping.unmapped_kinds("pinballx", game, known), [])

    def test_the_real_dmd_videos_and_the_other_flyer_pages_have_none(self) -> None:
        known = (*KINDS, "real_dmd", "real_dmd_color", "flyer", "instruction_card")
        game = self._with("Real DMD Videos", "Real DMD Color Videos",
                          "Flyer Images/Inside1", "Flyer Images/Back")

        self.assertEqual(mapping.media_for("pinballx", game, known), [])
        self.assertEqual(mapping.unmapped_kinds("pinballx", game, known),
                         ["Flyer Images/Back", "Flyer Images/Inside1",
                          "Real DMD Color Videos", "Real DMD Videos"])

    def test_the_files_left_behind_are_counted_by_folder(self) -> None:
        games = [self._with("Real DMD Videos", "Table Images"),
                 self._with("Real DMD Videos", "Flyer Images/Back")]
        games[1] = _game(media=tuple(
            SourceMedia(source_kind=one.source_kind, path=f"/t/{one.source_kind}.png")
            for one in games[1].media))

        self.assertEqual(mapping.left_behind("pinballx", games, KINDS),
                         {"Flyer Images/Back": 1, "Real DMD Videos": 2})

    def test_a_shared_file_listed_for_two_systems_is_one_file_left_behind(self) -> None:
        item = SourceMedia(source_kind="Flyer Images/Back", path="/m/Back/Taxi.png",
                           shared=True)
        games = [_game(media=(item,)), _game(media=(item,))]

        self.assertEqual(mapping.left_behind("pinballx", games, KINDS),
                         {"Flyer Images/Back": 1})

    def test_a_source_nothing_maps_carries_nothing_rather_than_guessing(self) -> None:
        game = self._with("Table Images")

        self.assertEqual(mapping.media_for("emulationstation", game, KINDS), [])


class FolderNameTests(unittest.TestCase):
    def test_what_the_source_shows_a_person_names_the_folder(self) -> None:
        """Taken whole, so a converted library stays recognizable to whoever converted
        it."""
        self.assertEqual(
            mapping.folder_name(_game(display_name="Taxi (Williams 1988)")),
            "Taxi (Williams 1988)")

    def test_a_source_with_no_display_name_gets_one_built(self) -> None:
        """EmulationStation names the machine and nothing else, so the folder is built
        the way our own import builds one rather than left as a bare title."""
        self.assertEqual(
            mapping.folder_name(_game(title="Taxi", manufacturer="Williams",
                                      year="1988")),
            "Taxi (Williams 1988)")

    def test_half_of_what_it_takes_still_builds_something(self) -> None:
        self.assertEqual(
            mapping.folder_name(_game(title="Taxi", manufacturer="Williams")),
            "Taxi (Williams)")

    def test_a_title_alone_is_the_folder(self) -> None:
        self.assertEqual(mapping.folder_name(_game(title="Taxi")), "Taxi")

    def test_the_key_is_the_last_resort(self) -> None:
        """And only because something has to be."""
        self.assertEqual(mapping.folder_name(_game(key="taxi")), "taxi")

    def test_prose_is_never_mistaken_for_a_name(self) -> None:
        """EmulationStation's desc is a sentence about the game. It shares a name with
        PinballX's element and means something else entirely, which is how a folder came
        to be called "A pinball machine."."""
        self.assertEqual(
            mapping.folder_name(_game(key="afm", title="Attack from Mars",
                                      blurb="A pinball machine.")),
            "Attack from Mars")

    def test_a_replacement_character_is_mended_from_the_key(self) -> None:
        """A description read in the wrong encoding names a folder a share cannot read
        back, so the name the key still holds is used."""
        game = _game(key="Jack-Bot (Williams 1995)",
                     display_name="Jack\ufffdBot (Williams 1995)")

        self.assertEqual(mapping.folder_name(game), "Jack-Bot (Williams 1995)")

    def test_a_mark_that_stood_for_more_than_one_character_is_mended_too(self) -> None:
        game = _game(key="Electromec\u00e1nica (Fliperama 1990)",
                     display_name="Electromec\ufffd\ufffdnica (Fliperama 1990)")

        self.assertEqual(mapping.folder_name(game), "Electromec\u00e1nica (Fliperama 1990)")

    def test_the_game_file_names_it_where_the_key_cannot(self) -> None:
        game = _game(key="pb1", display_name="Pin\ufffdBot (Gottlieb 1980)",
                     table_file="/tables/Pin-Bot (Gottlieb 1980).vpx")

        self.assertEqual(mapping.folder_name(game), "Pin-Bot (Gottlieb 1980)")

    def test_a_mark_nothing_can_mend_is_dropped(self) -> None:
        game = _game(key="x", display_name="Elec\ufffdtro (Bally 1980)")

        self.assertEqual(mapping.folder_name(game), "Electro (Bally 1980)")

    def test_a_name_comes_out_composed(self) -> None:
        decomposed = "Caf\u0065\u0301 (Bally 1980)"

        self.assertEqual(mapping.folder_name(_game(display_name=decomposed)),
                         "Caf\u00e9 (Bally 1980)")


if __name__ == "__main__":
    unittest.main()
