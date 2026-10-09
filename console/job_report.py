"""The report a finished job kept, opened from the Jobs view or from the toast that told
it ended, and drawn on a page of its own."""

from __future__ import annotations

from typing import Any

from nicegui import ui

from common.failures import why
from common.i18n import t
from console import dialog as frame
from console import import_report, jobs_list, offload, panel, report_groups, wizard
from console.api import ApiClient
from console.on_page import on_page

# Where each kind's result labels live in its catalog; a kind not named reads its keys as written.
UNDER = {"library_importer.import": "setup"}

# Rows of a list drawn before it says how many more there are: a library of thousands that
# all failed must not draw a label each.
SHOWN = 200


def draw(body: Any, job: dict) -> None:
    """The report of `job` in `body`."""
    wizard.report(body, job, UNDER.get(str(job.get("kind") or ""), ""), limit=SHOWN)


def in_its_own_tab(job_id: str) -> None:
    """The report's own address, with the opener kept: a link in it finds the Console's
    window by name only from a tab that has one."""
    panel.link_out(t("console.report.own_tab"), to=report_groups.report_address(job_id),
                   hint=t("console.report.own_tab.hint"), opener=True)()


@on_page
async def open_for(job_id: str) -> None:
    """The kept report for `job_id`, in a dialog of its own."""
    try:
        job = await offload.io(ApiClient().job, job_id)
    except Exception as exc:  # noqa: BLE001 - the reason belongs on screen
        ui.notify(t("console.jobs.report_unavailable"), caption=why(exc), type="negative")
        return
    with frame.opened("", wide=True, classes="console-wizard-card") as dialog:
        with ui.element("div").classes("console-wizard-scroll"):
            ui.label(jobs_list.named(job)) \
                .classes("console-dialog-title console-wizard-title")
            body = ui.column().classes("w-full gap-0 console-wizard-body")
        with frame.footer():
            in_its_own_tab(job_id)
            frame.cancel(dialog.close, t("word.close"))
    await import_report.check(job)
    draw(body, job)
    dialog.open()
