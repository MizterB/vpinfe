"""The Source a held file reads in the Discovery pane: the lister of the release it is tied
to, else Local."""

from __future__ import annotations

import asyncio
import unittest
from functools import partial
from types import SimpleNamespace
from typing import Any, cast
from unittest import mock

from nicegui import core, ui

from manager.library import discovery_list
from manager.library.discovery_kinds import Kind, Scene

_PAGE = ui.element()

RECORD = {"vps_file_id": "r1", "version": "1.0", "authors": ["Alice"]}
TIED = {"name": "rulesheet.pdf", "vps_file_id": "r1"}
LOOSE = {"name": "rulesheet.pdf", "vps_file_id": ""}


def _kind(**more: Any) -> Kind:
    return Kind(key="discovery_rulefiles", word="Rule Sheet", listed_as="ruleFiles",
                media="rule_sheet", records=[RECORD], **more)


def _scene() -> Scene:
    return cast(Scene, SimpleNamespace(game_id="g1", title="Alpha", vps_id="E1"))


class SourceLineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        was = core.loop
        core.loop = asyncio.get_running_loop()
        self.addCleanup(setattr, core, "loop", was)

    def _labels(self, draw: Any) -> list[str]:
        with _PAGE:
            body = ui.column()
            with body:
                draw()
        return [one.text for one in body.descendants() if isinstance(one, ui.label)]

    def _have(self, held: dict[str, str]) -> list[str]:
        library = mock.Mock()
        library.update_moves.return_value = []
        library.media = {}
        return self._labels(lambda: discovery_list._have(
            {"library": library}, _scene(), _kind(mine=[held]), held))

    async def test_a_file_tied_to_a_release_reads_vps(self) -> None:
        self.assertIn("Source: VPS", self._have(TIED))

    async def test_a_file_tied_to_nothing_reads_local(self) -> None:
        self.assertIn("Source: Local", self._have(LOOSE))

    async def test_the_full_card_says_the_same(self) -> None:
        for held, said in ((TIED, "Source: VPS"), (LOOSE, "Source: Local")):
            kind = _kind(mine=[held])
            labels = self._labels(partial(
                discovery_list._card, {"state": {}}, _scene(), kind, [RECORD],
                discovery_list._View(), False, lambda _id: None))
            self.assertIn(said, labels)

    async def test_the_held_tile_says_the_same(self) -> None:
        for matched, said in (("r1", "Source: VPS"), ("", "Source: Local")):
            kind = _kind(held=True, slot={"present": True, "matched_to": matched})
            scene = cast(Scene, SimpleNamespace(
                game_id="g1", title="Alpha", tray=mock.Mock(), sources={}))
            labels = self._labels(partial(
                discovery_list._tiles, {"library": mock.Mock(), "state": {}}, scene, kind))
            self.assertIn(said, labels)


if __name__ == "__main__":
    unittest.main()
