"""Back up now: the zip one press writes, what it lists as, and how its parts go back."""

from __future__ import annotations

import json
import pathlib
import zipfile
from datetime import UTC, datetime

from common.backups import archive, copies, pending
from tests.api.test_backups import BackupsCase
from tests.support.library import game_info, write_game


class ArchiveCase(BackupsCase):
    def take(self, scope: str, **body):
        return self.client.post("/backups", json={"scope": scope, **body})

    def games(self, *names: str) -> dict[str, pathlib.Path]:
        return {name: self.game(name) for name in names}

    def ids(self, *names: str) -> list[str]:
        return ["id-" + name for name in names]

    def rows(self) -> list[dict]:
        return self.client.get("/backups").json()["copies"]

    def whole(self) -> dict:
        return next(one for one in self.rows() if one["of_kind"] == "archive")

    def parts(self) -> list[dict]:
        return [one for one in self.rows() if one["within"]]

    def part(self, name: str) -> dict:
        return next(one for one in self.parts() if one["of_name"] == name)

    def put(self, response):
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def title_in(self, folder: pathlib.Path) -> str:
        return json.loads((folder / f"{folder.name}.info").read_text())["Info"]["Title"]

    def retitle(self, folder: pathlib.Path, title: str) -> None:
        path = folder / f"{folder.name}.info"
        data = json.loads(path.read_text())
        data["Info"]["Title"] = title
        path.write_text(json.dumps(data))


class TakingTests(ArchiveCase):
    def test_a_zip_of_games_holds_each_info_and_a_manifest(self) -> None:
        self.games("Taxi", "Medieval Madness", "Attack")

        body = self.put(self.take("games", games=self.ids("Taxi", "Attack"), note="before"))

        path = pathlib.Path(body["path"])
        self.assertTrue(archive.is_archive_name(path.name))
        with zipfile.ZipFile(path) as bundle:
            names = bundle.namelist()
        self.assertEqual(sorted(names), sorted([
            "manifest.json", "games/0001/Taxi.info", "games/0002/Attack.info"]))
        manifest = archive.read(path)
        assert manifest is not None
        self.assertEqual((manifest.scope, manifest.note), ("games", "before"))
        self.assertEqual([one.of_id for one in manifest.members], ["id-Taxi", "id-Attack"])

    def test_every_game_takes_each_one_in_the_library(self) -> None:
        self.games("Taxi", "Medieval Madness", "Attack")

        self.put(self.take("all_games"))

        self.assertEqual(len(self.parts()), 3)

    def test_records_takes_only_the_files_vpinfe_keeps(self) -> None:
        (self.config / "players.json").write_text("{}")
        (self.config / "tags.json").write_text("{}")
        (self.config / "watching.json").write_text("{}")

        self.put(self.take("records"))

        self.assertEqual(sorted(one["file"] for one in self.parts()),
                         ["players.json", "tags.json"])

    def test_everything_holds_games_records_and_a_launchers_settings(self) -> None:
        self.games("Taxi")
        (self.config / "players.json").write_text("{}")
        ini = pathlib.Path(self.tmp.name) / "Scratch.ini"
        ini.write_text("[Player]\nFXAA = 1\n")
        self.put(self.client.put("/launchers/l1", json={
            "app": "vpx", "display_name": "Main VPX",
            "settings": {"bin_path": "/opt/vpx", "ini_path": str(ini)}}))

        self.put(self.take("everything"))

        self.assertEqual(sorted((one["of_kind"], one["file"]) for one in self.parts()),
                         [("game", "Taxi.info"), ("launcher", "Scratch.ini"),
                          ("vpinfe", "players.json")])
        self.assertEqual(self.whole()["of_name"], "Everything")

    def test_a_launchers_backup_holds_that_launchers_files(self) -> None:
        ini = pathlib.Path(self.tmp.name) / "Scratch.ini"
        ini.write_text("[Player]\nFXAA = 1\n")
        self.put(self.client.put("/launchers/l1", json={
            "app": "vpx", "display_name": "Main VPX",
            "settings": {"bin_path": "/opt/vpx", "ini_path": str(ini)}}))

        self.put(self.take("launcher", launcher="l1"))

        self.assertEqual(self.whole()["of_name"], "Main VPX")

    def test_nothing_to_back_up_is_refused(self) -> None:
        self.assertEqual(self.take("records").status_code, 400)
        self.assertEqual(self.take("all_games").status_code, 400)

    def test_a_game_that_is_not_in_the_library_is_not_found(self) -> None:
        self.game("Taxi")

        self.assertEqual(self.take("games", games=["id-Nope"]).status_code, 404)

    def test_a_launcher_that_does_not_exist_is_not_found(self) -> None:
        self.assertEqual(self.take("launcher", launcher="nope").status_code, 404)

    def test_two_taken_in_one_second_are_both_kept(self) -> None:
        self.game("Taxi")

        first = self.put(self.take("all_games"))["path"]
        second = self.put(self.take("all_games"))["path"]

        self.assertNotEqual(first, second)
        self.assertEqual(len(archive.listed()), 2)

    def test_a_scope_that_is_not_one_is_refused(self) -> None:
        self.assertEqual(self.take("nothing").status_code, 422)


class ListingTests(ArchiveCase):
    def test_a_zip_is_one_row_and_each_part_is_another_that_names_it(self) -> None:
        self.games("Taxi", "Medieval Madness", "Attack")
        self.put(self.take("all_games", note="Before the move"))

        whole = self.whole()
        parts = self.parts()

        self.assertEqual((whole["of_name"], whole["why"], whole["note"], whole["within"]),
                         ("3 games", "yours", "Before the move", ""))
        self.assertEqual(sorted(one["of_name"] for one in parts),
                         ["Attack", "Medieval Madness", "Taxi"])
        self.assertEqual({one["within"] for one in parts}, {whole["id"]})

    def test_a_part_whose_game_has_gone_says_so_and_the_zip_does_not_until_all_have(self) -> None:
        folders = self.games("Taxi", "Attack")
        self.put(self.take("all_games"))
        for child in folders["Taxi"].iterdir():
            child.unlink()
        folders["Taxi"].rmdir()

        self.assertEqual({one["of_name"]: one["gone"] for one in self.parts()},
                         {"Taxi": True, "Attack": False})
        self.assertFalse(self.whole()["gone"])

    def test_a_file_that_is_not_a_zip_of_ours_still_lists_as_a_row(self) -> None:
        folder = self.config / "backups"
        folder.mkdir(exist_ok=True)
        (folder / "vpinfe-backup-20261001T010203Z.zip").write_text("not a zip")

        found = self.rows()

        self.assertEqual([(one["of_kind"], one["of_name"], one["taken"]) for one in found],
                         [("archive", "", "2026-10-01T01:02:03Z")])

    def test_a_zip_that_is_not_named_like_ours_is_not_listed(self) -> None:
        folder = self.config / "backups"
        folder.mkdir(exist_ok=True)
        (folder / "holiday.zip").write_text("x")

        self.assertEqual(self.rows(), [])


class RestoringTests(ArchiveCase):
    def three(self) -> dict[str, pathlib.Path]:
        folders = self.games("Taxi", "Medieval Madness", "Attack")
        self.put(self.take("all_games"))
        for name, folder in folders.items():
            self.retitle(folder, name + " (edited)")
        return folders

    def test_one_part_goes_back_and_what_it_replaced_is_kept(self) -> None:
        folders = self.three()

        body = self.put(self.client.post(f"/backups/{self.part('Taxi')['id']}/restore"))

        self.assertEqual(self.title_in(folders["Taxi"]), "Taxi")
        self.assertEqual(self.title_in(folders["Attack"]), "Attack (edited)")
        self.assertEqual([one["why"] for one in body["kept"]], ["restore"])

    def test_undoing_one_part_puts_back_what_it_replaced(self) -> None:
        folders = self.three()
        body = self.put(self.client.post(f"/backups/{self.part('Taxi')['id']}/restore"))

        self.put(self.client.post(f"/backups/{body['kept'][0]['id']}/restore"))

        self.assertEqual(self.title_in(folders["Taxi"]), "Taxi (edited)")

    def test_the_whole_zip_puts_back_all_three_and_each_can_be_undone(self) -> None:
        folders = self.three()

        body = self.put(self.client.post(f"/backups/{self.whole()['id']}/restore"))

        self.assertEqual({name: self.title_in(folder) for name, folder in folders.items()},
                         {name: name for name in folders})
        self.assertEqual(len(body["kept"]), 3)
        self.assertEqual(body["skipped"], [])
        for one in body["kept"]:
            self.put(self.client.post(f"/backups/{one['id']}/restore"))
        self.assertEqual({name: self.title_in(folder) for name, folder in folders.items()},
                         {name: name + " (edited)" for name in folders})

    def test_a_game_whose_folder_was_renamed_is_found_by_its_id(self) -> None:
        folders = self.three()
        renamed = folders["Taxi"].with_name("Taxi (Bally 1988)")
        folders["Taxi"].rename(renamed)
        (renamed / "Taxi.info").rename(renamed / "Taxi (Bally 1988).info")

        self.put(self.client.post(f"/backups/{self.part('Taxi')['id']}/restore"))

        self.assertEqual(self.title_in(renamed), "Taxi")

    def test_a_part_whose_game_has_gone_is_refused(self) -> None:
        folders = self.three()
        for child in folders["Taxi"].iterdir():
            child.unlink()
        folders["Taxi"].rmdir()

        response = self.client.post(f"/backups/{self.part('Taxi')['id']}/restore")

        self.assertEqual(response.status_code, 404, response.text)

    def test_the_whole_zip_skips_a_game_that_has_gone_and_says_which(self) -> None:
        folders = self.three()
        for child in folders["Taxi"].iterdir():
            child.unlink()
        folders["Taxi"].rmdir()

        body = self.put(self.client.post(f"/backups/{self.whole()['id']}/restore"))

        self.assertEqual(len(body["kept"]), 2)
        self.assertEqual([one["name"] for one in body["skipped"]], ["Taxi"])
        self.assertEqual(self.title_in(folders["Attack"]), "Attack")

    def test_a_record_waits_for_the_close_and_is_then_put_in_from_the_staged_file(self) -> None:
        live = self.config / "players.json"
        live.write_text('{"was": 1}')
        self.put(self.take("records"))
        live.write_text('{"is": 2}')
        part = self.part("VPinFE")

        body = self.put(self.client.post(f"/backups/{part['id']}/restore"))

        self.assertTrue(body["pending"])
        self.assertEqual(live.read_text(), '{"is": 2}')
        self.assertEqual(self.client.get("/backups").json()["pending"], [part["id"]])
        self.assertEqual(pending.apply(self.config), 1)
        self.assertEqual(live.read_text(), '{"was": 1}')
        self.assertFalse((self.config / pending.STAGED_DIR).exists())
        self.assertEqual(self.client.get("/backups").json()["pending"], [])

    def test_deleting_the_zip_cancels_the_wait_and_drops_what_was_staged(self) -> None:
        live = self.config / "players.json"
        live.write_text("{}")
        self.put(self.take("records"))
        self.put(self.client.post(f"/backups/{self.part('VPinFE')['id']}/restore"))

        self.put(self.client.delete(f"/backups/{self.whole()['id']}"))

        self.assertEqual(self.client.get("/backups").json()["pending"], [])
        self.assertEqual(list((self.config / pending.STAGED_DIR).iterdir()), [])
        self.assertEqual(pending.apply(self.config), 0)

    def test_a_launcher_part_goes_back_and_undoing_it_returns_what_it_replaced(self) -> None:
        ini = pathlib.Path(self.tmp.name) / "Scratch.ini"
        ini.write_text("[Player]\nFXAA = 1\n")
        self.put(self.client.put("/launchers/l1", json={
            "app": "vpx", "display_name": "Main VPX",
            "settings": {"bin_path": "/opt/vpx", "ini_path": str(ini)}}))
        self.put(self.take("launcher", launcher="l1"))
        ini.write_text("[Player]\nFXAA = 0\n")

        body = self.put(self.client.post(f"/backups/{self.part('Main VPX')['id']}/restore"))

        self.assertEqual(ini.read_text(), "[Player]\nFXAA = 1\n")
        self.put(self.client.post(f"/backups/{body['kept'][0]['id']}/restore"))
        self.assertEqual(ini.read_text(), "[Player]\nFXAA = 0\n")

    def test_launcher_parts_are_not_put_back_while_a_table_plays(self) -> None:
        ini = pathlib.Path(self.tmp.name) / "Scratch.ini"
        ini.write_text("[Player]\nFXAA = 1\n")
        self.put(self.client.put("/launchers/l1", json={
            "app": "vpx", "display_name": "Main VPX",
            "settings": {"bin_path": "/opt/vpx", "ini_path": str(ini)}}))
        self.put(self.take("launcher", launcher="l1"))
        ini.write_text("[Player]\nFXAA = 0\n")
        self.playing = True

        part = self.client.post(f"/backups/{self.part('Main VPX')['id']}/restore")
        whole = self.put(self.client.post(f"/backups/{self.whole()['id']}/restore"))

        self.assertEqual(part.status_code, 409)
        self.assertEqual(len(whole["skipped"]), 1)
        self.assertEqual(ini.read_text(), "[Player]\nFXAA = 0\n")


class DeletingAndForgeryTests(ArchiveCase):
    def test_deleting_a_zip_removes_it_and_its_parts(self) -> None:
        self.games("Taxi")
        self.put(self.take("all_games"))

        self.put(self.client.delete(f"/backups/{self.whole()['id']}"))

        self.assertEqual(self.rows(), [])
        self.assertEqual(archive.listed(), [])

    def test_a_part_cannot_be_deleted_on_its_own(self) -> None:
        self.games("Taxi")
        self.put(self.take("all_games"))

        response = self.client.delete(f"/backups/{self.part('Taxi')['id']}")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(len(archive.listed()), 1)

    def test_a_part_id_for_a_name_the_zip_does_not_hold_reaches_nothing(self) -> None:
        self.games("Taxi")
        body = self.put(self.take("all_games"))
        forged = copies.make_member_id(body["path"], "../../etc/passwd")

        self.assertEqual(self.client.post(f"/backups/{forged}/restore").status_code, 404)

    def test_a_part_id_for_a_zip_outside_the_backups_folder_reaches_nothing(self) -> None:
        stray = self.config / "vpinfe-backup-20261001T010203Z.zip"
        with zipfile.ZipFile(stray, "w") as bundle:
            bundle.writestr("manifest.json", "{}")
        forged = copies.make_member_id(stray, "manifest.json")

        self.assertEqual(self.client.post(f"/backups/{forged}/restore").status_code, 404)
        self.assertEqual(self.client.delete(
            f"/backups/{copies.make_id(copies.PLACE_ARCHIVE, stray)}").status_code, 404)

    def test_a_manifest_that_names_a_path_cannot_steer_where_a_file_goes(self) -> None:
        taxi = self.games("Taxi")["Taxi"]
        self.retitle(taxi, "Changed")
        victim = pathlib.Path(self.tmp.name) / "elsewhere.info"
        victim.write_text("untouched")
        folder = self.config / "backups"
        folder.mkdir(exist_ok=True)
        path = folder / "vpinfe-backup-20261001T010203Z.zip"
        manifest = {"format": 1, "note": "", "taken": "", "version": "", "scope": "games",
                    "members": [{"name": "games/0001/Taxi.info", "kind": "game_metadata",
                                 "of_id": "id-Taxi", "of_name": "Taxi",
                                 "path": str(victim), "size": 1}]}
        with zipfile.ZipFile(path, "w") as bundle:
            bundle.writestr("manifest.json", json.dumps(manifest))
            bundle.writestr("games/0001/Taxi.info",
                            json.dumps(game_info("Taxi", game_id="id-Taxi")))

        self.put(self.client.post(f"/backups/{self.whole()['id']}/restore"))

        self.assertEqual(victim.read_text(), "untouched")
        self.assertEqual(self.title_in(taxi), "Taxi")


class DamagedAndMismatchedTests(ArchiveCase):
    def zip_of(self, members: list[dict], files: dict[str, bytes],
               stamp: str = "20261001T010203Z", manifest: dict | None = None) -> pathlib.Path:
        folder = self.config / "backups"
        folder.mkdir(exist_ok=True)
        path = folder / f"vpinfe-backup-{stamp}.zip"
        body = manifest if manifest is not None else {
            "format": 1, "note": "", "taken": "", "version": "", "scope": "games",
            "members": members}
        with zipfile.ZipFile(path, "w") as bundle:
            bundle.writestr("manifest.json", json.dumps(body))
            for name, data in files.items():
                bundle.writestr(name, data)
        return path

    def damage(self, path: pathlib.Path, stored: bytes) -> None:
        raw = bytearray(path.read_bytes())
        at = raw.find(stored)
        self.assertGreater(at, 0)
        raw[at + 2] ^= 0xFF
        path.write_bytes(bytes(raw))

    def part_in(self, path: pathlib.Path) -> dict:
        return next(one for one in self.parts() if one["path"] == str(path))

    def game_member(self, name: str, game_id: str = "") -> dict:
        return {"name": f"games/0001/{name}.info", "kind": "game_metadata",
                "of_id": game_id, "of_name": name, "path": f"{name}/{name}.info", "size": 1}

    def test_a_manifest_with_values_of_the_wrong_type_still_lists(self) -> None:
        self.zip_of([], {}, manifest={"format": 1, "members": 5})
        self.zip_of([{"name": "a", "kind": "game_metadata", "size": "abc"}], {"a": b"x"},
                    stamp="20261002T010203Z")

        response = self.client.get("/backups")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()["copies"]), 3)

    def test_a_member_that_cannot_be_read_is_skipped_and_the_rest_goes_back(self) -> None:
        folders = self.games("Taxi", "Attack")
        for name, folder in folders.items():
            self.retitle(folder, name + " (edited)")
        taxi = json.dumps(game_info("Taxi", game_id="id-Taxi")).encode()
        path = self.zip_of(
            [self.game_member("Taxi", "id-Taxi"),
             {**self.game_member("Attack", "id-Attack"), "name": "games/0002/Attack.info"}],
            {"games/0001/Taxi.info": taxi, "games/0002/Attack.info":
             json.dumps(game_info("Attack", game_id="id-Attack")).encode()})
        self.damage(path, taxi)

        body = self.put(self.client.post(f"/backups/{self.whole()['id']}/restore"))

        self.assertEqual([one["name"] for one in body["skipped"]], ["Taxi"])
        self.assertEqual(self.title_in(folders["Attack"]), "Attack")
        self.assertEqual(self.title_in(folders["Taxi"]), "Taxi (edited)")

    def test_a_game_with_the_same_name_but_another_id_is_not_written_over(self) -> None:
        old = self.game("Taxi")
        self.put(self.take("all_games"))
        for child in old.iterdir():
            child.unlink()
        old.rmdir()
        other = write_game(self.library, "Taxi", info=game_info("Other", game_id="id-other"))
        part = self.part("Taxi")

        response = self.client.post(f"/backups/{part['id']}/restore")

        self.assertEqual((response.status_code, part["gone"]), (404, True))
        self.assertEqual(self.title_in(other), "Other")

    def test_a_member_without_an_id_goes_to_the_game_with_its_folders_name(self) -> None:
        folder = write_game(self.library, "Taxi", info=game_info("Taxi"))
        path = self.zip_of([self.game_member("Taxi")],
                           {"games/0001/Taxi.info": json.dumps(game_info("Was")).encode()})
        self.retitle(folder, "Now")

        self.put(self.client.post(f"/backups/{archive_row(self, path)['id']}/restore"))

        self.assertEqual(self.title_in(folder), "Was")

    def test_a_member_without_an_id_is_gone_only_when_no_game_has_its_name(self) -> None:
        write_game(self.library, "Other", info=game_info("Other"))
        self.zip_of([self.game_member("Taxi")],
                    {"games/0001/Taxi.info": json.dumps(game_info("Was")).encode()})

        self.assertTrue(self.part("Taxi")["gone"])

    def test_two_taken_in_the_same_second_get_different_names(self) -> None:
        (self.config / "backups").mkdir(exist_ok=True)
        now = datetime(2026, 10, 1, 1, 2, 3, tzinfo=UTC)
        first = archive._free_path(now)
        first.write_text("x")

        self.assertNotEqual(archive._free_path(now), first)

    def test_a_failed_extract_leaves_an_earlier_staged_file_whole(self) -> None:
        live = self.config / "players.json"
        live.write_text('{"a": 1}')
        good = pathlib.Path(self.put(self.take("records"))["path"])
        self.put(self.client.post(f"/backups/{self.part_in(good)['id']}/restore"))
        record = b'{"a": 1}'
        later = self.zip_of(
            [{"name": "records/players.json", "kind": "players", "of_id": "",
              "of_name": "VPinFE", "path": "players.json", "size": 8}],
            {"records/players.json": record}, stamp="20261002T010203Z")
        self.damage(later, record)

        response = self.client.post(f"/backups/{self.part_in(later)['id']}/restore")

        self.assertEqual(response.status_code, 400, response.text)
        staged = self.config / pending.STAGED_DIR / "players.json"
        self.assertEqual(staged.read_text(), '{"a": 1}')


def archive_row(case: ArchiveCase, path: pathlib.Path) -> dict:
    return next(one for one in case.rows() if one["path"] == str(path) and not one["within"])
