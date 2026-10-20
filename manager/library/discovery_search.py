"""Discovery's search box: the one on the tab row, and any page that wants the same.

Typing lists the authors, makers, themes and games it could mean, and a pick opens that
page (`discovery_ask.Suggest`). The box is drawn before a tab has read the catalog, so the
tab hands it what to suggest from with `feed`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from nicegui import ui

from common.i18n import t
from common.online import vps_find
from manager.kit import panel
from manager.library import discovery_ask

# Where the tab row's box is kept in the page state while its tab is drawn.
KEY = "discovery_search"

Choose = Callable[[str, dict[str, Any]], Awaitable[None]]


class SearchBox:
    """The box, drawn into the current container. Until it is fed it lists nothing."""

    def __init__(self) -> None:
        self.people: list[dict[str, Any]] = []
        self.games: list[dict[str, Any]] = []
        self.choose: Choose | None = None
        with ui.element("div").classes("manager-suggest-anchor manager-search-slot"):
            self.input = panel.search(t("manager.discovery.search")) \
                .classes(add="manager-search", remove="w-64")
            discovery_ask.Suggest(self.input, self._find, self._pick)

    def _find(self, text: str) -> dict[str, list[dict[str, Any]]]:
        return vps_find.find(text, self.people, self.games)

    async def _pick(self, group: str, one: dict[str, Any]) -> None:
        if self.choose is not None:
            await self.choose(group, one)

    def feed(self, people: list[dict[str, Any]], games: list[dict[str, Any]],
             choose: Choose, *, narrow: Callable[[str], Any] | None = None) -> None:
        """Suggest from `people` and `games`, and run `choose(group, one)` on a pick. The
        lists are kept, not copied, so a tab that reads again in place needs no new feed.
        `narrow(text)` runs on every change of the text, for a tab that filters by it."""
        self.people, self.games, self.choose = people, games, choose
        if narrow is not None:
            self.input.on_value_change(lambda: narrow(self.input.value or ""))


def feed(state: dict[str, Any], people: list[dict[str, Any]], games: list[dict[str, Any]],
         choose: Choose, *, narrow: Callable[[str], Any] | None = None) -> None:
    """Feed the tab row's box. A page drawn without one has no box to feed."""
    box = state.get(KEY)
    if box is not None:
        box.feed(people, games, choose, narrow=narrow)
