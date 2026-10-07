"""Linux: the cards, through nvtop for now."""

from __future__ import annotations

from typing import Any

from common.host.graphics import nvtop


def cards() -> list[dict[str, Any]]:
    return nvtop.cards()
