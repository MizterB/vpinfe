"""A selection of tables in the panel: the programs it names, what a write to it keeps for
Undo, and the hover on a setting the tables hold differently."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from common.i18n import t
from console import app_settings, workbench

KEY = "Player.BallTrail"
OTHER = "Player.FXAA"
GROUPS = [SimpleNamespace(key="more", label="More", curated=[], summarized=False, settings=[
    SimpleNamespace(key=KEY, label="Ball Trail", default="0", description="", help=""),
    SimpleNamespace(key=OTHER, label="FXAA", default="0", description="", help="")])]


class _Tables:
    """Each table's settings as the API answers for them, what was written where, and the
    job that writing several tables makes."""

    def __init__(self, **values: dict) -> None:
        self.values = values
        self.written: list[tuple[list[str], dict]] = []
        self.failed: list[dict] = []
        self.refused: set[str] = set()
        self.skipped: set[str] = set()
        self.refreshed = 0
        self._last: list[str] = []

    def launcher_config(self, _launcher: str, table: str, _scope: str) -> dict:
        return {"values": self.values[table], "shared_with_game": False}

    def write_launcher_config_tables(self, launcher: str, values: dict,
                                     tables: list[str]) -> dict:
        if launcher in self.refused:
            raise RuntimeError("refused")
        self.written.append((list(tables), values))
        self._last = list(tables)
        return {"id": "job-1"} if len(tables) > 1 else {}

    def job(self, _job_id: str) -> dict:
        lost = {one["table"] for one in self.failed} | self.skipped
        return {"state": "done", "result": {
            "failed": self.failed, "written": [one for one in self._last if one not in lost]}}

    def settings_written(self) -> None:
        self.refreshed += 1


def _targets(tables: _Tables, **launchers: str) -> list[dict]:
    return [{"table": {"id": table}, "launcher_id": launchers.get(table, "l1")}
            for table in tables.values]


def _own(value: str) -> dict:
    return {KEY: {"value": value, "set_here": True, "scope": "entry"}}


class ProgramsTests(unittest.TestCase):
    CONTEXT = {"launchers": {"launchers": [
        {"launcher_id": "vpx", "app": "vpx", "app_name": "Visual Pinball X"},
        {"launcher_id": "fp", "app": "fp", "app_name": "Future Pinball"}]}}

    def test_tables_are_grouped_by_program_with_the_most_first(self) -> None:
        tables = [{"id": "a", "launcher": "fp"}, {"id": "b", "launcher": "vpx"},
                  {"id": "c", "launcher": "vpx"}]

        found = app_settings._programs(self.CONTEXT, tables)

        self.assertEqual([([one["id"] for one in held], app_settings._program_name(launcher))
                          for launcher, held in found],
                         [(["b", "c"], "Visual Pinball X"), (["a"], "Future Pinball")])

    def test_a_table_with_no_launcher_has_no_program(self) -> None:
        found = app_settings._programs(self.CONTEXT, [{"id": "a", "launcher": "gone"}])

        self.assertEqual([(launcher, [one["id"] for one in held]) for launcher, held in found],
                         [(None, ["a"])])
        self.assertEqual(app_settings._program_name(None),
                         t("console.app_settings.no_program"))


class WriteSelectionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        async def inline(callback, *args, **kwargs):
            return callback(*args, **kwargs)

        for target in (patch.object(app_settings.offload, "io", inline),
                       patch.object(app_settings, "JOB_POLL_S", 0)):
            target.start()
            self.addCleanup(target.stop)

    async def _write(self, tables: _Tables, value: str) -> dict:
        return await app_settings.write_selection(
            tables, {}, _targets(tables), GROUPS, {KEY: value})

    async def test_undo_holds_each_table_s_own_value_and_a_blank_where_it_held_none(self) -> None:
        tables = _Tables(a=_own("1"), b={KEY: {"value": "0"}}, c=_own("2"))

        wrote = await self._write(tables, "3")

        self.assertEqual(sorted(wrote["undo"]), [
            ("a", "l1", {KEY: "1"}), ("b", "l1", {KEY: ""}), ("c", "l1", {KEY: "2"})])
        self.assertFalse(wrote["blank"])

    async def test_the_tables_go_in_one_write_and_the_job_is_waited_out(self) -> None:
        tables = _Tables(a=_own("1"), b={KEY: {"value": "0"}}, c=_own("2"))

        await self._write(tables, "3")

        self.assertEqual(tables.written, [(["a", "b", "c"], {KEY: "3"})])
        self.assertEqual(tables.refreshed, 1)

    async def test_a_table_already_holding_the_value_is_not_written_or_undone(self) -> None:
        tables = _Tables(a=_own("3"), b={KEY: {"value": "0"}}, c={KEY: {"value": "0"}})

        wrote = await self._write(tables, "3")

        self.assertEqual(tables.written, [(["b", "c"], {KEY: "3"})])
        self.assertEqual([table for table, _, _ in wrote["undo"]], ["b", "c"])

    async def test_clearing_undoes_only_the_tables_that_set_one(self) -> None:
        tables = _Tables(a=_own("1"), b={KEY: {"value": "0"}})

        wrote = await self._write(tables, "")

        self.assertTrue(wrote["blank"])
        self.assertEqual(tables.written, [(["a"], {KEY: ""})])
        self.assertEqual(wrote["undo"], [("a", "l1", {KEY: "1"})])

    async def test_a_table_the_job_could_not_write_is_named_and_left_out_of_undo(self) -> None:
        tables = _Tables(a=_own("1"), b=_own("2"))
        tables.failed = [{"table": "b", "reason": "read-only"}]

        wrote = await self._write(tables, "3")

        self.assertEqual(wrote["failed"], tables.failed)
        self.assertEqual([table for table, _, _ in wrote["undo"]], ["a"])

    async def test_a_launcher_that_cannot_be_written_is_named_and_the_others_keep_their_undo(
            self) -> None:
        tables = _Tables(a=_own("1"), b=_own("2"))
        tables.refused = {"l2"}

        wrote = await app_settings.write_selection(
            tables, {}, _targets(tables, b="l2"), GROUPS, {KEY: "3"})

        self.assertEqual([one["table"] for one in wrote["failed"]], ["b"])
        self.assertEqual(wrote["undo"], [("a", "l1", {KEY: "1"})])

    async def test_a_table_the_job_never_reached_is_failed_and_left_out_of_undo(self) -> None:
        tables = _Tables(a=_own("1"), b=_own("2"))
        tables.skipped = {"b"}

        wrote = await self._write(tables, "3")

        self.assertEqual([one["table"] for one in wrote["failed"]], ["b"])
        self.assertEqual([table for table, _, _ in wrote["undo"]], ["a"])

    async def test_a_table_is_sent_only_the_settings_it_changes(self) -> None:
        tables = _Tables(a={KEY: {"value": "3", "set_here": True}}, b={})

        wrote = await app_settings.write_selection(
            tables, {}, _targets(tables), GROUPS, {KEY: "3", OTHER: "5"})

        self.assertEqual(sorted(tables.written), [
            (["a"], {OTHER: "5"}), (["b"], {KEY: "3", OTHER: "5"})])
        self.assertEqual(sorted(wrote["undo"]), [
            ("a", "l1", {OTHER: ""}), ("b", "l1", {KEY: "", OTHER: ""})])

    async def test_nothing_to_change_holds_nothing_to_undo(self) -> None:
        tables = _Tables(a={KEY: {"value": "0"}}, b={KEY: {"value": "0"}})

        self.assertEqual((await self._write(tables, ""))["undo"], [])
        self.assertEqual(tables.written, [])


class VariesByValueTests(unittest.TestCase):
    def _hover(self, values: list[str], **kwargs) -> str:
        tables = [{"id": str(index)} for index in range(len(values))]
        held = {"varies": True, "each": list(zip(tables, values, strict=True))}
        field = SimpleNamespace(key=KEY, label="Ball Trail", default="0", kind="bool",
                                options=())
        with patch.object(workbench, "_said_value", side_effect=lambda _f, v: v), \
                patch.object(workbench.panel, "state") as state:
            drawn = workbench._varies([(None, held, field)], tables, "Visual Pinball X",
                                      **kwargs)
        assert drawn is not None
        return state.call_args.kwargs["hint"]

    def test_by_value_counts_the_tables_holding_each_and_the_commonest_first(self) -> None:
        hover = self._hover(["Off", "On", "Off", "Off", "On"], by_value=True)

        self.assertEqual(hover.splitlines(), [
            t("console.workbench.value_count", said="Off", count=3),
            t("console.workbench.value_count", said="On", count=2)])

    def test_otherwise_each_table_is_named_with_its_value(self) -> None:
        hover = self._hover(["Off", "On"])

        self.assertEqual(len(hover.splitlines()), 2)
        self.assertNotIn(t("console.workbench.value_count", said="Off", count=1), hover)


class PutBackTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        async def inline(callback, *args, **kwargs):
            return callback(*args, **kwargs)

        for target in (patch.object(app_settings.offload, "io", inline),
                       patch.object(app_settings, "JOB_POLL_S", 0)):
            target.start()
            self.addCleanup(target.stop)
        self.drawn = 0

    async def _rebuild(self) -> None:
        self.drawn += 1

    async def test_a_table_that_cannot_be_put_back_is_said_and_the_panel_still_draws(self) -> None:
        tables = _Tables(a=_own("1"), b=_own("2"))
        tables.failed = [{"table": "b", "reason": "locked"}]
        inner = {"library": tables, "state": {}, "rebuild": self._rebuild}

        with self.assertRaisesRegex(RuntimeError, "locked"):
            await app_settings._put_back(
                inner, [("a", "l1", {KEY: "1"}), ("b", "l1", {KEY: "1"})])

        self.assertEqual(self.drawn, 1)


class ConfigAppliedTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_coroutine_write_is_awaited_where_it_stands(self) -> None:
        async def write(values: dict) -> dict:
            return {"cut": [values]}

        self.assertEqual(await workbench.config_applied(write, {KEY: "1"}),
                         {"cut": [{KEY: "1"}]})

    async def test_a_plain_write_runs_off_the_loop(self) -> None:
        async def inline(callback, *args):
            return callback(*args)

        with patch.object(workbench.run, "io_bound", inline):
            found = await workbench.config_applied(lambda values: {"cut": [values]},
                                                   {KEY: "1"})

        self.assertEqual(found, {"cut": [{KEY: "1"}]})


if __name__ == "__main__":
    unittest.main()
