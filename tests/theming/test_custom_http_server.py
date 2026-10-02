import socket
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from frontend.custom_http_server import CustomHTTPServer


class TestCustomHttpServer(unittest.TestCase):
    def test_allows_only_pinball_primer_urls(self) -> None:
        handler = CustomHTTPServer.MultiDirHTTPRequestHandler

        self.assertTrue(handler._is_allowed_pinball_primer_url("https://pinballprimer.github.io/paddock_GR0W9.html"))
        self.assertFalse(handler._is_allowed_pinball_primer_url("http://pinballprimer.github.io/paddock_GR0W9.html"))
        self.assertFalse(handler._is_allowed_pinball_primer_url("https://example.com/tutorial.html"))

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
