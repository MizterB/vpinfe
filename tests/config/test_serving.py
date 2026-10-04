from __future__ import annotations

import configparser
import tempfile
import unittest
from pathlib import Path

from common import install_presence, serving
from console import api as console_api
from frontend import config_api


def _settings(**ports: int) -> configparser.ConfigParser:
    parser = configparser.ConfigParser()
    parser["network"] = {key: str(value) for key, value in ports.items()}
    return parser


class ServingPortsTests(unittest.TestCase):
    def setUp(self) -> None:
        serving.forget()
        self.addCleanup(serving.forget)

    def test_a_port_nothing_here_started_is_the_setting(self) -> None:
        network = serving.network(_settings(http_port=8101, ws_port=8102))

        self.assertEqual((network.http_port, network.ws_port), (8101, 8102))

    def test_a_started_port_outlives_a_new_setting(self) -> None:
        serving.bound("http_port", 8001)
        serving.bound("theme_assets_port", 8000)

        network = serving.network(_settings(http_port=9001, theme_assets_port=9000,
                                            ws_port=9002))

        self.assertEqual((network.http_port, network.theme_assets_port, network.ws_port),
                         (8001, 8000, 9002))

    def test_the_console_and_the_windows_follow_the_started_port(self) -> None:
        """Saving a new port in Settings must not point the open Console, a theme or a
        device at a port nothing is listening on."""
        serving.bound("http_port", 8765)
        serving.bound("theme_assets_port", 8764)
        moved = _settings(http_port=9001, theme_assets_port=9000)

        self.assertEqual(console_api.local_base_url(), "http://127.0.0.1:8765")
        self.assertEqual(config_api.get_http_port(moved), 8765)
        self.assertEqual(config_api.get_theme_assets_port(moved), 8764)
        self.assertEqual(install_presence.service_ports(), {"files": {"port": 8764}})


class PublishedPortTests(unittest.TestCase):
    def setUp(self) -> None:
        serving.forget()
        self.addCleanup(serving.forget)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)

    def test_the_port_a_run_bound_is_what_a_shell_finds(self) -> None:
        serving.bound("http_port", 8765)

        serving.publish(self.folder)

        self.assertEqual(serving.published(self.folder), 8765)

    def test_nothing_is_published_before_a_server_has_bound(self) -> None:
        serving.publish(self.folder)

        self.assertIsNone(serving.published(self.folder))
        self.assertFalse((self.folder / serving.PORT_FILE).exists())

    def test_a_run_that_ends_takes_it_back(self) -> None:
        serving.bound("http_port", 8765)
        serving.publish(self.folder)

        serving.withdraw(self.folder)
        serving.withdraw(self.folder)

        self.assertIsNone(serving.published(self.folder))

    def test_a_file_that_is_not_a_port_is_no_port(self) -> None:
        (self.folder / serving.PORT_FILE).write_text("not a port", encoding="utf-8")

        self.assertIsNone(serving.published(self.folder))


if __name__ == "__main__":
    unittest.main()
