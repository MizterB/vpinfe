"""Which files the source dialog offers and accepts: for media, an asset, a folder kind
and a collection's image."""

from __future__ import annotations

import asyncio
import mimetypes
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from nicegui import core, ui

from common import i18n, service_errors
from common.games.collections_service import IMAGE_EXTENSIONS
from common.media_specs import IMAGE_FAMILY
from console import mediasource
from console.data import Library
from tests.support import clicks

LIBRARY = SimpleNamespace(placements=None, displaced_by=None, place_media=None,
                          asset_placements=None, asset_displaced_by=None,
                          place_asset=None)


async def _nothing() -> None:
    return None


def _folder(kind: str) -> mediasource._Folder:
    return mediasource._Folder({"library": LIBRARY, "game_id": "game", "game": {}},
                               kind, kind, _nothing)


class WhatFits(unittest.TestCase):
    def test_a_folder_kind_takes_an_archive_or_a_file_of_any_kind_under_it(self) -> None:
        self.assertEqual([True, True, True, False],
                         [_folder("alt_color").fits({"name": name}) for name in
                          ("afm.cRZ", "afm.pal", "afm colors.ZIP", "afm.png")])

    def test_a_kind_known_only_by_its_folder_takes_only_an_archive(self) -> None:
        self.assertEqual([True, False],
                         [_folder("pup_pack").fits({"name": name}) for name in
                          ("afm pup.7z", "screen.mp4")])

    def test_a_file_picker_lists_only_what_it_takes_so_every_row_it_lists_fits(self) -> None:
        image = mediasource._Image(LIBRARY, "Favorites", "Image", _nothing)
        slot = mediasource._Slot({"library": LIBRARY, "game_id": "game", "game": {},
                                  "lens": "", "tables": []}, "pov", "Point of View",
                                 _nothing, mediasource._asset(LIBRARY, "pov"))
        self.assertEqual([True, True], [image.fits({"name": "any.png"}),
                                        slot.fits({"name": "any.pov"})])


class WhatThePickerOffers(unittest.TestCase):
    def test_an_asset_offers_its_own_extensions(self) -> None:
        self.assertEqual((".pov",), mediasource._asset(LIBRARY, "pov").accept)

    def test_media_offers_its_family(self) -> None:
        self.assertEqual(IMAGE_FAMILY, mediasource._media(LIBRARY, "wheel").accept)
        self.assertEqual((".mp4",), mediasource._media(LIBRARY, "playfield_video").accept)

    def test_a_collection_image_offers_what_a_collection_can_save(self) -> None:
        image = mediasource._Image(LIBRARY, "Favorites", "Image", _nothing)
        self.assertEqual(IMAGE_EXTENSIONS, set(image.accept))


class WhatIsAlreadyThere(unittest.TestCase):
    def test_the_current_file_is_named_as_the_host_tab_lists_it(self) -> None:
        context = {"library": LIBRARY, "game_id": "game", "game": {"folder": "/games/Afm"}}
        folder = mediasource._Folder(context, "alt_color", "Alt Color", _nothing,
                                     "pinmame/altcolor")
        self.assertEqual("/games/Afm/pinmame/altcolor", folder.current)

    def test_nothing_is_current_without_a_game_folder_or_a_file(self) -> None:
        self.assertEqual("", _folder("alt_color").current)
        context = {"library": LIBRARY, "game_id": "game", "game": {"folder": "/games/Afm"}}
        self.assertEqual("", mediasource._Folder(context, "alt_color", "Alt Color",
                                                 _nothing).current)


class ACollectionTakingAGameWheel(unittest.TestCase):
    def test_only_a_collection_image_offers_its_games(self) -> None:
        self.assertEqual([True, False],
                         [mediasource._Image(LIBRARY, "Favorites", "Image", _nothing).games,
                          mediasource._Folder.games])

    def test_every_image_the_library_serves_is_named_so_a_collection_can_save_it(
            self) -> None:
        for suffix in IMAGE_FAMILY:
            served = mimetypes.guess_type(f"wheel{suffix}")[0] or ""
            with self.subTest(served=served):
                named = mediasource._named_for("4 Queens", f"{served}; charset=binary")
                self.assertTrue(named.startswith("4 Queens."))
                self.assertIn(named[len("4 Queens"):], IMAGE_EXTENSIONS)


def _slot(in_view: str, saved_for: str, tables: tuple[str, ...] = (),
          own_names: tuple[str, ...] = (),
          own_files: tuple[str, ...] = ()) -> mediasource._Slot:
    """`own_names` are the tables named apart from the folder, and `own_files` those of
    them already holding a file of their own."""
    slot = mediasource._Slot({"library": LIBRARY, "game_id": "game", "game": {},
                              "lens": in_view,
                              "tables": [{"id": one, "filename": f"{one}.vpx"}
                                         for one in tables]},
                             "wheel", "Wheel", _nothing, mediasource._media(LIBRARY, "wheel"))
    slot.placements = [{"table": "", "label": "", "displaces": []},
                       *({"table": one, "label": f"{one}.vpx",
                          "displaces": [f"medias/(Wheel) {one}.png"] if one in own_files
                          else []} for one in own_names)]
    slot.placed_at = {"table": saved_for, "label": f"{saved_for}.vpx"}
    return slot


class WhereItWent(unittest.TestCase):
    def test_saved_for_the_table_in_view_names_the_table(self) -> None:
        self.assertEqual("Wheel saved for Attack from Mars",
                         _slot("Attack from Mars", "Attack from Mars").said_where("Wheel saved"))

    def test_saved_for_every_table_while_one_with_its_own_is_in_view_says_so(self) -> None:
        """Its own file still covers the shared one, so nothing on screen changes."""
        self.assertEqual(
            "Wheel saved for every table in this game - not what this view is showing",
            _slot("AFM VPW", "", tables=("AFM VPW",), own_names=("AFM VPW",),
                  own_files=("AFM VPW",)).said_where("Wheel saved"))

    def test_saved_for_every_table_while_one_with_none_is_in_view_is_shown(self) -> None:
        self.assertEqual(
            "Wheel saved for every table in this game",
            _slot("AFM VPW", "", tables=("AFM VPW",), own_names=("AFM VPW",))
            .said_where("Wheel saved"))

    def test_a_table_named_as_its_folder_is_shown_a_shared_save(self) -> None:
        one = {"tables": ("Attack from Mars",)}
        several = {"tables": ("Attack from Mars", "AFM VR"), "own_names": ("AFM VR",),
                   "own_files": ("AFM VR",)}
        for game, shape in (("one table", one), ("several", several)):
            for in_view in ("Attack from Mars", ""):
                with self.subTest(game=game, in_view=in_view):
                    self.assertEqual("Wheel saved for every table in this game",
                                     _slot(in_view, "", **shape).said_where("Wheel saved"))

    def test_saved_for_a_table_not_in_view_says_so(self) -> None:
        self.assertEqual(
            "Wheel saved for AFM VR - not what this view is showing",
            _slot("", "AFM VR", tables=("Attack from Mars", "AFM VR"),
                  own_names=("AFM VR",)).said_where("Wheel saved"))

    def test_saved_for_every_table_of_several_says_so(self) -> None:
        self.assertEqual("Wheel saved for every table in this game",
                         _slot("", "", tables=("Attack from Mars", "Attack from Mars VR"))
                         .said_where("Wheel saved"))

    def test_a_translation_orders_what_and_where(self) -> None:
        self.addCleanup(i18n.set_language, i18n.language())
        i18n.set_language("xx")
        with mock.patch.dict(i18n._catalogs, {"xx": {
                "console.mediasource.saved_where": "{where}: {message}"}}):
            said = _slot("", "").said_where("Wheel saved")

        self.assertEqual("for every table in this game: Wheel saved", said)


class TheHostTab(unittest.TestCase):
    def test_it_is_named_from_what_the_page_load_read(self) -> None:
        client = mock.Mock()
        client.games.return_value = []
        client.all_media.return_value = []
        client.library_policy.return_value = {}
        client.discovery.return_value = {"display_name": "Garage"}
        library = Library(client)
        library.load()

        named = mediasource._host_name(library)

        self.assertEqual((named, client.discovery.call_count), ("Garage", 1))


def _library() -> mock.Mock:
    library = mock.Mock()
    library.displaced_by.return_value = []
    library.place_media.return_value = {}
    library.disk_file.return_value = b"bytes"
    library.browsed_file_url.side_effect = lambda path: f"/api/v1/filesystem/file?path={path}"
    library.disk_file_url.side_effect = lambda path: f"/api/v1/folders/file?path={path}"
    return library


def _wheel_slot(library: mock.Mock) -> mediasource._Slot:
    return mediasource._Slot({"library": library, "game_id": "game", "game": {},
                              "lens": "", "tables": []},
                             "wheel", "Wheel", _nothing, mediasource._media(library, "wheel"))


async def _now(callback, *args, **kwargs):
    return callback(*args, **kwargs)


class WhatThePickerLooksAt(unittest.TestCase):
    def test_it_lists_the_whole_machine_held_to_what_the_slot_takes(self) -> None:
        library = _library()
        library.disk_listing.return_value = {"path": "/x", "parent": "/", "entries": []}

        found = _wheel_slot(library).listing("/x")

        library.disk_listing.assert_called_once_with("/x", IMAGE_FAMILY)
        self.assertEqual(found["path"], "/x")

    def test_it_starts_where_the_library_does_and_then_the_rest_of_the_machine(self) -> None:
        client = mock.Mock()
        client.browse_roots.return_value = [
            {"path": "/games/Afm", "name": "Afm", "source": "game"},
            {"path": "/Volumes/share", "name": "Home", "source": "configured"}]
        client.folders.return_value = {"roots": [{"path": "/", "name": "/"},
                                                 {"path": "/Volumes/share", "name": "Home"}]}

        starts = Library(client).disk_starts("game")

        self.assertEqual(["/games/Afm", "/Volumes/share", "/"], [one["path"] for one in starts])
        client.browse_roots.assert_called_once_with("game")

    def test_folders_come_first_and_each_entry_says_which_it_is(self) -> None:
        client = mock.Mock()
        client.folders.return_value = {
            "path": "/x", "parent": "/", "above": [], "roots": [],
            "folders": [{"name": "sub", "path": "/x/sub"}],
            "files": [{"name": "a.png", "path": "/x/a.png"}]}

        found = Library(client).disk_listing("/x", (".png",))

        self.assertEqual([("folder", "sub"), ("file", "a.png")],
                         [(one["kind"], one["name"]) for one in found["entries"]])
        client.folders.assert_called_once_with("/x", "file", (".png",))


class WhereAFileIsShownFrom(unittest.TestCase):
    def setUp(self) -> None:
        self.slot = _wheel_slot(_library())
        self.slot.browse_roots = [{"path": "/games/Afm", "name": "Afm", "source": "game"},
                                  {"path": "/", "name": "/"}]

    def test_a_file_in_a_library_folder_is_shown_from_the_route_any_console_can_use(
            self) -> None:
        self.assertEqual("/api/v1/filesystem/file?path=/games/Afm/medias/a.png",
                         self.slot.preview("/games/Afm/medias/a.png"))

    def test_a_file_anywhere_else_is_shown_from_the_route_for_this_device_only(self) -> None:
        for path in ("/Volumes/share/a.png", "/games/Afm2/a.png"):
            with self.subTest(path=path):
                self.assertEqual(f"/api/v1/folders/file?path={path}", self.slot.preview(path))

    def test_the_top_of_the_disk_is_not_a_library_folder(self) -> None:
        self.assertTrue(self.slot.preview("/Volumes/share/a.png").startswith("/api/v1/folders/"))


class ReadingAFileOnThisMachine(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.root = Path(self.dir.name).resolve()

    def test_the_bytes_come_from_here_not_from_the_api(self) -> None:
        (self.root / "view.pov").write_bytes(b"pov")
        client = mock.Mock()

        data = Library(client).disk_file(str(self.root / "view.pov"), (".pov",))

        self.assertEqual(b"pov", data)
        self.assertEqual([], client.mock_calls)

    def test_another_kind_of_file_is_refused(self) -> None:
        (self.root / "view.png").write_bytes(b"png")

        with self.assertRaises(service_errors.RefusedError):
            Library(mock.Mock()).disk_file(str(self.root / "view.png"), (".pov",))

    def test_a_file_in_a_private_folder_is_refused(self) -> None:
        (self.root / ".ssh").mkdir()
        (self.root / ".ssh" / "key.pov").write_bytes(b"key")

        with mock.patch("common.folder_browse.Path.home", return_value=self.root), \
                self.assertRaises(service_errors.RefusedError):
            Library(mock.Mock()).disk_file(str(self.root / ".ssh" / "key.pov"), (".pov",))


class TakingAFileFromTheDisk(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.library = _library()
        self.slot = _wheel_slot(self.library)
        self.finished = mock.AsyncMock()
        self.said = mock.Mock()
        for patched in (mock.patch("console.offload.run.io_bound", new=_now),
                        mock.patch.object(self.slot, "finish", new=self.finished),
                        mock.patch.object(mediasource.ui, "notify", new=self.said),
                        mock.patch.object(mediasource.candidates, "row")):
            patched.start()
            self.addCleanup(patched.stop)

    async def _take(self, name: str = "art.png", path: str = "/Volumes/share/art.png") -> None:
        self.slot.file_row({"name": name, "path": path})
        take = mediasource.candidates.row.call_args.args[4]
        await clicks.press(take)

    async def test_the_file_is_read_here_and_placed_as_bytes_under_its_name(self) -> None:
        with mock.patch.object(mediasource.confirm, "replace",
                               new=mock.AsyncMock(return_value=True)):
            await self._take()

        self.library.disk_file.assert_called_once_with("/Volumes/share/art.png", IMAGE_FAMILY)
        self.library.place_media.assert_called_once_with("game", "", "wheel", "art.png",
                                                         b"bytes")
        self.finished.assert_awaited_once()

    async def test_a_replacement_somebody_declines_costs_no_read_and_no_write(self) -> None:
        self.library.displaced_by.return_value = ["medias/old.png"]

        with mock.patch.object(mediasource.confirm, "replace",
                               new=mock.AsyncMock(return_value=False)):
            await self._take()

        self.library.disk_file.assert_not_called()
        self.library.place_media.assert_not_called()
        self.finished.assert_not_awaited()

    async def test_a_file_that_cannot_be_read_is_said_and_nothing_is_written(self) -> None:
        self.library.disk_file.side_effect = service_errors.RefusedError("not for this slot")

        await self._take()

        self.said.assert_called_once()
        self.assertEqual("negative", self.said.call_args.kwargs["type"])
        self.library.place_media.assert_not_called()
        self.finished.assert_not_awaited()

    async def test_a_collection_image_reads_the_same_way_and_hands_over_name_and_bytes(
            self) -> None:
        image = mediasource._Image(self.library, "Favorites", "Image", _nothing)
        taken = mock.AsyncMock()
        with mock.patch.object(image, "took", new=taken):
            image.file_row({"name": "art.png", "path": "/Volumes/share/art.png"})
            await clicks.press(mediasource.candidates.row.call_args.args[4])

        self.library.disk_file.assert_called_once_with("/Volumes/share/art.png", image.accept)
        taken.assert_awaited_once_with("art.png", b"bytes")


def _folder_of(count: int) -> dict:
    sessions = [{"kind": "folder", "name": f"session-{n:03}", "path": f"/x/session-{n:03}"}
                for n in range(count)]
    return {"path": "/x", "parent": "/", "entries": [
        *sessions,
        {"kind": "folder", "name": "Outside-Art", "path": "/x/Outside-Art"},
        {"kind": "file", "name": "Wheel Art.png", "path": "/x/Wheel Art.png"}]}


class AFolderLongerThanTheListIsNarrowedByName(unittest.TestCase):
    """Whole-disk browsing meets folders of hundreds, and what the list cuts off has
    to stay reachable."""

    def _drawn(self, wanted: str) -> tuple[list[str], list[str]]:
        slot = _wheel_slot(_library())
        slot.here = _folder_of(200)
        slot.narrow = SimpleNamespace(value=wanted)
        names: list[str] = []
        with mock.patch.object(slot, "_folder_link",
                               new=lambda name, *_a, up=False: up or names.append(name)), \
                mock.patch.object(slot, "file_row",
                                  new=lambda item: names.append(item["name"])):
            with ui.column() as listing:
                slot._draw_folder(listing)
        notes = [one.text for one in listing.descendants() if isinstance(one, ui.label)]
        return names, notes

    def test_without_a_filter_the_list_is_cut_and_says_how_much(self) -> None:
        names, notes = self._drawn("")

        self.assertEqual((60, ["142 more not shown"]), (len(names), notes))
        self.assertNotIn("Outside-Art", names)

    def test_a_filter_reaches_what_the_cut_left_out(self) -> None:
        names, notes = self._drawn("outside")

        self.assertEqual((["Outside-Art"], []), (names, notes))

    def test_a_filter_matches_files_and_ignores_case_and_edge_spaces(self) -> None:
        names, _ = self._drawn("  WHEEL art ")

        self.assertEqual(["Wheel Art.png"], names)

    def test_a_filter_that_matches_nothing_says_so(self) -> None:
        names, notes = self._drawn("zzz")

        self.assertEqual(([], ["Nothing here"]), (names, notes))


class OpeningAFolderUnderAFilter(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        # Built here because a coroutine has no slot to put an element in.
        self.slot = _wheel_slot(_library())
        self.slot.browse_roots = []
        self.slot.listing = lambda path: {
            "path": path, "parent": "/",
            "entries": [{"kind": "file", "name": name, "path": f"{path}/{name}"}
                        for name in ("a.png", "b.png")]}
        with ui.column() as self.listing:
            self.slot.narrow = ui.input(value="b")
        self.slot.narrow.on_value_change(lambda: self.slot._draw_folder(self.listing))

    async def test_the_filter_clears_and_the_new_folder_is_drawn_once_in_full(self) -> None:
        drawn: list[str] = []
        self.enterContext(mock.patch.object(core, "loop", asyncio.get_running_loop()))
        self.enterContext(mock.patch("console.offload.run.io_bound", new=_now))
        self.enterContext(mock.patch.object(self.slot, "_folder_link"))
        self.enterContext(mock.patch.object(
            self.slot, "file_row", new=lambda item: drawn.append(item["name"])))

        await self.slot._show_folder(self.listing, "/y")

        self.assertEqual(("", ["a.png", "b.png"]), (self.slot.narrow.value, drawn))


if __name__ == "__main__":
    unittest.main()
