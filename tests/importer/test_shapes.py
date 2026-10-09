"""What a source's wheel images are, read from their PNG headers alone."""

from __future__ import annotations

import importlib
import struct
import tempfile
import unittest
from pathlib import Path

from common.extensions import host


def _loaded(module: str):
    """A module of the importer, loaded the way core loads it."""
    record = host.Registry().load(host.BUNDLED_DIR / "library_importer")
    assert record.state == host.LOADED, record.reason
    return importlib.import_module(f"vpinfe_ext_library_importer.{module}")


def png(width: int, height: int, color: int = 6, trns: bool = False) -> bytes:
    """The start of a PNG: its signature, header chunk and, if asked, a transparency chunk.
    Nothing after it is read, so nothing after it is written."""
    head = struct.pack(">IIBBBBB", width, height, 8, color, 0, 0, 0)
    out = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + head + b"\0\0\0\0"
    if trns:
        out += struct.pack(">I", 1) + b"tRNS" + b"\0" + b"\0\0\0\0"
    return out + struct.pack(">I", 0) + b"IDAT" + b"\0\0\0\0"


class ShapesCase(unittest.TestCase):
    def setUp(self) -> None:
        self.shapes = _loaded("shapes")
        self.mapping = _loaded("mapping")
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def file(self, name: str, data: bytes) -> str:
        path = self.root / name
        path.write_bytes(data)
        return str(path)

    def many(self, count: int, data: bytes) -> list[str]:
        return [self.file(f"{index}.png", data) for index in range(count)]


class ReadTests(ShapesCase):
    def test_the_size_and_an_alpha_channel_are_read(self) -> None:
        found = self.shapes.read(self.file("a.png", png(600, 200)))

        self.assertEqual(found, self.shapes.Shape(600, 200, True))

    def test_a_picture_with_no_alpha_is_opaque(self) -> None:
        found = self.shapes.read(self.file("a.png", png(600, 200, color=2)))

        self.assertEqual(found, self.shapes.Shape(600, 200, False))

    def test_a_transparency_chunk_makes_a_palette_picture_transparent(self) -> None:
        found = self.shapes.read(self.file("a.png", png(600, 200, color=3, trns=True)))

        self.assertTrue(found and found.transparent)

    def test_anything_that_is_not_a_png_reads_as_nothing(self) -> None:
        self.assertIsNone(self.shapes.read(self.file("a.png", b"JFIF not a png at all")))
        self.assertIsNone(self.shapes.read(self.root / "missing.png"))
        self.assertIsNone(self.shapes.read(self.file("empty.png", png(0, 0))))

    def test_a_png_cut_short_reads_as_nothing(self) -> None:
        whole = png(600, 200)

        for length in (8, 16, 20, 24, 25):
            with self.subTest(length=length):
                self.assertIsNone(self.shapes.read(self.file("cut.png", whole[:length])))


class MeasuredAsTests(ShapesCase):
    def test_wide_transparent_titles_are_logos(self) -> None:
        self.assertEqual(self.shapes.measured_as(self.many(5, png(800, 200))), self.mapping.LOGOS)

    def test_round_art_is_wheels(self) -> None:
        self.assertEqual(self.shapes.measured_as(self.many(5, png(300, 300))), self.mapping.WHEELS)

    def test_wide_but_opaque_is_wheels(self) -> None:
        self.assertEqual(self.shapes.measured_as(self.many(5, png(800, 200, color=2))),
                         self.mapping.WHEELS)

    def test_it_takes_the_larger_half(self) -> None:
        mixed = [*self.many(2, png(800, 200)), self.file("round.png", png(300, 300))]

        self.assertEqual(self.shapes.measured_as(mixed), self.mapping.LOGOS)

    def test_a_long_list_is_judged_by_the_readable_pictures_in_a_spread_sample(self) -> None:
        wide = self.many(100, png(800, 200))
        unreadable = [self.file(f"{index}.jpg", b"JFIF") for index in range(300)]

        self.assertEqual(self.shapes.measured_as([*wide, *unreadable]), self.mapping.LOGOS)
        self.assertEqual(self.shapes.measured_as(self.many(200, png(300, 300))),
                         self.mapping.WHEELS)

    def test_pictures_it_cannot_read_leave_them_where_they_were(self) -> None:
        jpeg = self.file("a.jpg", b"JFIF")

        self.assertEqual(self.shapes.measured_as([jpeg]), self.mapping.WHEELS)
        self.assertEqual(self.shapes.measured_as([]), self.mapping.WHEELS)


if __name__ == "__main__":
    unittest.main()
