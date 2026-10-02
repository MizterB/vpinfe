"""The dialog host's own new drawing: `ready`/`reason` on any step, `acts`, the step
row an answer's `steps` draws, and reopening a done step through it - all proven with
a fake flow, since the importer sends none of this."""

from __future__ import annotations

import asyncio
import contextlib
import unittest
from collections.abc import Callable
from typing import Any
from unittest import mock

from nicegui import core, ui

from console import wizard
from tests.support.clicks import said

# Made at import, outside any task, where NiceGUI still hands out the script's own page.
_PAGE = ui.element()


def _calls(*, first: dict[str, Any],
          on_check: Callable[[dict[str, Any], str], dict[str, Any]] | None = None,
          on_act: Callable[[str, dict[str, Any], str], dict[str, Any]] | None = None,
          on_goto: Callable[[str], dict[str, Any]] | None = None,
          on_run: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
          on_job: Callable[[str], dict[str, Any]] | None = None) -> wizard.Calls:
    async def first_call(step: str | None = None) -> dict:
        if step is None:
            return first
        if on_goto is None:
            raise AssertionError("this flow answers no step by key")
        return on_goto(step)

    async def check(values: dict[str, Any], step: str) -> dict:
        if on_check is None:
            raise AssertionError("this flow answers no check")
        return on_check(values, step)

    async def act(key: str, values: dict[str, Any], step: str) -> dict:
        if on_act is None:
            raise AssertionError("this flow answers no act")
        return on_act(key, values, step)

    async def run(values: dict[str, Any]) -> dict:
        return on_run(values) if on_run is not None else {"ok": True}

    async def job(job_id: str) -> dict:
        if on_job is None:
            raise AssertionError("no test here drives a job")
        return on_job(job_id)

    return wizard.Calls(first_call, check, act, run, job)


async def _settled() -> None:
    for _ in range(8):
        await asyncio.sleep(0)


async def _opened(calls: wizard.Calls) -> tuple[asyncio.Task, ui.dialog]:
    """The dialog running as its own task, past its first draw."""
    async def go() -> None:
        with _PAGE:
            await wizard.open_dialog(label="Test", calls=calls, under="test.action")

    was = set(_PAGE.client.layout.descendants())
    task = asyncio.create_task(go())
    await _settled()
    dialog = next(one for one in set(_PAGE.client.layout.descendants()) - was
                  if isinstance(one, ui.dialog))
    return task, dialog


async def _finished(task: asyncio.Task) -> None:
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


def _forward(dialog: ui.dialog) -> ui.button:
    return next(one for one in dialog.descendants()
               if isinstance(one, ui.button) and wizard._FORWARD in one.classes)


def _labelled(dialog: ui.dialog, text: str) -> ui.label:
    return next(one for one in dialog.descendants()
               if isinstance(one, ui.label) and one.text == text)


def _labelled_in(root: ui.element) -> ui.label:
    return next(one for one in root.descendants() if isinstance(one, ui.label))


def _segments(root: ui.element) -> list[tuple[str, str, bool]]:
    """Each step of the row as (name, state, reopens): `here`, `done` or '' for one still
    ahead, and whether its name answers a click."""
    found = []
    for one in root.descendants():
        if "console-wizard-step" not in one.classes:
            continue
        name = next(inner for inner in one.descendants() if isinstance(inner, ui.label))
        state = next((c.removeprefix("console-wizard-step--") for c in one.classes
                      if c.startswith("console-wizard-step--")), "")
        found.append((name.text, state, "console-link" in name.classes))
    return found


def _ran(run: Callable[[], Any]) -> Any:
    """`run`, with NiceGUI's loop set so a handler's own task is started at all."""
    async def inside() -> Any:
        was = core.loop
        core.loop = asyncio.get_running_loop()
        try:
            return await run()
        finally:
            core.loop = was

    return asyncio.run(inside())


class NotReadyTests(unittest.TestCase):
    def test_a_plain_step_held_not_ready_disables_next_and_says_why(self) -> None:
        first = {"step": "one", "fields": [], "ready": False, "reason": "Pick something first"}

        async def run() -> tuple[bool, str]:
            task, dialog = await _opened(_calls(first=first))
            disabled = _forward(dialog)._props.get("disable", False)
            reason = _labelled(dialog, "Pick something first").text
            await _finished(task)
            return disabled, reason

        disabled, reason = _ran(run)
        self.assertEqual((True, "Pick something first"), (disabled, reason))

    def test_ready_absent_leaves_a_plain_step_alone(self) -> None:
        first = {"step": "one", "fields": []}

        async def run() -> bool:
            task, dialog = await _opened(_calls(first=first))
            disabled = _forward(dialog)._props.get("disable", False)
            await _finished(task)
            return disabled

        self.assertFalse(_ran(run))


class ActTests(unittest.TestCase):
    def test_pressing_an_act_asks_for_it_by_key_and_redraws_the_same_step(self) -> None:
        first = {"step": "one", "fields": [], "acts": [{"key": "connect", "label": "Connect"}],
                 "ready": False, "reason": "Not connected"}
        redrawn = {"step": "one", "fields": [], "notes": ["Connected"], "ready": True}
        acted: list[tuple[str, str]] = []

        def acting(key: str, values: dict[str, Any], step: str) -> dict[str, Any]:
            acted.append((key, step))
            return redrawn

        async def run() -> tuple[list[tuple[str, str]], str, bool]:
            task, dialog = await _opened(_calls(first=first, on_act=acting))
            said(next(one for one in dialog.descendants()
                     if isinstance(one, ui.button) and one.text == "Connect"), "click")
            await _settled()
            note = _labelled(dialog, "Connected").text
            disabled = _forward(dialog)._props.get("disable", False)
            await _finished(task)
            return acted, note, disabled

        found, note, disabled = _ran(run)
        self.assertEqual([("connect", "one")], found)
        self.assertEqual("Connected", note)
        self.assertFalse(disabled)


class StepRowTests(unittest.TestCase):
    def test_no_steps_key_draws_no_row(self) -> None:
        first = {"step": "one", "fields": []}

        async def run() -> bool:
            task, dialog = await _opened(_calls(first=first))
            found = any("console-wizard-steps" in one.classes for one in dialog.descendants())
            await _finished(task)
            return found

        self.assertFalse(_ran(run))

    def test_the_row_has_one_segment_per_step_and_only_a_done_one_reopens(self) -> None:
        first = {"step": "two", "fields": [],
                 "steps": [{"key": "one", "label": "One", "done": True},
                          {"key": "two", "label": "Two", "done": False},
                          {"key": "three", "label": "Three", "done": False}]}

        async def run() -> list[tuple[str, str, bool]]:
            task, dialog = await _opened(_calls(first=first))
            found = _segments(dialog)
            await _finished(task)
            return found

        self.assertEqual([("One", "done", True), ("Two", "here", False),
                          ("Three", "", False)], _ran(run))

    def test_the_current_segment_alone_says_it_is_the_current_step(self) -> None:
        first = {"step": "two", "fields": [],
                 "steps": [{"key": "one", "label": "One", "done": True},
                          {"key": "two", "label": "Two", "done": False},
                          {"key": "three", "label": "Three", "done": False}]}

        async def run() -> list[tuple[str, str | None]]:
            task, dialog = await _opened(_calls(first=first))
            found = [(_labelled_in(one).text, one.props.get("aria-current"))
                     for one in dialog.descendants() if "console-wizard-step" in one.classes]
            await _finished(task)
            return found

        self.assertEqual([("One", None), ("Two", "step"), ("Three", None)], _ran(run))

    def test_the_row_stays_put_while_the_body_scrolls(self) -> None:
        first = {"step": "one", "title": "Question", "help": "Why", "fields": [],
                 "steps": [{"key": "one", "label": "One", "done": False}]}

        async def run() -> tuple[bool, bool, bool]:
            task, dialog = await _opened(_calls(first=first))
            scroll = next(one for one in dialog.descendants()
                         if "console-wizard-scroll" in one.classes)
            inside = {id(one) for one in scroll.descendants()}
            row = next(one for one in dialog.descendants()
                      if "console-wizard-steps" in one.classes)
            footer = next(one for one in dialog.descendants()
                         if "console-dialog-footer" in one.classes)
            lead = _labelled(dialog, "Why")
            await _finished(task)
            return id(row) not in inside, id(footer) not in inside, id(lead) in inside

        self.assertEqual((True, True, True), _ran(run))

    def test_clicking_a_done_step_reopens_it_by_key(self) -> None:
        first = {"step": "two", "fields": [],
                 "steps": [{"key": "one", "label": "One", "done": True},
                          {"key": "two", "label": "Two", "done": False}]}
        reopened = {"step": "one", "fields": [], "notes": ["Back on one"],
                   "steps": first["steps"]}
        asked: list[str] = []

        def going(key: str) -> dict[str, Any]:
            asked.append(key)
            return reopened

        async def run() -> tuple[list[str], str]:
            task, dialog = await _opened(_calls(first=first, on_goto=going))
            said(_labelled(dialog, "One"), "click")
            await _settled()
            note = _labelled(dialog, "Back on one").text
            await _finished(task)
            return asked, note

        asked, note = _ran(run)
        self.assertEqual(["one"], asked)
        self.assertEqual("Back on one", note)


class RowOnRunTests(unittest.TestCase):
    """The row says where a person is in the steps, and a run is not one of them."""

    _last = {"step": "review", "fields": [], "summary": [["Folder", "/tables"]],
             "steps": [{"key": "one", "label": "One", "done": True},
                      {"key": "review", "label": "Review", "done": False}]}

    def _pressed(self, calls: wizard.Calls) -> tuple[list[tuple[str, str, bool]], list[str]]:
        async def run() -> tuple[list[tuple[str, str, bool]], list[str]]:
            task, dialog = await _opened(calls)
            said(_forward(dialog), "click")
            await _settled()
            found = (_segments(dialog),
                     [one.text for one in dialog.descendants() if isinstance(one, ui.label)])
            await _finished(task)
            return found

        return _ran(run)

    def test_a_run_that_finishes_at_once_takes_the_row_away(self) -> None:
        segments, words = self._pressed(_calls(
            first=self._last, on_run=lambda values: {"ok": True, "message": "All set"}))

        self.assertEqual([], segments)
        self.assertIn("All set", words)

    def test_a_run_that_becomes_a_job_takes_the_row_away(self) -> None:
        segments, _words = self._pressed(_calls(
            first=self._last, on_run=lambda values: {"job_id": "j1"},
            on_job=lambda job_id: {"state": "done", "pct": 100}))

        self.assertEqual([], segments)

    def test_a_run_that_is_refused_leaves_the_row_for_the_step_it_is_still_on(self) -> None:
        with mock.patch.object(ui, "notify"):
            segments, _words = self._pressed(_calls(
                first=self._last,
                on_run=lambda values: {"ok": False, "reason": "Not yet"}))

        self.assertEqual([("One", "done", True), ("Review", "here", False)], segments)


class TitleFocusTests(unittest.TestCase):
    def test_a_step_transition_focuses_the_title_not_a_field(self) -> None:
        first = {"step": "one", "fields": [{"key": "name", "type": "string", "label": "Name"}]}
        second = {"step": "two", "fields": []}

        async def run() -> list[str]:
            with mock.patch.object(ui, "run_javascript") as js:
                task, dialog = await _opened(_calls(first=first, on_check=lambda v, s: second))
                heading = next(one for one in dialog.descendants()
                              if "console-dialog-title" in one.classes)
                js.reset_mock()
                said(_forward(dialog), "click")
                await _settled()
                calls_seen = [call.args[0] for call in js.call_args_list]
            await _finished(task)
            return [text for text in calls_seen if f"c{heading.id}" in text]

        self.assertTrue(_ran(run))

    def test_an_act_redraw_focuses_the_field_not_the_title(self) -> None:
        first = {"step": "one", "fields": [{"key": "name", "type": "string", "label": "Name"}],
                 "acts": [{"key": "go", "label": "Go"}]}
        redrawn = {"step": "one", "fields": [{"key": "name", "type": "string", "label": "Name"}]}

        async def run() -> bool:
            with mock.patch.object(ui, "run_javascript") as js:
                task, dialog = await _opened(_calls(first=first, on_act=lambda k, v, s: redrawn))
                heading = next(one for one in dialog.descendants()
                              if "console-dialog-title" in one.classes)
                js.reset_mock()
                said(next(one for one in dialog.descendants()
                         if isinstance(one, ui.button) and one.text == "Go"), "click")
                await _settled()
                calls_seen = [call.args[0] for call in js.call_args_list]
            await _finished(task)
            return any(f"c{heading.id}" in text for text in calls_seen)

        self.assertFalse(_ran(run))



class FieldTypeTests(unittest.TestCase):
    def _drawn(self, field: dict[str, Any], errors: dict[str, Any] | None = None
              ) -> tuple[dict[str, Any], dict[str, tuple[str, Any]], ui.element]:
        from console.api import ApiClient

        values: dict[str, Any] = {}
        with _PAGE:
            holder = ui.column()
            with holder:
                held = wizard._controls([field], values, client=mock.Mock(spec=ApiClient),
                                        errors=errors or {})
        return values, held, holder

    def test_a_choice_field_draws_its_options_and_their_help(self) -> None:
        field = {"key": "layout", "type": "choice", "label": "Layout",
                "choices": [["desktop", "Desktop", "Windowed, no cabinet hardware."],
                           ["cabinet", "Cabinet", "Full screen across the cabinet."]],
                "value": "desktop"}

        _values, _held, holder = self._drawn(field)

        radio = next(one for one in holder.descendants() if isinstance(one, ui.radio))
        helps = [one.text for one in holder.descendants()
                if isinstance(one, ui.label) and "console-help" in one.classes]
        self.assertEqual({"desktop": "Desktop", "cabinet": "Cabinet"}, radio.options)
        self.assertEqual(["Windowed, no cabinet hardware.", "Full screen across the cabinet."],
                         helps)

    def test_a_number_field_carries_its_unit_and_bounds(self) -> None:
        field = {"key": "screens", "type": "number", "label": "Screens",
                "unit": "screens", "min": 1, "max": 4, "value": 2}

        _values, _held, holder = self._drawn(field)

        control = next(one for one in holder.descendants() if isinstance(one, ui.number))
        self.assertEqual((2, "screens", 1, 4), (control.value, control.suffix,
                                                control.min, control.max))

    def test_sync_reads_a_cleared_number_back_as_none_not_the_word_none(self) -> None:
        field = {"key": "screens", "type": "number", "label": "Screens", "value": 2}
        values, held, holder = self._drawn(field)
        control = next(one for one in holder.descendants() if isinstance(one, ui.number))

        control.value = None
        wizard._sync(values, held)

        self.assertIsNone(values["screens"])


class RefusalTests(unittest.TestCase):
    """A refusal is drawn under its field, whatever kind of control the field is."""

    _drawn = FieldTypeTests._drawn

    def _lines(self, holder: ui.element) -> list[str]:
        return [one.text for one in holder.descendants()
                if isinstance(one, ui.label) and "text-negative" in one.classes]

    def test_a_refused_choice_says_so_under_its_options(self) -> None:
        field = {"key": "layout", "type": "choice", "label": "Layout", "value": "desktop",
                "choices": [["desktop", "Desktop", "One screen"],
                           ["cabinet", "Cabinet", "Several screens"]]}

        _values, _held, holder = self._drawn(field, {"layout": "Not on this machine"})

        self.assertEqual(["Not on this machine"], self._lines(holder))

    def test_a_choice_with_nothing_picked_draws_and_can_be_refused(self) -> None:
        field = {"key": "layout", "type": "choice", "label": "Layout", "value": None,
                "choices": [["desktop", "Desktop", "One screen"],
                           ["cabinet", "Cabinet", "Several screens"]]}

        _values, held, holder = self._drawn(field, {"layout": "Pick one to go on"})

        self.assertIsNone(held["layout"][1].value)
        self.assertEqual(["Pick one to go on"], self._lines(holder))

    def test_a_refused_switch_says_so_under_it(self) -> None:
        field = {"key": "sound", "type": "switch", "label": "Sound", "value": False}

        _values, _held, holder = self._drawn(field, {"sound": "Needs a sound card"})

        self.assertEqual(["Needs a sound card"], self._lines(holder))

    def test_a_refusal_with_a_reason_carries_it_as_the_line_s_tooltip(self) -> None:
        field = {"key": "layout", "type": "choice", "label": "Layout", "value": "desktop",
                "choices": [["desktop", "Desktop", ""], ["cabinet", "Cabinet", ""]]}

        _values, _held, holder = self._drawn(
            field, {"layout": {"text": "Pick one to go on", "detail": "Nothing is chosen"}})

        line = next(one for one in holder.descendants()
                   if isinstance(one, ui.label) and "text-negative" in one.classes)
        tips = [one.text for one in holder.descendants()
               if isinstance(one, ui.tooltip) and one._props.get("target") == f"#c{line.id}"]
        self.assertEqual(["Nothing is chosen"], tips)

    def test_a_field_that_can_show_its_own_refusal_keeps_it_in_its_props(self) -> None:
        field = {"key": "name", "type": "string", "label": "Name", "value": ""}

        _values, held, holder = self._drawn(field, {"name": "Needs a name"})

        control = held["name"][1]
        self.assertEqual("Needs a name", control.props["error-message"])
        self.assertEqual([], self._lines(holder))

    def test_a_field_with_no_refusal_draws_none(self) -> None:
        field = {"key": "layout", "type": "choice", "label": "Layout", "value": "desktop",
                "choices": [["desktop", "Desktop", ""], ["cabinet", "Cabinet", ""]]}

        _values, _held, holder = self._drawn(field)

        self.assertEqual([], self._lines(holder))


if __name__ == "__main__":
    unittest.main()
