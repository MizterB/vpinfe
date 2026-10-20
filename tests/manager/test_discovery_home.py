"""Discovery's front page: which tab opens, which window is remembered, what a tile says,
and the page drawn and driven the way the Manager draws it."""

from __future__ import annotations

import asyncio
import unittest
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from unittest import mock
from unittest.mock import patch

from nicegui import core, run, ui

from common.online import vps_home
from manager.kit import dropdown, views
from manager.kit.data import Library
from manager.library import discovery, discovery_ask, discovery_releases, games
from manager.library import discovery_home as home
from manager.overview import needs

# Made at import, outside any task, where NiceGUI still hands out the script's own page.
_PAGE = ui.element()


class TabTests(unittest.TestCase):
    def test_home_is_the_front_page(self) -> None:
        self.assertEqual(discovery.tab_of({}), discovery.HOME)

    def test_an_address_naming_a_subject_or_a_game_opens_browse(self) -> None:
        self.assertEqual(discovery.tab_of({"subject": {"type": "author", "name": "A"}}),
                         discovery.BROWSE)
        self.assertEqual(discovery.tab_of({"entry": "g1"}), discovery.BROWSE)

    def test_the_tab_chosen_wins_over_a_game_in_the_address(self) -> None:
        self.assertEqual(discovery.tab_of({"discovery_tab": discovery.HOME, "entry": "g1"}),
                         discovery.HOME)
        self.assertEqual(discovery.tab_of({"discovery_tab": discovery.RELEASES}),
                         discovery.RELEASES)

    def test_a_tab_that_is_not_one_falls_back_to_the_front_page(self) -> None:
        self.assertEqual(discovery.tab_of({"discovery_tab": "games"}), discovery.HOME)

    def test_a_shelf_opens_the_grid_on_the_tab_it_names(self) -> None:
        state: dict[str, Any] = {"discovery_tab": discovery.HOME}
        opening = {"name": "New in the Past Week", "filters": {}}
        with patch.object(discovery.deeplink, "sync"):
            discovery.open_page(state, [], lambda: None, None, opening=opening,
                                tab=discovery.RELEASES)

        self.assertEqual(discovery.tab_of(state), discovery.RELEASES)
        self.assertEqual(discovery_ask.opening_on(state, discovery.RELEASES),
                         {**opening, "tab": discovery.RELEASES})
        self.assertIsNone(discovery_ask.opening_on(state, discovery.BROWSE))


class WindowTests(unittest.TestCase):
    def test_the_windows_are_a_week_two_and_a_month(self) -> None:
        self.assertEqual(sorted(home.WINDOWS), [7, 14, 30])

    def test_an_unknown_window_is_a_week(self) -> None:
        self.assertEqual(home.window_days(14), 14)
        self.assertEqual(home.window_days(365), 7)
        self.assertEqual(home.window_days(None), 7)

    def test_the_window_remembered_is_the_one_read_back(self) -> None:
        with patch.object(home.remembered, "get", return_value=30):
            self.assertEqual(home.remembered_days(), 30)
        with patch.object(home.remembered, "get", return_value=None):
            self.assertEqual(home.remembered_days(), 7)


class SeeAllTests(unittest.TestCase):
    def test_the_window_of_a_shelf_is_the_added_filter_on_releases(self) -> None:
        filters = discovery_releases.arrival_filters({"since": 14}, counted=True)

        self.assertEqual(filters, {"added": {"days": 14}})

    def test_the_kind_and_the_library_are_asked_beside_the_window(self) -> None:
        filters = discovery_releases.arrival_filters(
            {"since": 7, "kind": "b2sFiles", "owned": "yes"}, counted=True)

        self.assertEqual(filters, {"added": {"days": 7}, "kind": {"values": ["b2sFiles"]},
                                   "in_library": {"values": ["yes"]}})

    def test_in_library_is_left_out_before_the_library_is_counted(self) -> None:
        filters = discovery_releases.arrival_filters({"since": 7, "owned": "yes"},
                                                     counted=False)

        self.assertEqual(filters, {"added": {"days": 7}})


class TileTests(unittest.TestCase):
    def test_a_re_dated_release_says_what_it_was(self) -> None:
        self.assertEqual(home.version_line({"version": "1.0.8", "was": "1.0.7"}),
                         "1.0.8, was 1.0.7")

    def test_a_release_that_never_changed_says_only_its_version(self) -> None:
        self.assertEqual(home.version_line({"version": "1.0.8", "was": ""}), "1.0.8")

    def test_a_release_with_no_version_says_nothing(self) -> None:
        self.assertEqual(home.version_line({"version": "", "was": "1.0"}), "")


class ViewCountTests(unittest.TestCase):
    ROWS = [{"in_library": "yes", "gap": "missing"}, {"in_library": "yes", "gap": ""},
            {"in_library": "no", "gap": ""}]

    def test_a_view_of_plain_value_lists_is_counted(self) -> None:
        one = views.View(id="v", name="Gaps", filters={
            "in_library": {"values": ["yes"]}, "gap": {"values": ["missing"]}})

        self.assertEqual(home.view_count(one, self.ROWS, compared=True), 1)

    def test_a_filter_it_cannot_read_leaves_the_count_out(self) -> None:
        one = views.View(id="v", name="Text", filters={"name": {"type": "contains"}})

        self.assertIsNone(home.view_count(one, self.ROWS, compared=True))

    def test_a_filtered_view_has_no_count_before_the_library_is_compared(self) -> None:
        one = views.View(id="v", name="Gaps", filters={"gap": {"values": ["missing"]}})
        everything = views.View(id="w", name="All", filters={})

        self.assertIsNone(home.view_count(one, self.ROWS, compared=False))
        self.assertEqual(home.view_count(everything, self.ROWS, compared=False), 3)


class ListCellTests(unittest.TestCase):
    def test_a_list_column_counts_a_row_that_holds_any_value_picked(self) -> None:
        rows: list[dict[str, Any]] = [
            {"themes": ["Space", "Horror"]}, {"themes": ["Sports"]}, {"themes": []}]
        one = views.View(id="v", name="Space", filters={"themes": {"values": ["Space"]}})

        self.assertEqual(home.view_count(one, rows, compared=True), 1)

    def test_a_row_matching_any_of_several_values_is_counted_once(self) -> None:
        rows: list[dict[str, Any]] = [{"themes": ["Space", "Horror"]}, {"themes": ["Sports"]}]
        one = views.View(id="v", name="Two", filters={
            "themes": {"values": ["Space", "Horror", "Sports"]}})

        self.assertEqual(home.view_count(one, rows, compared=True), 2)


def _day(ago: int) -> str:
    return (datetime.now(UTC) - timedelta(days=ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _release(rid: str, ago: int, **more: Any) -> dict[str, Any]:
    return {"id": rid, "by": [0], "added": _day(ago), "held": False, "mod": False,
            "version": "", **more}


PEOPLE = [{"name": "Alpha", "aliases": [], "releases": 4}]
FOUND: dict[str, Any] = {"counted": "2026-10-01T10:00:00Z", "people": PEOPLE, "rows": [
    {"vps_id": "g1", "name": "Alien", "in_library": True, "img_url": "", "manufacturer": "",
     "year": None, "type": "", "themes": ["Space"], "url": "",
     "listed": ["tableFiles", "b2sFiles", "romFiles"], "held": ["tableFiles"],
     "releases": {
         "tableFiles": [_release("t1", 0, held=True, version="1.2")],
         "b2sFiles": [_release("b1", 3)],
         "romFiles": [_release("r1", 0)],
         "ruleFiles": [_release("x1", 0)]}},
    {"vps_id": "g2", "name": "Batman", "in_library": False, "img_url": "", "manufacturer": "",
     "year": None, "type": "", "themes": [], "url": "", "listed": ["tableFiles"], "held": [],
     "releases": {"tableFiles": [_release("t2", 2, mod=True), _release("t9", 20)]}},
]}
KEPT = ["tableFiles", "b2sFiles", "romFiles", "ruleFiles"]


def _words(body: ui.element) -> list[str]:
    return [str(one.text) for one in body.descendants()
            if isinstance(one, ui.label) and not one.is_deleted]


def _options(toggle: ui.toggle) -> list[str]:
    return [str(label) for label in cast(dict[Any, Any], toggle.options).values()]


def _labels(body: ui.element) -> list[str]:
    return [label for one in body.descendants()
            if isinstance(one, ui.toggle) and not one.is_deleted for label in _options(one)]


async def _settle() -> None:
    for _ in range(8):
        await asyncio.sleep(0)


class SeeAllCountsTests(unittest.TestCase):
    """The number on a chip is the number of rows See All opens."""

    @staticmethod
    def _opened(filters: dict[str, Any], days: int) -> int:
        cutoff = vps_home.since(days)
        values = filters["kind"]["values"]
        owned = filters.get("in_library", {}).get("values") == ["yes"]
        return sum(1 for row in FOUND["rows"]
                   for listing, releases in row["releases"].items() if listing in values
                   for one in releases
                   if one["added"] >= cutoff and (row["in_library"] or not owned))

    def test_every_chip_opens_as_many_releases_as_it_counts(self) -> None:
        with mock.patch.object(vps_home.arrivals, "was", return_value=""):
            shelf = vps_home.home(FOUND, KEPT, 30)["new"]
        for chip in (vps_home.ALL, vps_home.YOURS, "tableFiles", "b2sFiles"):
            with self.subTest(chip=chip):
                filters = home.new_filters(30, chip, KEPT, counted=True)

                self.assertEqual(self._opened(filters, 30), shelf[chip]["count"])

    def test_rule_sheets_are_left_out_of_all_as_the_shelf_leaves_them_out(self) -> None:
        filters = home.new_filters(7, vps_home.ALL, KEPT, counted=True)

        self.assertNotIn("ruleFiles", filters["kind"]["values"])
        self.assertEqual(filters["added"], {"days": 7})

    def test_a_chip_for_a_kind_opens_that_kind_alone(self) -> None:
        filters = home.new_filters(14, "b2sFiles", KEPT, counted=True)

        self.assertEqual(filters["kind"], {"values": ["b2sFiles"]})

    def test_your_games_asks_for_the_library_once_it_is_counted(self) -> None:
        self.assertEqual(home.new_filters(7, vps_home.YOURS, KEPT, counted=True)["in_library"],
                         {"values": ["yes"]})
        self.assertNotIn("in_library",
                         home.new_filters(7, vps_home.YOURS, KEPT, counted=False))


def _offered(game_id: str, vps_id: str, name: str) -> dict:
    return {"game_id": game_id, "vps_id": vps_id, "name": name, "available": 1}


class DrivenHome(unittest.IsolatedAsyncioTestCase):
    """Home drawn by `_fill_home`, through the Library and a client that answers."""

    def setUp(self) -> None:
        self.prefs: dict[str, dict[str, Any]] = {}
        self.writes: list[tuple[str, dict[str, Any]]] = []
        self.client = mock.Mock()
        self.client.library_policy.return_value = {"hidden_asset_kinds": [],
                                                   "hidden_media_kinds": []}
        self.client.catalog_discovery.return_value = FOUND
        self.client.preferences.side_effect = lambda scope: self.prefs.get(scope, {})
        self.client.put_preferences.side_effect = \
            lambda scope, value: self.writes.append((scope, value))
        self.client.discovery_home.side_effect = self._answer
        self.library = Library(self.client)
        self.library.load_kept_kinds()
        self.state: dict[str, Any] = {}
        self.rerender = mock.Mock()
        self.selected: list[Any] = []
        self.io: list[str] = []
        self.remembered: list[int] = []
        self.pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self.slow = False
        self.unreadable = False
        self.media: dict[str, list[dict]] = {}

        async def inline(call: Any, *args: Any, **more: Any) -> Any:
            self.io.append(getattr(call, "__name__", str(call)))
            return call(*args, **more)

        for patcher in (
                mock.patch.object(run, "io_bound", inline),
                mock.patch.object(vps_home.arrivals, "was",
                                  side_effect=lambda _s, item: "1.0" if item == "t1" else ""),
                mock.patch.object(home.remembered, "get", return_value=None),
                mock.patch.object(home.remembered, "put",
                                  side_effect=lambda _k, days: self.remembered.append(days)),
                mock.patch.object(discovery.deeplink, "sync")):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _answer(self, days: int) -> dict[str, Any]:
        if self.unreadable and days != 7:
            raise RuntimeError("no answer")
        holders = {row["vps_id"]: [f"game-{row['vps_id']}"] for row in FOUND["rows"]}
        return vps_home.home(FOUND, KEPT, days, media=self.media, holders=holders)

    async def asyncSetUp(self) -> None:
        was = core.loop
        core.loop = asyncio.get_running_loop()
        self.addCleanup(setattr, core, "loop", was)

    async def _select(self, row: Any) -> None:
        self.selected.append(row)
        self.state["entry"] = row["id"]

    async def _draw(self) -> ui.element:
        spied: dict[str, Any] = {}
        real = home.fill

        def spy(*args: Any, **more: Any) -> None:
            spied.update(more)
            real(*args, **more)

        self.spied = spied
        with _PAGE:
            body = ui.column()
            with mock.patch.object(home, "fill", spy):
                await discovery._fill_home(self.library, body, self.state, self._select,
                                           self.rerender)
        await _settle()
        return body

    async def test_every_shelf_is_drawn_from_one_read(self) -> None:
        body = await self._draw()

        words = _words(body)
        self.client.discovery_home.assert_called_once_with(7)
        for word in ("New In", "Alien", "Batman", "Missing from Your Games",
                     "Authors You Collect", "Your Views"):
            self.assertIn(word, words)
        self.assertEqual([one for one in _labels(body) if one.startswith(("All", "Your"))],
                         ["All 4", "Your Games 3"])

    async def test_a_re_dated_release_says_what_it_was(self) -> None:
        self.assertIn("1.2, was 1.0", _words(await self._draw()))

    async def test_the_saved_views_are_read_before_they_are_listed(self) -> None:
        self.prefs["discovery.views"] = {"views": [
            views.to_record(views.View(id="v1", name="Mine"))], "active": ""}

        body = await self._draw()

        self.assertIn("discovery.views", [c.args[0] for c in self.client.preferences.mock_calls])
        self.assertIn("Mine", _words(body))

    async def test_a_view_chosen_is_written_off_the_loop_with_the_views_kept(self) -> None:
        self.prefs["discovery.views"] = {"views": [
            views.to_record(views.View(id="v1", name="Mine"))], "active": ""}
        await self._draw()

        with _PAGE:
            await self.spied["open_view"]("v1")

        scope, value = self.writes[-1]
        self.assertEqual((scope, value["active"], [one["id"] for one in value["views"]]),
                         ("discovery.views", "v1", ["v1"]))
        self.assertIn("remember", self.io)
        self.assertEqual(self.state["discovery_tab"], discovery.BROWSE)
        self.rerender.assert_called()

    async def test_the_counts_on_your_views_follow_the_catalog(self) -> None:
        self.prefs["discovery.views"] = {"views": [views.to_record(views.View(
            id="v1", name="Space", filters={"themes": {"values": ["Space"]}}))], "active": ""}

        body = await self._draw()

        self.assertIn("1 game", _words(body))

    async def test_search_finds_a_game_once_the_catalog_has_loaded(self) -> None:
        await self._draw()

        people, rows = await self.spied["catalog"]()

        self.assertEqual([one["id"] for one in rows], ["g1", "g2"])
        self.assertEqual([one["name"] for one in people], ["Alpha"])

    async def test_a_game_opened_from_home_leaves_home_where_it_is(self) -> None:
        """The pane opening sets the entry; a redraw after it, such as Add to Library or a
        comparison ending, is still Home."""
        with _PAGE, mock.patch.object(discovery.busy, "fill") as filled:
            discovery.build(self.library, self.state, self._select, self.rerender)
        self.assertEqual(self.state["discovery_tab"], discovery.HOME)

        await self._select({"id": "g1"})
        with _PAGE:
            await filled.call_args.args[1]()
        await _settle()
        with _PAGE:
            await self.state["redraw_discovery"]()

        self.assertEqual(discovery.tab_of(self.state), discovery.HOME)

    async def test_an_address_that_names_a_game_opens_browse(self) -> None:
        self.state["entry"] = "g1"
        with _PAGE, mock.patch.object(discovery.busy, "fill"):
            discovery.build(self.library, self.state, self._select, self.rerender)

        self.assertEqual(self.state["discovery_tab"], discovery.BROWSE)

    async def test_see_all_on_new_opens_releases_with_the_filters_the_shelf_counts(self) -> None:
        await self._draw()

        self.spied["see_new"](7, vps_home.YOURS)

        opening = discovery_ask.opening_on(self.state, discovery.RELEASES)
        assert opening is not None
        self.assertEqual(opening["name"], "New in the Past Week")
        self.assertEqual(opening["filters"], home.new_filters(
            7, vps_home.YOURS, discovery.kept_listings(self.library), counted=True))
        self.assertEqual(discovery.tab_of(self.state), discovery.RELEASES)

    async def test_see_all_on_missing_opens_games_on_every_game_the_tab_counts(self) -> None:
        self.media = {"backglass": [_offered("i9", "zz", "Zed")]}
        await self._draw()
        tab = vps_home.home(FOUND, KEPT, 7, media=self.media, holders={
            row["vps_id"]: [f"game-{row['vps_id']}"] for row in FOUND["rows"]},
        )["missing"]["b2sFiles"]
        opened: list[needs.Opens] = []

        async def open_on(opens: needs.Opens) -> None:
            opened.append(opens)

        self.state["open_on"] = open_on
        await self.spied["see_missing"](tab["game_ids"])

        [opens] = opened
        ids = opens.keys[games.LACKING_KEY]
        self.assertEqual(("games", tab["count"]), (opens.view, len(ids)))
        library = [{"id": one} for one in ("i9", "game-g1", "game-g2", "other")]
        shown = [row for row in games.stamp_lacking(library, ids) if row[games.LACKING_COLUMN]]
        self.assertEqual(tab["count"], len(shown))

    async def test_a_gap_a_source_can_fill_is_a_tab_with_its_own_see_all(self) -> None:
        self.media = {"playfield": [_offered("i1", "g1", "Alien")]}
        body = await self._draw()
        self.assertIn("Playfields 1", _labels(body))
        toggle = next(one for one in body.descendants() if isinstance(one, ui.toggle)
                      and "Playfields 1" in _options(one))
        self.assertEqual(self._see_alls(body), 2)

        toggle.set_value("playfield")
        await _settle()

        self.assertEqual(self._see_alls(body), 2)
        self.assertIn("Alien", _words(body))
        self.assertIn("1 from a source", _words(body))
        self.assertNotIn("1 on VPS", _words(body))

    async def test_a_kind_is_one_tab_whichever_way_it_is_known(self) -> None:
        self.media = {"backglass": [_offered("i9", "zz", "Zed")]}
        body = await self._draw()
        toggle = next(one for one in body.descendants() if isinstance(one, ui.toggle)
                      and "Backglasses 2" in _options(one))

        self.assertEqual(sum(1 for text in _labels(body) if text.startswith("Backglass")), 2)
        self.assertEqual(sum(1 for opt in _options(toggle) if opt.startswith("Backglass")), 1)
        self.assertNotIn("backglass", toggle.options)
        self.assertEqual(self._see_alls(body), 2)
        self.assertIn("Zed", _words(body))
        self.assertIn("1 from a source", _words(body))
        self.assertIn("1 on VPS", _words(body))

    async def test_the_two_playfield_videos_keep_a_tab_each_under_their_own_name(self) -> None:
        self.media = {"playfield_fss": [_offered("i1", "g1", "Alien")],
                      "playfield_video": [_offered("i2", "g1", "Alien")]}
        body = await self._draw()
        toggle = next(one for one in body.descendants() if isinstance(one, ui.toggle)
                      and "Full-Screen Playfield 1" in _options(one))

        self.assertIn("Playfield Video 1", _options(toggle))

    async def test_every_game_a_source_can_fill_is_drawn_on_its_tab(self) -> None:
        self.media = {"wheel": [_offered(f"i{n}", f"v{n}", f"Game {n:02d}")
                                for n in range(vps_home.GAPS_SHOWN * 5)]}
        body = await self._draw()
        toggle = next(one for one in body.descendants() if isinstance(one, ui.toggle)
                      and f"Wheels {len(self.media['wheel'])}" in _options(one))

        toggle.set_value("wheelArtFiles")
        await _settle()

        names = _words(body)
        self.assertTrue(all(f"Game {n:02d}" in names for n in range(len(self.media["wheel"]))))

    @staticmethod
    def _see_alls(body: ui.element) -> int:
        return sum(1 for one in body.descendants() if not one.is_deleted
                   and str(getattr(one, "text", "")) == "See All")

    def _picker(self, body: ui.element) -> dropdown.Select:
        return next(one for one in body.descendants() if isinstance(one, dropdown.Select))

    async def test_a_longer_window_is_remembered_once_it_has_answered(self) -> None:
        body = await self._draw()
        picker = self._picker(body)

        picker.set_value(30)
        await _settle()

        self.assertEqual(self.remembered, [30])
        self.assertIn("All 5", _labels(body))
        self.assertIs(picker, self._picker(body))
        self.assertFalse(picker.is_deleted)

    async def test_a_window_that_cannot_be_read_leaves_the_shelf_and_the_window(self) -> None:
        body = await self._draw()
        picker = self._picker(body)
        self.unreadable = True

        with mock.patch.object(ui, "notify") as notified:
            picker.set_value(30)
            await _settle()

        self.assertEqual((self.remembered, picker.value), ([], 7))
        self.assertIn("All 4", _labels(body))
        notified.assert_called_once()

    async def test_an_answer_that_arrives_after_a_later_pick_is_dropped(self) -> None:
        await self._draw()
        gates: dict[int, asyncio.Future[None]] = {14: asyncio.Future(), 30: asyncio.Future()}

        async def reread(days: int) -> dict[str, Any]:
            await gates[days]
            return vps_home.home(FOUND, KEPT, days)

        # Drive the shelf's own picker with answers released out of order.
        with _PAGE:
            body2 = ui.column()
            home.fill(body2, vps_home.home(FOUND, KEPT, 7), library=self.library,
                      scope="discovery", view_presets={}, catalog=self.spied["catalog"],
                      reread=reread, on_select=self._select, see_new=mock.Mock(),
                      see_missing=mock.Mock(), open_view=mock.Mock(),
                      open_subject=mock.Mock())
        picker = self._picker(body2)
        picker.set_value(14)
        await _settle()
        picker.set_value(30)
        await _settle()
        gates[30].set_result(None)
        await _settle()
        gates[14].set_result(None)
        await _settle()

        self.assertEqual(self.remembered, [30])
        self.assertEqual(picker.value, 30)
        self.assertIn("All 5", _labels(body2))

    async def test_a_chip_narrows_the_tiles_to_its_kind(self) -> None:
        body = await self._draw()
        toggle = next(one for one in body.descendants() if isinstance(one, ui.toggle)
                      and "All 4" in _options(one))
        self.assertIn("Batman", _words(body))

        toggle.set_value("b2sFiles")
        await _settle()

        self.assertNotIn("Batman", _words(body))
        self.assertIn("Alien", _words(body))


if __name__ == "__main__":
    unittest.main()
