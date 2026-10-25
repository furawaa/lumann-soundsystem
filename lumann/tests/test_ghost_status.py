"""Segments that claim to be recording while nothing is recording them.

Seen for real: a book had a segment stuck at `recording` with no takes and no
error while the worker was busy elsewhere. The status is written before
generation and cleared after it, so anything that interrupts the runner between
those two points strands the segment — and a stranded one is invisible to every
recording scope and skipped by enqueue, so it can never be recorded again while
the server lives.
"""
import os
import unittest

os.environ["LUMANN_FAKE_TTS"] = "1"

from base import ProjectTest, para                              # noqa: E402
from fastapi.testclient import TestClient                       # noqa: E402
from test_recording import wait_until                           # noqa: E402

from server.core import projects                                # noqa: E402
from server.jobs.runner import runner                           # noqa: E402
from server.main import app                                     # noqa: E402

TEXT = para("Первый абзац.", "Второй абзац.", "Третий абзац.")


class GhostStatusTest(ProjectTest):

    def setUp(self):
        super().setUp()
        self.client = TestClient(app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.addCleanup(runner.shutdown)
        self.project = projects.create("ghost", TEXT)
        self.pid = self.project["id"]
        runner.clear(self.pid)
        self.addCleanup(runner.clear, self.pid)

    def strand(self, index, status):
        """Leave a segment claiming to be busy, as an interruption would."""
        with projects.lock(self.pid):
            project = projects.load(self.pid)
            segment = projects.segments(project)[index]
            segment["status"] = status
            projects.save(project)
            return segment["id"]

    def status_of(self, seg_id):
        project = self.client.get(f"/api/projects/{self.pid}").json()
        return next(item["status"] for item in project["timeline"] if item["id"] == seg_id)

    def test_a_stranded_recording_is_freed(self):
        ghost = self.strand(0, "recording")
        self.assertEqual(runner.reconcile(self.pid), 1)
        self.assertEqual(self.status_of(ghost), "pending")

    def test_a_stranded_queued_is_freed(self):
        ghost = self.strand(1, "queued")
        self.assertEqual(runner.reconcile(self.pid), 1)
        self.assertEqual(self.status_of(ghost), "pending")

    def test_a_freed_segment_is_recorded_again(self):
        """The point of the fix: before it, this segment was unreachable."""
        ghost = self.strand(0, "recording")
        self.client.post(f"/api/projects/{self.pid}/record/start", json={"scope": "remaining"})
        self.assertTrue(wait_until(lambda: self.stats()["done"] == 3, timeout=60))
        self.assertEqual(self.status_of(ghost), "done")

    def test_real_work_is_left_alone(self):
        """Reconcile must not touch a segment that is genuinely queued."""
        self.client.post(f"/api/projects/{self.pid}/record/stop")
        ids = [seg["id"] for seg in projects.segments(self.project)]
        runner.enqueue(self.project, ids)
        self.assertEqual(runner.reconcile(self.pid), 0)
        self.assertEqual([self.status_of(i) for i in ids], ["queued"] * 3)

    def stats(self):
        return self.client.get(f"/api/projects/{self.pid}").json()["stats"]


if __name__ == "__main__":
    unittest.main()
