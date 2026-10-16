import socket
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from common import i18n
from frontend.custom_http_server import CustomHTTPServer


class TestCustomHttpServer(unittest.TestCase):
    def test_allows_only_pinball_primer_urls(self) -> None:
        handler = CustomHTTPServer.MultiDirHTTPRequestHandler

        self.assertTrue(handler._is_allowed_pinball_primer_url("https://pinballprimer.github.io/paddock_GR0W9.html"))
        self.assertFalse(handler._is_allowed_pinball_primer_url("http://pinballprimer.github.io/paddock_GR0W9.html"))
        self.assertFalse(handler._is_allowed_pinball_primer_url("https://example.com/tutorial.html"))

    def test_the_error_page_shows_markup_in_the_message_and_url_as_text(self) -> None:
        handler = CustomHTTPServer.MultiDirHTTPRequestHandler

        page = handler._build_pinball_primer_error_html(
            "<script>alert(1)</script>", 'https://x/"><img src=x onerror=alert(2)>')

        self.assertNotIn("<script>alert(1)", page)
        self.assertNotIn("<img src=x", page)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page)

    def test_a_base_address_cannot_close_its_own_tag(self) -> None:
        handler = CustomHTTPServer.MultiDirHTTPRequestHandler

        updated = handler._inject_base_tag(
            "<html><head></head></html>",
            'https://pinballprimer.github.io/x?"><script>alert(1)</script>')

        self.assertNotIn("<script>", updated)

    def test_injects_base_tag_into_head(self) -> None:
        handler = CustomHTTPServer.MultiDirHTTPRequestHandler
        html = "<html><head><title>Test</title></head><body>Hello</body></html>"

        updated = handler._inject_base_tag(html, "https://pinballprimer.github.io/paddock_GR0W9.html")

        self.assertIn('<base href="https://pinballprimer.github.io/paddock_GR0W9.html">', updated)
        self.assertIn("<title>Test</title>", updated)

    def test_injects_base_tag_when_head_missing(self) -> None:
        handler = CustomHTTPServer.MultiDirHTTPRequestHandler
        html = "<html><body>Hello</body></html>"

        updated = handler._inject_base_tag(html, "https://pinballprimer.github.io/paddock_GR0W9.html")

        self.assertTrue(updated.startswith('<head><base href="https://pinballprimer.github.io/paddock_GR0W9.html"></head>'))


class BurstTests(unittest.TestCase):
    def test_connections_made_before_the_server_accepts_are_all_answered(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        Path(tmp.name, "wheel.png").write_bytes(b"\x89PNG")
        server = CustomHTTPServer({"/tables/": tmp.name})
        with mock.patch("frontend.custom_http_server.threading.Thread"):
            server.start_file_server(port=0)
        self.addCleanup(server.stop_file_server)
        assert server.file_server is not None
        port = server.file_server.server_address[1]

        windows, connections_per_window = 3, 6
        opened, refused = [], []
        for _ in range(windows * connections_per_window):
            try:
                one = socket.create_connection(("127.0.0.1", port), timeout=5)
                one.sendall(b"GET /tables/wheel.png HTTP/1.0\r\n\r\n")
                opened.append(one)
            except OSError as exc:
                refused.append(exc)
        threading.Thread(target=server.file_server.serve_forever, daemon=True).start()

        answers = []
        for one in opened:
            with one:
                try:
                    answers.append(one.makefile("rb").readline().split(b" ")[1])
                except OSError as exc:
                    refused.append(exc)
        self.assertEqual(refused, [])
        self.assertEqual(answers, [b"200"] * windows * connections_per_window)


class ThemeWordsTests(unittest.TestCase):
    """`/core/i18n.json?theme=` adds a theme's `locales/` words under `theme.`."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.themes = tmp.name
        mine = Path(tmp.name, "mine", "locales")
        mine.mkdir(parents=True)
        mine.joinpath("en.json").write_text(
            '{"authors": "Authors",'
            ' "tables": {"one": "{count} table", "other": "{count} tables"},'
            ' "frontend.theme.launching": "Mine"}')
        mine.joinpath("de.json").write_text('{"authors": "Autoren"}')
        Path(tmp.name, "bare").mkdir()
        broken = Path(tmp.name, "broken", "locales")
        broken.mkdir(parents=True)
        broken.joinpath("en.json").write_text("{not json")
        server = CustomHTTPServer({"/themes/": tmp.name})
        server.start_file_server(port=0)
        self.addCleanup(server.stop_file_server)
        assert server.file_server is not None
        self.port = server.file_server.server_address[1]
        self.addCleanup(i18n.set_language, i18n.language())
        i18n.set_language("en")

    def words(self, query: str = "") -> dict:
        import json
        import urllib.request
        url = f"http://127.0.0.1:{self.port}/core/i18n.json{query}"
        with urllib.request.urlopen(url, timeout=5) as response:
            return json.load(response)

    def test_a_theme_with_locales_adds_its_words_under_theme(self) -> None:
        words = self.words("?theme=mine")
        self.assertEqual(words["theme.authors"], "Authors")
        self.assertEqual(words["theme.tables"]["one"], "{count} table")

    def test_a_theme_cannot_replace_a_core_word(self) -> None:
        core = self.words()["frontend.theme.launching"]
        words = self.words("?theme=mine")
        self.assertEqual(words["frontend.theme.launching"], core)
        self.assertEqual(words["theme.frontend.theme.launching"], "Mine")

    def test_the_language_in_use_wins_and_english_fills_the_rest(self) -> None:
        i18n.set_language("de")
        words = self.words("?theme=mine")
        self.assertEqual(words["theme.authors"], "Autoren")
        self.assertEqual(words["theme.tables"]["other"], "{count} tables")

    def test_a_theme_without_locales_changes_nothing(self) -> None:
        self.assertEqual(self.words("?theme=bare"), self.words())

    def test_a_malformed_file_or_an_unknown_theme_changes_nothing(self) -> None:
        self.assertEqual(self.words("?theme=broken"), self.words())
        self.assertEqual(self.words("?theme=nobody"), self.words())

    def test_an_entry_t_could_not_use_is_dropped_so_the_english_shows(self) -> None:
        for shape in ('[]', '"x"', 'null', '{"a": ""}', '{"a": {"one": 5, "other": "x"}}',
                      '{"a": {"one": "x"}}', '{"a": {"one": "", "other": "x"}}',
                      '{"a": null, "b": ["x"]}'):
            Path(self.themes, "broken", "locales", "en.json").write_text(shape, encoding="utf-8")
            self.assertEqual(self.words("?theme=broken"), self.words(), shape)

    def test_a_folder_name_with_a_space_is_found(self) -> None:
        folder = Path(self.themes, "My Theme", "locales")
        folder.mkdir(parents=True)
        folder.joinpath("en.json").write_text('{"authors": "Authors"}')
        self.assertEqual(self.words("?theme=My%20Theme")["theme.authors"], "Authors")

    def test_a_name_that_leaves_the_themes_folder_is_refused(self) -> None:
        for name in ("..", "../mine", "mine/..", "%2e%2e"):
            self.assertEqual(self.words(f"?theme={name}"), self.words(), name)
