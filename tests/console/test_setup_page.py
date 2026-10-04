"""Setup's own shape: what each step draws, what answering it writes, where it reopens, and
how the path through `STEPS` behaves - the last proven with fake steps, since the real
list holds one and every later step relies on the same mechanics."""

from __future__ import annotations

import asyncio
import json
import unittest
from typing import Any
from unittest import mock

from nicegui import ui

from common import install_setup
from common.config_store import ConfigStore
from common.games.launchers import Launcher
from console import setup, setup_tables, setup_vpx
from tests.support.library import TempTree

# Made at import, outside any task, where NiceGUI still hands out the script's own page.
_PAGE = ui.element()


def _ran(coro: Any) -> Any:
    return asyncio.run(coro)


class _Fresh(TempTree):
    """An install that has just been created, in a temporary folder."""

    def setUp(self) -> None:
        super().setUp()
        self.store = ConfigStore(str(self.root / "vpinfe.ini"))
        patch = mock.patch.object(setup, "_config", return_value=self.store)
        patch.start()
        self.addCleanup(patch.stop)

    def _screens(self, count: int) -> Any:
        return mock.patch.object(setup, "_screens_here", mock.AsyncMock(return_value=count))


class AskHowTests(_Fresh):
    def _field(self, step: dict[str, Any]) -> dict[str, Any]:
        (field,) = step["fields"]
        return field

    def test_one_screen_preselects_desktop(self) -> None:
        with self._screens(1):
            step = _ran(setup._ask_how(setup.Session(again=False)))

        self.assertEqual(self._field(step)["value"], "desktop")

    def test_two_screens_preselect_cabinet(self) -> None:
        with self._screens(2):
            step = _ran(setup._ask_how(setup.Session(again=False)))

        self.assertEqual(self._field(step)["value"], "cabinet")

    def test_screens_that_cannot_be_counted_preselect_desktop(self) -> None:
        with mock.patch.object(setup.screens, "connected", side_effect=RuntimeError("no")), \
             self.assertLogs("vpinfe.console.setup", level="WARNING"):
            step = _ran(setup._ask_how(setup.Session(again=False)))

        self.assertEqual(self._field(step)["value"], "desktop")

    def test_both_answers_are_picture_tiles(self) -> None:
        with self._screens(1):
            step = _ran(setup._ask_how(setup.Session(again=False)))

        choices = self._field(step)["choices"]
        self.assertEqual([(key, picture) for key, _label, _help, picture in choices],
                         [("desktop", "desktop"), ("cabinet", "cabinet")])
        self.assertTrue(all(label and hint for _key, label, hint, _picture in choices))

    def test_the_first_time_it_is_the_welcome(self) -> None:
        with self._screens(1):
            step = _ran(setup._ask_how(setup.Session(again=False)))

        self.assertTrue(step["welcome"])
        self.assertEqual(step["title"], "Welcome to VPinFE")

    def test_an_answer_already_given_beats_the_screen_count(self) -> None:
        self.store.set_value("presentation", "cab_mode", False)
        install_setup.answer(self.store, setup.HOW)

        with self._screens(3):
            step = _ran(setup._ask_how(setup.Session(again=False)))

        self.assertEqual(self._field(step)["value"], "desktop")

    def test_asked_again_it_opens_on_the_current_answer_titled_setup(self) -> None:
        self.store.set_value("presentation", "cab_mode", True)

        with self._screens(1):
            step = _ran(setup._ask_how(setup.Session(again=True)))

        self.assertEqual(self._field(step)["value"], "cabinet")
        self.assertFalse(step["welcome"])
        self.assertEqual(step["title"], "Setup")
        self.assertEqual(step["help"], self._field(step)["label"],
                         "the title is no longer the question, so the lead asks it")

    def test_the_window_the_frontend_opened_says_where_else_to_reach_setup(self) -> None:
        with self._screens(1), mock.patch.object(setup, "_address",
                                                 return_value="http://192.168.1.20:8001"):
            step = _ran(setup._ask_how(setup.Session(again=False, window=True)))

        self.assertEqual(step["notes"],
                         ["From another computer, open http://192.168.1.20:8001"])

    def test_any_other_window_says_nothing_of_the_address(self) -> None:
        with self._screens(1):
            step = _ran(setup._ask_how(setup.Session(again=False)))

        self.assertNotIn("notes", step)


class AnswerHowTests(_Fresh):
    def _answer(self, session: setup.Session, mode: str, *, launcher: bool = True) -> Any:
        client = mock.Mock()
        found = Launcher(launcher_id="vpx-1", app="vpx") if launcher else None
        with mock.patch.object(setup, "ApiClient", return_value=client), \
             mock.patch("common.games.launchers.default_launcher", return_value=found):
            _ran(setup._answer_how(session, {"cab_mode": mode}))
        return client

    def test_cabinet_writes_the_setting_and_the_default_launchers_bgset(self) -> None:
        client = self._answer(setup.Session(again=False), "cabinet")

        client.put_config.assert_called_once_with({"presentation": {"cab_mode": True}})
        client.write_launcher_config.assert_called_once_with("vpx-1", {setup.BGSET_KEY: "1"})

    def test_desktop_writes_bgset_zero(self) -> None:
        client = self._answer(setup.Session(again=False), "desktop")

        client.put_config.assert_called_once_with({"presentation": {"cab_mode": False}})
        client.write_launcher_config.assert_called_once_with("vpx-1", {setup.BGSET_KEY: "0"})

    def test_no_launcher_yet_still_writes_the_setting(self) -> None:
        client = self._answer(setup.Session(again=False), "cabinet", launcher=False)

        client.put_config.assert_called_once_with({"presentation": {"cab_mode": True}})
        client.write_launcher_config.assert_not_called()

    def test_a_launcher_with_no_settings_file_warns_and_the_answer_stands(self) -> None:
        client = mock.Mock()
        client.write_launcher_config.side_effect = RuntimeError("no settings file")
        launcher = Launcher(launcher_id="vpx-1", app="vpx")

        with mock.patch.object(setup, "ApiClient", return_value=client), \
             mock.patch("common.games.launchers.default_launcher", return_value=launcher), \
             self.assertLogs("vpinfe.console.setup", level="WARNING"):
            _ran(setup._answer_how(setup.Session(again=False), {"cab_mode": "cabinet"}))

        client.put_config.assert_called_once()

    def test_asked_again_and_answered_the_same_writes_nothing(self) -> None:
        self.store.set_value("presentation", "cab_mode", True)

        client = self._answer(setup.Session(again=True), "cabinet")

        client.put_config.assert_not_called()
        client.write_launcher_config.assert_not_called()

    def test_asked_again_and_answered_differently_writes_it(self) -> None:
        self.store.set_value("presentation", "cab_mode", True)

        client = self._answer(setup.Session(again=True), "desktop")

        client.put_config.assert_called_once_with({"presentation": {"cab_mode": False}})

    def test_the_first_time_an_unchanged_answer_is_still_written(self) -> None:
        """cab_mode defaults to off, so desktop reads the same answered or untouched."""
        client = self._answer(setup.Session(again=False), "desktop")

        client.put_config.assert_called_once()


def _fake(key: str, *, applies: Any = None, writes: list[str] | None = None,
          after: Any = None) -> setup.Step:
    """A step that draws a title and records that it was answered."""
    async def ask(session: setup.Session) -> dict[str, Any]:
        return {"title": key, "fields": []}

    async def answer(session: setup.Session, values: dict[str, Any]) -> None:
        if writes is not None:
            writes.append(key)
        if after is not None:
            after(values)

    return setup.Step(key, f"console.setup.step.{key}", ask, answer,
                      applies or (lambda session: True))


class PathTests(_Fresh):
    """The path through `STEPS` for three steps standing where the real ones will."""

    def setUp(self) -> None:
        super().setUp()
        self.writes: list[str] = []

    def _steps(self, **applies: Any) -> Any:
        steps = tuple(_fake(key, applies=applies.get(key), writes=self.writes)
                      for key in ("one", "two", "three"))
        return mock.patch.object(setup, "STEPS", steps)

    def test_it_opens_on_the_first_step_not_answered(self) -> None:
        install_setup.answer(self.store, "one")

        with self._steps():
            step = _ran(setup.calls(setup.Session(again=False)).first(None))

        self.assertEqual(step["step"], "two")

    def test_with_every_step_answered_it_opens_on_the_last(self) -> None:
        for key in ("one", "two", "three"):
            install_setup.answer(self.store, key)

        with self._steps():
            step = _ran(setup.calls(setup.Session(again=False)).first(None))

        self.assertEqual(step["step"], "three")

    def test_asked_again_it_opens_on_the_first_and_marks_every_step_done(self) -> None:
        with self._steps():
            step = _ran(setup.calls(setup.Session(again=True)).first(None))

        self.assertEqual(step["step"], "one")
        self.assertTrue(all(one["done"] for one in step["steps"]))

    def test_a_step_asked_for_by_name_is_the_one_drawn(self) -> None:
        with self._steps():
            step = _ran(setup.calls(setup.Session(again=False)).first("three"))

        self.assertEqual(step["step"], "three")

    def test_the_row_marks_what_is_answered(self) -> None:
        install_setup.answer(self.store, "one")

        with self._steps():
            step = _ran(setup.calls(setup.Session(again=False)).first("two"))

        self.assertEqual([(one["key"], one["done"]) for one in step["steps"]],
                         [("one", True), ("two", False), ("three", False)])

    def test_only_the_last_step_carries_the_finish_button(self) -> None:
        with self._steps():
            calls = setup.calls(setup.Session(again=False))
            first = _ran(calls.first("one"))
            last = _ran(calls.first("three"))

        self.assertNotIn("confirm", first)
        self.assertEqual(last["confirm"], "Finish")

    def test_checking_a_step_saves_it_and_draws_the_next(self) -> None:
        with self._steps():
            step = _ran(setup.calls(setup.Session(again=False)).check({}, "one"))

        self.assertEqual(self.writes, ["one"])
        self.assertEqual(install_setup.answered(self.store), ["one"])
        self.assertEqual(step["step"], "two")

    def test_a_step_that_does_not_apply_is_neither_asked_nor_in_the_row(self) -> None:
        with self._steps(two=lambda session: False):
            calls = setup.calls(setup.Session(again=False))
            after_one = _ran(calls.check({}, "one"))

        self.assertEqual(after_one["step"], "three")
        self.assertEqual([one["key"] for one in after_one["steps"]], ["one", "three"])

    def test_a_step_that_stops_applying_hands_the_finish_button_to_the_one_before(self) -> None:
        with self._steps(three=lambda session: False):
            step = _ran(setup.calls(setup.Session(again=False)).first("two"))

        self.assertEqual(step["confirm"], "Finish")

    def test_finish_on_the_last_step_clears_the_mark(self) -> None:
        self.assertTrue(install_setup.pending(self.store))

        with self._steps():
            answer = _ran(setup.calls(setup.Session(again=False)).run({}, "three"))

        self.assertTrue(answer["ok"])
        self.assertFalse(install_setup.pending(self.store))
        self.assertEqual(install_setup.answered(self.store), ["three"])

    def test_finish_runs_what_was_waiting_for_it(self) -> None:
        started = mock.Mock()
        install_setup.after_finish(self.store, started)
        self.addCleanup(install_setup._after_finish.clear)

        with self._steps():
            _ran(setup.calls(setup.Session(again=False)).run({}, "three"))

        started.assert_called_once_with()

    def test_an_answer_that_adds_a_step_after_this_one_moves_on_instead_of_finishing(self) -> None:
        """Finish was drawn before the answer that decides whether another question follows."""
        asked_for = {"later": False}
        steps = (
            _fake("one", after=lambda values: asked_for.update(later=True)),
            _fake("two", applies=lambda session: asked_for["later"]),
        )

        with mock.patch.object(setup, "STEPS", steps):
            calls = setup.calls(setup.Session(again=False))
            drawn = _ran(calls.first("one"))
            answer = _ran(calls.run({}, "one"))

        self.assertEqual(drawn["confirm"], "Finish")
        self.assertEqual(answer["step"], "two")
        self.assertTrue(install_setup.pending(self.store), "Setup is not over")

    def test_asked_again_nothing_is_recorded_and_the_mark_stays_off(self) -> None:
        self.store.set_value(install_setup.SECTION, install_setup.KEY, False)
        self.store.save()

        with self._steps():
            answer = _ran(setup.calls(setup.Session(again=True)).run({}, "three"))

        self.assertTrue(answer["ok"])
        self.assertEqual(install_setup.answered(self.store), [])
        self.assertFalse(install_setup.pending(self.store))

    def test_progress_survives_a_new_store_reading_the_same_file(self) -> None:
        with self._steps():
            _ran(setup.calls(setup.Session(again=False)).check({}, "one"))

        reread = ConfigStore(str(self.root / "vpinfe.ini"))
        saved = json.loads((self.root / "vpinfe.json").read_text(encoding="utf-8"))
        self.assertEqual(install_setup.answered(reread), ["one"])
        self.assertEqual(saved["settings"]["install"]["setup_done"], ["one"])


class OpenSetupTests(_Fresh):
    """What opening Setup asks of the dialog host, and what the page does when it closes."""

    def _opened(self, *, answers: bool) -> tuple[mock.AsyncMock, mock.Mock]:
        host = mock.AsyncMock(return_value=answers)

        async def go() -> None:
            with _PAGE:
                await setup.open_setup()

        with mock.patch.object(setup.wizard, "open_dialog", host), \
             mock.patch.object(ui.navigate, "reload") as reload:
            _ran(go())
        return host, reload

    def test_the_first_run_closes_on_finish_and_leaves_the_way_out_for_later(self) -> None:
        host, _reload = self._opened(answers=True)

        self.assertEqual(host.call_args.kwargs["label"], "Setup")
        self.assertEqual(host.call_args.kwargs["aside"], "Finish later")
        self.assertTrue(host.call_args.kwargs["close_when_done"])

    def test_finishing_the_first_run_reloads_to_the_consoles_usual_home(self) -> None:
        _host, reload = self._opened(answers=True)

        reload.assert_called_once_with()

    def test_leaving_the_first_run_for_later_leaves_the_page_as_it_is(self) -> None:
        _host, reload = self._opened(answers=False)

        reload.assert_not_called()

    def test_a_resumed_run_knows_the_screens_were_answered(self) -> None:
        install_setup.answer(self.store, setup.SCREENS)
        sessions: list[setup.Session] = []

        def calls(session: setup.Session) -> mock.Mock:
            sessions.append(session)
            return mock.Mock()

        async def go() -> None:
            with _PAGE:
                await setup.open_setup()

        with mock.patch.object(setup, "calls", calls), \
             mock.patch.object(setup.wizard, "open_dialog", mock.AsyncMock(return_value=False)):
            _ran(go())

        self.assertTrue(sessions[0].screens.answered)

    def test_asked_again_the_way_out_is_close_and_the_page_is_not_reloaded(self) -> None:
        install_setup.finish(self.store)

        host, reload = self._opened(answers=True)

        self.assertEqual(host.call_args.kwargs["aside"], "Close")
        self.assertTrue(host.call_args.kwargs["close_when_done"])
        reload.assert_not_called()


class TheRealStepsTests(_Fresh):
    def test_how_you_play_comes_first_and_the_row_names_it_and_visual_pinball(self) -> None:
        with self._screens(1):
            step = _ran(setup.calls(setup.Session(again=False)).first(None))

        self.assertEqual([setup.HOW, setup.SCREENS, setup.VPX, setup.GLASS, setup.VPX_KEYS,
                          setup.TABLES],
                         [one.key for one in setup.STEPS])
        self.assertEqual(step["step"], setup.HOW)
        self.assertNotIn("confirm", step, "Visual Pinball's pages follow it")
        self.assertEqual(["How you play", "Visual Pinball", "Tables"],
                         [segment["label"] for segment in step["steps"]])

    def test_every_step_names_itself_for_the_row(self) -> None:
        from common.i18n import t

        for one in setup.STEPS:
            with self.subTest(step=one.key):
                self.assertNotEqual(t(one.label), one.label)

    def test_answering_how_you_play_writes_it_and_goes_on_to_the_program(self) -> None:
        client = mock.Mock()
        session = setup.Session(again=False)

        with mock.patch.object(setup, "ApiClient", return_value=client), \
             mock.patch("common.games.launchers.default_launcher", return_value=None), \
             mock.patch.object(setup_vpx, "ApiClient", return_value=client):
            answer = _ran(setup.calls(session).check({"cab_mode": "cabinet"}, setup.HOW))

        client.put_config.assert_called_once_with({"presentation": {"cab_mode": True}})
        self.assertEqual(answer["step"], setup.VPX)
        self.assertTrue(install_setup.pending(self.store))
        self.assertEqual(install_setup.answered(self.store), [setup.HOW])

    def test_the_last_page_carries_finish_and_answering_it_finishes_setup(self) -> None:
        session = setup.Session(again=False, vpx=setup_vpx.Vpx(chosen="/x/vpx", answered=True))
        client = mock.Mock()
        client.launcher_config.return_value = {"values": {}}

        with mock.patch.object(setup, "_cabinet", return_value=False), \
             mock.patch.object(setup_vpx, "ApiClient", return_value=client), \
             mock.patch.object(setup_tables, "answer", mock.AsyncMock()), \
             mock.patch.object(setup_tables, "ask",
                               mock.AsyncMock(return_value={"title": "Tables"})):
            step = _ran(setup.calls(session).first(setup.TABLES))
            answer = _ran(setup.calls(session).run({}, setup.TABLES))

        self.assertEqual(step["confirm"], "Finish")
        self.assertEqual(answer, {"ok": True})
        self.assertFalse(install_setup.pending(self.store))
        self.assertEqual(install_setup.answered(self.store), [setup.TABLES])

    def test_not_installed_yet_makes_the_program_page_the_last(self) -> None:
        session = setup.Session(again=False, vpx=setup_vpx.Vpx(answered=True))
        with mock.patch.object(setup, "_cabinet", return_value=True):
            self.assertEqual([setup.HOW, setup.SCREENS, setup.VPX, setup.TABLES],
                             [one.key for one in setup._applicable(session)])
            self.assertEqual(setup.TABLES, setup._after(session, setup._step(setup.VPX)).key)


if __name__ == "__main__":
    unittest.main()
