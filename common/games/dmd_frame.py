"""Where Visual Pinball's Automatic puts the DMD on a backglass picture.

`find` is a port of `DMDOverlay::SearchDmdSubFrame` (vpinball/vpinball, plugins/b2s): the
largest dark rectangle in the art, fitted to the DMD's aspect ratio, found by halving a
luminance threshold over seven passes. It runs once on the picture and its numbers are
written as a plain position.

The result is in Visual Pinball's own units, not the picture's: the picture's rows are
scanned from its top, as the texture is held in memory, and the answer is turned over by
`height - 1 - y - h`.
"""

from __future__ import annotations

from array import array
from struct import pack, unpack
from typing import NamedTuple

from PIL import Image

PASSES = 7
THIRD = 3


class Frame(NamedTuple):
    x: int
    y: int
    width: int
    height: int


def find(image: Image.Image, aspect: float = 4.0) -> Frame | None:
    """The DMD's frame on `image`, or None where no dark rectangle is wide enough: a third
    of the picture's width, and more than six paddings by three."""
    rgb = image.convert("RGB")
    wide, high = rgb.size
    lum = _luminance(rgb)
    padding = (2 * wide) // 1920
    ratio = _single(aspect)
    low, top = 0.0, 256.0
    search = (0, 0, wide, high)
    best = (0, 0, 0, 0)
    for _ in range(PASSES):
        limit = (low + top) * 0.5
        sub, next_search = _largest_dark(lum, wide, search, limit, padding, ratio)
        if sub[3] > 0:
            top = limit
            best = sub
            search = next_search
        else:
            low = limit
    if best[2] == 0 or best[3] == 0:
        return None
    x, y, across, down = best
    return Frame(x, high - 1 - y - down, across, down)


def _single(value: float) -> float:
    """A value as the C++ holds it, a 32-bit float."""
    return float(unpack("f", pack("f", value))[0])


def _luminance(rgb: Image.Image) -> array:
    """Rec.601 luma of each pixel, rounded to a 32-bit float after each operation, as the
    original computes it. A grey on a threshold's own value falls the same side."""
    data = rgb.tobytes()
    red = [_single(_single(0.299) * value) for value in range(256)]
    green = [_single(_single(0.587) * value) for value in range(256)]
    blue = [_single(_single(0.114) * value) for value in range(256)]
    partial = array("f", [red[r] + green[g] for r, g in zip(data[0::3], data[1::3], strict=True)])
    return array("f", [low + blue[b] for low, b in zip(partial, data[2::3], strict=True)])


def _largest_dark(lum: array, wide: int, search: tuple[int, int, int, int], limit: float,
                  padding: int, ratio: float) -> tuple[tuple[int, int, int, int],
                                                       tuple[int, int, int, int]]:
    """The best frame of one pass, and the area the next pass searches: every rectangle the
    pass considered, joined."""
    left, first, across, down = search
    wide_f = float(wide)
    heights = [0] * wide
    best = (0, 0, 0, 0)
    best_score = _score(best, wide_f)
    joined: tuple[int, int, int, int] | None = None
    stack: list[int] = []
    for y in range(first, first + down):
        start = y * wide + left
        row = lum[start:start + across]
        for offset, value in enumerate(row, left):
            heights[offset] = heights[offset] + 1 if value < limit else 0
        for x in range(left, left + across + 1):
            while stack and (x == left + across or heights[stack[-1]] > heights[x]):
                height = heights[stack.pop()]
                span = x - left if not stack else x - stack[-1] - 1
                if span > 6 * padding and height > 3 * padding:
                    box = (left if not stack else stack[-1] + 1, y - height + 1, span, height)
                    joined = box if joined is None else _join(joined, box)
                    frame = _fit(box, padding, ratio)
                    if THIRD * frame[2] >= wide and (score := _score(frame, wide_f)) > best_score:
                        best, best_score = frame, score
            if x < left + across:
                stack.append(x)
    return best, joined or (0, 0, 0, 0)


def _join(one: tuple[int, int, int, int], other: tuple[int, int, int, int]
          ) -> tuple[int, int, int, int]:
    x = min(one[0], other[0])
    y = min(one[1], other[1])
    return (x, y, max(one[0] + one[2], other[0] + other[2]) - x,
            max(one[1] + one[3], other[1] + other[3]) - y)


def _fit(box: tuple[int, int, int, int], padding: int, ratio: float
         ) -> tuple[int, int, int, int]:
    """The box less its padding, narrowed or shortened to the DMD's aspect ratio and
    centered in what is left."""
    x, y, across, down = box[0] + padding, box[1] + padding, box[2] - 2 * padding, \
        box[3] - 2 * padding
    if _single(across / down) > ratio:
        fitted = int(_single(down * ratio))
        return x + (across - fitted) // 2, y, fitted, down
    fitted = int(_single(across / ratio))
    return x, y + (down - fitted) // 2, across, fitted


def _score(frame: tuple[int, int, int, int], wide: float) -> float:
    """Large, and near the picture's center."""
    return frame[2] / wide - 1.0 * abs(0.5 - (frame[0] + frame[2] // 2) / wide)
