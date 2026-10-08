"""Listing the folders a source keeps its artwork in, together rather than one by one."""

from __future__ import annotations

import os
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def files_in(folder: Path) -> list[tuple[str, str]]:
    """The files directly in a folder as (name, path); nothing where it cannot be read.

    The listing carries the file-or-folder answer with each name, where `is_file()` on
    each is another call across the same mount.
    """
    try:
        with os.scandir(folder) as entries:
            return [(entry.name, entry.path) for entry in entries if entry.is_file()]
    except OSError:
        return []


def files_across(root: Path, folders: Sequence[str]) -> list[list[tuple[str, str]]]:
    """`files_in` for each of `folders` under `root`, in the order given."""
    if not folders:
        return []
    with ThreadPoolExecutor(max_workers=len(folders)) as pool:
        return list(pool.map(lambda name: files_in(root / name), folders))
