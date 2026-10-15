"""The window on each screen that says its number, for the Manager's Show numbers."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock
from urllib.parse import unquote

from frontend import screen_numbers

ONE = SimpleNamespace(number=1, name="Dell P2419H", width=2560, height=1440, x=0, y=0)
TWO = SimpleNamespace(number=2, name="", width=1280, height=390, x=0, y=1440)


class PageTests(unittest.TestCase):
    def test_it_says_the_number_the_name_and_the_size(self) -> None:
        page = screen_numbers.page(1, "Dell P2419H", "2560 x 1440")

        for word in ('class="number">1<', "Dell P2419H", "2560 x 1440"):
            self.assertIn(word, page)

    def test_a_screen_with_no_name_has_no_name_line(self) -> None:
        self.assertNotIn('class="name"', screen_numbers.page(2, "", "1280 x 390"))

    def test_a_name_is_text_and_not_markup(self) -> None:
        page = screen_numbers.page(1, "<script>x()</script>", "1 x 1")

        self.assertNotIn("<script>", page)
        self.assertIn("&lt;script&gt;", page)

    def test_the_arrow_is_drawn_only_when_asked_for(self) -> None:
        self.assertNotIn("<svg", screen_numbers.page(1, "", "1 x 1"))
        self.assertIn("<svg", screen_numbers.page(1, "", "1 x 1", arrow=True))


class AddressTests(unittest.TestCase):
    def test_it_is_the_page_itself_as_a_data_address(self) -> None:
        address = screen_numbers.address(3, "A & B", "1 x 1", arrow=True)

        self.assertTrue(address.startswith("data:text/html;charset=utf-8,"))
        self.assertEqual(unquote(address.split(",", 1)[1]),
                         screen_numbers.page(3, "A & B", "1 x 1", arrow=True))

    def test_it_holds_nothing_that_ends_an_address_early(self) -> None:
        address = screen_numbers.address(1, "", "1 x 1")

        self.assertNotIn("#", address)
        self.assertNotIn(" ", address)


class ShowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = self.enterContext(mock.patch.object(screen_numbers, "ChromiumManager"))
        self.enterContext(mock.patch.object(screen_numbers.paths, "get_ini_config"))
        self.enterContext(mock.patch.object(
            screen_numbers.SettingsConfig, "from_config",
            return_value=SimpleNamespace(chrome_options="--x",
                                         default_chrome_options=True)))
        self.enterContext(mock.patch.object(screen_numbers, "cfg_get", return_value=""))
        self.sleep = self.enterContext(mock.patch.object(screen_numbers.time, "sleep"))
        self.launch = self.manager.return_value.launch_window

    def test_each_screen_gets_a_window_of_its_own_on_it(self) -> None:
        screen_numbers.show([ONE, TWO])

        [first, second] = self.launch.call_args_list
        self.assertEqual((first.args[0], first.args[2], first.args[3]), ("screen1", ONE, 1))
        self.assertEqual((second.args[0], second.args[2], second.args[3]), ("screen2", TWO, 2))
        self.assertIn("Dell P2419H", unquote(first.args[1]))
        self.assertIn("1280 x 390", unquote(second.args[1]))

    def test_only_the_arrowed_screen_has_the_arrow(self) -> None:
        screen_numbers.show([ONE, TWO], arrowed=2)

        [first, second] = self.launch.call_args_list
        self.assertNotIn("<svg", unquote(first.args[1]))
        self.assertIn("<svg", unquote(second.args[1]))

    def test_the_windows_are_opened_with_the_chromium_options_the_frontend_uses(self) -> None:
        screen_numbers.show([ONE])

        kwargs = self.launch.call_args.kwargs
        self.assertEqual(kwargs["additional_options"], "--x")
        self.assertTrue(kwargs["include_default_options"])
        self.assertTrue(kwargs["mute_audio"])

    def test_they_stay_for_the_time_given_and_are_then_all_closed(self) -> None:
        screen_numbers.show([ONE, TWO], seconds=3)

        self.sleep.assert_called_once_with(3)
        self.manager.return_value.terminate_all.assert_called_once_with()

    def test_one_window_that_will_not_open_leaves_the_others(self) -> None:
        self.launch.side_effect = [RuntimeError("no"), mock.Mock()]

        with self.assertLogs("vpinfe.frontend.screen_numbers", "WARNING"):
            screen_numbers.show([ONE, TWO])

        self.sleep.assert_called_once()
        self.manager.return_value.terminate_all.assert_called_once_with()

    def test_no_window_opening_raises_the_reason_and_closes_what_it_started(self) -> None:
        self.launch.side_effect = FileNotFoundError("Chromium binary not found")

        with self.assertRaises(FileNotFoundError), \
                self.assertLogs("vpinfe.frontend.screen_numbers", "WARNING"):
            screen_numbers.show([ONE, TWO])

        self.sleep.assert_not_called()
        self.manager.return_value.terminate_all.assert_called_once_with()

    def test_it_can_be_shown_again_once_it_is_over(self) -> None:
        self.launch.side_effect = FileNotFoundError("gone")
        with self.assertRaises(FileNotFoundError), \
                self.assertLogs("vpinfe.frontend.screen_numbers", "WARNING"):
            screen_numbers.show([ONE])
        self.launch.side_effect = None

        screen_numbers.show([ONE])

        self.assertEqual(self.sleep.call_count, 1)

    def test_a_manager_that_cannot_be_made_does_not_leave_it_showing_forever(self) -> None:
        self.manager.side_effect = RuntimeError("no browser")
        with self.assertRaises(RuntimeError):
            screen_numbers.show([ONE])
        self.manager.side_effect = None

        screen_numbers.show([ONE])

        self.assertEqual(self.launch.call_count, 1)
        self.assertEqual(self.sleep.call_count, 1)

    def test_the_size_is_said_in_the_catalogs_words(self) -> None:
        with mock.patch.object(screen_numbers, "t", return_value="W by H") as said:
            screen_numbers.show([ONE])

        said.assert_called_once_with("manager.screens.size", width=2560, height=1440)
        self.assertIn("W by H", unquote(self.launch.call_args.args[1]))

    def test_a_second_call_while_one_is_showing_opens_nothing(self) -> None:
        asked: list[int] = []

        def ask_again(_seconds: float) -> None:
            before = self.launch.call_count
            screen_numbers.show([ONE])
            asked.append(self.launch.call_count - before)

        self.sleep.side_effect = ask_again

        screen_numbers.show([ONE])

        self.assertEqual(asked, [0])
        self.assertEqual(self.manager.return_value.terminate_all.call_count, 1)


if __name__ == "__main__":
    unittest.main()
