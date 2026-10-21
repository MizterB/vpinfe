"""Setup's key access: asked on a Mac, shown as a command on Wayland, silent where keys are
heard, and never a reason to stop Setup."""

from __future__ import annotations

import asyncio
import unittest
from typing import Any
from unittest import mock

from common.host import key_reader
from common.i18n import t
from manager.setup import setup_key_access

MAC_DENIED = key_reader.hearing({}, "darwin", listen_access=lambda: False)
MAC_ALLOWED = key_reader.hearing({}, "darwin", listen_access=lambda: True)
NO_GROUP = key_reader.hearing({"WAYLAND_DISPLAY": "wayland-1"}, "linux", devices=list)
NO_DESKTOP = key_reader.hearing({}, "linux")


def _ran(coro: Any) -> Any:
    return asyncio.run(coro)


def _looked(heard: key_reader.Hearing, asked: setup_key_access.Asked) -> Any:
    with mock.patch.object(setup_key_access.key_reader, "hearing", return_value=heard), \
         mock.patch.object(setup_key_access.key_reader, "ask_listen_access") as ask:
        return _ran(setup_key_access.look(asked)), ask


class MacTests(unittest.TestCase):
    def test_a_mac_without_input_monitoring_is_asked(self) -> None:
        found, ask = _looked(MAC_DENIED, setup_key_access.Asked())

        ask.assert_called_once_with()
        assert found is not None
        self.assertEqual("", found.command)
        self.assertIn(t(key_reader.NO_INPUT_MONITORING), found.lines[0])
        self.assertIn(t(key_reader.ALLOW_INPUT_MONITORING), found.lines[0])
        self.assertIn(t("manager.setup.keys.restart"), found.lines)

    def test_it_is_asked_once_however_often_the_step_is_drawn(self) -> None:
        asked = setup_key_access.Asked()

        _, first = _looked(MAC_DENIED, asked)
        found, second = _looked(MAC_DENIED, asked)

        first.assert_called_once_with()
        second.assert_not_called()
        self.assertIsNotNone(found, "the finding stays after the question")

    def test_a_mac_that_has_input_monitoring_is_not_asked(self) -> None:
        found, ask = _looked(MAC_ALLOWED, setup_key_access.Asked())

        self.assertIsNone(found)
        ask.assert_not_called()


class WaylandTests(unittest.TestCase):
    def test_the_command_has_this_devices_user_in_it(self) -> None:
        with mock.patch.object(setup_key_access.getpass, "getuser", return_value="pinball"):
            found, ask = _looked(NO_GROUP, setup_key_access.Asked())

        assert found is not None
        self.assertEqual("sudo usermod -aG input pinball", found.command)
        ask.assert_not_called()

    def test_it_says_where_to_run_it_and_that_it_needs_a_restart(self) -> None:
        found, _ = _looked(NO_GROUP, setup_key_access.Asked())

        assert found is not None
        self.assertIn(t("manager.setup.keys.group_fix"), found.lines)
        said = t("manager.setup.keys.group_fix")
        self.assertIn("cabinet", said)
        self.assertIn("restart", said)

    def test_a_user_the_shell_would_split_is_quoted(self) -> None:
        self.assertEqual("sudo usermod -aG input 'a b'",
                         setup_key_access.join_command("a b"))

    def test_a_user_that_cannot_be_named_gets_a_placeholder_not_a_crash(self) -> None:
        with mock.patch.object(setup_key_access.getpass, "getuser", side_effect=OSError):
            found, _ = _looked(NO_GROUP, setup_key_access.Asked())

        assert found is not None
        self.assertEqual("sudo usermod -aG input <user>", found.command)

    def test_a_question_macos_cannot_be_put_to_leaves_setup_alone(self) -> None:
        with mock.patch.object(setup_key_access.offload, "io",
                               side_effect=[MAC_DENIED, RuntimeError("pool is shut")]):
            found = _ran(setup_key_access.look(setup_key_access.Asked()))

        assert found is not None
        self.assertEqual("", found.command)


class NothingToDoTests(unittest.TestCase):
    def test_keys_that_are_heard_draw_nothing(self) -> None:
        found, _ = _looked(key_reader.Hearing(key_reader.PYNPUT), setup_key_access.Asked())

        self.assertIsNone(found)

    def test_a_device_with_no_desktop_has_nothing_the_person_can_fix(self) -> None:
        found, ask = _looked(NO_DESKTOP, setup_key_access.Asked())

        self.assertIsNone(found)
        ask.assert_not_called()

    def test_a_check_that_fails_leaves_setup_alone(self) -> None:
        with mock.patch.object(setup_key_access.key_reader, "hearing",
                               side_effect=OSError("down")):
            self.assertIsNone(_ran(setup_key_access.look(setup_key_access.Asked())))


class CatalogTests(unittest.TestCase):
    def test_the_new_lines_are_in_the_catalog(self) -> None:
        for key in ("manager.setup.keys.group_fix", "manager.setup.keys.restart"):
            self.assertNotEqual(key, t(key))


if __name__ == "__main__":
    unittest.main()
