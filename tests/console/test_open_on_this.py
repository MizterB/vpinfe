"""A collection's Open On: what the frontend opens on, and the act that moves it."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

from common.i18n import t
from console import workbench
from tests.support.clicks import press


async def _now(callback: Any, *args: Any, **kwargs: Any) -> Any:
    return callback(*args, **kwargs)


class OpenOn(unittest.IsolatedAsyncioTestCase):
    def _drawn(self, name: str, opens_on: str) -> tuple[str, str, Any, dict[str, Any]]:
        """The value shown, the label of the one act, that act, and the context."""
        context = {"library": Mock(), "state": {},
                   "settings": {"behavior": {"startup_collection": opens_on}}}
        shown: list[str] = []
        acts: list[Any] = []

        def action(label: str, on_click: Any, **_: Any) -> Any:
            acts.append((label, on_click))
            return lambda: None

        class Label:
            def __init__(self, text: str) -> None:
                shown.append(text)

            def classes(self, *_: Any) -> Label:
                return self

        class Row:
            def __enter__(self) -> Row:
                return self

            def __exit__(self, *_: Any) -> None:
                return None

            def classes(self, *_: Any) -> Row:
                return self

        with patch.object(workbench.panel, "action", new=action), \
                patch.object(workbench.ui, "row", new=lambda: Row()), \
                patch.object(workbench.ui, "label", new=Label):
            workbench._open_on(context, {"name": name})()
        label, act = acts[0]
        return shown[0], label, act, context

    async def _used(self, name: str, opens_on: str) -> dict[str, Any]:
        _, _, use, context = self._drawn(name, opens_on)
        with patch.object(workbench.run, "io_bound", new=_now), \
                patch.object(workbench, "_written", new=AsyncMock()) as written:
            await press(use)
        context["written"] = written
        return context

    def test_it_names_the_collection_the_frontend_opens_on_and_offers_all_games(self) -> None:
        shown, label, _, _ = self._drawn("Friday Night", "Friday Night")

        self.assertEqual(("Friday Night", t("console.workbench.open_on.use_all")),
                         (shown, label))

    def test_another_collection_is_named_and_this_one_is_offered(self) -> None:
        shown, label, _, _ = self._drawn("90s Bally", "Friday Night")

        self.assertEqual(("Friday Night", t("console.workbench.open_on.use_this")),
                         (shown, label))

    def test_nothing_set_says_all_games_and_offers_this_one(self) -> None:
        shown, label, _, _ = self._drawn("90s Bally", "")

        self.assertEqual((t("console.workbench.open_on.all_games"),
                          t("console.workbench.open_on.use_this")), (shown, label))

    async def test_using_this_writes_the_setting_settings_writes(self) -> None:
        context = await self._used("90s Bally", "Friday Night")

        context["library"].put_config.assert_called_once_with(
            {"behavior": {"startup_collection": "90s Bally"}})
        context["written"].assert_awaited_once()

    async def test_using_all_games_empties_it(self) -> None:
        context = await self._used("Friday Night", "Friday Night")

        context["library"].put_config.assert_called_once_with(
            {"behavior": {"startup_collection": ""}})


if __name__ == "__main__":
    unittest.main()
