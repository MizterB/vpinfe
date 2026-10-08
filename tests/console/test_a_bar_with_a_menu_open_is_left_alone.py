"""The Logs control bar is drawn again only when what it is drawn from changed.

The page reads on a timer, and clearing the bar on a tick closes a menu somebody has
open before they can pick from it.
"""

from __future__ import annotations

import unittest
from typing import Any

from console import logs


def _held(**more: Any) -> dict[str, Any]:
    return {"view": logs.STREAM, "sources": ["a.log"], "path": "/logs/a.log", "source": "",
            "visual_pinball": "", **more}


class WhatTheBarIsDrawnFrom(unittest.TestCase):
    def test_a_tick_that_read_the_same_log_leaves_the_bar_as_it_is(self) -> None:
        self.assertEqual(logs._bar_key(_held()), logs._bar_key(_held()))

    def test_every_view_has_a_key_of_its_own(self) -> None:
        keys = {logs._bar_key(_held(view=view)) for view in logs.VIEWS}

        self.assertEqual(len(logs.VIEWS), len(keys))

    def test_a_log_that_rotated_draws_its_bar_again(self) -> None:
        self.assertNotEqual(logs._bar_key(_held()),
                            logs._bar_key(_held(sources=["a.log", "a.log.1"])))

    def test_another_file_draws_its_bar_again(self) -> None:
        self.assertNotEqual(logs._bar_key(_held()),
                            logs._bar_key(_held(path="/logs/b.log")))

    def test_a_source_that_appears_draws_its_bar_again(self) -> None:
        """Visual Pinball's log is named once a launcher says where it writes, and the
        select has to offer it."""
        self.assertNotEqual(logs._bar_key(_held()),
                            logs._bar_key(_held(visual_pinball="v.log")))


if __name__ == "__main__":
    unittest.main()
