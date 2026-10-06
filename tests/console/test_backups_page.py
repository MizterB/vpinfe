"""The Backups page: what a copy becomes as a row, and what can be done to one."""

from __future__ import annotations

import unittest
from unittest import mock

from common import i18n
from common.backups import copies
from common.i18n import t
from console import backups, when
from console.data import Library


def _copy(copy_id: str = "c1", **over) -> dict:
    return {"id": copy_id, "of_kind": copies.OF_GAME, "of_id": "g1", "of_name": "Attack from Mars",
            "kind": copies.KIND_GAME, "file": "Attack from Mars.info.vpinfe-20260909T110917Z",
            "path": "/library/Attack from Mars/Attack from Mars.info.vpinfe-20260909T110917Z",
            "taken": "2026-09-09T11:09:17Z", "written_by": copies.BY_3X,
            "why": copies.WHY_UPGRADE, "note": "", "size": 2048, "gone": False, **over}


class Rows(unittest.TestCase):
    def test_a_part_of_a_backup_is_not_a_row(self) -> None:
        found = [_copy("a"), _copy("b", within="a")]

        self.assertEqual(["a"], [row["id"] for row in backups.rows(found)])

    def test_the_stamp_is_kept_and_the_text_is_drawn_from_it(self) -> None:
        row = backups.rows([_copy()])[0]

        self.assertEqual("2026-09-09T11:09:17Z", row["taken"])
        self.assertEqual("2026-09-09T11:09:17Z", row["taken_utc"])
        self.assertEqual(when.local_seconds("2026-09-09T11:09:17Z"), row["taken_text"])

    def test_the_size_is_drawn_as_a_size(self) -> None:
        self.assertEqual(i18n.size(2048), backups.rows([_copy()])[0]["size_text"])

    def test_a_copy_with_nothing_to_say_has_empty_cells(self) -> None:
        row = backups.rows([{"id": "x"}])[0]

        self.assertEqual(("", "", 0, False), (row["note"], row["taken_text"], row["size"],
                                              row["gone"]))

    def test_a_backup_holding_records_says_so_and_one_without_does_not(self) -> None:
        found = [_copy("a", of_kind=copies.OF_ARCHIVE), _copy("b", of_kind=copies.OF_ARCHIVE),
                 _copy("a1", within="a", of_kind=copies.OF_VPINFE),
                 _copy("b1", within="b", of_kind=copies.OF_GAME)]

        held = {row["id"]: row["holds_records"] for row in backups.rows(found)}

        self.assertEqual({"a": True, "b": False}, held)
        self.assertTrue(backups._waits_for_a_restart(backups.rows(found)[0]))
        self.assertFalse(backups._waits_for_a_restart(backups.rows(found)[1]))

    def test_a_backup_is_found_by_the_names_of_what_is_in_it(self) -> None:
        found = [_copy("a", of_kind=copies.OF_ARCHIVE, of_name="2 games"),
                 _copy("a1", within="a", of_name="Attack from Mars"),
                 _copy("a2", within="a", of_name="Medieval Madness")]

        row = backups.rows(found)[0]

        self.assertEqual("Attack from Mars Medieval Madness", row["holds"])
        self.assertEqual("2 games", row["of"])

    def test_a_copy_with_no_owner_is_named_by_its_file(self) -> None:
        row = backups.rows([_copy(of_name="")])[0]

        self.assertEqual(row["file"], backups.name_of(row))

    def test_every_kind_why_and_writer_has_a_word(self) -> None:
        for table, tokens in (
                (backups.KIND_WORDS, [v for k, v in vars(copies).items() if k.startswith("KIND_")]),
                (backups.WHY_WORDS, [v for k, v in vars(copies).items() if k.startswith("WHY_")]),
                (backups.BY_WORDS, [copies.BY_2X, copies.BY_3X])):
            for token in tokens:
                with self.subTest(token=token):
                    self.assertIn(token, table)
                    self.assertNotEqual(table[token], t(table[token]))


class Summary(unittest.TestCase):
    def test_it_counts_and_sizes_what_is_listed(self) -> None:
        shown = backups.rows([_copy("a", size=1024), _copy("b", size=1024)])

        self.assertEqual(t("console.backups.summary", count=2, size=i18n.size(2048)),
                         backups.summary(shown))

    def test_one_copy_reads_as_one(self) -> None:
        one = backups.summary(backups.rows([_copy("a")]))
        two = backups.summary(backups.rows([_copy("a"), _copy("b")]))

        self.assertNotEqual(one, two.replace("2", "1", 1))


class Acts(unittest.TestCase):
    def _acts(self, *rows: dict, many: bool = False):
        return backups.acts(mock.Mock(spec=Library), list(rows), mock.Mock(), many=many)

    def test_delete_is_last_and_dangerous(self) -> None:
        verbs = self._acts(backups.rows([_copy()])[0])

        self.assertEqual(t("word.delete"), verbs[-1].label)
        self.assertTrue(verbs[-1].danger)

    def test_copy_path_is_for_one_row(self) -> None:
        row = backups.rows([_copy()])[0]

        self.assertIn(t("console.backups.copy_path"), [v.label for v in self._acts(row)])
        self.assertNotIn(t("console.backups.copy_path"),
                         [v.label for v in self._acts(row, row, many=True)])

    def test_a_copy_whose_owner_is_gone_cannot_be_restored_and_says_why(self) -> None:
        row = backups.rows([_copy(gone=True)])[0]

        restore = self._acts(row)[0]

        self.assertIsNone(restore.run)
        self.assertEqual(t("console.backups.owner_gone"), restore.hint)

    def test_a_selection_with_one_present_copy_can_still_be_restored(self) -> None:
        gone, present = backups.rows([_copy("a", gone=True), _copy("b")])

        self.assertIsNotNone(self._acts(gone, present, many=True)[0].run)


class Wrappers(unittest.TestCase):
    def test_a_restore_makes_the_library_read_its_games_again(self) -> None:
        client = mock.Mock()
        client.restore_backup.return_value = {"copy": {}}
        library = Library(client)

        with mock.patch.object(library, "_forget_games") as forget:
            library.restore_backup("c1")

        client.restore_backup.assert_called_once_with("c1")
        forget.assert_called_once_with()

    def test_a_run_of_restores_reads_the_games_once_when_it_says_so(self) -> None:
        client = mock.Mock()
        client.restore_backup.return_value = {"copy": {}}
        library = Library(client)

        with mock.patch.object(library, "_forget_games") as forget:
            library.restore_backup("c1", reread=False)
            library.restore_backup("c2", reread=False)
            library.restored_backups()

        forget.assert_called_once_with()


class Deleting(unittest.IsolatedAsyncioTestCase):
    async def test_a_delete_that_answers_nothing_still_reads_the_copies_again(self) -> None:
        library = mock.Mock(spec=Library)
        library.delete_backup.return_value = None
        refresh = mock.AsyncMock()
        row = backups.rows([_copy()])[0]

        with mock.patch("console.on_page.ui"), \
                mock.patch.object(backups.confirm, "ask", mock.AsyncMock(return_value=True)), \
                mock.patch.object(backups, "ui"):
            await backups.delete(library, [row], refresh)

        library.delete_backup.assert_called_once_with("c1")
        refresh.assert_awaited_once_with()


class Columns(unittest.TestCase):
    def test_every_column_header_has_a_tooltip(self) -> None:
        bare = [one["field"] for one in backups.COLUMNS if not one.get("headerTooltip")]

        self.assertEqual([], bare)


class Views(unittest.TestCase):
    def test_every_kind_a_copy_can_be_is_in_a_view_and_the_first_view_is_everything(self) -> None:
        filtered = {kind for preset in backups.VIEWS.values()
                    for kind in preset.filters.get("kind", {}).get("values", [])}

        self.assertEqual(set(backups.KIND_WORDS), filtered)
        self.assertEqual("console.view.everything", next(iter(backups.VIEWS)))

    def test_a_view_names_only_columns_the_grid_has(self) -> None:
        for key, preset in backups.VIEWS.items():
            self.assertLessEqual(set(preset.columns), set(backups._ALL), key)

    def test_a_view_of_one_kind_does_not_repeat_the_kind_in_a_column(self) -> None:
        for key in ("console.view.backups_games", "console.view.backups_themes"):
            self.assertNotIn("kind", backups.VIEWS[key].columns)

    def test_a_view_shows_its_columns_in_the_grids_order(self) -> None:
        for key, preset in backups.VIEWS.items():
            self.assertEqual(sorted(preset.columns, key=backups._ALL.index),
                             list(preset.columns), key)

    def test_the_file_name_is_the_last_column_and_only_everything_shows_it(self) -> None:
        self.assertEqual("file", backups._ALL[-1])
        for key, preset in backups.VIEWS.items():
            self.assertEqual(key == "console.view.everything", "file" in preset.columns, key)

    def test_a_view_leaves_out_a_column_that_holds_one_value_there(self) -> None:
        vpinfe = backups.VIEWS["console.view.backups_vpinfe"].columns
        yours = backups.VIEWS["console.view.backups_yours"].columns

        self.assertNotIn("of", vpinfe)
        self.assertIn("kind", vpinfe)
        self.assertTrue({"why", "written_by"}.isdisjoint(yours))

    def test_a_linked_search_opens_on_everything_and_keeps_the_users_views(self) -> None:
        library = mock.Mock(spec=Library)
        library.preferences.return_value = {
            "views": [{"id": "view:1", "name": "Mine"}],
            "active": "builtin:console.view.backups_themes"}

        backups._open_on_everything(library)

        saved = library.put_preferences.call_args.args[1]
        self.assertEqual("builtin:console.view.everything", saved["active"])
        self.assertEqual(["view:1"], [one["id"] for one in saved["views"]])


class LocalSeconds(unittest.TestCase):
    def test_two_copies_in_one_minute_read_differently(self) -> None:
        self.assertNotEqual(when.local_seconds("2026-09-09T11:09:17Z"),
                            when.local_seconds("2026-09-09T11:09:18Z"))

    def test_what_is_not_a_time_is_said_as_it_is(self) -> None:
        self.assertEqual("", when.local_seconds(None))
        self.assertEqual("soon", when.local_seconds("soon"))


if __name__ == "__main__":
    unittest.main()
