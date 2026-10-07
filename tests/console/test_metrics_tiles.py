"""Metrics draws one tile per reading, and titles a volume by what it holds."""

from __future__ import annotations

import unittest
from typing import Any

from nicegui import ui

from common import i18n
from common.host import tools
from console import metrics
from httpapi import metrics as wire

_GB = 1024 ** 3


def t(key: str, **params: Any) -> str:
    return i18n.t(key, **params)


def _titles(body: ui.element) -> list[str]:
    return [one.text for one in body.descendants()
            if isinstance(one, ui.label) and "console-card-title" in one.classes]


def _names(body: ui.element) -> list[str]:
    return [one.text for one in body.descendants()
            if isinstance(one, ui.label) and "text-sm" in one.classes]


def _values(body: ui.element) -> list[str]:
    return [one.text for one in body.descendants()
            if isinstance(one, ui.label) and "console-kpi" in one.classes]


def _tiles(body: ui.element) -> list[int]:
    return [one.id for one in body.descendants() if "console-card" in one.classes]


def _bars(body: ui.element) -> int:
    return len([one for one in body.descendants() if one._style.get("flex")])


def _card(**more: Any) -> dict[str, Any]:
    return {"id": "0000:01:00.0", "name": "RTX 3060", "source": "nvidia-smi", **more}


def _empty() -> ui.element:
    with ui.column() as target:
        pass
    return target


def _pair() -> tuple[ui.element, dict[str, Any]]:
    return _empty(), {}


class CardLinesTests(unittest.TestCase):
    def test_a_card_that_has_everything_reads_in_two_lines(self) -> None:
        used = int(9.4 * _GB)
        card = _card(busy=40, memory_used=used, memory_total=12 * _GB,
                     temperature=71, power=142, clock=1830, fan_percent=54)

        first, second = metrics._card_lines(card)

        self.assertEqual(
            t("console.metrics.card.memory",
              value=t("console.metrics.usage", used=i18n.size(used),
                      total=i18n.size(12 * _GB))) + ", 71°C", first)
        self.assertEqual("142 W, 1830 MHz, " + t("console.metrics.card.fan", value="54%"),
                         second)

    def test_memory_with_no_total_is_in_use(self) -> None:
        first, second = metrics._card_lines(_card(memory_used=3 * _GB))

        self.assertEqual(t("console.metrics.card.shared_memory", used=i18n.size(3 * _GB)), first)
        self.assertEqual("", second)

    def test_a_reading_the_source_lacks_is_not_listed(self) -> None:
        self.assertEqual(("", ""), metrics._card_lines(_card(busy=10)))
        self.assertEqual(("", "1830 MHz"), metrics._card_lines(_card(clock=1830)))

    def test_a_fan_in_revolutions_is_worded_as_one(self) -> None:
        self.assertEqual(("", t("console.metrics.card.fan", value="1200 rpm")),
                         metrics._card_lines(_card(fan_rpm=1200)))


class CardTileTests(unittest.TestCase):
    def test_each_card_is_a_tile_with_its_name_and_its_busy(self) -> None:
        target = _empty()
        graphics = {"cards": [_card(busy=40), _card(id="b", name="RX 580", busy=7)]}

        metrics._draw_cards(target, graphics, [], {})

        graphics = t("console.metrics.graphics")
        self.assertEqual([graphics, graphics], _titles(target))
        self.assertEqual(["RTX 3060", "RX 580"], _names(target))
        self.assertEqual(["40%", "7%"], _values(target))
        self.assertEqual([t("console.metrics.busy")] * 2,
                         [one.text for one in target.descendants()
                          if isinstance(one, ui.label) and "text-xs" in one.classes
                          and one.text == t("console.metrics.busy")])

    def test_a_card_with_no_busy_reading_shows_a_dash(self) -> None:
        target = _empty()

        metrics._draw_cards(target, {"cards": [_card(temperature=60)]}, [], {})

        self.assertEqual(["-"], _values(target))

    def test_the_same_cards_move_their_numbers_rather_than_being_drawn_again(self) -> None:
        target, held = _pair()
        metrics._draw_cards(target, {"cards": [_card(busy=40)]}, [], held)
        before = _tiles(target)

        metrics._draw_cards(target, {"cards": [_card(busy=65)]}, [], held)

        self.assertEqual(before, _tiles(target))
        self.assertEqual(["65%"], _values(target))

    def test_a_card_is_drawn_from_its_own_series_in_the_history(self) -> None:
        target = _empty()
        history = [{"gpus": {"0000:01:00.0": 20}}, {"gpus": {"0000:01:00.0": 30}},
                   {"gpus": {"other": 90}}, {}]

        metrics._draw_cards(target, {"cards": [_card(busy=30)]}, history, {})

        self.assertEqual(2, _bars(target))

    def test_a_card_nothing_reads_says_why_in_place_of_numbers(self) -> None:
        target = _empty()

        metrics._draw_cards(target, {"cards": [_card(reason="Not readable")]}, [], {})

        self.assertEqual([t("console.metrics.graphics")], _titles(target))
        self.assertEqual(["RTX 3060"], _names(target))
        self.assertEqual(["-"], _values(target))
        self.assertIn("Not readable", [one.text for one in target.descendants()
                                       if isinstance(one, ui.label)])

    def test_a_card_missing_its_tool_links_the_settings_row_that_fixes_it(self) -> None:
        target = _empty()
        card = _card(reason="nvtop is not installed", tool="nvtop")

        metrics._draw_cards(target, {"cards": [card]}, [], {})

        links = [one for one in target.descendants() if isinstance(one, ui.link)]
        self.assertEqual([one.text for one in links], [tools.hint(tools.NVTOP)])
        self.assertIn("page=vpinfe.tools", links[0].props["href"])

    def test_a_reason_with_no_tool_to_fix_it_links_nothing(self) -> None:
        target = _empty()

        metrics._draw_cards(target, {"cards": [_card(reason="Not readable")]}, [], {})

        self.assertEqual([], [one for one in target.descendants() if isinstance(one, ui.link)])

    def test_no_card_at_all_is_one_graphics_tile_with_the_reason(self) -> None:
        target = _empty()

        metrics._draw_cards(target, {"cards": [], "reason": "No card found"}, [], {})

        self.assertEqual([t("console.metrics.graphics")], _titles(target))
        self.assertIn("No card found", [one.text for one in target.descendants()
                                        if isinstance(one, ui.label)])

    def test_the_tooltip_names_what_read_the_card(self) -> None:
        target = _empty()

        metrics._draw_cards(target, {"cards": [_card(busy=1)]}, [], {})

        tips = [one.text for one in target.descendants() if isinstance(one, ui.tooltip)]
        self.assertEqual(["RTX 3060\n" + t("console.metrics.card.source", source="nvidia-smi")],
                         tips)


    def test_a_card_that_is_named_again_is_drawn_again(self) -> None:
        target, held = _pair()
        metrics._draw_cards(target, {"cards": [_card(busy=1)]}, [], held)

        metrics._draw_cards(target, {"cards": [_card(busy=1, name="RTX 4070")]}, [], held)

        self.assertEqual(["RTX 4070"], _names(target))


def _disk(**more: Any) -> dict[str, Any]:
    return {"path": "/lib", "also": [], "percent": 40.0, "free": 6 * _GB,
            "holds": [{"role": "library", "name": "x/lib"}], **more}


def _sayings(body: ui.element) -> list[str]:
    return [one.text for one in body.descendants() if isinstance(one, ui.label)]


class VolumeTileTests(unittest.TestCase):
    def test_a_volume_says_how_full_and_how_much_is_free(self) -> None:
        target = _empty()

        metrics._draw_disks(target, [_disk()], {})

        self.assertIn(t("console.metrics.full_free", value=40.0, free=i18n.size(6 * _GB)),
                      _sayings(target))

    def test_a_volume_that_cannot_be_read_says_so(self) -> None:
        target = _empty()

        metrics._draw_disks(target, [_disk(error="gone", percent=None, free=None)], {})

        self.assertIn(t("console.metrics.cannot_read"), _sayings(target))

    def test_a_volume_with_no_free_figure_shows_a_dash_for_it(self) -> None:
        target = _empty()

        metrics._draw_disks(target, [_disk(free=None)], {})

        self.assertIn(t("console.metrics.full_free", value=40.0, free="-"), _sayings(target))

    def test_the_tooltip_lists_every_path_on_the_volume(self) -> None:
        target = _empty()

        metrics._draw_disks(target, [_disk(also=["/cfg"])], {})

        self.assertEqual(["/lib\n/cfg"],
                         [one.text for one in target.descendants() if isinstance(one, ui.tooltip)])

    def test_a_reading_that_moves_leaves_the_tiles_and_their_tooltips_standing(self) -> None:
        target, held = _pair()
        metrics._draw_disks(target, [_disk()], held)
        before = [one.id for one in target.descendants() if isinstance(one, ui.tooltip)]

        metrics._draw_disks(target, [_disk(percent=41.0, free=5 * _GB)], held)

        self.assertEqual(before, [one.id for one in target.descendants()
                                  if isinstance(one, ui.tooltip)])
        self.assertIn(t("console.metrics.full_free", value=41.0, free=i18n.size(5 * _GB)),
                      _sayings(target))

    def test_a_volume_that_gains_a_path_is_drawn_again(self) -> None:
        target, held = _pair()
        metrics._draw_disks(target, [_disk()], held)

        metrics._draw_disks(target, [_disk(also=["/cfg"])], held)

        self.assertEqual(["/lib\n/cfg"],
                         [one.text for one in target.descendants() if isinstance(one, ui.tooltip)])


class VolumeTitleTests(unittest.TestCase):
    def test_a_library_is_titled_library(self) -> None:
        disk = {"path": "/a", "holds": [{"role": "library", "name": "x/tables"}]}

        self.assertEqual(t("console.metrics.disk.library"), metrics._volume_title(disk, False))

    def test_among_several_a_library_is_named_by_its_folder(self) -> None:
        disk = {"path": "/a", "holds": [{"role": "library", "name": "x/tables"}]}

        self.assertEqual(t("console.metrics.disk.library_named", name="x/tables"),
                         metrics._volume_title(disk, True))

    def test_one_volume_holding_several_things_lists_each(self) -> None:
        disk = {"path": "/a", "holds": [{"role": "library", "name": "x/tables"},
                                        {"role": "config"}, {"role": "cache"}]}

        self.assertEqual(", ".join([t("console.metrics.disk.library"),
                                    t("console.metrics.disk.config"),
                                    t("console.metrics.disk.cache")]),
                         metrics._volume_title(disk, False))

    def test_two_libraries_on_one_volume_are_one_library_title(self) -> None:
        disk = {"path": "/a", "holds": [{"role": "library", "name": "x/tables"},
                                        {"role": "library", "name": "y/tables"}]}

        self.assertEqual(t("console.metrics.disk.library"), metrics._volume_title(disk, True))

    def test_a_volume_that_holds_nothing_known_is_its_path(self) -> None:
        self.assertEqual("/a", metrics._volume_title({"path": "/a"}, False))


class WireRolesTests(unittest.TestCase):
    def test_a_volume_carries_what_is_watched_on_it_by_any_of_its_paths(self) -> None:
        disks = [{"path": "/lib", "also": ["/cfg"]}, {"path": "/cache", "also": []}]
        watched = [("/lib", {"role": "library", "name": "a/lib"}), ("/cfg", {"role": "config"}),
                   ("/cache", {"role": "cache"})]

        found = wire._with_holds(disks, watched)

        self.assertEqual([[{"role": "library", "name": "a/lib"}, {"role": "config"}],
                          [{"role": "cache"}]], [one["holds"] for one in found])

    def test_the_shared_reading_is_not_written_to(self) -> None:
        disks: list[dict[str, Any]] = [{"path": "/lib", "also": []}]

        wire._with_holds(disks, [("/lib", {"role": "config"})])

        self.assertNotIn("holds", disks[0])


if __name__ == "__main__":
    unittest.main()
