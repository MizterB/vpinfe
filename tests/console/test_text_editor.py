"""The text editor's drafts: what is kept per file, what the leave question lists, and what
marks a file on the Assets grid."""

from __future__ import annotations

import asyncio
import unittest
from typing import Any
from unittest import mock

from nicegui import core, ui

from console import assets, offload, text_editor, workbench


def _draft(name: str) -> dict[str, Any]:
    return {"text": "x", "base": "y", "version": "v", "name": name}


class Drafts(unittest.TestCase):
    def test_a_state_with_no_drafts_waits_on_nothing(self) -> None:
        self.assertEqual([], text_editor.waiting({}))

    def test_the_leave_question_lists_every_file_by_name(self) -> None:
        state: dict[str, Any] = {}
        text_editor.drafts_of(state)[("g1", "a.vbs")] = _draft("Game One - Table Script")
        text_editor.drafts_of(state)[("g2", "b.ini")] = _draft("Game Two - Table INI")

        self.assertEqual(["Game One - Table Script", "Game Two - Table INI"],
                         text_editor.waiting(state))

    def test_the_same_file_in_one_game_is_one_draft(self) -> None:
        state: dict[str, Any] = {}
        text_editor.drafts_of(state)[text_editor.draft_key("g", "a.vbs")] = _draft("one")
        text_editor.drafts_of(state)[text_editor.draft_key("g", "a.vbs")] = _draft("two")

        self.assertEqual(["two"], text_editor.waiting(state))


class WhichKinds(unittest.TestCase):
    def test_every_text_kind_the_assets_view_lists_is_edited(self) -> None:
        for kind in ("script", "ini", "pov", "scv", "patch", "readme"):
            with self.subTest(kind=kind):
                self.assertTrue(text_editor.edits(kind))

    def test_the_info_and_the_backglass_are_not(self) -> None:
        for kind in ("metadata", "backglass", "wheel"):
            with self.subTest(kind=kind):
                self.assertFalse(text_editor.edits(kind))

    def test_only_notes_wrap(self) -> None:
        self.assertEqual(frozenset({"readme"}), text_editor.WRAPPED)


class TheGridMark(unittest.TestCase):
    ROW = {"game_id": "g1", "path": "a.vbs", "kind": "script", "label": "Table Script",
           "present": True}

    def test_a_file_with_a_draft_is_marked(self) -> None:
        built = assets.rows([self.ROW, {**self.ROW, "path": "b.ini", "kind": "ini"}],
                            {("g1", "a.vbs")})

        self.assertEqual([True, False], [row["unsaved"] for row in built])

    def test_the_same_path_in_another_game_is_not(self) -> None:
        built = assets.rows([{**self.ROW, "game_id": "g2"}], {("g1", "a.vbs")})

        self.assertFalse(built[0]["unsaved"])


class TheStage(unittest.TestCase):
    def test_a_file_read_as_text_has_a_stage_though_its_head_is_empty(self) -> None:
        self.assertTrue(workbench._asset_has_stage(
            {"kind": "scv", "detail": {"text": {"text": "x", "editable": True}}}))

    def test_a_file_that_is_not_text_has_none(self) -> None:
        self.assertFalse(workbench._asset_has_stage({"kind": "scv", "detail": {}}))


class _Library:
    """What the editor reads and writes through; `typing` runs inside a save."""

    def __init__(self) -> None:
        self.saved: list[str] = []
        self.typing: Any = None
        self.version = 1
        self.on_disk = "x = 1"
        self.unreadable = False

    def asset_text(self, game_id: str, path: str) -> dict[str, Any]:
        if self.unreadable:
            raise OSError("gone")
        return {"text": self.on_disk, "version": f"v{self.version}"}

    def save_asset_text(self, game_id: str, path: str, text: str, version: str,
                        replace_changed: bool, keep_copy: bool) -> dict[str, Any]:
        self.saved.append(text)
        if self.typing:
            self.typing()
        self.on_disk = text
        self.version += 1
        return {"version": f"v{self.version}"}


async def _inline(callback: Any, *args: Any) -> Any:
    await asyncio.sleep(0)
    return callback(*args)


class TheStrip(unittest.TestCase):
    FOUND = {"text": "x = 1", "version": "v1"}

    def setUp(self) -> None:
        self.library = _Library()
        self.state: dict[str, Any] = {}
        self.notes: list[str] = []
        for patcher in (mock.patch.object(offload, "io", _inline),
                        mock.patch.object(text_editor.ui, "run_javascript"),
                        mock.patch.object(text_editor.ui, "notify",
                                          lambda message, **_: self.notes.append(message))):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _drawn(self, locked: str = "") -> ui.card:
        context = {"state": self.state, "library": self.library, "game_id": "g",
                   "kind": "ini"}
        holder = ui.card()
        with holder:
            text_editor.editor(context, "a.ini", "Table INI", self.FOUND, locked,
                               lambda text: None, locked_help="why")
        self.holder = holder
        return holder

    def _editor(self) -> ui.codemirror:
        return next(one for one in self.holder.descendants() if isinstance(one, ui.codemirror))

    def _button(self, label: str) -> ui.button:
        return next(one for one in self.holder.descendants()
                    if isinstance(one, ui.button) and one.props.get("label") == label)

    def _pressed(self, label: str) -> Any:
        listener = next(one for one in self._button(label)._event_listeners.values()
                        if one.type == "click")
        assert listener.handler is not None
        return listener.handler(None)

    def _press(self, label: str, times: int = 1) -> None:
        async def together() -> None:
            was = core.loop
            core.loop = asyncio.get_running_loop()
            try:
                for _ in range(times):
                    self._pressed(label)
                await asyncio.sleep(0.05)
            finally:
                core.loop = was

        asyncio.run(together())

    def test_a_file_that_cannot_be_saved_is_read_only_with_no_save(self) -> None:
        self._drawn("Playing")

        self.assertFalse(self._editor().enabled)
        self.assertFalse(self._button("Save").visible)
        self.assertFalse(self._button("Cancel").visible)

    def test_a_draft_on_a_file_that_cannot_be_saved_can_still_be_dropped(self) -> None:
        self._drawn("Playing")
        self._editor().value = "x = 2"

        self.assertTrue(self._button("Cancel").visible)
        self._press("Cancel")
        self.assertEqual("x = 1", self._editor().value)
        self.assertEqual([], text_editor.waiting(self.state))

    def test_a_file_that_can_be_saved_is_editable_with_both(self) -> None:
        self._drawn()

        self.assertTrue(self._editor().enabled)
        self.assertTrue(self._button("Save").visible)
        self.assertTrue(self._button("Cancel").visible)

    def test_saving_ends_the_draft(self) -> None:
        self._drawn()
        self._editor().value = "x = 2"
        self.assertEqual(["Table INI"], [n.split(" - ")[-1] for n in
                                        text_editor.waiting(self.state)])
        self._press("Save")

        self.assertEqual(["x = 2"], self.library.saved)
        self.assertEqual([], text_editor.waiting(self.state))

    def test_text_typed_during_a_save_stays_a_draft(self) -> None:
        self._drawn()
        self._editor().value = "x = 2"
        self.library.typing = lambda: setattr(self._editor(), "value", "x = 3")
        self._press("Save")

        self.assertEqual("x = 3", self._editor().value)
        self.assertEqual(1, len(text_editor.waiting(self.state)))
        self.library.typing = None
        self._press("Save")
        self.assertEqual(["x = 2", "x = 3"], self.library.saved)
        self.assertEqual([], text_editor.waiting(self.state))

    def test_a_second_save_while_one_is_going_is_not_sent(self) -> None:
        self._drawn()
        self._editor().value = "x = 2"
        self._press("Save", times=2)

        self.assertEqual(["x = 2"], self.library.saved)

    def test_cancel_that_cannot_read_the_file_says_so_and_goes_back(self) -> None:
        self._drawn()
        self._editor().value = "x = 2"
        self.library.unreadable = True
        self._press("Cancel")

        self.assertEqual("x = 1", self._editor().value)
        self.assertEqual(1, len(self.notes))
        self.assertEqual([], text_editor.waiting(self.state))


if __name__ == "__main__":
    unittest.main()
