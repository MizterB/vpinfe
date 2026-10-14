"""The address the Manager UI listens on reaches the server that binds it.

The setting is only worth having if it arrives: `NetworkConfig` reading it correctly and
`ui.run` still being handed a hardcoded host would look right everywhere except on the
socket, and the default is the value that hides that - it is what the code said before.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from common import encrypted_connections, serving
from managerui import loopback, managerui
from tests.api.test_encrypted_connections import make_certificate


class ManagerUiBindTests(unittest.TestCase):
    def setUp(self) -> None:
        self.addCleanup(setattr, managerui, "_ui_bind", managerui._ui_bind)
        self.addCleanup(setattr, managerui, "_ui_port", managerui._ui_port)

    def _ran_with(self, **kwargs) -> dict:
        """What `_run_ui` would hand NiceGUI, without starting a server."""
        managerui._ui_bind = kwargs.get("bind", "0.0.0.0")
        managerui._ui_port = kwargs.get("port", 8001)
        with mock.patch.object(managerui, "ui") as nicegui, \
             mock.patch.object(managerui, "_manager_ui_urls", return_value=[]):
            managerui._run_ui()
        return nicegui.run.call_args.kwargs

    def test_it_answers_every_interface_by_default(self) -> None:
        """What it has always done: a cabinet is administered from another machine."""
        self.assertEqual(self._ran_with()["host"], "0.0.0.0")

    def test_an_install_can_pull_it_back_to_this_machine(self) -> None:
        self.assertEqual(self._ran_with(bind="127.0.0.1")["host"], "127.0.0.1")

    def test_the_port_still_arrives_with_it(self) -> None:
        ran = self._ran_with(bind="127.0.0.1", port=9001)

        self.assertEqual((ran["host"], ran["port"]), ("127.0.0.1", 9001))

    def test_a_forwarding_header_is_never_rewritten_into_the_peer(self) -> None:
        """The listed-proxy check reads the real socket, so uvicorn must leave it alone."""
        self.assertIs(self._ran_with()["proxy_headers"], False)


class ManagerUiHttpsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if shutil.which("openssl") is None:
            raise unittest.SkipTest("openssl is needed to make a certificate")
        cls.holder = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.holder.cleanup)
        cls.cert, cls.key = make_certificate(Path(cls.holder.name))

    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.connections = encrypted_connections.Connections(Path(folder.name) / "c.json")
        self.addCleanup(encrypted_connections.use, encrypted_connections.instance())
        encrypted_connections.use(self.connections)
        serving.forget()
        encrypted_connections.forget_listening()
        self.addCleanup(serving.forget)
        self.addCleanup(encrypted_connections.forget_listening)
        self.addCleanup(setattr, managerui, "_tls", managerui._tls)

    def test_no_certificate_means_plain_http_and_no_second_listener(self) -> None:
        self.assertEqual(managerui._certificate_to_serve(), {})
        self.assertFalse(encrypted_connections.listening().https)
        self.assertEqual(encrypted_connections.listening().problem, "")

    def test_a_certificate_that_loads_is_served(self) -> None:
        self.connections.set_certificate(self.cert, self.key)

        self.assertEqual(managerui._certificate_to_serve(),
                         {"ssl_certfile": self.cert, "ssl_keyfile": self.key})
        self.assertTrue(encrypted_connections.listening().https)

    def test_a_certificate_gone_since_it_was_chosen_starts_plain_http_and_says_why(self) -> None:
        self.connections.set_certificate(self.cert, self.key)
        with mock.patch.object(encrypted_connections, "unreadable_reason",
                               return_value=encrypted_connections.NO_FILE):
            self.assertEqual(managerui._certificate_to_serve(), {})

        self.assertFalse(encrypted_connections.listening().https)
        self.assertEqual(encrypted_connections.listening().problem, encrypted_connections.NO_FILE)

    def test_https_gives_this_computers_own_windows_a_port_of_their_own(self) -> None:
        self.connections.set_certificate(self.cert, self.key)
        with mock.patch.object(managerui, "_ui_thread", None), \
             mock.patch.object(managerui.threading, "Thread"), \
             mock.patch.object(loopback, "serve_on_startup") as serve:
            managerui.start_manager_ui(port=8765)
        sock = serve.call_args.args[0]
        self.addCleanup(sock.close)

        own = serving.bound_port("loopback_port")
        self.assertEqual(sock.getsockname(), ("127.0.0.1", own))
        self.assertNotEqual(own, 8765)
        self.assertEqual(serving.bound_port("http_port"), 8765)
        self.assertEqual(serving.loopback_or(8765), own)

    def test_plain_http_has_no_loopback_port(self) -> None:
        with mock.patch.object(managerui, "_ui_thread", None), \
             mock.patch.object(managerui.threading, "Thread"), \
             mock.patch.object(loopback, "serve_on_startup") as serve:
            managerui.start_manager_ui(port=8765)

        serve.assert_not_called()
        self.assertIsNone(serving.bound_port("loopback_port"))


if __name__ == "__main__":
    unittest.main()
