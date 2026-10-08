"""The report a finished job kept, opened from the Jobs view or from the toast that told
it ended."""

from __future__ import annotations

from nicegui import ui

from common.failures import why
from common.i18n import t
from console import dialog as frame
from console import jobs_list, offload, wizard
from console.api import ApiClient
from console.on_page import on_page

# Where each kind's result labels live in its catalog; a kind not named reads its keys as written.
UNDER = {"library_importer.import": "setup"}

# Rows of a list drawn before it says how many more there are: a library of thousands that
# all failed must not draw a label each.
SHOWN = 200


@on_page
async def open_for(job_id: str) -> None:
    """The kept report for `job_id`, in a dialog of its own."""
    try:
        job = await offload.io(ApiClient().job, job_id)
    except Exception as exc:  # noqa: BLE001 - the reason belongs on screen
        ui.notify(t("console.jobs.report_unavailable"), caption=why(exc), type="negative")
        return
    kind = str(job.get("kind") or "")
    with frame.opened("", wide=True, classes="console-wizard-card") as dialog:
        with ui.element("div").classes("console-wizard-scroll"):
            ui.label(jobs_list.what_ran(kind)) \
                .classes("console-dialog-title console-wizard-title")
            body = ui.column().classes("w-full gap-0 console-wizard-body")
        with frame.footer():
            frame.cancel(dialog.close, t("word.close"))
    wizard.report(body, job, UNDER.get(kind, ""), limit=SHOWN)
    dialog.open()
