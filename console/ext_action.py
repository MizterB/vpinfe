"""What core draws when somebody presses an action an extension offers.

The extension describes what to ask and what to call; this is the one place it is drawn.
Nothing about the treatment comes from the extension, so every action looks like the
Console rather than like whoever wrote it, and it keeps working if that extension later
runs somewhere else.

How many steps there are is read off what the extension answers, never declared. No
fields means press it and it happens. Fields mean fill them in first. A `confirm` means a
step showing what would happen before it runs. So an action that is nothing but a verb
costs a person one press, and the guided one is the same contract with more of it filled
in.
"""

from __future__ import annotations

from typing import Any

from nicegui import run, ui

from console import panel
from console.api import ApiClient

# How often to ask a running job how it is doing. A job here is minutes of copying, so a
# tighter loop would be a question asked hundreds of times for the same answer.
POLL_SECONDS = 1.0


def _controls(fields: list[dict], values: dict[str, Any]) -> None:
    """Draw what the task asked for, in the Console's own grammar."""
    entries = []
    for field in fields:
        key = str(field.get("key") or "")
        if not key:
            continue
        values.setdefault(key, field.get("value"))
        kind = str(field.get("type") or "string")
        label = str(field.get("label") or key)
        if kind == "multi":
            choices = {str(one[0]): str(one[1]) for one in field.get("choices") or []}
            entries.append((label, panel.multi_select(
                choices, list(values.get(key) or []),
                lambda event, key=key: values.__setitem__(key, list(event.value or [])))))
        else:
            entries.append((label, panel.field(
                str(values.get(key) or ""),
                lambda text, key=key: values.__setitem__(key, text))))
        if field.get("help"):
            entries.append((panel.ASIDE, _aside(str(field["help"]))))
    panel.facts(ui, entries)


def _aside(text: str):
    def draw() -> None:
        ui.label(text).classes("console-help")
    return draw


def _lines(target, title: str, lines: list[str], classes: str) -> None:
    if not lines:
        return
    if title:
        ui.label(title).classes("console-group mt-3")
    for line in lines:
        ui.label(str(line)).classes(classes)


async def open_action(extension: str, action: dict) -> None:
    """Run one action: ask if it asks, confirm if it confirms, then do it."""
    client = ApiClient()
    base = f"/ext/{extension}{action.get('base') or ''}"
    values: dict[str, Any] = {}

    form = await run.io_bound(client.ext_get, base)

    with ui.dialog().props("persistent") as dialog, \
            ui.card().classes("console-import-card"):
        # The title names the task and stands for all three steps. The help is about
        # the question being asked, so it belongs to the step that asks it - carried
        # forward it would still be telling somebody to point at a folder while they
        # read what the import did.
        ui.label(str(form.get("title") or action.get("label") or "")) \
            .classes("console-confirm-title")

        body = ui.column().classes("w-full gap-0")
        buttons = ui.row().classes("justify-end gap-2 w-full pt-2")

        def steps_from(found: dict) -> tuple[bool, bool]:
            """What this action needs, read off its own answer.

            Never a mode it declares: a declaration is a second statement of what the
            fields and the confirm already say, and the two come apart.
            """
            return bool(found.get("fields")), bool(found.get("confirm"))

        def draw_form(found: dict) -> None:
            body.clear()
            buttons.clear()
            with body:
                if found.get("help"):
                    ui.label(str(found["help"])).classes("console-help")
                _controls(list(found.get("fields") or []), values)
                if found.get("facts"):
                    panel.facts(ui, [(one[0], one[1]) for one in found["facts"]])
                _lines(body, "", list(found.get("notes") or []), "console-help")
            asks, confirms = steps_from(found)
            with buttons:
                ui.button("Cancel", on_click=lambda: dialog.submit(False)) \
                    .props("flat no-caps")
                # The verb, unless there is something after this. An action with no
                # confirm and no more to ask says what it does rather than "Next".
                onward = "Next" if confirms else str(action.get("label") or "Go")
                ui.button(onward,
                          on_click=(_check if confirms else _start)).props("no-caps")

        def draw_confirm(found: dict) -> None:
            body.clear()
            buttons.clear()
            with body:
                if found.get("summary"):
                    panel.facts(ui, [(one[0], one[1]) for one in found["summary"]])
                _controls(list(found.get("fields") or []), values)
                # What the read could not do travels with what it found. A summary that
                # said 148 games and stayed quiet about their tables being on a machine
                # that is not here would be describing an import that will not happen.
                _lines(body, "Worth knowing", list(found.get("notes") or []),
                       "console-help")
                if not found.get("ready"):
                    ui.label(str(found.get("reason") or "")).classes("console-help")
            with buttons:
                ui.button("Back", on_click=lambda: draw_form(form)).props("flat no-caps")
                go = ui.button(str(found.get("confirm") or action.get("label") or "Go"),
                               on_click=lambda: _start()).props("no-caps")
                if not found.get("ready"):
                    go.disable()

        async def _check() -> None:
            try:
                found = await run.io_bound(client.ext_post, f"{base}/check",
                                           {"values": values})
            except Exception as exc:  # noqa: BLE001
                ui.notify(str(exc), type="negative")
                return
            draw_confirm(found)

        async def _start() -> None:
            try:
                started = await run.io_bound(client.ext_post, f"{base}/run",
                                             {"values": values})
            except Exception as exc:  # noqa: BLE001
                ui.notify(str(exc), type="negative")
                return
            job_id = str(started.get("job_id") or "")
            if job_id:
                await _watch(job_id)
                return
            if started.get("ok") is False:
                ui.notify(str(started.get("reason") or "It did not run"),
                          type="negative")
                return
            # Finished already. Some actions are one call and a sentence, and making
            # those wear a progress bar would be theatre.
            _finished(body, buttons, dialog, started)

        async def _watch(job_id: str) -> None:
            body.clear()
            buttons.clear()
            with body:
                bar = ui.linear_progress(value=0, show_value=False).classes("w-full")
                said = ui.label("Working").classes("console-help")
            with buttons:
                close = ui.button("Close", on_click=lambda: dialog.submit(True)) \
                    .props("flat no-caps")
                close.disable()

            while True:
                job = await run.io_bound(client.job, job_id)
                bar.value = int(job.get("pct") or 0) / 100
                said.text = str(job.get("message") or "Working")
                if str(job.get("state")) not in ("running", "queued"):
                    break
                await run.io_bound(_wait)

            close.enable()
            _report(body, job)

        draw_form(form)

    await dialog


def _finished(body, buttons, dialog, answer: dict) -> None:
    """An action that ran and is done, with whatever it wants to say about it."""
    body.clear()
    buttons.clear()
    with body:
        said = str(answer.get("message") or "Done")
        ui.label(said).classes("console-help")
        facts = [(one[0], one[1]) for one in (answer.get("summary") or [])]
        if facts:
            panel.facts(ui, facts)
    with buttons:
        ui.button("Close", on_click=lambda: dialog.submit(True)).props("flat no-caps")


def _wait() -> None:
    import time

    time.sleep(POLL_SECONDS)


def _report(body, job: dict) -> None:
    """What happened, once it has. The counts, and every game that did not come across -
    an import that says only "done" leaves somebody to find the gaps themselves."""
    body.clear()
    with body:
        if job.get("state") == "failed":
            ui.label(str(job.get("error") or "It did not finish")) \
                .classes("console-help")
            return
        result = job.get("result") or {}
        counts = [(label, str(result.get(key, 0)))
                  for key, label in (("created", "Brought in"),
                                     ("failed", "Not brought in"),
                                     ("with_a_game_file", "With a game file"),
                                     ("media_files", "Artwork files"))
                  if key in result]
        if counts:
            panel.facts(ui, counts)
        missed = [row for row in (result.get("games") or []) if row.get("error")]
        if missed:
            ui.label(f"Did not come across ({len(missed)})").classes("console-group mt-3")
            for row in missed[:20]:
                ui.label(f"{row.get('name') or row.get('key')} - {row['error']}") \
                    .classes("console-help")
            if len(missed) > 20:
                ui.label(f"and {len(missed) - 20} more").classes("console-help")
