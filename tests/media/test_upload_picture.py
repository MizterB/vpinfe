"""A picture in an upload that has not been imported yet, drawn by the dialog that asks
whether to import it."""

from __future__ import annotations

import io
from unittest import mock

from PIL import Image
from starlette.testclient import TestClient

import httpapi
from common import service_errors
from common.media import sized_media
from common.uploads import upload_ops
from tests.support.library import TempTree


def _png(width: int = 800, height: int = 400) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), (200, 40, 40)).save(out, "PNG")
    return out.getvalue()


class _Staged(TempTree):
    def setUp(self) -> None:
        super().setUp()
        patcher = mock.patch.object(sized_media, "ROOT", self.root / "sized")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.upload = upload_ops.begin()["id"]
        self.addCleanup(upload_ops.abort, self.upload)
        upload_ops.add_file(self.upload, "(RuleSheet) 300.png", io.BytesIO(_png()))
        upload_ops.add_file(self.upload, "table.vpx", io.BytesIO(b"x"))
        upload_ops.add_file(self.upload, "in/a folder/inside.png", io.BytesIO(_png()))


class PictureTests(_Staged):
    def test_a_loose_image_is_served_at_the_size_asked_for(self) -> None:
        served = upload_ops.picture(self.upload, "(RuleSheet) 300.png", 256)

        with Image.open(served.path) as drawn:
            self.assertEqual(256, max(drawn.size))

    def test_without_a_size_it_is_the_file_itself(self) -> None:
        served = upload_ops.picture(self.upload, "(RuleSheet) 300.png", None)

        with Image.open(served.path) as drawn:
            self.assertEqual((800, 400), drawn.size)

    def test_an_image_in_a_folder_of_the_drop_is_found_by_its_name(self) -> None:
        served = upload_ops.picture(self.upload, "inside.png", 256)

        self.assertTrue(served.path.is_file())

    def test_a_file_that_is_not_an_image_has_no_picture(self) -> None:
        with self.assertRaises(service_errors.NotFoundError):
            upload_ops.picture(self.upload, "table.vpx", 256)

    def test_a_name_that_is_not_in_the_upload_has_no_picture(self) -> None:
        with self.assertRaises(service_errors.NotFoundError):
            upload_ops.picture(self.upload, "nothing.png", 256)

    def test_a_name_that_climbs_out_of_the_upload_has_no_picture(self) -> None:
        with self.assertRaises(service_errors.NotFoundError):
            upload_ops.picture(self.upload, "../../outside.png", 256)

    def test_an_upload_that_is_not_there_is_not_found(self) -> None:
        with self.assertRaises(service_errors.NotFoundError):
            upload_ops.picture("not-an-upload", "a.png", 256)

    def test_a_size_the_api_does_not_cut_is_refused(self) -> None:
        with self.assertRaises(service_errors.RefusedError):
            upload_ops.picture(self.upload, "(RuleSheet) 300.png", 100)


class PictureRouteTests(_Staged):
    def setUp(self) -> None:
        super().setUp()
        self.client = TestClient(httpapi.create_api_app(), raise_server_exceptions=False)

    def test_the_route_sends_the_picture(self) -> None:
        response = self.client.get(f"/uploads/{self.upload}/picture",
                                   params={"name": "(RuleSheet) 300.png", "size": 256})

        self.assertEqual(200, response.status_code, response.text)
        self.assertTrue(response.headers["content-type"].startswith("image/"))

    def test_the_route_is_a_404_for_a_file_that_is_not_a_picture(self) -> None:
        response = self.client.get(f"/uploads/{self.upload}/picture",
                                   params={"name": "table.vpx"})

        self.assertEqual(404, response.status_code)

    def test_the_route_needs_a_name(self) -> None:
        response = self.client.get(f"/uploads/{self.upload}/picture")

        self.assertEqual(422, response.status_code)
