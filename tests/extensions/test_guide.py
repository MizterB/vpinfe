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
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from common import events, i18n, jobs
from common.extensions import check, contract, fields, host, serving, store
from common.extensions.context import COLUMN_KINDS, ExtensionContext, logger_for
from common.service_errors import RefusedError

GUIDE = Path(__file__).resolve().parents[2] / "docs" / "extensions"
EXAMPLES = GUIDE / "examples"
RECIPES = sorted(one for one in (EXAMPLES / "recipes").iterdir() if one.is_dir())
PAGES = sorted(GUIDE.glob("*.md"))

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
    "score_rows": ["list       scores in community: 3 columns, 0 views, 3 verbs"],
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


class RecipesDoWhatTheyClaim(unittest.TestCase):
    """The recipes loaded as the host loads them, and driven through what core serves."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.registry = host.Registry(store.ExtensionStore(Path(tmp.name)))
        self.addCleanup(self.registry.clear)
        jobs.reset_for_tests()
        self.site = serving_practice_site()
        self.addCleanup(self.site.server_close)
        self.addCleanup(self.site.shutdown)

    def load(self, name: str) -> host.Record:
        self.addCleanup(i18n.disown, f"ext.{name}")
        record = self.registry.load(EXAMPLES / "recipes" / name)
        self.assertEqual(record.state, host.LOADED, record.error)
        return record

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
        self.assertIn("ADA", [one["player"] for one in self._top()])

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

    def _top(self) -> list[dict]:
        request = urllib.request.Request(
            f"http://{practice_site.HOST}:{practice_site.PORT}/top",
            headers={"X-API-Key": practice_site.KEY})
        with urllib.request.urlopen(request, timeout=5) as answer:
            return json.loads(answer.read())

    @staticmethod
    def _until(done: Any, seconds: float = 10) -> None:
        stop = time.monotonic() + seconds
        while not done():
            if time.monotonic() > stop:
                raise AssertionError("Waited for the job and it did not get there")
            time.sleep(0.02)


# A line holding only a path in backticks, then the block that is that file.
BLOCK = re.compile(r"^`([\w./-]+\.\w+)`\n\n```\w*\n(.*?)^```$", re.S | re.M)


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

    def test_every_file_of_a_recipe_is_shown_by_the_cookbook(self) -> None:
        shown = {path for path, _ in self.blocks(GUIDE / "cookbook.md")}
        for folder in RECIPES:
            for one in folder.rglob("*"):
                if one.is_file() and "__pycache__" not in one.parts:
                    name = one.relative_to(EXAMPLES).as_posix()
                    with self.subTest(name):
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


REFERENCE = GUIDE / "reference.md"


def reference_sections() -> dict[str, str]:
    """Each `####` heading's name against the text under it, to the next heading of any level."""
    text = REFERENCE.read_text()
    found: dict[str, str] = {}
    for match in re.finditer(r"^#### `([^`]+)`\n(.*?)(?=^#{1,4} |\Z)", text, re.M | re.S):
        found[match.group(1)] = match.group(2)
    return found


def table_first_column(header: str) -> set[str]:
    """The backticked first cells of the last table whose header row reads `| <header> |`
    (the settings types are listed twice, the later list being the comparison)."""
    text = REFERENCE.read_text()
    starts = list(re.finditer(rf"^\| {re.escape(header)} \|$", text, re.M))
    assert starts, f"no table headed {header!r}"
    start = starts[-1]
    names: set[str] = set()
    for row in text[start.end():].lstrip("\n").splitlines()[1:]:
        if not row.startswith("|"):
            break
        names.update(re.findall(r"`([^`]+)`", row.split("|")[1]))
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
        text = REFERENCE.read_text()
        for heading in ("ctx.ui.settings", "ctx.ui.list", "ctx.ui.action", "ctx.ui.account",
                        "ctx.jobs.submit"):
            target: Any = self.ctx
            for part in heading.split(".")[1:]:
                target = getattr(target, part)
            for name in inspect.signature(target).parameters:
                with self.subTest(f"{heading} {name}"):
                    self.assertRegex(text, rf"\b{name}\b")

    def test_the_field_types_the_reference_lists_are_the_ones_each_surface_draws(self) -> None:
        self.assertEqual(table_first_column("type | asks for"), set(fields.DIALOG_TYPES))
        self.assertEqual(table_first_column("type | draws"), set(fields.SETTINGS_TYPES))

    def test_the_cell_kinds_a_column_may_have_are_all_named(self) -> None:
        for kind in COLUMN_KINDS:
            with self.subTest(kind=kind):
                self.assertIn(f"`{kind}`", REFERENCE.read_text())

    def test_the_step_vocabulary_is_named_whole(self) -> None:
        text = REFERENCE.read_text()
        for key in fields.STEP_KEYS:
            with self.subTest(key=key):
                self.assertIn(f"`{key}`", text)


if __name__ == "__main__":
    unittest.main()
