"""Settings > Hardware > Output: what the DOF section cannot say from the schema alone.

The DOF Config Tool is asked on a schedule, and the foot says when it last was and offers
the act of asking now. Only this install's own client is asked, as the other pages' feet are.
The foot also tests an event: turn it on, see it on the cabinet, stop it.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from nicegui import run, ui

from common.failures import why
from common.host import dof_service
from common.i18n import t
from console import offload, panel, verbs
from console.on_page import on_page

SECTION = "dof"
FIRST_EVENT = "E900"
# The settings the foot below them reads, so the page is drawn again once one is saved.
READ_BELOW = frozenset({"config_tool_api_key", "enabled"})


async def event_state(library: Any) -> dict[str, Any]:
    """The event on now and why none could be turned on. Empty where it could not be read:
    the press then answers in words for itself."""
    try:
        return dict(await offload.io(library.dof_event_state))
    except Exception:  # noqa: BLE001 - a test that cannot be dimmed is still refused in words
        return {}


def _token(text: str) -> str:
    """The event a field holds as the helper is told it, or empty where it holds none."""
    try:
        return dof_service.normalize_event_token(text) or ""
    except ValueError:
        return ""


class Tester:
    """Test beside a field holding an event, which reads Stop while that event is on.

    Dimmed, with the reason under it, while none could be turned on, and while `event()`
    holds none. `state` is `event_state`'s answer and is kept current as it is pressed.
    `refresh()` draws it again once the field has changed.
    """

    def __init__(self, library: Any, state: dict[str, Any],
                 event: Callable[[], str]) -> None:
        self.library = library
        self.state = state
        self.event = event
        self.column: Any = None

    def __call__(self) -> None:
        self.column = ui.column().classes("gap-0 min-w-0")
        self.refresh()

    def refresh(self) -> None:
        column = self.column
        if column is None or column.is_deleted:
            return
        column.clear()
        reason = str(self.state.get("blocked") or "")
        token = _token(self.event())
        with column:
            if token and self.state.get("event") == token:
                panel.action(t("word.stop"), self._stop, icon=verbs.STOP, inline=True,
                             hint=t("console.dof.stop_hint"))()
                return
            panel.action(t("console.dof.test"), self._test, icon=verbs.RUN, inline=True,
                         enabled=not reason and bool(token),
                         hint=reason or t("console.dof.test_hint"))()
            if reason:
                ui.label(reason).classes("console-help")

    async def _reread(self) -> None:
        self.state.clear()
        self.state.update(await event_state(self.library))
        self.refresh()

    @on_page
    async def _test(self) -> None:
        try:
            on = await offload.io(self.library.test_dof_event, _token(self.event()))
        except Exception as exc:  # noqa: BLE001 - the refusal is the words
            ui.notify(t("console.dof.test_failed"), caption=why(exc), type="negative")
            await self._reread()
            return
        self.state.clear()
        self.state.update(event=on.get("event"), blocked="")
        self.refresh()

    @on_page
    async def _stop(self) -> None:
        try:
            await run.io_bound(self.library.stop_dof_event)
        except Exception as exc:  # noqa: BLE001 - the reason belongs on screen
            ui.notify(t("console.dof.stop_failed"), caption=why(exc), type="negative")
        await self._reread()
        if self.state.get("event"):
            ui.notify(t("console.dof.stop_failed"), type="negative")


# What was last typed, kept across the page being drawn again.
_typed = {"event": FIRST_EVENT}


def event_row(library: Any, state: dict[str, Any]) -> tuple[Any, Any]:
    """Test Event: the field, then Test."""
    test = Tester(library, state, lambda: _typed["event"])

    async def keep(text: str) -> str:
        try:
            _typed["event"] = dof_service.normalize_event_token(text) or ""
        except ValueError:
            _typed["event"] = ""
            test.refresh()
            return t("dof.event.malformed")
        test.refresh()
        return ""

    field = panel.field(_typed["event"], keep, refuses=True)

    def draw() -> None:
        with ui.column().classes("gap-1 min-w-0"):
            with ui.row().classes("items-start gap-2 no-wrap min-w-0"):
                field()
                test()
            ui.label(t("console.dof.test_event.help")).classes("console-help")

    return (t("console.dof.test_event"), draw)


async def foot(library: Any, rerender: Any, **_: Any) -> list[tuple[Any, Any]]:
    """When the config was last asked for and the way to ask now, then the event test."""
    return [await _download_row(library, rerender), event_row(library, await event_state(library))]


async def _download_row(library: Any, rerender: Any) -> tuple[Any, Any]:
    """Dimmed, with the reason, while there is no API key to ask with."""
    from console.settings import last_checked

    try:
        state = await offload.io(library.dof_config_state)
    except Exception as exc:  # noqa: BLE001 - a settings page says why, never 500s
        return panel.intro(t("console.dof.state_failed"), hint=why(exc))

    @on_page
    async def now() -> None:
        from console import record

        # Held: an ongoing notification never times out on its own.
        downloading = ui.notification(t("said.dof_config.download"), spinner=True,
                                      timeout=None)
        try:
            job = await offload.io(library.download_dof_config)
            ended = await record.ended_job(library, str(job.get("id") or ""))
        except Exception as exc:  # noqa: BLE001 - the reason belongs on screen
            ui.notify(t("console.settings.check_failed"), caption=why(exc), type="negative")
            return
        finally:
            downloading.dismiss()
        if not ended or ended.get("error"):
            ui.notify(t("console.settings.check_failed"),
                      caption=str(ended.get("error") or ""), type="negative")
        else:
            # "Already up to date" is the ordinary outcome and says itself.
            changed = bool(ended.get("changed"))
            ui.notify(t("said.dof_config.updated") if changed
                      else t("console.settings.already_date"),
                      type="positive" if changed else "info")
        rerender()

    return last_checked(str(state.get("checked") or ""), now,
                        blocked="" if state.get("has_key") else t("error.dof_config.no_key"))
