"""A backglass file's facts and its picture over the API."""

from __future__ import annotations

import base64
import io
from pathlib import Path
from unittest.mock import MagicMock, patch

from PIL import Image
from starlette.testclient import TestClient

import httpapi
from common import sized_media
from common.games import asset_origin, backglass_ops, directb2s_parser
from common.online.vpsdb_media import file_md5
from tests.support.library import TempTree, fake_game, write_game

GAME_ID = "Glass0001"
FOLDER = "Example (Maker 1990)"
DARK = (20, 20, 20)


def _png(size: tuple[int, int], color: tuple[int, ...]) -> str:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, "PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _directb2s(*, size: tuple[int, int] = (40, 30), lamps: bool = True,
               header: str = "", score_view: tuple[int, int] | None = None) -> bytes:
    bulb = ('<Bulb Parent="Backglass" ID="1" Name="" RomID="1" RomIDType="1" '
            'InitialState="1" DualMode="0" Visible="1" LocX="2" LocY="2" Width="4" '
            f'Height="4" ZOrder="0" IsImageSnippit="0" Image="{_png((4, 4), (250, 250, 0))}" />'
            if lamps else "")
    drawn = f'<DMDImage Value="{_png(score_view, DARK)}" />' if score_view else ""
    return (
        '<DirectB2SData Version="1.2">\n'
        '  <Name Value="Example" />\n'
        '  <Author Value="Pat Maker" />\n'
        '  <GameName Value="exmpl_l1" />\n'
        '  <NumberOfPlayers Value="4" />\n'
        f"{header}"
        f"  <Illumination>{bulb}</Illumination>\n"
        f'  <Images><BackglassImage Value="{_png(size, DARK)}" />{drawn}</Images>\n'
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
                   "t1.directb2s": _directb2s(score_view=(24, 8)),
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

    def test_the_score_view_art_of_a_file_is_drawn(self) -> None:
        response = self.client.get(f"/games/{GAME_ID}/assets/backglass/score-view",
                                   params={"path": "t1.directb2s"})

        self.assertEqual((24, 8), self._drawn(response))

    def test_a_file_without_score_view_art_has_none_to_draw(self) -> None:
        response = self.client.get(f"/games/{GAME_ID}/assets/backglass/score-view",
                                   params={"path": f"{FOLDER}.directb2s"})

        self.assertEqual(404, response.status_code)

    def test_a_table_gets_the_score_view_of_the_file_named_for_it(self) -> None:
        response = self.client.get(f"/games/{GAME_ID}/tables/t1/assets/backglass/score-view")

        self.assertEqual((24, 8), self._drawn(response))

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


class BackglassFileAsPicture(BackglassRoutes):
    """The backglass file offered as the slot's picture, and kept in step with it."""

    def _settings(self, **held: str) -> None:
        row = {"id": "t1", "filename": "t1.vpx", "launcher": "vpx",
               "launcher_app_configurable": True}
        for patcher in (patch.object(backglass_ops, "_table_rows", return_value=[row]),
                        patch("common.games.launcher_ops.effective_values",
                              return_value=held)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _placed(self) -> tuple[Path, dict]:
        path = self.folder / "medias" / "(Backglass) t1.png"
        return path, asset_origin.sources(self.folder).get("medias/(Backglass) t1.png", {})

    def _changed(self) -> None:
        (self.folder / "t1.directb2s").write_bytes(_directb2s(size=(90, 70)))
        directb2s_parser._facts.clear()

    def test_the_offer_names_the_file_and_its_picture(self) -> None:
        offered = backglass_ops.offer(GAME_ID, "t1")

        self.assertEqual(("t1.directb2s", "t1.directb2s"),
                         (offered["file"], offered["path"]))
        self.assertTrue(offered["version"])

    def test_the_shared_slot_with_no_folder_file_is_offered_the_default_tables(self) -> None:
        (self.folder / f"{FOLDER}.directb2s").unlink()

        self.assertEqual("t1.directb2s", backglass_ops.offer(GAME_ID, "")["file"])

    def test_a_table_with_no_file_of_its_own_is_offered_the_folders(self) -> None:
        self.assertEqual(f"{FOLDER}.directb2s", backglass_ops.offer(GAME_ID, "t2")["file"])

    def test_no_file_means_no_offer(self) -> None:
        (self.folder / "t1.directb2s").unlink()
        (self.folder / f"{FOLDER}.directb2s").unlink()

        self.assertIsNone(backglass_ops.offer(GAME_ID, "t1"))

    def test_a_damaged_file_is_not_offered(self) -> None:
        (self.folder / "t1.directb2s").write_bytes(b"not a backglass at all")
        directb2s_parser._facts.clear()

        self.assertIsNone(backglass_ops.offer(GAME_ID, "t1"))

    def test_the_grill_is_cut_unless_the_renderer_shows_it(self) -> None:
        for held, cut in (({}, False),
                          ({"Plugin.B2SLegacy.Enable": ""}, False),
                          ({"Plugin.B2SLegacy.B2SHideGrill": "1"}, True),
                          ({"Plugin.B2SLegacy.Enable": "1",
                            "Plugin.B2SLegacy.B2SHideGrill": "0"}, False),
                          ({"Plugin.B2SLegacy.Enable": "0"}, True),
                          ({"Plugin.B2SLegacy.Enable": "0", "Plugin.B2S.ShowGrill": "1"}, False),
                          ({"Plugin.B2SLegacy.Enable": "0", "Plugin.B2S.ShowGrill": "0"}, True),
                          ({"Plugin.B2S.Enable": "1", "Plugin.B2S.ShowGrill": "1",
                            "Plugin.B2SLegacy.B2SHideGrill": "1"}, True)):
            with self.subTest(held=held), \
                    patch.object(backglass_ops, "_table_rows", return_value=[
                        {"id": "t1", "launcher": "vpx", "launcher_app_configurable": True}]), \
                    patch("common.games.launcher_ops.effective_values", return_value=held):
                self.assertEqual(cut, backglass_ops.grill_cut(GAME_ID, "t1"))

    def test_a_table_whose_settings_cannot_be_read_is_cut(self) -> None:
        with patch.object(backglass_ops, "_table_rows", return_value=[
                {"id": "t1", "launcher": "vpx", "launcher_app_configurable": True}]), \
                patch("common.games.launcher_ops.effective_values",
                      side_effect=OSError("gone")):
            self.assertTrue(backglass_ops.grill_cut(GAME_ID, "t1"))

    def test_using_the_picture_places_it_recorded_as_the_file(self) -> None:
        self._settings()

        backglass_ops.place_picture(GAME_ID, "t1")

        path, source = self._placed()
        self.assertEqual(("backglass_file", file_md5(path)),
                         (source.get("host"), source.get("hash")))

    def test_the_route_places_the_picture(self) -> None:
        self._settings()

        response = self.client.post(f"/games/{GAME_ID}/media/backglass/from-file",
                                    json={"table": "t1"})

        self.assertEqual(200, response.status_code, response.text)
        self.assertTrue(self._placed()[0].is_file())

    def test_a_game_with_no_file_cannot_use_one(self) -> None:
        (self.folder / "t1.directb2s").unlink()
        (self.folder / f"{FOLDER}.directb2s").unlink()

        response = self.client.post(f"/games/{GAME_ID}/media/backglass/from-file",
                                    json={"table": "t1"})

        self.assertEqual(404, response.status_code, response.text)

    def test_a_changed_file_redraws_the_picture_it_made(self) -> None:
        self._settings()
        backglass_ops.place_picture(GAME_ID, "t1")
        before = file_md5(self._placed()[0])
        self._changed()

        redrawn = backglass_ops.redraw(GAME_ID)

        path, source = self._placed()
        self.assertEqual(1, redrawn)
        self.assertNotEqual(before, file_md5(path))
        self.assertEqual(file_md5(path), source["hash"])

    def test_an_unchanged_file_redraws_nothing(self) -> None:
        self._settings()
        backglass_ops.place_picture(GAME_ID, "t1")

        self.assertEqual(0, backglass_ops.redraw(GAME_ID))

    def test_a_picture_somebody_replaced_is_left(self) -> None:
        self._settings()
        backglass_ops.place_picture(GAME_ID, "t1")
        path = self._placed()[0]
        path.write_bytes(b"theirs")
        self._changed()

        self.assertEqual(0, backglass_ops.redraw(GAME_ID))
        self.assertEqual(b"theirs", path.read_bytes())

    def test_a_game_with_no_such_picture_redraws_nothing(self) -> None:
        self.assertEqual(0, backglass_ops.redraw(GAME_ID))

    def test_the_slots_detail_carries_the_offer_for_a_backglass_only(self) -> None:
        self._settings()

        one = self.client.get(f"/games/{GAME_ID}/tables/t1/media/backglass/detail").json()
        other = self.client.get(f"/games/{GAME_ID}/tables/t1/media/wheel/detail").json()

        self.assertEqual("t1.directb2s", one["backglass_file"]["file"])
        self.assertIsNone(other["backglass_file"])

    def test_a_table_named_with_a_dot_in_it_reads_its_own_file(self) -> None:
        info = {"Info": {"Title": "Dotted"},
                "vpinfe": {"schema": 2, "id": "Dotted0001", "default_table": "d1"},
                "tables": {"d1": {"id": "d1", "filename": "Dotted (v1.1) - Maker.vpx"}}}
        folder = write_game(self.root, "Dotted (Maker 1990)", info=info, vpx=False,
                            files={"Dotted (v1.1) - Maker.vpx": b"vpx",
                                   "Dotted (v1.1) - Maker.directb2s": _directb2s()})
        game = fake_game(folder, "Dotted (Maker 1990)", meta=info)
        with patch("common.games.game_repository.catalog",
                   return_value={"Dotted0001": game}):
            offered = backglass_ops.offer("Dotted0001", "d1")

        self.assertEqual("Dotted (v1.1) - Maker.directb2s", offered["file"])

    def test_a_picture_with_another_file_at_its_tier_is_left(self) -> None:
        self._settings()
        backglass_ops.place_picture(GAME_ID, "t1")
        theirs = self.folder / "medias" / "(Backglass) t1.jpg"
        theirs.write_bytes(b"theirs")
        before = file_md5(self._placed()[0])
        self._changed()

        self.assertEqual(0, backglass_ops.redraw(GAME_ID))
        self.assertEqual(b"theirs", theirs.read_bytes())
        self.assertEqual(before, file_md5(self._placed()[0]))

    def test_a_folders_own_picture_is_redrawn(self) -> None:
        self._settings()
        backglass_ops.place_picture(GAME_ID, "")
        path = self.folder / "medias" / f"(Backglass) {FOLDER}.png"
        before = file_md5(path)
        (self.folder / f"{FOLDER}.directb2s").write_bytes(_directb2s(size=(90, 70)))
        directb2s_parser._facts.clear()

        self.assertEqual(1, backglass_ops.redraw(GAME_ID))
        self.assertNotEqual(before, file_md5(path))

    def test_placing_a_new_backglass_file_redraws_the_picture(self) -> None:
        from common.games import asset_ops

        self._settings()
        backglass_ops.place_picture(GAME_ID, "t1")
        before = file_md5(self._placed()[0])
        staged = self.root / "staged.directb2s"
        staged.write_bytes(_directb2s(size=(90, 70)))

        asset_ops.place_file(GAME_ID, "backglass", "t1", staged, "t1.directb2s")

        self.assertNotEqual(before, file_md5(self._placed()[0]))

    def test_a_failed_redraw_does_not_fail_the_placing(self) -> None:
        from common.games import asset_ops

        staged = self.root / "staged.directb2s"
        staged.write_bytes(_directb2s())
        with patch.object(backglass_ops, "redraw", side_effect=OSError("gone")):
            asset_ops.place_file(GAME_ID, "backglass", "t1", staged, "t1.directb2s")

        self.assertTrue((self.folder / "t1.directb2s").is_file())

    def test_the_sweep_redraws_every_game_that_has_such_a_picture(self) -> None:
        self._settings()
        backglass_ops.place_picture(GAME_ID, "t1")
        self._changed()

        self.assertEqual(1, backglass_ops.redraw_all())
        self.assertEqual(0, backglass_ops.redraw_all())

    def test_the_sweep_stops_when_told_to(self) -> None:
        self._settings()
        backglass_ops.place_picture(GAME_ID, "t1")
        self._changed()

        self.assertEqual(0, backglass_ops.redraw_all(lambda: False))

    def test_one_games_failure_does_not_stop_the_sweep(self) -> None:
        self._settings()
        backglass_ops.place_picture(GAME_ID, "t1")
        with patch.object(backglass_ops, "redraw", side_effect=OSError("gone")):
            self.assertEqual(0, backglass_ops.redraw_all())

    def test_updating_art_runs_the_sweep_first(self) -> None:
        from common import jobs
        from common.games import media_fill

        order: list[str] = []
        with patch.object(jobs, "submit",
                          side_effect=lambda kind, work, **_: work(MagicMock())), \
                patch.object(media_fill, "update_enabled", return_value=True), \
                patch.object(backglass_ops, "redraw_all",
                             side_effect=lambda _proceed: order.append("sweep") or 0), \
                patch.object(media_fill, "update_downloaded",
                             side_effect=lambda *_: order.append("update") or {}):
            self.assertTrue(media_fill.start_update())

        self.assertEqual(["sweep", "update"], order)
