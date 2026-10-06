"""The Backups row on a panel: what it says, and the one press that takes a copy."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

from common.backups import copies
from common.i18n import t
from console import backup_rows, deeplink, when


def _copy(taken: str, copy_id: str = "c") -> dict:
    return {"id": copy_id, "taken": taken}


class Said(unittest.TestCase):
    def test_no_copies_says_none(self) -> None:
        self.assertEqual(backup_rows.said([]), t("word.none"))

    def test_the_count_and_the_newest_are_said_together(self) -> None:
        found = [_copy("2026-10-02T01:02:03Z", "a"), _copy("2026-10-04T09:08:07Z", "b")]

        self.assertEqual(backup_rows.said(found),
                         t("console.backups.row", count=2,
                           newest=when.local_seconds("2026-10-04T09:08:07Z")))


class Listed(unittest.TestCase):
    def test_a_listing_that_cannot_be_read_is_no_copies(self) -> None:
        library = Mock()
        library.backups.side_effect = OSError("down")

        self.assertEqual(asyncio.run(backup_rows.listed(library, "game", "g1")), [])

    def test_the_copies_of_one_thing_are_asked_for_by_kind_and_id(self) -> None:
        library = Mock()
        library.backups.return_value = {"copies": [_copy("2026-10-02T01:02:03Z")]}

        found = asyncio.run(backup_rows.listed(library, "theme", "Classic"))

        library.backups.assert_called_once_with("theme", "Classic")
        self.assertEqual(len(found), 1)


class BackUp(unittest.TestCase):
    def _press(self, of_kind: str, of_id: str) -> tuple[Mock, AsyncMock]:
        library, after = Mock(), AsyncMock()
        with patch.object(backup_rows.ui, "notify"):
            asyncio.run(backup_rows.back_up(library, of_kind, of_id, after))
        return library, after

    def test_a_game_is_backed_up_as_the_games_scope(self) -> None:
        library, after = self._press(copies.OF_GAME, "g1")

        library.take_backup.assert_called_once_with("games", games=["g1"], launcher="")
        after.assert_awaited_once()

    def test_a_launcher_is_backed_up_as_the_launcher_scope(self) -> None:
        library, _ = self._press(copies.OF_LAUNCHER, "l1")

        library.take_backup.assert_called_once_with("launcher", games=[], launcher="l1")

    def test_a_failure_is_said_and_the_panel_is_left_as_it_was(self) -> None:
        library, after = Mock(), AsyncMock()
        library.take_backup.side_effect = OSError("full")
        with patch.object(backup_rows.ui, "notify") as notify:
            asyncio.run(backup_rows.back_up(library, copies.OF_GAME, "g1", after))

        self.assertEqual(notify.call_args.args[0], t("console.backups.back_up_failed"))
        after.assert_not_awaited()

    def test_several_games_are_one_backup(self) -> None:
        library = Mock()
        with patch.object(backup_rows.ui, "notify") as notify:
            asyncio.run(backup_rows.back_up_games(library, ["g1", "g2"]))

        library.take_backup.assert_called_once_with("games", games=["g1", "g2"])
        self.assertEqual(notify.call_args.args[0],
                         t("console.backups.done_games", count=2))


class OpenInBackups(unittest.TestCase):
    def test_the_address_names_the_page_and_what_to_find(self) -> None:
        with patch.object(backup_rows.ui.navigate, "to") as go:
            backup_rows._open_in_backups("Attack from Mars")

        self.assertEqual(go.call_args.args[0],
                         "/console?view=backups&find=Attack+from+Mars")

    def test_the_page_seeds_its_search_from_the_address(self) -> None:
        state: dict = {}
        deeplink.apply(state, {"view": "backups", "find": " Mars "},
                       views=["backups"], sections=[])

        self.assertEqual(state["find"], "Mars")

    def test_it_means_nothing_on_another_page(self) -> None:
        state: dict = {}
        deeplink.apply(state, {"view": "games", "find": "Mars"},
                       views=["games", "backups"], sections=[])

        self.assertNotIn("find", state)


if __name__ == "__main__":
    unittest.main()
