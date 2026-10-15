"""The media slot's provenance line: where a file the view does not own comes from."""

from __future__ import annotations

import unittest
from unittest import mock

from common.i18n import t
from manager import workbench
from manager.kit import media_ownership


def _drawn(via: str | None, borrowed: bool, lens: str = "tbl") -> tuple[list[str], list[dict]]:
    context = {"lens": lens, "game_id": "g1"}
    with mock.patch.object(workbench, "ui") as ui, mock.patch.object(workbench, "panel") as panel:
        workbench._provenance(context, via, borrowed)
    labels = [call.args[0] for call in ui.label.call_args_list]
    links = [{"label": call.args[0], **call.kwargs} for call in panel.link.call_args_list]
    return labels, links


class TheProvenanceOfABorrowedFile(unittest.TestCase):
    def test_a_games_file_seen_from_a_table_links_to_the_game(self) -> None:
        labels, links = _drawn("game", borrowed=True)

        self.assertEqual([], labels)
        self.assertEqual([t("manager.media_ownership.from_game")], [one["label"] for one in links])
        self.assertIn("view=games", links[0]["to"])
        self.assertIn("game=g1", links[0]["to"])

    def test_the_library_default_is_a_plain_label(self) -> None:
        labels, links = _drawn("default", borrowed=True)

        self.assertEqual([t("manager.media_ownership.from_default")], labels)
        self.assertEqual([], links)

    def test_a_file_the_view_owns_keeps_its_sentence(self) -> None:
        for via in ("table", "game"):
            with self.subTest(via=via):
                labels, links = _drawn(via, borrowed=False)
                self.assertEqual([media_ownership.sentence(via, viewing_a_table=True)], labels)
                self.assertEqual([], links)

    def test_a_stand_in_keeps_its_sentence_borrowed_or_not(self) -> None:
        labels, links = _drawn("set:Colorful", borrowed=True)

        self.assertEqual([media_ownership.sentence("set:Colorful", viewing_a_table=True)], labels)
        self.assertEqual([], links)

    def test_a_tables_own_file_is_never_said_to_come_from_the_game(self) -> None:
        labels, links = _drawn("table", borrowed=True)

        self.assertEqual([], links)
        self.assertEqual(1, len(labels))


if __name__ == "__main__":
    unittest.main()
