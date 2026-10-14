"""How far the request an extension is answering reached.

Core marks each request with the tier it reached, and `ctx.os` reads the mark before it
lets a change through. The mark lives in a context variable, so it follows the request into
the threads FastAPI runs a route on and into a job started from it. It is absent from an
event handler, a timer or a thread the extension started itself, and it stops counting when
the request ends. Absent means refused.
"""

from __future__ import annotations

import contextlib
import contextvars
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

PLAY = "play"
LIBRARY = "library"
PROTECTED = "protected"

TIERS = (PLAY, LIBRARY, PROTECTED)


@dataclass
class Reach:
    tier: str
    origin: str
    # False once the block that set the mark has ended. A task started inside a request
    # copies the context, and the copy outlives the request.
    live: bool = field(default=True, compare=False)


_current: contextvars.ContextVar[Reach | None] = contextvars.ContextVar(
    "vpinfe_request_reach", default=None)


def current() -> Reach | None:
    """The mark on what is running now, or None where no request is being answered."""
    mark = _current.get()
    return mark if mark is not None and mark.live else None


@contextlib.contextmanager
def marking(tier: str, origin: str = "") -> Iterator[Reach]:
    """Run the block with the mark set. A mark already set is replaced for the block and
    restored after it."""
    if tier not in TIERS:
        raise KeyError(tier)
    mark = Reach(tier, origin)
    token = _current.set(mark)
    try:
        yield mark
    finally:
        mark.live = False
        _current.reset(token)


@contextlib.contextmanager
def unmarked() -> Iterator[None]:
    """Run the block as work no request is answering, wherever it was called from."""
    token = _current.set(None)
    try:
        yield
    finally:
        _current.reset(token)


def carried(work: Callable[..., Any]) -> Callable[..., Any]:
    """`work` wrapped so it runs under the mark now in force, for a thread started from
    this request. The thread gets a mark of its own that lasts as long as the work does.
    With no mark in force, `work` itself."""
    mark = current()
    if mark is None:
        return work

    def under_mark(*args: Any, **kwargs: Any) -> Any:
        with marking(mark.tier, mark.origin):
            return work(*args, **kwargs)

    return under_mark
