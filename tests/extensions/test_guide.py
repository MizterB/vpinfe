"""The developer guide under `docs/extensions/` stays true because these fail when it does not.

The recipes are real extensions run against the practice site, a code block that names a file
is that file, and every link inside the guide goes somewhere.
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import re
import tempfile
import time
import unittest
import unittest.mock
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from common import events, i18n, jobs, sized_media
from common.extensions import check, contract, fields, host, pictures, serving, store
from common.extensions.context import COLUMN_KINDS, ExtensionContext, logger_for
from common.service_errors import NotFoundError, RefusedError
from console import ext_links

GUIDE = Path(__file__).resolve().parents[2] / "docs" / "extensions"
EXAMPLES = GUIDE / "examples"
RECIPES = sorted(one for one in (EXAMPLES / "recipes").iterdir()
                 if one.is_dir() and not one.name.startswith("."))
SCOREBOARD = EXAMPLES / "scoreboard"
PAGES = sorted(GUIDE.rglob("*.md"))

SPEC = importlib.util.spec_from_file_location("practice_site", EXAMPLES / "practice_site.py")
assert SPEC is not None and SPEC.loader is not None
practice_site = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(practice_site)

# What `--check-extension` says each recipe declares, as the recipe's own text claims it.
DECLARES: dict[str, list[str]] = {
    "smallest": ["settings   greeting (string, default 'Hello')"],
    "hello_dialog": ["dialog     hello: ask run"],
    "post_score": ["settings   site (string", "dialog     post: ask check run"],
    "slow_sync": ["dialog     sync: ask run"],
    "play_log": [],
    "top_scores": ["settings   key (secret)", "list       top in community: 3 columns"],
    "add_score": ["settings   key (secret)", "dialog     post: ask run",
                  "list       scores in community: 3 columns, 0 views, 0 verbs, adds post"],
    "score_rows": ["list       scores in community: 3 columns, 0 views, 3 verbs"],
    "weekly_board": ["list       board in community: 5 columns, 0 views, 0 verbs"],
    "challenge_pane": ["list       board in community: 1 columns, 0 views, 0 verbs, opens a pane",
                       "a pane of 2 sections"],
    "game_notes": ["group      on a game's panel, with fields",
                   "group      on a table's panel"],
    "machine_page": ["page       machine in system, with fields",
                     "reads      page machine: 2 sections, acts: check, manual"],
    "review_queue": ["list       queue in community: 3 columns",
                     "need       to_review opens the list queue, danger"],
    "secret_key": ["settings   key (secret)", "dialog     connect: ask run"],
    "player_handle": ["account    a player can hold one"],
    "tool_link": ["settings   port (number", "link       console in system: http://{host}:9090/",
                  "link       manual: https://tool.example.com/manual"],
    "vpinos_only": ["platforms  vpinos", "settings   boot (select, default 'play')"],
}


def serving_practice_site() -> Any:
    """The practice site on its own port, ended when the test is."""
    try:
        return practice_site.serve_in_background(practice_site.PORT)
    except OSError as exc:
        raise AssertionError(
            f"The practice site's port {practice_site.PORT} is taken, probably by a practice "
            "site left running. Stop it and run this again") from exc


class ExampleFolders(unittest.TestCase):
    def test_every_recipe_has_a_line_here_and_the_other_way_round(self) -> None:
        self.assertEqual([one.name for one in RECIPES], sorted(DECLARES))

    def test_every_recipe_loads_and_passes_the_check_the_guide_tells_a_reader_to_run(
            self) -> None:
        site = serving_practice_site()
        self.addCleanup(site.server_close)
        self.addCleanup(site.shutdown)
        for folder in RECIPES:
            with self.subTest(folder.name):
                lines, passed = check.check(folder)

                self.assertTrue(passed, "\n".join(lines))
                self.assertIn(f"loads      {folder.name} 1.0.0", lines)
                shown = "\n".join(lines)
                for wanted in DECLARES[folder.name]:
                    self.assertIn(wanted, shown)

    def test_a_recipe_names_what_it_is_in_its_own_words(self) -> None:
        for folder in RECIPES:
            with self.subTest(folder.name):
                manifest = json.loads((folder / "extension.json").read_text())
                words = json.loads((folder / "i18n" / "en.json").read_text())

                self.assertEqual(manifest["name"], folder.name)
                self.assertIn("name", words)
                self.assertIn("description", words)


class PracticeSite(unittest.TestCase):
    def setUp(self) -> None:
        self.site = practice_site.serve_in_background(0)
        self.addCleanup(self.site.server_close)
        self.addCleanup(self.site.shutdown)
        self.base = f"http://{practice_site.HOST}:{self.site.server_address[1]}"

    def ask(self, path: str, key: str = practice_site.KEY, body: Any = None,
            base: str = "") -> tuple[int, Any]:
        request = urllib.request.Request(
            (base or self.base) + path, headers={"X-API-Key": key},
            data=None if body is None else json.dumps(body).encode())
        try:
            with urllib.request.urlopen(request, timeout=5) as answer:
                return answer.status, json.loads(answer.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def test_it_is_open_to_anyone_at_status_and_closed_elsewhere_to_a_wrong_key(self) -> None:
        self.assertEqual(self.ask("/status", key="no")[0], 200)
        self.assertEqual(self.ask("/check", key="no")[0], 401)
        self.assertEqual(self.ask("/top", key="no")[0], 401)

    def test_it_lists_the_best_score_first_and_keeps_what_is_posted(self) -> None:
        self.assertEqual(self.ask("/top")[1][0]["score"], 1_240_000_000)

        status, _ = self.ask("/scores", body={"player": "ZED", "table": "T", "score": 2 * 10**9})

        self.assertEqual(status, 201)
        self.assertEqual(self.ask("/top")[1][0]["player"], "ZED")

    def test_a_score_missing_a_part_is_refused(self) -> None:
        self.assertEqual(self.ask("/scores", body={"player": "ZED"})[0], 400)

    def test_each_server_keeps_its_own_scores(self) -> None:
        other = practice_site.serve_in_background(0)
        self.addCleanup(other.server_close)
        self.addCleanup(other.shutdown)
        self.ask("/scores", body={"player": "ZED", "table": "T", "score": 2 * 10**9})

        theirs = self.ask("/top", base=f"http://{practice_site.HOST}:{other.server_address[1]}")

        self.assertEqual(len(theirs[1]), 3)

    def test_a_port_of_zero_is_any_free_one(self) -> None:
        self.assertNotIn(self.site.server_address[1], (0, practice_site.PORT))


class ExamplesLoadedByTheHost(unittest.TestCase):
    """An example folder loaded as the host loads it, with the practice site serving."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.registry = host.Registry(store.ExtensionStore(Path(tmp.name)))
        self.addCleanup(self.registry.clear)
        jobs.reset_for_tests()
        self.site = serving_practice_site()
        self.addCleanup(self.site.server_close)
        self.addCleanup(self.site.shutdown)

    def load(self, name: str, folder: Path | None = None) -> host.Record:
        self.addCleanup(i18n.disown, f"ext.{name}")
        record = self.registry.load(folder or EXAMPLES / "recipes" / name)
        self.assertEqual(record.state, host.LOADED, record.error)
        return record

    def posted_scores(self) -> list[dict]:
        request = urllib.request.Request(
            f"http://{practice_site.HOST}:{practice_site.PORT}/top",
            headers={"X-API-Key": practice_site.KEY})
        with urllib.request.urlopen(request, timeout=5) as answer:
            return json.loads(answer.read())


class RecipesDoWhatTheyClaim(ExamplesLoadedByTheHost):
    """The recipes loaded as the host loads them, and driven through what core serves."""

    def test_the_smallest_extension_keeps_what_its_setting_is_changed_to(self) -> None:
        record = self.load("smallest")

        shown = serving.settings_read(record)["fields"][0]
        self.assertEqual((shown["value"], shown["placeholder"]), ("", "Hello"))
        self.assertEqual(record.context.config.get("greeting"), "Hello")
        serving.settings_write(record, {"greeting": "Howdy"})

        self.assertEqual(record.context.config.get("greeting"), "Howdy")

    def test_the_smallest_dialog_asks_one_question_and_says_hello_to_the_answer(self) -> None:
        record = self.load("hello_dialog")

        asked = serving.dialog_ask(record, "hello")

        self.assertEqual([one["key"] for one in asked["fields"]], ["who"])
        self.assertEqual(serving.dialog_run(record, "hello", {"who": "Ada"}),
                         {"message": "Hello, Ada"})

    def test_a_wrong_key_keeps_the_dialog_on_its_step_and_says_why(self) -> None:
        record = self.load("post_score")

        refused = serving.dialog_check(record, "post", {"key": "nope"}, "key")

        self.assertEqual(refused["step"], "key")
        self.assertEqual(refused["errors"], {"key": "The site did not accept that key"})

    def test_a_right_key_leads_to_the_score_and_then_to_a_summary_that_posts_it(self) -> None:
        record = self.load("post_score")

        score = serving.dialog_check(record, "post", {"key": practice_site.KEY}, "key")
        sure = serving.dialog_check(
            record, "post", {"key": practice_site.KEY, "player": "ADA", "table": "Taxi",
                             "score": 5_000_000}, "score")
        done = serving.dialog_run(
            record, "post", {"key": practice_site.KEY, "player": "ADA", "table": "Taxi",
                             "score": 5_000_000}, "sure")

        self.assertEqual(score["step"], "score")
        self.assertEqual(sure["step"], "sure")
        self.assertEqual(sure["summary"][2], ["Score", "5,000,000"])
        self.assertEqual(done, {"message": "Posted a score for Taxi"})
        self.assertIn("ADA", [one["player"] for one in self.posted_scores()])

    def test_the_site_being_down_is_the_services_failure_and_not_the_dialogs(self) -> None:
        record = self.load("post_score")
        self.site.shutdown()
        self.site.server_close()

        with self.assertLogs(logger_for("post_score").name, "WARNING"):
            with self.assertRaises(serving.ExtensionError) as raised:
                serving.dialog_check(record, "post", {"key": practice_site.KEY}, "key")

        self.assertTrue(raised.exception.unreachable)

    def test_a_long_job_reports_how_far_it_has_got_and_ends_when_it_is_stopped(self) -> None:
        record = self.load("slow_sync")

        started = serving.dialog_run(record, "sync", {})
        job = jobs.get(started["job_id"])
        self._until(lambda: job.pct > 0)
        stopped = serving.job_stop(record, "sync")
        self._until(lambda: job.state == jobs.DONE)

        self.assertEqual(stopped, {"stopped": True})
        self.assertTrue(job.stopped)
        self.assertLess(job.result["done"], 20)
        self.assertRegex(job.message, r"^Step \d+ of 20$")

    def test_a_game_ending_writes_a_line_to_the_extensions_log(self) -> None:
        self.load("play_log")

        with self.assertLogs(logger_for("play_log").name, "INFO") as logged:
            events.emit("table.play_recorded", game_id="medieval-madness", seconds=840,
                        private=False)

        self.assertEqual(logged.records[0].getMessage(),
                         "medieval-madness was played for 14 minutes")

    def test_the_list_says_the_key_was_refused_until_it_is_set_and_then_lists_best_first(
            self) -> None:
        record = self.load("top_scores")

        with self.assertLogs(logger_for("top_scores").name, "WARNING"):
            with self.assertRaises(serving.ExtensionError) as raised:
                serving.list_rows(record, "top")
        record.context.config.set("key", practice_site.KEY)
        rows = serving.list_rows(record, "top")["rows"]

        self.assertEqual(raised.exception.message, "The site did not accept the key")
        self.assertEqual([one["player"] for one in rows], ["AAA", "BEE", "CJ"])

    def test_the_rows_carry_what_a_verb_needs_and_a_verb_acts_on_the_rows_it_is_given(
            self) -> None:
        record = self.load("score_rows")
        record.context.config.set("key", practice_site.KEY)
        rows = serving.list_rows(record, "scores")["rows"]

        said = serving.list_verb(record, "scores", "flag", [rows[0]["id"]])
        flagged = serving.list_rows(record, "scores")["rows"]
        with self.assertRaisesRegex(RefusedError, "Already flagged"):
            serving.list_verb(record, "scores", "flag", [rows[0]["id"]])
        serving.list_verb(record, "scores", "remove", [rows[1]["id"]])

        self.assertEqual(rows[0]["page"], f"http://127.0.0.1:8790/scores/{rows[0]['id']}")
        self.assertEqual(said, {"message": "Flagged the score"})
        self.assertEqual([one["can_flag"] for one in flagged], [False, True, True])
        self.assertEqual([one["player"] for one in serving.list_rows(record, "scores")["rows"]],
                         ["AAA", "CJ"])

    def test_the_board_names_a_picture_only_as_an_address_core_serves_and_serves_it(
            self) -> None:
        record = self.load("weekly_board")
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        for module in (pictures, sized_media):
            patcher = unittest.mock.patch.object(
                module, "ROOT", Path(scratch.name) / module.__name__)
            patcher.start()
            self.addCleanup(patcher.stop)

        rows = serving.list_rows(record, "board")["rows"]
        served = serving.picture(record, rows[0]["art"].rsplit("/", 1)[1])

        self.assertEqual(["", ""], [one["art"] for one in rows[2:4]])
        self.assertRegex(rows[0]["art"], r"^/api/v1/ext/weekly_board/pictures/[0-9a-f]+$")
        self.assertEqual(rows[0]["art"], rows[1]["art"])
        self.assertTrue(served.path.is_file())
        self.assertEqual(["open", "closing", "closed", "cancelled", "planned"],
                         [one["status"] for one in rows])

    def test_the_challenge_pane_answers_a_row_and_keeps_what_is_set_in_it(self) -> None:
        record = self.load("challenge_pane")

        pane = serving.list_detail(record, "board", "mm")
        serving.list_save(record, "board", "mm", {"note": "Try the left ramp", "goal": "4"})
        again = serving.list_detail(record, "board", "mm")

        self.assertEqual((pane["title"], pane["under"]), ("Medieval Madness", "Week 41"))
        self.assertEqual([one["label"] for one in pane["sections"]], ["About", "Yours"])
        self.assertEqual(pane["sections"][0]["facts"][0]["tier"], "on")
        fields = {one["key"]: one["value"] for one in again["sections"][1]["fields"]}
        self.assertEqual((fields["note"], fields["goal"]), ("Try the left ramp", "4"))
        with self.assertRaises(NotFoundError):
            serving.list_detail(record, "board", "nobody")

    def test_the_game_notes_group_keeps_a_note_for_each_game_and_names_a_tables_version(
            self) -> None:
        record = self.load("game_notes")
        game = {"game_id": "g1", "vps_id": "v", "name": "Taxi"}

        serving.group_save(record, "game", game, {"note": "Left ramp"})
        mine = serving.group_read(record, "game", game)
        other = serving.group_read(record, "game", {**game, "game_id": "g2"})
        table = serving.group_read(record, "table", {
            **game, "table_id": "t1", "vps_file_id": "f9", "version": "1.2"})

        fields = {one["key"]: one["value"] for one in mine["section"]["fields"]}
        self.assertEqual((mine["title"], fields["note"]), ("Game Notes", "Left ramp"))
        self.assertEqual(other["section"]["fields"][0]["value"], "")
        self.assertEqual([one["value"] for one in table["section"]["facts"]], ["1.2", "f9"])
        self.assertEqual(table["title"], "This table")

    def test_the_tool_links_follow_the_port_and_fill_in_the_host_the_console_was_opened_at(
            self) -> None:
        record = self.load("tool_link")

        before = {one["key"]: one for one in record.links()}
        serving.settings_write(record, {"port": "9191"})
        after = {one["key"]: one for one in record.links()}

        self.assertEqual("http://{host}:9090/", before["console"]["url"])
        self.assertEqual("http://{host}:9191/", after["console"]["url"])
        self.assertEqual(("Tool console", "system"),
                         (after["console"]["label"], after["console"]["area"]))
        self.assertEqual("", after["manual"]["area"])
        self.assertEqual("http://cab:9191/",
                         ext_links.filled(after["console"]["url"], "cab"))

    def test_the_vpinos_recipe_runs_on_vpinos_and_names_the_distribution_it_is_refused_on(
            self) -> None:
        folder = EXAMPLES / "recipes" / "vpinos_only"
        with unittest.mock.patch.object(host, "this_platform", return_value="linux"), \
                unittest.mock.patch.object(host, "this_distribution",
                                           return_value=("ubuntu", "Ubuntu")):
            refused = self.registry.load(folder)
            checked, passed = check.check(folder)
        self.registry.clear()
        with unittest.mock.patch.object(host, "this_platform", return_value="linux"), \
                unittest.mock.patch.object(host, "this_distribution",
                                           return_value=("vpinos", "VPinOS")):
            self.load("vpinos_only")
            checked_there, _passed = check.check(folder)

        self.assertEqual((host.OFF, "It does not run on Ubuntu"),
                         (refused.state, refused.reason))
        self.assertTrue(passed)
        self.assertIn("platforms  vpinos - not this machine: It does not run on Ubuntu", checked)
        self.assertIn("platforms  vpinos", checked_there)

    def test_the_check_says_the_same_in_english_whatever_language_is_set(self) -> None:
        folder = EXAMPLES / "recipes" / "vpinos_only"
        self.addCleanup(i18n.set_language, i18n.language())
        i18n.set_language("qps")
        with unittest.mock.patch.object(host, "this_platform", return_value="linux"), \
                unittest.mock.patch.object(host, "this_distribution",
                                           return_value=("ubuntu", "Ubuntu")):
            checked, _passed = check.check(folder)

        self.assertIn("platforms  vpinos - not this machine: It does not run on Ubuntu", checked)

    @staticmethod
    def _until(done: Any, seconds: float = 10) -> None:
        stop = time.monotonic() + seconds
        while not done():
            if time.monotonic() > stop:
                raise AssertionError("Waited for the job and it did not get there")
            time.sleep(0.02)


class ScoreboardDoesWhatTheTutorialSays(ExamplesLoadedByTheHost):
    """The tutorial's extension, driven through each thing the tutorial says appears."""

    def setUp(self) -> None:
        super().setUp()
        self.record = self.load("scoreboard", SCOREBOARD)
        self.record.context.config.set("key", practice_site.KEY)

    def test_it_loads_and_passes_the_check_with_what_the_tutorial_says_it_declares(self) -> None:
        lines, passed = check.check(SCOREBOARD)

        self.assertTrue(passed, "\n".join(lines))
        shown = "\n".join(lines)
        for wanted in ("loads      scoreboard 1.0.0",
                       "settings   site (string, default 'http://127.0.0.1:8790')",
                       "settings   key (secret)",
                       "list       scores in community: 3 columns, 0 views, 3 verbs",
                       "dialog     post: ask check run"):
            self.assertIn(wanted, shown)

    def test_the_settings_page_has_the_site_and_a_key_that_is_never_sent_back(self) -> None:
        shown = serving.settings_read(self.record)["fields"]

        self.assertEqual([one["key"] for one in shown], ["site", "key"])
        self.assertEqual(shown[0]["placeholder"], "http://127.0.0.1:8790")
        self.assertEqual((shown[1]["type"], shown[1]["set"]), ("secret", True))
        self.assertNotIn("value", shown[1])

    def test_the_list_is_the_sites_scores_with_what_each_verb_needs_and_flag_dims_after_use(
            self) -> None:
        rows = serving.list_rows(self.record, "scores")["rows"]

        said = serving.list_verb(self.record, "scores", "flag", [rows[0]["id"]])
        after = serving.list_rows(self.record, "scores")["rows"]

        self.assertEqual([one["player"] for one in rows], ["AAA", "BEE", "CJ"])
        self.assertEqual(rows[0]["page"], f"http://127.0.0.1:8790/scores/{rows[0]['id']}")
        self.assertEqual(said, {"message": "Flagged the score"})
        self.assertEqual([one["can_flag"] for one in after], [False, True, True])
        with self.assertRaisesRegex(RefusedError, "Already flagged"):
            serving.list_verb(self.record, "scores", "flag", [rows[0]["id"]])

    def test_a_refused_key_says_so_in_the_pages_words(self) -> None:
        self.record.context.config.set("key", "nope")

        with self.assertLogs(logger_for("scoreboard").name, "WARNING"):
            with self.assertRaises(serving.ExtensionError) as raised:
                serving.list_rows(self.record, "scores")

        self.assertEqual(raised.exception.message, "The site did not accept the key")

    def test_the_dialog_names_each_missing_field_then_summarizes_then_posts(self) -> None:
        empty = serving.dialog_check(self.record, "post", {})
        values = {"player": "DEV", "table": "Twilight Zone", "score": 1_500_000}
        sure = serving.dialog_check(self.record, "post", values)
        done = serving.dialog_run(self.record, "post", values, "sure")

        self.assertEqual(empty["errors"], {"player": "This is needed", "table": "This is needed",
                                           "score": "This is needed"})
        self.assertEqual(sure["title"], "Post this score?")
        self.assertEqual(sure["summary"][2], ["Score", "1,500,000"])
        self.assertEqual(done, {"message": "Posted a score for Twilight Zone"})
        self.assertIn("DEV", [one["player"] for one in self.posted_scores()])

    def test_a_game_ending_writes_a_line_to_the_extensions_log(self) -> None:
        with self.assertLogs(logger_for("scoreboard").name, "INFO") as logged:
            events.emit("table.play_recorded", game_id="medieval-madness", seconds=840,
                        private=False)

        self.assertEqual(logged.records[0].getMessage(),
                         "medieval-madness was played for 14 minutes")

    def test_one_minute_reads_in_the_singular_and_a_private_game_writes_nothing(self) -> None:
        with self.assertLogs(logger_for("scoreboard").name, "INFO") as logged:
            events.emit("table.play_recorded", game_id="a", seconds=60, private=True)
            events.emit("table.play_recorded", game_id="b", seconds=60, private=False)

        self.assertEqual([one.getMessage() for one in logged.records],
                         ["b was played for a minute"])


# A line holding only a path in backticks, then the block that is that file.
BLOCK = re.compile(r"^`([\w./-]+\.\w+)`\n\n```\w*\n(.*?)^```$", re.S | re.M)
# The same with "(excerpt)" after the path, then a piece of that file.
EXCERPT = re.compile(r"^`([\w./-]+\.\w+)` \(excerpt\)\n\n```\w*\n(.*?)^```$", re.S | re.M)


class CodeBlocksAreFiles(unittest.TestCase):
    def blocks(self, page: Path) -> list[tuple[str, str]]:
        return [(m.group(1), m.group(2)) for m in BLOCK.finditer(page.read_text())]

    def test_a_block_headed_with_a_path_is_that_file(self) -> None:
        found = 0
        for page in PAGES:
            for path, text in self.blocks(page):
                found += 1
                with self.subTest(f"{page.name}: {path}"):
                    self.assertTrue((EXAMPLES / path).is_file(), f"{path} is not a file")
                    self.assertEqual(text, (EXAMPLES / path).read_text())
        self.assertGreater(found, 0, "no block names a file, so nothing was held to one")

    def test_an_excerpt_is_a_piece_of_the_file_it_names(self) -> None:
        found = 0
        for page in PAGES:
            for match in EXCERPT.finditer(page.read_text()):
                found += 1
                path, text = match.group(1), match.group(2).rstrip("\n")
                with self.subTest(f"{page.name}: {path}: {text.splitlines()[0].strip()}"):
                    self.assertTrue((EXAMPLES / path).is_file(), f"{path} is not a file")
                    whole = (EXAMPLES / path).read_text()
                    if path.endswith(".json"):
                        self.assertTrue(self.in_order(text.splitlines(), whole.splitlines()))
                    else:
                        self.assertIn(text, whole)
        self.assertGreater(found, 0, "no block is an excerpt, so none was held to its file")

    @staticmethod
    def in_order(wanted: list[str], lines: list[str]) -> bool:
        """Every wanted line is in `lines`, in the same order, not necessarily side by side."""
        rest = iter(lines)
        return all(any(line == one for one in rest) for line in wanted)

    def test_the_tutorial_shows_every_file_of_the_scoreboard_whole(self) -> None:
        shown = {path for path, _ in self.blocks(GUIDE / "tutorial.md")}
        for one in SCOREBOARD.rglob("*"):
            if one.is_file() and "__pycache__" not in one.parts:
                name = one.relative_to(EXAMPLES).as_posix()
                with self.subTest(name):
                    self.assertIn(name, shown)

    def test_every_file_of_a_recipe_is_shown_by_the_cookbook(self) -> None:
        cookbook = GUIDE / "cookbook.md"
        shown = {path for path, _ in self.blocks(cookbook)}
        for folder in RECIPES:
            for one in folder.rglob("*"):
                if one.is_file() and "__pycache__" not in one.parts:
                    name = one.relative_to(EXAMPLES).as_posix()
                    with self.subTest(name):
                        if one.suffix == ".png":
                            self.assertIn(f"`{name}`", cookbook.read_text())
                        else:
                            self.assertIn(name, shown)


LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)\)")
FENCE = re.compile(r"^```.*?^```", re.S | re.M)
HEADING = re.compile(r"^#{1,6}\s+(.*?)\s*$", re.M)


def slug(heading: str) -> str:
    """How GitHub spells a heading as an address."""
    text = re.sub(r"[`*_]", "", heading).lower()
    return re.sub(r"[^\w\- ]", "", text).strip().replace(" ", "-")


def anchors(page: Path) -> set[str]:
    return {slug(one) for one in HEADING.findall(FENCE.sub("", page.read_text()))}


def links(page: Path) -> Iterator[str]:
    yield from LINK.findall(FENCE.sub("", page.read_text()))


class LinksResolve(unittest.TestCase):
    def test_every_link_in_the_guide_goes_to_a_file_and_a_heading_that_exist(self) -> None:
        found = 0
        for page in PAGES:
            for link in links(page):
                if re.match(r"[a-z]+:", link):
                    continue
                found += 1
                target, _, anchor = link.partition("#")
                there = (page.parent / target).resolve() if target else page
                with self.subTest(f"{page.name}: {link}"):
                    self.assertTrue(there.exists(), f"{link} goes nowhere")
                    if anchor:
                        self.assertTrue(there.suffix == ".md" and there.is_file())
                        self.assertIn(anchor, anchors(there))
        self.assertGreater(found, 0)

    def test_an_address_is_spelled_the_way_a_heading_is(self) -> None:
        self.assertEqual(slug("4. A dialog with steps and a check"),
                         "4-a-dialog-with-steps-and-a-check")
        self.assertEqual(slug("`ctx.ui.list`"), "ctxuilist")


REFERENCE_PAGES = sorted((GUIDE / "reference").glob("*.md"))


def reference_text() -> str:
    """Every page of the reference as one text."""
    return "\n".join(page.read_text() for page in REFERENCE_PAGES)


def reference_sections() -> dict[str, str]:
    """Each `ctx.` call's name against the text under its heading, to the next heading of any
    level. A heading that only introduces the calls under it (`ctx.ui`) is not a call."""
    found: dict[str, str] = {}
    for match in re.finditer(r"^#{2,4} `(ctx\.[^`]+)`\n(.*?)(?=^#{1,4} |\Z)", reference_text(),
                             re.M | re.S):
        found[match.group(1)] = match.group(2)
    return {name: text for name, text in found.items()
            if not any(other.startswith(name + ".") for other in found)}


def table_first_column(header: str) -> set[str]:
    """The backticked first cells of the last table whose header row reads `| <header> |`
    (the settings types are listed twice, the later list being the comparison)."""
    text = reference_text()
    starts = list(re.finditer(rf"^\| {re.escape(header)} \|$", text, re.M))
    assert starts, f"no table headed {header!r}"
    start = starts[-1]
    names: set[str] = set()
    for row in text[start.end():].lstrip("\n").splitlines()[1:]:
        if not row.startswith("|"):
            break
        names.update(re.findall(r"`([^`]+)`", row.split("|")[1]))
    return names


def table_column_yes(header: str, column: int) -> set[str]:
    """The types of the table headed `| <header> |` whose cell in `column` (counting from
    the asks-for cell as 1) reads `yes`."""
    text = reference_text()
    start = re.search(rf"^\| {re.escape(header)} \|$", text, re.M)
    assert start, f"no table headed {header!r}"
    names: set[str] = set()
    for row in text[start.end():].lstrip("\n").splitlines()[1:]:
        if not row.startswith("|"):
            break
        cells = [cell.strip() for cell in row.strip("|").split("|")]
        if cells[column] == "yes":
            names.update(re.findall(r"`([^`]+)`", cells[0]))
    return names


class ReferenceMatchesCore(unittest.TestCase):
    """The reference lists what core accepts, and nothing it does not."""

    @classmethod
    def setUpClass(cls) -> None:
        manifest = contract.parse({"name": "refcheck", "requires_platform": 1})
        with tempfile.TemporaryDirectory() as folder:
            cls.ctx = ExtensionContext(manifest, store.ExtensionStore(folder),
                                       on_failure=lambda why: None)
        cls.sections = reference_sections()

    def drawn(self) -> set[str]:
        """Every `ctx.` name core offers: the context's own, and each container's."""
        names: set[str] = set()
        for one in set(vars(self.ctx)) | set(vars(ExtensionContext)):
            if one.startswith("_"):
                continue
            value = getattr(self.ctx, one)
            if type(value).__module__.startswith("common.extensions.") \
                    and type(value).__name__.startswith("Extension"):
                # The state a container keeps for core's own reading is not an API.
                for inner, member in vars(type(value)).items():
                    if not inner.startswith("_") and (callable(member) or inner.isupper()):
                        names.add(f"ctx.{one}.{inner}")
            else:
                names.add(f"ctx.{one}")
        return names

    def test_every_ctx_call_core_has_is_a_heading_and_every_heading_is_a_call(self) -> None:
        self.assertEqual(set(self.sections), self.drawn())

    def test_every_keyword_a_declaration_takes_is_named_in_the_reference(self) -> None:
        text = reference_text()
        for heading in ("ctx.ui.settings", "ctx.ui.list", "ctx.ui.action", "ctx.ui.account",
                        "ctx.jobs.submit"):
            target: Any = self.ctx
            for part in heading.split(".")[1:]:
                target = getattr(target, part)
            for name in inspect.signature(target).parameters:
                with self.subTest(f"{heading} {name}"):
                    self.assertRegex(text, rf"\b{name}\b")

    def test_the_field_types_the_reference_lists_are_the_ones_each_surface_draws(self) -> None:
        header = "type | asks for | dialog | settings | account"
        self.assertEqual(table_first_column(header), set(fields.DIALOG_TYPES))
        self.assertEqual(table_column_yes(header, 2), set(fields.DIALOG_TYPES))
        self.assertEqual(table_column_yes(header, 3), set(fields.SETTINGS_TYPES))

    def test_the_cell_kinds_a_column_may_have_are_all_named(self) -> None:
        for kind in COLUMN_KINDS:
            with self.subTest(kind=kind):
                self.assertIn(f"`{kind}`", reference_text())

    def test_the_step_vocabulary_is_named_whole(self) -> None:
        text = reference_text()
        for key in fields.STEP_KEYS:
            with self.subTest(key=key):
                self.assertIn(f"`{key}`", text)


if __name__ == "__main__":
    unittest.main()
