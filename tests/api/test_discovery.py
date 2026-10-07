"""What an install hears on the network, and what it makes of it.

The network itself is not exercised here - two processes on one machine finding each
other is a thing to watch happen, not to assert in a unit test. What is asserted is the
reading: an announcement carries identity, and anything on a LAN can send one, so a
record that does not identify itself is not a peer.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import httpapi
from common import device_registry as registry_module
from common import discovery, install_identity, install_presence
from tests.support.library import TempTree

try:
    from starlette.testclient import TestClient
except ImportError:  # pragma: no cover
    TestClient = None


class _Announcement:
    """What zeroconf hands back for one resolved service."""

    def __init__(self, properties: dict, addresses=("192.168.1.20",), port=8001):
        self.properties = properties
        self.port = port
        self._addresses = list(addresses)

    def parsed_addresses(self):
        return self._addresses


def _said(**overrides) -> dict:
    said = {b"id": b"Aaaa111111", b"name": b"basement cab",
            b"features": b"library,frontend", b"version": b"3.0.0"}
    said.update(overrides)
    return said


class ReadingAnAnnouncementTests(unittest.TestCase):
    def test_identity_comes_back_whole(self) -> None:
        peer = discovery._as_peer(_Announcement(_said()))

        self.assertEqual(peer.install_id, "Aaaa111111")
        self.assertEqual(peer.display_name, "basement cab")
        self.assertEqual(peer.features, ("library", "frontend"))
        self.assertEqual(peer.url, "http://192.168.1.20:8001")

    def test_a_record_with_no_identity_is_not_a_peer(self) -> None:
        """Anything on the network can announce a service of this type. What makes one
        of ours is the id every other surface keys on."""
        self.assertIsNone(discovery._as_peer(_Announcement(_said(id=b""))))

    def test_a_record_that_resolved_to_no_address_is_not_a_peer(self) -> None:
        """There is nothing to ask, so there is nothing to offer."""
        self.assertIsNone(discovery._as_peer(_Announcement(_said(), addresses=())))

    def test_no_features_is_read_as_none_rather_than_as_one_blank(self) -> None:
        peer = discovery._as_peer(_Announcement(_said(features=b"")))

        self.assertEqual(peer.features, ())

    def test_the_address_the_route_leaves_on_is_the_one_announced(self) -> None:
        class OnTheLan:
            def connect(self, _target):
                pass

            def getsockname(self):
                return ("192.168.1.20", 0)

            def close(self):
                pass

        with patch.object(discovery.socket, "socket", return_value=OnTheLan()):
            self.assertEqual(discovery._routable_address(), "192.168.1.20")

    def test_an_address_that_is_only_this_machine_is_not_a_peer(self) -> None:
        """A peer filed at 127.0.0.1 is reached by asking the machine that filed it."""
        self.assertIsNone(discovery._as_peer(_Announcement(_said(), addresses=("127.0.0.1",))))

    def test_the_first_address_that_leads_somewhere_is_the_peers(self) -> None:
        peer = discovery._as_peer(
            _Announcement(_said(), addresses=("127.0.0.1", "192.168.1.20")))

        self.assertEqual(peer.address, "192.168.1.20")

    def test_a_machine_with_no_route_has_no_address_to_announce(self) -> None:
        class NoRoute:
            def connect(self, _target):
                raise OSError("Network is unreachable")

            def close(self):
                pass

        with patch.object(discovery.socket, "socket", return_value=NoRoute()):
            self.assertEqual(discovery._routable_address(), "")

    def test_a_route_that_ends_on_loopback_is_no_address_either(self) -> None:
        class OnLoopback:
            def connect(self, _target):
                pass

            def getsockname(self):
                return ("127.0.0.1", 0)

            def close(self):
                pass

        with patch.object(discovery.socket, "socket", return_value=OnLoopback()):
            self.assertEqual(discovery._routable_address(), "")

    def test_with_no_address_nothing_is_registered(self) -> None:
        mine = discovery._Discovery()
        mine._zeroconf = MagicMock()

        with patch.object(discovery, "_routable_address", return_value=""), \
                patch.object(discovery.serving, "network",
                             return_value=MagicMock(http_port=8001)):
            announced = mine._announce(object())

        self.assertFalse(announced)
        mine._zeroconf.register_service.assert_not_called()


class AnnouncingTests(unittest.TestCase):
    def test_a_failure_with_no_text_still_names_its_type(self) -> None:
        class NoTextError(Exception):
            pass

        with patch.object(discovery._discovery, "start", side_effect=NoTextError()), \
                self.assertLogs("vpinfe.common.discovery", level="WARNING") as seen:
            discovery.start(object())

        self.assertTrue(seen.output[0].endswith("on the network: NoTextError()"), seen.output)


@unittest.skipIf(TestClient is None, "starlette test client unavailable")
class DiscoveredRouteTests(TempTree):
    def setUp(self) -> None:
        super().setUp()
        self.client = TestClient(httpapi.create_api_app(), raise_server_exceptions=False)

    def test_nothing_heard_is_an_empty_list_rather_than_an_error(self) -> None:
        with patch.object(discovery, "peers", lambda: []):
            body = self.client.get("/devices/discovered").json()

        self.assertEqual(body, {"count": 0, "installs": []})

    def test_what_was_heard_is_offered_with_a_url_to_reach_it(self) -> None:
        peer = discovery.Peer(install_id="Aaaa111111", display_name="basement cab",
                              features=("library",), address="192.168.1.20", port=8001)
        with patch.object(discovery, "peers", lambda: [peer]):
            body = self.client.get("/devices/discovered").json()

        self.assertEqual(body["count"], 1)
        self.assertEqual(body["installs"][0]["url"], "http://192.168.1.20:8001")
        self.assertEqual(body["installs"][0]["features"], ["library"])

    def test_the_word_is_not_read_as_a_device_id(self) -> None:
        """`/devices/{device_id}` would match it, so the order of the two matters."""
        with patch.object(discovery, "peers", lambda: []):
            self.assertEqual(self.client.get("/devices/discovered").status_code, 200)


class RecordingWhatWasHeardTests(TempTree):
    """What an install does with a peer depends on what it is for."""

    def setUp(self) -> None:
        super().setUp()
        self.registry = registry_module.DeviceRegistry(self.root / "devices.json")
        patcher = patch.object(registry_module, "get_device_registry",
                               lambda: self.registry)
        patcher.start()
        self.addCleanup(patcher.stop)
        also = patch("common.install_presence.get_device_registry",
                     lambda: self.registry)
        also.start()
        self.addCleanup(also.stop)

    def _peer(self):
        return discovery.Peer(install_id="Aaaa111111", display_name="basement cab",
                              features=("library",), address="192.168.1.20", port=8001)

    def _with_features(self, *names):
        return patch.object(install_identity, "features", lambda _config: list(names))

    def test_an_install_that_manages_devices_files_what_it_heard(self) -> None:
        with self._with_features(install_identity.DEVICES):
            install_presence._heard_from(self._peer())

        held = self.registry.get("Aaaa111111")
        self.assertEqual(held.display_name, "basement cab")
        self.assertEqual(held.address, "192.168.1.20")
        self.assertEqual(held.port, 8001)

    def test_an_install_that_does_not_keeps_no_list(self) -> None:
        """Announcing is to everybody; what to do with it is each install's own."""
        with self._with_features(install_identity.FRONTEND):
            install_presence._heard_from(self._peer())

        self.assertEqual(self.registry.devices(), [])


class PublishedServicesTests(unittest.TestCase):
    def test_a_frontend_reads_the_file_server_under_the_name_it_is_published(self) -> None:
        from types import SimpleNamespace

        from frontend import chromium_manager

        published = install_presence.service_ports()
        elsewhere = SimpleNamespace(library_url="http://library.example:9000",
                                    http_port=8001, theme_assets_port=1)
        with patch.object(chromium_manager.remote_library, "remote_services",
                          return_value=published):
            resolved = chromium_manager._library_endpoint(elsewhere)

        self.assertEqual(resolved.files_port, published["files"]["port"])
        self.assertNotEqual(resolved.files_port, 1)


if __name__ == "__main__":
    unittest.main()
