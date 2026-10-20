"""Browse's Playable and Held columns, and the built-in view that waits for a count."""

from __future__ import annotations

import unittest
from typing import Any
from unittest import mock

from nicegui import ui

from manager.kit import grid, views
from manager.kit.data import Library
from manager.library import discovery

_PAGE = ui.element()

BALLY = {"type": "maker", "name": "Bally"}
SPACE = {"type": "theme", "name": "Space"}


def _release(rid: str, *, fmt: str = "VPX", held: bool = False) -> dict[str, Any]:
    return {"id": rid, "by": [0], "added": "2020-01-01T00:00:00Z", "held": held,
            "mod": False, "version": "", "format": fmt}


def _entry(vps_id: str = "g1", releases: dict[str, list[dict[str, Any]]] | None = None,
           **over: Any) -> dict[str, Any]:
    return {"vps_id": vps_id, "name": "Attack from Mars", "manufacturer": "Bally",
            "year": 1995, "type": "SS", "themes": ["Space"], "url": "", "in_library": True,
            "listed": ["tableFiles", "b2sFiles"], "held": [],
            "releases": releases if releases is not None else {}, **over}


def _row(entry: dict[str, Any], *, counted: bool = True, formats: tuple[str, ...] = (),
         kept: list[str] | None = None) -> dict[str, Any]:
    found = {"counted": "2026-10-01T10:00:00Z" if counted else "", "rows": [entry]}
    return discovery.rows(found, kept, None, formats)[0]


def _browse_columns() -> list[dict[str, Any]]:
    built = [{"manufacturer": f"Maker {n}", "game_type": "SS"} for n in range(2)]
    return grid.with_derived_facets(discovery.COLUMNS, built, discovery.CATALOG_FACET_CEILING)


class PlayableColumn(unittest.TestCase):
    def test_a_game_with_a_table_the_launchers_play_is_playable(self) -> None:
        row = _row(_entry(releases={"tableFiles": [_release("t1", fmt="VPX")]}),
                   formats=("VPX",))

        self.assertEqual("yes", row[discovery.PLAYABLE])

    def test_a_game_whose_only_tables_are_another_format_is_not(self) -> None:
        row = _row(_entry(releases={"tableFiles": [_release("t1", fmt="FP")]}),
                   formats=("VPX",))

        self.assertEqual("no", row[discovery.PLAYABLE])

    def test_a_table_filed_under_no_format_counts_as_playable(self) -> None:
        row = _row(_entry(releases={"tableFiles": [_release("t1", fmt="")]}),
                   formats=("VPX",))

        self.assertEqual("yes", row[discovery.PLAYABLE])

    def test_launchers_that_name_no_format_play_any_table(self) -> None:
        row = _row(_entry(releases={"tableFiles": [_release("t1", fmt="FP")]}))

        self.assertEqual("yes", row[discovery.PLAYABLE])

    def test_a_game_with_no_table_is_not_playable(self) -> None:
        row = _row(_entry(releases={"b2sFiles": [_release("b1", fmt="")]}))

        self.assertEqual("no", row[discovery.PLAYABLE])

    def test_it_is_read_before_the_library_is_counted(self) -> None:
        row = _row(_entry(releases={"tableFiles": [_release("t1")]}), counted=False)

        self.assertEqual("yes", row[discovery.PLAYABLE])

    def test_it_is_blank_where_the_library_collects_no_tables(self) -> None:
        row = _row(_entry(releases={"tableFiles": [_release("t1")]}), kept=["b2sFiles"])

        self.assertEqual("", row[discovery.PLAYABLE])


class HeldColumn(unittest.TestCase):
    def test_a_game_the_library_holds_a_release_of_reads_yes(self) -> None:
        row = _row(_entry(releases={"tableFiles": [_release("t1"), _release("t2", held=True)]}))

        self.assertEqual("yes", row[discovery.HELD])

    def test_a_game_with_no_release_held_reads_no(self) -> None:
        row = _row(_entry(releases={"tableFiles": [_release("t1")]}))

        self.assertEqual("no", row[discovery.HELD])

    def test_a_release_of_a_kind_the_library_does_not_collect_is_not_counted(self) -> None:
        row = _row(_entry(releases={"tableFiles": [_release("t1")],
                                    "b2sFiles": [_release("b1", held=True)]}),
                   kept=["tableFiles"])

        self.assertEqual("no", row[discovery.HELD])

    def test_it_is_blank_until_the_library_is_counted(self) -> None:
        row = _row(_entry(releases={"tableFiles": [_release("t1", held=True)]}), counted=False)

        self.assertEqual("", row[discovery.HELD])

    def test_rows_of_reads_what_the_launchers_play(self) -> None:
        library = mock.Mock(spec=Library)
        found = {"counted": "x", "rows": [
            _entry("g1", releases={"tableFiles": [_release("t1", fmt="FP")]})]}
        with mock.patch.object(discovery, "kept_listings", return_value=None), \
                mock.patch.object(discovery.discovery_marks, "read", return_value=None), \
                mock.patch.object(discovery.launchers, "get_launcher_store"), \
                mock.patch.object(discovery.launchers, "playable_formats",
                                  return_value=("VPX",)):
            row = discovery.rows_of(library, found)[0]

        self.assertEqual("no", row[discovery.PLAYABLE])


class TheColumnsAreNoViewsOwn(unittest.TestCase):
    def test_both_are_columns_of_the_grid(self) -> None:
        fields = {one["field"] for one in discovery.COLUMNS}

        self.assertLessEqual({discovery.PLAYABLE, discovery.HELD}, fields)

    def test_no_built_in_view_shows_either(self) -> None:
        for name, preset in discovery.VIEWS.items():
            with self.subTest(name):
                assert not isinstance(preset, list)
                self.assertFalse(set(preset.columns) & {discovery.PLAYABLE, discovery.HELD})

    def test_a_view_opened_on_them_shows_what_it_filters(self) -> None:
        fields = [one["field"] for one in discovery.COLUMNS]
        start = views.builtins(discovery.VIEWS)[0]

        view = views.opened(start, "Bally", {discovery.PLAYABLE: {"values": ["yes"]}}, fields)

        self.assertIn(discovery.PLAYABLE, view.columns)
        self.assertNotIn(discovery.HELD, view.columns)

    def test_both_are_yes_or_no(self) -> None:
        for field in (discovery.PLAYABLE, discovery.HELD):
            with self.subTest(field):
                column = next(one for one in discovery.COLUMNS if one["field"] == field)
                choices = column["filterParams"]["choices"]
                self.assertEqual(["yes", "no"], [one["value"] for one in choices])


class OpenInGridCarries(unittest.TestCase):
    def _filters(self, subject: dict[str, str], question: dict[str, Any], *,
                 counted: bool = True) -> dict[str, Any]:
        _tab, opening = discovery.opening_for(subject, question, _browse_columns(),
                                              counted=counted)
        return opening["filters"]

    def test_playable_tables_set_the_playable_column(self) -> None:
        filters = self._filters(BALLY, {"maker": "Bally", "kind": "tableFiles",
                                        "format": ["VPX"]})

        self.assertEqual({"values": ["yes"]}, filters[discovery.PLAYABLE])

    def test_a_theme_page_carries_it_too(self) -> None:
        filters = self._filters(SPACE, {"theme": "Space", "kind": "tableFiles",
                                        "format": ["VPX"]})

        self.assertEqual({"values": ["yes"]}, filters[discovery.PLAYABLE])

    def test_no_format_asked_leaves_the_column_alone(self) -> None:
        filters = self._filters(BALLY, {"maker": "Bally", "kind": "tableFiles"})

        self.assertNotIn(discovery.PLAYABLE, filters)

    def test_playable_does_not_wait_for_a_count(self) -> None:
        filters = self._filters(BALLY, {"maker": "Bally", "kind": "tableFiles",
                                        "format": ["VPX"]}, counted=False)

        self.assertEqual({"manufacturer": {"values": ["Bally"]},
                          discovery.PLAYABLE: {"values": ["yes"]}}, filters)

    def test_without_on_every_kind_is_in_library_and_not_held(self) -> None:
        filters = self._filters(BALLY, {"maker": "Bally", "owned": "yes", "held": "missing"})

        self.assertEqual({"manufacturer": {"values": ["Bally"]},
                          "in_library": {"values": ["yes"]},
                          discovery.HELD: {"values": ["no"]}}, filters)

    def test_without_on_a_kind_lists_that_kind_and_is_not_held(self) -> None:
        filters = self._filters(BALLY, {"maker": "Bally", "kind": "b2sFiles", "owned": "yes",
                                        "held": "missing"})

        self.assertEqual({"values": ["have", "missing"]}, filters["kind_backglass"])
        self.assertEqual({"values": ["no"]}, filters[discovery.HELD])

    def test_without_waits_for_a_count(self) -> None:
        filters = self._filters(BALLY, {"maker": "Bally", "owned": "yes", "held": "missing"},
                                counted=False)

        self.assertEqual({"manufacturer": {"values": ["Bally"]}}, filters)

    def test_the_filters_hold_the_games_the_page_lists(self) -> None:
        held = _entry("g1", releases={"tableFiles": [_release("t1", held=True)]})
        lacking = _entry("g2", releases={"tableFiles": [_release("t2", fmt="FP")]})
        elsewhere = _entry("g3", in_library=False,
                           releases={"tableFiles": [_release("t3")]})
        found = {"counted": "x", "rows": [held, lacking, elsewhere]}
        built = discovery.rows(found, None, None, ("VPX",))

        without = self._filters(BALLY, {"maker": "Bally", "owned": "yes", "held": "missing"})
        playable = self._filters(BALLY, {"maker": "Bally", "kind": "tableFiles",
                                         "format": ["VPX"]})

        def kept(filters: dict[str, Any]) -> list[str]:
            return [row["id"] for row in built
                    if all(row[field] in model["values"] for field, model in filters.items()
                           if field in row and "values" in model and field != "manufacturer")]

        self.assertEqual(["g2"], kept(without))
        self.assertEqual(["g1", "g3"], kept(playable))


class PresetsWaitForACount(unittest.TestCase):
    def test_missing_games_is_unfiltered_until_the_library_is_counted(self) -> None:
        preset = discovery.presets_for(counted=False)["manager.view.missing_games"]

        assert isinstance(preset, views.Preset)
        self.assertEqual({}, preset.filters)

    def test_it_keeps_its_columns_and_its_sort(self) -> None:
        was = discovery.VIEWS["manager.view.missing_games"]
        now = discovery.presets_for(counted=False)["manager.view.missing_games"]

        assert isinstance(was, views.Preset) and isinstance(now, views.Preset)
        self.assertEqual((was.columns, was.sort, was.help), (now.columns, now.sort, now.help))

    def test_once_counted_it_filters_as_before(self) -> None:
        preset = discovery.presets_for(counted=True)["manager.view.missing_games"]

        assert isinstance(preset, views.Preset)
        self.assertEqual({"in_library": {"values": ["yes"]}, "gap": {"values": ["missing"]}},
                         preset.filters)

    def test_the_built_in_itself_is_not_changed(self) -> None:
        discovery.presets_for(counted=False)

        preset = discovery.VIEWS["manager.view.missing_games"]
        assert isinstance(preset, views.Preset)
        self.assertTrue(preset.filters)

    def test_no_preset_filters_on_a_blank_column_once_the_guard_has_run(self) -> None:
        for name, preset in discovery.presets_for(counted=False).items():
            with self.subTest(name):
                assert not isinstance(preset, list)
                self.assertFalse(set(preset.filters) & discovery._COUNTED_FIELDS)


class _StopError(Exception):
    pass


class BrowseOpensOnTheGuardedPresets(unittest.IsolatedAsyncioTestCase):
    """What `_fill` hands the view control, which is where an empty first screen came from."""

    async def _handed(self, counted: bool) -> dict[str, Any]:
        client = mock.Mock()
        client.library_policy.return_value = {"hidden_asset_kinds": [], "hidden_media_kinds": []}
        client.discovery_marks.return_value = []
        client.preferences.return_value = {}
        library = Library(client)
        found = {"counted": "x" if counted else "", "people": [], "rows": [_entry()]}
        seen: dict[str, Any] = {}

        def view_control(_library: Any, _scope: str, presets: Any, *_more: Any,
                         **_kwargs: Any) -> Any:
            seen["presets"] = presets
            raise _StopError

        async def inline(call: Any, *args: Any, **more: Any) -> Any:
            return call(*args, **more)

        with _PAGE:
            body = ui.column()
        with mock.patch("manager.library.games.view_control", view_control), \
                mock.patch.object(discovery.run, "io_bound", inline), \
                mock.patch.object(discovery, "_read", mock.AsyncMock(return_value=found)), \
                mock.patch.object(discovery.discovery_marks, "refresh", mock.AsyncMock()), \
                mock.patch.object(discovery.launchers, "get_launcher_store"), \
                mock.patch.object(discovery.deeplink, "sync"):
            with self.assertRaises(_StopError):
                await discovery._fill(library, body, {}, mock.AsyncMock(), mock.Mock())
        return seen["presets"]

    async def test_before_a_count_missing_games_opens_unfiltered(self) -> None:
        preset = (await self._handed(counted=False))["manager.view.missing_games"]

        self.assertEqual({}, preset.filters)

    async def test_after_a_count_it_opens_filtered(self) -> None:
        preset = (await self._handed(counted=True))["manager.view.missing_games"]

        self.assertEqual({"in_library", "gap"}, set(preset.filters))


if __name__ == "__main__":
    unittest.main()
