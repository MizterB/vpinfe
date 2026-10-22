"""The source registry holding exactly the sources a test names."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from common.online import script_fixes, sources
from common.online.sources import Source


@contextmanager
def only(*held: Source) -> Iterator[None]:
    """The registry holding these sources and no others, the ones that ship included."""
    with patch.object(sources, "_sources", {one.id: one for one in held}), \
            patch.object(sources, "_built_in_loaded", True):
        yield


def fixes_apply_here() -> Any:
    """The script fixes answering as they do off Windows, wherever the tests run."""
    return patch.object(script_fixes, "sys", SimpleNamespace(platform="linux"))
