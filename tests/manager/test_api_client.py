"""What the Manager's API client raises when nothing answers it."""

from __future__ import annotations

import socket
import unittest
from unittest.mock import patch

import requests

from common.i18n import t
from manager.api import ApiClient, ApiError


def _closed_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class NothingAnsweredTests(unittest.TestCase):
    def test_nothing_on_the_port_is_said_in_words(self) -> None:
        client = ApiClient(f"http://127.0.0.1:{_closed_port()}")

        with self.assertRaises(ApiError) as caught:
            client.discovery()

        self.assertEqual(str(caught.exception), t("device.reason.refused"))
        self.assertIsInstance(caught.exception.__cause__, requests.ConnectionError)

    def test_an_answer_that_never_came_says_it_may_be_asleep(self) -> None:
        with patch.object(requests.adapters.HTTPAdapter, "send",
                          side_effect=requests.ReadTimeout()), \
                self.assertRaises(ApiError) as caught:
            ApiClient("http://127.0.0.1:1").set_favorite("g1", True)

        self.assertEqual(str(caught.exception), t("device.reason.timed_out"))


class HowLongEachReadWaitsTests(unittest.TestCase):
    @staticmethod
    def _waited(call) -> float:
        seen: dict = {}

        def send(_adapter, _request, **kwargs):
            seen.update(kwargs)
            response = requests.Response()
            response.status_code = 200
            response._content = b"{}"
            return response

        with patch.object(requests.adapters.HTTPAdapter, "send", send):
            call(ApiClient("http://127.0.0.1:1"))
        return seen["timeout"]

    def test_reading_the_whole_library_waits_for_a_cold_share(self) -> None:
        for read in (lambda c: c.games(), lambda c: c.all_tables(),
                     lambda c: c.all_media(), lambda c: c.all_assets(),
                     lambda c: c.filter_axes(), lambda c: c.library_entries(),
                     lambda c: c.tags(), lambda c: c.locations(),
                     lambda c: c.library_game_collections(),
                     lambda c: c.collection_games("c"), lambda c: c.collection_entries("c"),
                     lambda c: c.info_maintenance()):
            self.assertGreater(self._waited(read), 60)

    def test_a_question_about_one_thing_still_gives_up_quickly(self) -> None:
        self.assertEqual(self._waited(lambda c: c.game("g1")), 15)

    def test_sending_a_file_waits_as_long_as_importing_one(self) -> None:
        """The write can finish after a short wait ends, and the person is then told a
        placed file failed."""
        for send in (lambda c: c.place_media("g1", "", "wheel", "a.png", b"x"),
                     lambda c: c.place_asset("g1", "", "pov", "a.pov", b"x")):
            self.assertGreater(self._waited(send), 60)


if __name__ == "__main__":
    unittest.main()
