"""What Add asks before a launcher exists."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

from console import launchers

ASKED = [{"key": "bin_path", "label": "Program", "path": "exe", "blank": ""},
         {"key": "ini_path", "label": "Settings File", "path": "file",
          "suffixes": [".ini"], "blank": "Its own"}]


class _Cancelled:
    """The dialog, answered Cancel."""

    def __enter__(self) -> _Cancelled:
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None

    def submit(self, _answer: Any) -> None:
        return None

    def __await__(self) -> Any:
        return _answered(False).__await__()


async def _answered(value: bool) -> bool:
    return value


class EmptyPaths(unittest.IsolatedAsyncioTestCase):
    async def test_an_empty_path_reads_as_the_word_its_app_gives_it(self) -> None:
        hints: list[str] = []

        def field(value: str = "", *, placeholder: str = "", lines: int = 0,
                  browse: Any = None) -> Mock:
            hints.append(placeholder)
            return Mock(value=value)

        def facts(_target: Any, entries: list[tuple[Any, Any]]) -> None:
            for _label, draw in entries:
                draw()

        with patch.object(launchers.frame, "opened", return_value=_Cancelled()), \
                patch.object(launchers.frame, "field", side_effect=field), \
                patch.object(launchers.frame, "footer"), \
                patch.object(launchers.frame, "cancel"), \
                patch.object(launchers.frame, "answer"), \
                patch.object(launchers.frame, "focus"), \
                patch.object(launchers.frame, "enter_presses"), \
                patch.object(launchers.panel, "facts", side_effect=facts):
            await launchers.ask_name("New", "Add", [], AsyncMock(), asked=ASKED,
                                     placeholder="VPX")

        self.assertEqual(hints, ["VPX", "", "Its own"])


class Browse(unittest.IsolatedAsyncioTestCase):
    async def _asked(self, **kwargs: Any) -> dict[str, Any]:
        """The `browse` each field was drawn with, by the placeholder it carries."""
        browsing: dict[str, Any] = {}

        def field(value: str = "", *, placeholder: str = "", lines: int = 0,
                  browse: Any = None) -> Mock:
            browsing[placeholder] = browse
            return Mock(value=value)

        def facts(_target: Any, entries: list[tuple[Any, Any]]) -> None:
            for _label, draw in entries:
                draw()

        with patch.object(launchers.frame, "opened", return_value=_Cancelled()), \
                patch.object(launchers.frame, "field", side_effect=field), \
                patch.object(launchers.frame, "footer"), \
                patch.object(launchers.frame, "cancel"), \
                patch.object(launchers.frame, "answer"), \
                patch.object(launchers.frame, "focus"), \
                patch.object(launchers.frame, "enter_presses"), \
                patch.object(launchers.panel, "facts", side_effect=facts):
            await launchers.ask_name("New", "Add", [], AsyncMock(), asked=ASKED,
                                     placeholder="name", **kwargs)
        return browsing

    async def test_the_path_fields_browse_for_what_they_are_and_the_name_does_not(self) -> None:
        listing = Mock()
        browsing = await self._asked(looking=listing)

        self.assertIsNone(browsing["name"])
        self.assertIsNotNone(browsing[""])
        with patch.object(launchers.folder_picker, "pick_path",
                          AsyncMock(return_value="/x/vpx")) as pick:
            self.assertEqual(await browsing[""]("/typed"), "/x/vpx")
            pick.assert_awaited_with(listing, "/typed", kind="exe", suffixes=())
            await browsing["Its own"]("")
            pick.assert_awaited_with(listing, "", kind="file", suffixes=(".ini",))

    async def test_without_a_listing_they_are_typed_only(self) -> None:
        browsing = await self._asked()

        self.assertEqual(set(browsing.values()), {None})


if __name__ == "__main__":
    unittest.main()
