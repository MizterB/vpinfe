"""What a source's wheel images look like, measured from their PNG headers.

A PinballX or PinballY wheel image is most often a game's title logo, and sometimes round
wheel art. The headers tell the two apart without decoding a pixel.
"""

from __future__ import annotations

import struct
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from . import mapping

SAMPLE = 40
# Wider than tall by at least this much, with transparency, reads as a title.
WIDE = 1.5

_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# Color types that carry an alpha channel.
_ALPHA = (4, 6)


@dataclass(frozen=True)
class Shape:
    width: int
    height: int
    transparent: bool


def read(path: str | Path) -> Shape | None:
    """The size of a PNG and whether it has transparency, or None for anything else."""
    try:
        with open(path, "rb") as handle:
            head = handle.read(4096)
    except OSError:
        return None
    if len(head) < 26 or not head.startswith(_SIGNATURE) or head[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", head[16:24])
    if not (width and height):
        return None
    transparent = head[25] in _ALPHA
    at = 8
    while not transparent and at + 8 <= len(head):
        size, kind = struct.unpack(">I4s", head[at:at + 8])
        if kind == b"tRNS":
            transparent = True
        if kind == b"IDAT":
            break
        at += 12 + size
    return Shape(width, height, transparent)


def wheel_images(library_games: Sequence, source_id: str, kinds: tuple[str, ...]) -> list[str]:
    """The files the source keeps as wheels, in the order its games are held."""
    return [path for game in library_games
            for kind, path in mapping.media_for(source_id, game, kinds, mapping.WHEELS)
            if kind == mapping.WHEELS]


def readable(paths: Sequence[str]) -> list[Shape]:
    """The shapes of the sampled files that could be read; empty where none could."""
    sample = list(paths[::max(1, len(paths) // SAMPLE)][:SAMPLE])
    return [one for one in (read(path) for path in sample) if one is not None]


def measured_as(paths: Sequence[str]) -> str:
    """`logo` where most of a sample are wide and transparent, `wheel` otherwise.

    An image that is not a PNG says nothing either way, so a source of JPEGs is Wheels:
    the answer that leaves its images where the source had them.
    """
    shapes = readable(paths)
    if not shapes:
        return mapping.WHEELS
    wide = sum(1 for one in shapes if one.width >= WIDE * one.height and one.transparent)
    return mapping.LOGOS if wide * 2 > len(shapes) else mapping.WHEELS
