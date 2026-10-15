"""The reporter that carries a long job's log and progress back to whoever asked."""

from __future__ import annotations

import unittest
from unittest import mock

from common.jobs import Job, JobReporter


class JobReporterTests(unittest.TestCase):
    def test_job_reporter_wraps_log_and_progress_callbacks(self) -> None:
        messages: list[str] = []
        progress: list[tuple[int, int, str]] = []
        reporter = JobReporter(
            logger=mock.Mock(),
            log_cb=messages.append,
            progress_cb=lambda current, total, message: progress.append((current, total, message)),
        )

        reporter.log("hello")
        reporter.progress(1, 2, "half")

        self.assertEqual(messages, ["hello"])
        self.assertEqual(progress, [(1, 2, "half")])


class JobLogTests(unittest.TestCase):
    def job(self, messages: list[str]) -> Job:
        return Job(id="one", kind="test", title="", log_cb=messages.append)

    def test_a_line_reported_by_a_service_is_logged_once(self) -> None:
        heard: list[str] = []

        with self.assertLogs("vpinfe.common.jobs", "INFO") as logged:
            self.job(heard).reporter().log("Enriching Fathom")

        self.assertEqual(heard, ["Enriching Fathom"])
        self.assertEqual([r.getMessage() for r in logged.records], ["Enriching Fathom"])

    def test_a_line_the_job_logs_itself_is_logged_once(self) -> None:
        heard: list[str] = []

        with self.assertLogs("vpinfe.common.jobs", "INFO") as logged:
            self.job(heard).log("Enriching Fathom")

        self.assertEqual(heard, ["Enriching Fathom"])
        self.assertEqual(len(logged.records), 1)

    def test_a_line_handed_on_is_heard_and_not_logged(self) -> None:
        heard: list[str] = []

        with self.assertNoLogs("vpinfe.common.jobs", "INFO"):
            self.job(heard).heard("Enriching Fathom")

        self.assertEqual(heard, ["Enriching Fathom"])

    def test_a_listener_that_raises_does_not_stop_the_service(self) -> None:
        def broken(message: str) -> None:
            raise RuntimeError(message)

        job = Job(id="one", kind="test", title="", log_cb=broken)

        job.reporter().log("Enriching Fathom")


if __name__ == "__main__":
    unittest.main()
