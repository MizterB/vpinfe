"""The import's report: which groups it draws and in what order, how many rows each names,
what it checks against the library when it is shown, and what the two retry links start."""

from __future__ import annotations

import asyncio
import unittest
from typing import Any
from unittest.mock import AsyncMock, patch

from nicegui import ui

from console import import_report, library_folders, offload, report_groups, wizard

JOB = "7f3a"


def _item(group: str, n: int, **extra: Any) -> dict[str, Any]:
    return {"group": group, "key": f"{group}{n}", "game_id": f"{group}-{n}",
            "name": f"{group} {n}", "reason": "", **extra}


def _job(*, items: list[dict[str, Any]] | None = None, **result: Any) -> dict[str, Any]:
    return {"id": JOB, "state": "done", "result": {
        "rows": [], "already_here": [], "left_behind": [], "items": items or [],
        "answers": {"source": "PinballY"}, **result}}


def _drawn(job: dict[str, Any]) -> list[str]:
    with ui.column() as body:
        wizard.report(body, job, "")
    return [one.text for one in body.descendants() if isinstance(one, ui.label)]


class TheGroupsTheImporterRecords(unittest.TestCase):
    def test_each_recorded_group_is_a_group_of_its_games(self) -> None:
        found = report_groups.groups(_job(items=[
            _item(import_report.NEED_ROM, 1), _item(import_report.NEED_ROM, 2),
            _item(import_report.NO_WHEEL, 1)]))

        self.assertEqual(("need_rom-1", "need_rom-2"), found[import_report.NEED_ROM].game_ids)
        self.assertEqual(("no_wheel-1",), found[import_report.NO_WHEEL].game_ids)
        self.assertNotIn(import_report.NOT_MATCHED, found)

    def test_a_game_in_two_groups_is_in_each(self) -> None:
        both = {"game_id": "g1"}
        found = report_groups.groups(_job(items=[
            _item(import_report.NOT_MATCHED, 1, **both), _item(import_report.NO_WHEEL, 1, **both)]))

        self.assertEqual(("g1",), found[import_report.NOT_MATCHED].game_ids)
        self.assertEqual(("g1",), found[import_report.NO_WHEEL].game_ids)


class WhatTheReportDraws(unittest.TestCase):
    def test_the_headings_come_in_the_order_a_person_works_down(self) -> None:
        drawn = _drawn(_job(
            items=[_item(import_report.NEED_ROM, 1), _item(import_report.DMD_ALONE, 1)],
            rows=[{"key": "bad", "name": "Bad", "game_id": "", "error": "no table"}],
            already_here=[{"key": "old", "name": "Old", "game_id": "o1"}],
            left_behind=[{"what": "ScreenRes.txt", "displays": True}]))

        order = ["Needs a look", "Not imported", "Need a ROM", "Good to know",
                 "Already in VPinFE, left alone", "DMD placed on its own", "Left behind",
                 "ScreenRes.txt", "Imported"]
        self.assertEqual(order, [one for one in drawn if one in order])

    def test_a_group_over_three_rows_names_three_and_the_rest_is_a_count(self) -> None:
        with ui.column() as body:
            wizard.report(body, _job(items=[_item(import_report.NOT_MATCHED, n)
                                            for n in range(5)]), "")
        words = [one.text for one in body.descendants() if isinstance(one, ui.label)]
        links = [one.text for one in body.descendants() if isinstance(one, ui.link)]

        self.assertEqual(3, len([one for one in words if one.startswith("not_matched ")]))
        self.assertIn("2 more", links)

    def test_the_rest_of_a_group_is_a_link_to_it_in_tables(self) -> None:
        job = _job(items=[_item(import_report.NO_WHEEL, n) for n in range(5)])
        with ui.column() as body:
            wizard.report(body, job, "")
        hrefs = [one.props["href"] for one in body.descendants() if isinstance(one, ui.link)]

        self.assertIn(report_groups.tables_address(JOB, import_report.NO_WHEEL), hrefs)

    def test_a_row_the_library_now_satisfies_keeps_a_tick_and_loses_its_link(self) -> None:
        job = _job(items=[_item(import_report.NEED_ROM, 1), _item(import_report.NEED_ROM, 2)])
        job["checked"] = {import_report.NEED_ROM: {"need_rom-1"}}
        with ui.column() as body:
            wizard.report(body, job, "")
        words = [one.text for one in body.descendants() if isinstance(one, ui.label)]
        links = [one for one in body.descendants() if isinstance(one, ui.link)]

        self.assertIn("Added", words)
        self.assertEqual(1, len([one for one in links if one.text == "Add the ROM"]))

    def test_a_fixed_row_follows_the_ones_still_to_do(self) -> None:
        job = _job(items=[_item(import_report.NO_WHEEL, 1), _item(import_report.NO_WHEEL, 2)])
        job["checked"] = {import_report.NO_WHEEL: {"no_wheel-1"}}

        named = [one for one in _drawn(job) if one.startswith("no_wheel ")]

        self.assertEqual(["no_wheel 2", "no_wheel 1"], named)

    def test_a_cabinet_file_with_no_place_to_set_it_has_no_displays_link(self) -> None:
        with ui.column() as body:
            wizard.report(body, _job(left_behind=[
                {"what": "DirectOutput", "displays": False},
                {"what": "ScreenRes.txt", "displays": True}]), "")
        links = [one.text for one in body.descendants() if isinstance(one, ui.link)]

        self.assertEqual(["Displays"], links)

    def test_each_link_opens_the_game_where_the_fix_is(self) -> None:
        job = _job(items=[_item(import_report.NEED_ROM, 1), _item(import_report.NOT_MATCHED, 1),
                          _item(import_report.NO_WHEEL, 1)])
        with ui.column() as body:
            wizard.report(body, job, "")
        hrefs = {one.text: one.props["href"] for one in body.descendants()
                 if isinstance(one, ui.link)}

        self.assertEqual("/console?view=assets&game=need_rom-1&slot=rom", hrefs["Add the ROM"])
        self.assertEqual("/console?view=tables&game=not_matched-1&section=game_details",
                         hrefs["Match"])
        self.assertEqual("/console?view=media&game=no_wheel-1&slot=wheel", hrefs["Add a wheel"])

    def test_a_report_without_the_lists_is_drawn_the_way_it_was(self) -> None:
        job = {"id": JOB, "state": "done", "result": {"rows": [], "already_here": []}}

        self.assertFalse(import_report.has_report(job))


class TheLibraryIsReadAgain(unittest.TestCase):
    def _checked(self, job: dict[str, Any], **reads: Any) -> dict[str, set[str]]:
        async def inline(call: Any, *args: Any) -> Any:
            return call(*args)

        client = AsyncMock()
        client.all_tables = lambda: reads.get("tables", [])
        client.games = lambda: reads.get("games", [])
        client.all_media = lambda kind: reads.get("media", {}).get(kind, [])
        with patch.object(import_report, "ApiClient", return_value=client), \
                patch.object(offload, "io", new=inline):
            asyncio.run(import_report.check(job))
        return job["checked"]

    def test_a_rom_now_installed_fixes_that_game(self) -> None:
        job = _job(items=[_item(import_report.NEED_ROM, 1), _item(import_report.NEED_ROM, 2)])

        fixed = self._checked(job, tables=[
            {"game_id": "need_rom-1", "rom_installed": True},
            {"game_id": "need_rom-2", "rom_installed": None}])

        self.assertEqual({"need_rom-1"}, fixed[import_report.NEED_ROM])

    def test_a_game_now_matched_to_vps_is_fixed(self) -> None:
        job = _job(items=[_item(import_report.NOT_MATCHED, 1)])

        fixed = self._checked(job, games=[{"id": "not_matched-1", "vps_id": "abc"}])

        self.assertEqual({"not_matched-1"}, fixed[import_report.NOT_MATCHED])

    def test_a_wheel_or_a_logo_fills_the_wheel(self) -> None:
        job = _job(items=[_item(import_report.NO_WHEEL, 1), _item(import_report.NO_WHEEL, 2)])

        fixed = self._checked(job, media={
            "wheel": [{"game_id": "no_wheel-1", "present": True}],
            "logo": [{"game_id": "no_wheel-2", "present": False}]})

        self.assertEqual({"no_wheel-1"}, fixed[import_report.NO_WHEEL])

    def test_a_read_that_fails_leaves_the_report_as_it_was_written(self) -> None:
        job = _job(items=[_item(import_report.NEED_ROM, 1)])

        async def broken(call: Any, *args: Any) -> Any:
            raise OSError("down")

        with patch.object(offload, "io", new=broken):
            asyncio.run(import_report.check(job))

        self.assertEqual({}, job["checked"])

    def test_a_read_that_fails_later_keeps_the_ticks_already_earned(self) -> None:
        job = _job(items=[_item(import_report.NEED_ROM, 1)])
        job["checked"] = {import_report.NEED_ROM: {"need_rom-1"}}

        async def broken(call: Any, *args: Any) -> Any:
            raise OSError("down")

        with patch.object(offload, "io", new=broken):
            asyncio.run(import_report.check(job))

        self.assertEqual({import_report.NEED_ROM: {"need_rom-1"}}, job["checked"])


class TheRetryLinks(unittest.TestCase):
    def _retry(self, keys: list[str], found: list[dict[str, Any]]) -> AsyncMock:
        async def inline(call: Any, *args: Any) -> Any:
            return found

        opened = AsyncMock()
        with patch.object(offload, "io", new=inline), \
                patch.object(library_folders, "open_importer", new=opened):
            asyncio.run(import_report.retry(_job(), keys))
        return opened

    def test_the_second_import_starts_from_the_first_ones_answers_with_these_ticked(self) -> None:
        action = {"key": "import", "label": "Import"}
        found = [{"name": library_folders.IMPORTER, "actions": [action]}]

        opened = self._retry(["a", "b"], found)

        opened.assert_awaited_once_with(
            action, None, values={"source": "PinballY", "only": ["a", "b"]}, until="games")

    def test_an_importer_that_is_not_running_opens_nothing(self) -> None:
        with patch.object(import_report.ui, "notify") as said:
            opened = self._retry(["a"], [])

        opened.assert_not_awaited()
        said.assert_called_once()


if __name__ == "__main__":
    unittest.main()
