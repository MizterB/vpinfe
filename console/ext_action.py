"""What core draws when somebody presses an action an extension offers.

The extension describes what to ask and what to call; this binds its four calls -
`GET {base}`, `POST {base}/check`, `POST {base}/act` and `POST {base}/run`, and
`GET {base}/progress` while one of them is slow - and hands
them to the shared wizard control (`console/wizard.py`), which does the drawing.
Nothing about the treatment comes from the extension, so every action looks like the
Console rather than like whoever wrote it, and it keeps working if that extension later
runs somewhere else.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from console import offload, wizard
from console.api import STEP_TIMEOUT, ApiClient
from console.on_page import on_page

GIVE_UP_AFTER = 3


def calls(extension: str, action: dict) -> wizard.Calls:
    """The action's four calls over HTTP, for the dialog host or for a flow that nests it
    inside steps of its own."""
    client = ApiClient()
    base = f"/ext/{extension}{action.get('base') or ''}"

    async def first(step: str | None = None) -> dict:
        path = f"{base}?step={quote(step, safe='')}" if step else base
        return await offload.io(client.ext_get, path)

    async def check(values: dict[str, Any], step: str) -> dict:
        return await offload.io(client.ext_post, f"{base}/check",
                                 {"values": values, "step": step}, STEP_TIMEOUT)

    async def act(key: str, values: dict[str, Any], step: str) -> dict:
        return await offload.io(client.ext_post, f"{base}/act",
                                 {"act": key, "values": values, "step": step}, STEP_TIMEOUT)

    async def run(values: dict[str, Any], step: str) -> dict:
        return await offload.io(client.ext_post, f"{base}/run",
                                 {"values": values, "step": step}, STEP_TIMEOUT)

    async def job(job_id: str) -> dict:
        return await offload.io(client.job, job_id)

    failed = {"in_a_row": 0}

    async def progress() -> dict:
        """How far a slow step has got, from the action's `GET {base}/progress`. An action
        that serves none stops being asked after a few answers in a row that say so; a
        busy server's one slow answer does not stop it."""
        if failed["in_a_row"] >= GIVE_UP_AFTER:
            return {}
        try:
            said = await offload.io(client.ext_get, f"{base}/progress")
        except Exception:  # noqa: BLE001 - a wait is not made worse by not knowing
            failed["in_a_row"] += 1
            return {}
        failed["in_a_row"] = 0
        return said

    return wizard.Calls(first, check, act, run, job, progress)


@on_page
async def open_action(extension: str, action: dict, *,
                      values: dict[str, Any] | None = None, until: str = "") -> bool:
    """Run one action: ask what it asks, in as many steps as it asks it, then do it.

    True once it ran and the dialog was closed, so a page that shows what the action
    changes can redraw; False when it was cancelled first. `values` are answers it starts
    with, and `until` the step it is walked to, unasked, before it is shown."""
    return await wizard.open_dialog(
        label=str(action.get("label") or ""),
        calls=calls(extension, action),
        under=f"ext.{extension}.action.{action.get('key')}",
        values=values, until=until)
