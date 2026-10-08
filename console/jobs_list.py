"""What has run since this install started, one row per job.

Drawn on the Logs page beside the log's own views. The registry keeps it in memory, so a
restart starts the list again, apart from the jobs that kept their result: those come back
with a report to open.
"""

from __future__ import annotations

from typing import Any

from common import jobs
from common.i18n import t
from console import grid, when

SCOPE = "console.jobs"

LIMIT = jobs.HISTORY_LIMIT

STOPPED = "stopped"
# Finished, with parts that did not come across. A `done` job to the registry, which has
# three states; to the person reading the list it is a run to open.
WITH_ERRORS = "with_errors"
OUTCOMES = (jobs.RUNNING, jobs.DONE, WITH_ERRORS, jobs.FAILED, STOPPED)


def _said(field: str) -> dict[str, Any]:
    """A column whose cell holds a number to sort by, and shows the row's `<field>_said`."""
    return {":valueFormatter": f"params => (params.data || {{}}).{field}_said || ''"}


COLUMNS = [
    grid.identifier("what", t("console.jobs.what"), 230, pinned="left",
                    help=t("console.jobs.what.help")),
    grid.column("started", t("console.jobs.started"), 190, filter=False,
                help=t("console.jobs.started.help"), **_said("started")),
    grid.column("took", t("console.jobs.took"), 130, filter=False,
                help=t("console.jobs.took.help"), **_said("took")),
    grid.column("outcome", t("console.jobs.outcome"), 120,
                help="\n".join(t(f"console.jobs.outcome.{one}.help") for one in OUTCOMES),
                **grid.choice_filter([{"value": one, "label": t(f"console.jobs.outcome.{one}")}
                                      for one in OUTCOMES])),
    grid.column("detail", t("console.jobs.detail"), 420,
                help=t("console.jobs.detail.help")),
]


def outcome_of(job: dict[str, Any]) -> str:
    state = str(job.get("state") or "")
    if state == jobs.DONE and job.get("stopped"):
        return STOPPED
    if state == jobs.DONE and int(job.get("problems") or 0):
        return WITH_ERRORS
    return state


def what_ran(kind: str) -> str:
    """The kind in words, or as written where nothing names it: an extension's kinds are
    its own and carry its name."""
    key = f"console.jobs.kind.{kind.replace('.', '_')}"
    said = t(key)
    return kind if said == key else said


def _detail(job: dict[str, Any], outcome: str) -> str:
    """The error for a failure, what it is doing now for a running job, else its counts."""
    field = {jobs.FAILED: "error", jobs.RUNNING: "message"}.get(outcome, "detail")
    return str(job.get(field) or "")


def row(job: dict[str, Any], now: float) -> dict[str, Any]:
    started = float(job.get("started_at") or 0)
    finished = job.get("finished_at")
    outcome = outcome_of(job)
    ran = (float(finished) if finished else now) - started
    return {"id": str(job.get("id") or ""),
            "what": what_ran(str(job.get("kind") or "")),
            "kind": str(job.get("kind") or ""),
            "started": started, "started_said": when.at_second(started),
            "took": ran, "took_said": when.took(ran) if started else "",
            "outcome": outcome,
            "report": bool(job.get("report")),
            "detail": _detail(job, outcome)}


def rows(found: list[dict[str, Any]], now: float, outcome: str = "") -> list[dict[str, Any]]:
    """Newest first, narrowed to one outcome where one is asked for."""
    kept = [row(job, now) for job in found if not outcome or outcome_of(job) == outcome]
    return sorted(kept, key=lambda one: one["started"], reverse=True)
