"""The rows of the whole library are built once and kept, and rebuilt only where a game changed."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from common import events, service_errors
from common.games import game_repository, table_lens


def _rows_for(game_id, entry, media, media_settings, launcher_view):
    return [{"id": f"tbl-{game_id}", "game_id": game_id, "game": entry.name,
             "filename": f"{entry.name}.vpx", "key": "", "source": None}]


class LibraryRowsHeld(unittest.TestCase):
    def setUp(self) -> None:
        table_lens._rows_held.clear()
        self.clock = [1000.0]
        self.entries = {f"G{n}": SimpleNamespace(name=f"Game {n}", full_path_game=f"/g/G{n}")
                        for n in range(3)}
        self.stamps: dict[str, int] = {}
        self.vps: list = []
        self.built: list[str] = []
        self._patches = [
            mock.patch.object(game_repository, "catalog", lambda: dict(self.entries)),
            mock.patch.object(table_lens, "_game_rows", self._build),
            mock.patch.object(table_lens, "LauncherView", lambda: object()),
            mock.patch.object(table_lens, "game_stamp",
                              lambda path: (self.stamps.get(str(path), 0),)),
            mock.patch.object(table_lens, "load_vpsdb", lambda: self.vps),
            mock.patch.object(table_lens, "monotonic", lambda: self.clock[0]),
            mock.patch.object(table_lens.media_service, "media_settings",
                              lambda: ("table", None)),
        ]
        for patch in self._patches:
            patch.start()
            self.addCleanup(patch.stop)
        for name in (events.SETTINGS_CHANGED, events.COLLECTIONS_CHANGED):
            events.subscribe(name, game_repository.touch)
            self.addCleanup(events.unsubscribe, name, game_repository.touch)
        self.addCleanup(table_lens._rows_held.clear)

    def _build(self, game_id, entry, media, media_settings, launcher_view):
        self.built.append(game_id)
        return _rows_for(game_id, entry, media, media_settings, launcher_view)

    def test_a_second_read_builds_nothing(self) -> None:
        first = table_lens.library_rows()
        self.built.clear()

        second = table_lens.library_rows()

        self.assertEqual(self.built, [])
        self.assertEqual(second, first)

    def test_a_game_whose_folder_changed_rebuilds_alone(self) -> None:
        table_lens.library_rows()
        self.built.clear()
        self.stamps["/g/G2"] = 1

        table_lens.library_rows()
        self.assertEqual(self.built, ["G2"])
        table_lens.library_rows()
        self.assertEqual(self.built, ["G2"])

    def test_one_game_is_read_afresh_each_time(self) -> None:
        table_lens.library_rows()
        self.built.clear()

        table_lens.library_rows(game="G1")
        table_lens.library_rows(game="G1")

        self.assertEqual(self.built, ["G1", "G1"])

    def test_a_reloaded_catalog_rebuilds(self) -> None:
        table_lens.library_rows()
        self.built.clear()

        self.vps = []
        table_lens.library_rows()

        self.assertEqual(len(self.built), 3)

    def test_a_replaced_entry_rebuilds_only_its_game(self) -> None:
        table_lens.library_rows()
        self.built.clear()
        self.entries["G1"] = SimpleNamespace(name="Renamed", full_path_game="/g/G1")

        rows = table_lens.library_rows()

        self.assertEqual(self.built, ["G1"])
        self.assertIn("Renamed", [row["game"] for row in rows["tables"]])

    def test_a_game_that_is_gone_leaves_the_list(self) -> None:
        table_lens.library_rows()
        del self.entries["G0"]

        rows = table_lens.library_rows()

        self.assertEqual(rows["total"], 2)
        self.assertNotIn("G0", [row["game_id"] for row in rows["tables"]])

    def test_a_read_of_one_game_leaves_the_others_held(self) -> None:
        table_lens.library_rows()
        self.built.clear()

        rows = table_lens.library_rows(game="G2")
        table_lens.library_rows()

        self.assertEqual([row["game_id"] for row in rows["tables"]], ["G2"])
        self.assertEqual(self.built, ["G2"])

    def test_a_touch_rebuilds_every_game(self) -> None:
        table_lens.library_rows()
        self.built.clear()

        game_repository.touch()
        table_lens.library_rows()

        self.assertEqual(sorted(self.built), ["G0", "G1", "G2"])

    def test_a_change_to_settings_or_collections_rebuilds(self) -> None:
        for name in (events.SETTINGS_CHANGED, events.COLLECTIONS_CHANGED):
            with self.subTest(event=name):
                table_lens.library_rows()
                self.built.clear()

                events.emit(name)
                table_lens.library_rows()

                self.assertEqual(len(self.built), 3)
                self.built.clear()

    def test_rows_older_than_the_limit_are_built_again(self) -> None:
        table_lens.library_rows()
        self.built.clear()

        self.clock[0] += table_lens.ROWS_HELD_S - 1
        table_lens.library_rows()
        self.assertEqual(self.built, [])

        self.clock[0] += 1
        table_lens.library_rows()
        self.assertEqual(len(self.built), 3)

    def test_each_thumbnail_kind_holds_its_own_rows(self) -> None:
        table_lens.library_rows(media="wheel")
        self.built.clear()

        table_lens.library_rows(media="wheel")
        table_lens.library_rows(media="")
        self.assertEqual(len(self.built), 3)
        self.built.clear()

        table_lens.library_rows(media="wheel")
        table_lens.library_rows(media="")
        self.assertEqual(self.built, [])

    def test_a_changed_media_setting_rebuilds(self) -> None:
        table_lens.library_rows(media="wheel")
        self.built.clear()

        with mock.patch.object(table_lens.media_service, "media_settings",
                               lambda: ("table", {"wheel": "classic"})):
            table_lens.library_rows(media="wheel")

        self.assertEqual(len(self.built), 3)

    def test_the_window_is_cut_from_the_held_rows(self) -> None:
        table_lens.library_rows()
        self.built.clear()

        rows = table_lens.library_rows(limit=2, offset=1)

        self.assertEqual((rows["total"], rows["count"]), (3, 2))
        self.assertEqual(self.built, [])


class SettingsWritesTouch(unittest.TestCase):
    def test_a_table_settings_write_moves_the_generation(self) -> None:
        from common.games import launcher_ops

        config = mock.Mock()
        config.write.return_value = set()
        found = mock.Mock()
        before = game_repository.generation()
        with mock.patch.object(launcher_ops, "_writable_before_writing"):
            launcher_ops._write_one(found, config, {}, "table", "/t/a.vpx",
                                    {"k": "v"}, False)

        self.assertGreater(game_repository.generation(), before)

    def test_a_refused_write_moves_it_too(self) -> None:
        from common.games import launcher_ops

        config = mock.Mock()
        config.write.side_effect = ValueError("no")
        before = game_repository.generation()
        with mock.patch.object(launcher_ops, "_writable_before_writing"), \
                self.assertRaises(service_errors.RefusedError):
            launcher_ops._write_one(mock.Mock(), config, {}, "table", "/t/a.vpx",
                                    {"k": "v"}, False)

        self.assertGreater(game_repository.generation(), before)


if __name__ == "__main__":
    unittest.main()
