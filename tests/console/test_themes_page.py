"""The Themes grid: what each row says, and what the panel leaves out."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, Mock, patch

from console import themes
from tests.support.clicks import press


def _theme(**more) -> dict:
    return {"key": "k", "name": "Name", "author": "someone", "version": "1.0",
            "installed_version": "", "installed": False, "active": False,
            "update_available": False, "type": "", "preview": "", **more}


class ARow(unittest.TestCase):
    def test_each_state_is_one_of_four(self) -> None:
        self.assertEqual(
            [themes.ACTIVE, themes.UPDATE, themes.INSTALLED, themes.AVAILABLE],
            [themes.status(_theme(installed=True, active=True)),
             themes.status(_theme(installed=True, update_available=True)),
             themes.status(_theme(installed=True)),
             themes.status(_theme())])

    def test_made_for_says_only_what_the_manifest_declared(self) -> None:
        self.assertEqual(["cab", ""], [row["made_for"] for row in themes.rows(
            [_theme(key="a", type="cab"), _theme(key="b", type="")])])

    def test_an_update_reads_as_the_version_you_have_and_the_one_on_offer(self) -> None:
        said = themes.version_said(_theme(installed=True, update_available=True,
                                          installed_version="1.7", version="1.9"))
        self.assertIn("1.7", said)
        self.assertIn("1.9", said)


class WhereItComesFrom(unittest.TestCase):
    def test_a_repository_or_a_file_in_one_reads_as_owner_and_repo(self) -> None:
        for url in ("https://github.com/owner/repo",
                    "https://raw.githubusercontent.com/owner/repo/master/themes.json",
                    "https://github.com/owner/repo/raw/refs/heads/master/manifest.json",
                    "https://git.example.net/owner/repo/raw/branch/main/themes.json"):
            with self.subTest(url=url):
                self.assertEqual("owner/repo", themes.repo_name(url))

    def test_a_file_in_a_repository_links_to_the_repository_s_page(self) -> None:
        for url, page in (
                ("https://raw.githubusercontent.com/owner/repo/master/themes.json",
                 "https://github.com/owner/repo"),
                ("https://git.example.net/owner/repo/raw/branch/main/themes.json",
                 "https://git.example.net/owner/repo"),
                ("https://example.net/vpinfe/catalogs/themes.json",
                 "https://example.net/vpinfe/catalogs/themes.json")):
            with self.subTest(url=url):
                self.assertEqual(page, themes.repo_page(url))

    def test_any_other_address_is_shown_whole(self) -> None:
        url = "https://example.net/vpinfe/catalogs/themes.json"
        self.assertEqual(url, themes.repo_name(url))

    def test_a_row_carries_its_registry_repository_and_author(self) -> None:
        row = themes.rows([_theme(
            registry="https://raw.githubusercontent.com/owner/catalog/master/themes.json",
            url="https://github.com/owner/theme")])[0]
        self.assertEqual(("owner/catalog", "owner/theme", "someone"),
                         (row["registry"], row["repository"], row["author"]))

    def test_a_theme_added_by_hand_has_neither(self) -> None:
        row = themes.rows([_theme(registry="", url="")])[0]
        self.assertEqual(("", ""), (row["registry"], row["repository"]))


class TheChangelog(unittest.TestCase):
    def test_a_template_placeholder_is_not_news(self) -> None:
        self.assertEqual("", themes.changes_worth_showing(
            _theme(change_log="What changed in this version?")))

    def test_it_is_shown_before_installing_and_with_an_update_waiting(self) -> None:
        self.assertEqual("Faster", themes.changes_worth_showing(_theme(change_log="Faster")))
        self.assertEqual("Faster", themes.changes_worth_showing(
            _theme(change_log="Faster", installed=True, update_available=True)))

    def test_it_is_old_news_on_the_copy_you_run(self) -> None:
        self.assertEqual("", themes.changes_worth_showing(
            _theme(change_log="Faster", installed=True)))


class Installing(unittest.IsolatedAsyncioTestCase):
    async def _install(self, outcome: object) -> tuple[Mock, Mock, AsyncMock]:
        downloading, notify, again = Mock(), Mock(), AsyncMock()
        self.notification = Mock(return_value=downloading)
        with patch.object(themes.ui, "notification", new=self.notification), \
                patch.object(themes.ui, "notify", new=notify), \
                patch.object(themes.run, "io_bound", new=AsyncMock(side_effect=outcome)):
            await press(themes._install, Mock(), "carousel-desktop", again)
        return downloading, notify, again

    async def test_the_download_notice_stays_until_the_install_is_over(self) -> None:
        await self._install([None])

        self.notification.assert_called_once()
        self.assertEqual((True, None), (self.notification.call_args.kwargs["spinner"],
                                        self.notification.call_args.kwargs["timeout"]))

    async def test_the_download_notice_goes_once_the_theme_is_in(self) -> None:
        downloading, notify, again = await self._install([None])

        downloading.dismiss.assert_called_once_with()
        self.assertEqual("positive", notify.call_args.kwargs["type"])
        again.assert_awaited_once()

    async def test_the_download_notice_goes_when_the_install_fails(self) -> None:
        downloading, notify, again = await self._install(OSError("down"))

        downloading.dismiss.assert_called_once_with()
        self.assertEqual("negative", notify.call_args.kwargs["type"])
        again.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
