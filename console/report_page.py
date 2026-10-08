"""A kept report on a page of its own, to keep open beside the Console while the games in it
are worked through. No rail: the Console is the other tab."""

from __future__ import annotations

from nicegui import ui

from common.failures import why
from common.i18n import t
from console import appearance, job_report, jobs_list, offload, report_groups
from console import panel as panel_parts
from console.api import ApiClient
from console.grid import install_filters


@ui.page(report_groups.ADDRESS, title=t("console.report.page_title"), reconnect_timeout=300)
async def report_page(job: str = "") -> None:
    """The report of the job `job` names."""
    appearance.apply_mode(appearance.configured_mode())
    install_filters()
    panel_parts.install_fact_tooltips()
    ui.query(".nicegui-content").classes("p-0 gap-0")
    await ui.context.client.connected()

    with ui.column().classes("w-full max-w-4xl mx-auto p-4 gap-2"):
        try:
            found = await offload.io(ApiClient().job, job)
        except Exception as exc:  # noqa: BLE001 - the reason belongs on screen
            ui.label(t("console.jobs.report_unavailable")).classes("console-dialog-title")
            ui.notify(t("console.jobs.report_unavailable"), caption=why(exc), type="negative")
            return
        said = jobs_list.what_ran(str(found.get("kind") or ""))
        ui.page_title(t("console.report.title", what=said))
        ui.label(said).classes("console-dialog-title console-wizard-title")
        body = ui.column().classes("w-full gap-0 console-wizard-body")
        job_report.draw(body, found)
