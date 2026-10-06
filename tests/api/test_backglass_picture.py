"""A backglass file's facts and its picture over the API."""

from __future__ import annotations

import base64
import io
from unittest.mock import patch

from PIL import Image
from starlette.testclient import TestClient

import httpapi
from common import sized_media
from common.games import directb2s_parser
from tests.support.library import TempTree, fake_game, write_game

GAME_ID = "Glass0001"
FOLDER = "Example (Maker 1990)"
DARK = (20, 20, 20)


def _png(size: tuple[int, int], color: tuple[int, ...]) -> str:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, "PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _directb2s(*, size: tuple[int, int] = (40, 30), lamps: bool = True,
               header: str = "") -> bytes:
    bulb = ('<Bulb Parent="Backglass" ID="1" Name="" RomID="1" RomIDType="1" '
            'InitialState="1" DualMode="0" Visible="1" LocX="2" LocY="2" Width="4" '
            f'Height="4" ZOrder="0" IsImageSnippit="0" Image="{_png((4, 4), (250, 250, 0))}" />'
            if lamps else "")
    return (
        '<DirectB2SData Version="1.2">\n'
        '  <Name Value="Example" />\n'
        '  <Author Value="Pat Maker" />\n'
        '  <GameName Value="exmpl_l1" />\n'
        '  <NumberOfPlayers Value="4" />\n'
        f"{header}"
        f"  <Illumination>{bulb}</Illumination>\n"
        f'  <Images><BackglassImage Value="{_png(size, DARK)}" /></Images>\n'
        "</DirectB2SData>\n").encode()


class BackglassRoutes(TempTree):
    def setUp(self) -> None:
        super().setUp()
        info = {"Info": {"Title": "Example"},
                "vpinfe": {"schema": 2, "id": GAME_ID, "default_table": "t1"},
                "tables": {"t1": {"id": "t1", "filename": "t1.vpx"},
                           "t2": {"id": "t2", "filename": "t2.vpx"}}}
        self.folder = write_game(
            self.root, FOLDER, info=info, vpx=False,
            files={"t1.vpx": b"vpx", "t2.vpx": b"vpx",
                   "t1.directb2s": _directb2s(),
                   f"{FOLDER}.directb2s": _directb2s(size=(80, 60), lamps=False),
                   "Broken.directb2s": b"not a backglass at all",
                   "notes.txt": b"hello"})
        game = fake_game(self.folder, FOLDER, meta=info)
        for patcher in (patch("common.games.game_repository.catalog",
                              return_value={GAME_ID: game}),
                        patch.object(sized_media, "ROOT", self.root / "sized"),
                        patch.object(directb2s_parser, "ROOT", self.root / "glass")):
            patcher.start()
            self.addCleanup(patcher.stop)
        directb2s_parser._facts.clear()
        self.addCleanup(directb2s_parser._facts.clear)
        self.client = TestClient(httpapi.create_api_app(), raise_server_exceptions=False)

    def _detail(self, path: str) -> dict:
        response = self.client.get(f"/games/{GAME_ID}/assets/detail", params={"path": path})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def _drawn(self, response) -> tuple[int, int]:
        self.assertEqual(response.status_code, 200, response.text)
        return Image.open(io.BytesIO(response.content)).size

    def test_a_backglass_file_says_what_it_holds(self) -> None:
        glass = self._detail("t1.directb2s")["backglass"]

        self.assertEqual(("Pat Maker", "exmpl_l1", 4, [40, 30], 1, False),
                         (glass["author"], glass["rom"], glass["players"], glass["size"],
                          glass["lamps"], glass["damaged"]))
        self.assertTrue(glass["version"])

    def test_a_file_that_is_not_a_backglass_is_damaged(self) -> None:
        self.assertTrue(self._detail("Broken.directb2s")["backglass"]["damaged"])

    def test_another_kind_of_file_carries_no_backglass_facts(self) -> None:
        self.assertIsNone(self._detail("notes.txt")["backglass"])

    def test_the_picture_of_a_named_file_is_drawn(self) -> None:
        response = self.client.get(f"/games/{GAME_ID}/assets/backglass/picture",
                                   params={"path": "t1.directb2s"})

        self.assertEqual((40, 30), self._drawn(response))

    def test_a_table_gets_the_file_named_for_it(self) -> None:
        response = self.client.get(f"/games/{GAME_ID}/tables/t1/assets/backglass/picture")

        self.assertEqual((40, 30), self._drawn(response))

    def test_a_table_without_one_of_its_own_gets_the_folders(self) -> None:
        response = self.client.get(f"/games/{GAME_ID}/tables/t2/assets/backglass/picture")

        self.assertEqual((80, 60), self._drawn(response))

    def test_the_game_without_a_table_reads_the_folders_file(self) -> None:
        response = self.client.get(f"/games/{GAME_ID}/assets/backglass/picture")

        self.assertEqual((80, 60), self._drawn(response))

    def test_a_size_scales_the_picture(self) -> None:
        response = self.client.get(f"/games/{GAME_ID}/assets/backglass/picture",
                                   params={"path": "t1.directb2s", "size": 256})

        self.assertEqual(200, response.status_code, response.text)

    def test_the_files_version_keeps_the_picture_for_good(self) -> None:
        version = self._detail("t1.directb2s")["backglass"]["version"]

        kept = self.client.get(f"/games/{GAME_ID}/assets/backglass/picture",
                               params={"path": "t1.directb2s", "v": version})
        asked = self.client.get(f"/games/{GAME_ID}/assets/backglass/picture",
                                params={"path": "t1.directb2s", "v": "stale"})

        self.assertEqual(("public, max-age=31536000, immutable", "no-cache"),
                         (kept.headers["cache-control"], asked.headers["cache-control"]))

    def test_a_damaged_file_has_no_picture(self) -> None:
        response = self.client.get(f"/games/{GAME_ID}/assets/backglass/picture",
                                   params={"path": "Broken.directb2s"})

        self.assertEqual(404, response.status_code)

    def test_only_a_backglass_file_is_drawn(self) -> None:
        response = self.client.get(f"/games/{GAME_ID}/assets/backglass/picture",
                                   params={"path": "notes.txt"})

        self.assertEqual(400, response.status_code)

    def test_a_path_out_of_the_folder_is_refused(self) -> None:
        response = self.client.get(f"/games/{GAME_ID}/assets/backglass/picture",
                                   params={"path": "../../x.directb2s"})

        self.assertEqual(400, response.status_code)

    def test_a_look_that_is_not_one_is_refused(self) -> None:
        response = self.client.get(f"/games/{GAME_ID}/assets/backglass/picture",
                                   params={"path": "t1.directb2s", "look": "glow"})

        self.assertEqual(400, response.status_code)

    def test_a_table_that_is_not_the_games_is_not_found(self) -> None:
        response = self.client.get(f"/games/{GAME_ID}/tables/nope/assets/backglass/picture")

        self.assertEqual(404, response.status_code)
