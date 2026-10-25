"""Two books sharing one worker.

One model serves the whole app, so narrating a second book does not start a
second process — it joins the same queue. These tests pin the two things that
follow from that and are easy to get wrong: what order the shared queue runs
in, and what "stop" means when it is pressed on one book while another is
recording.
"""
import os
import unittest

os.environ["LUMANN_FAKE_TTS"] = "1"

from base import ProjectTest, para                              # noqa: E402
from fastapi.testclient import TestClient                       # noqa: E402
from test_recording import wait_until                           # noqa: E402

from server.core import projects                                # noqa: E402
from server.jobs.runner import FIRST_PASS, RERECORD, runner     # noqa: E402
from server.main import app                                     # noqa: E402

A_TEXT = para("Первый абзац книги А.", "Второй абзац книги А.", "Третий абзац книги А.")
# Longer than A on purpose: the pause has to land while this book still has
# work left, or "a paused book records nothing more" proves nothing.
B_TEXT = para("Первый абзац книги Б.", "Второй абзац книги Б.", "Третий абзац книги Б.",
              "Четвёртый абзац книги Б.", "Пятый абзац книги Б.")


class TwoProjectsTest(ProjectTest):

    def setUp(self):
        super().setUp()
        self.client = TestClient(app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.addCleanup(runner.shutdown)

        self.a = projects.create("book A", A_TEXT)
        self.b = projects.create("book B", B_TEXT)
        # Project ids are slugs, so every test gets the same two — and the
        # runner is one process-wide singleton. Whatever the previous test left
        # in the queue has to go, or the order under test is not the one built
        # here.
        for pid in (self.a["id"], self.b["id"]):
            runner.clear(pid)
            self.addCleanup(runner.clear, pid)
        self.a_ids = [seg["id"] for seg in projects.segments(self.a)]
        self.b_ids = [seg["id"] for seg in projects.segments(self.b)]
        # Readable names in assertion failures: A0, A1, ... B0, B1.
        self.name = {}
        for tag, ids in (("A", self.a_ids), ("B", self.b_ids)):
            for i, seg_id in enumerate(ids):
                self.name[seg_id] = f"{tag}{i}"

    def order(self):
        return [self.name[job["segment"]] for job in runner.all_jobs()]

    # --- the shared queue ---------------------------------------------------

    def test_the_second_book_queues_behind_the_first(self):
        runner.enqueue(self.a, self.a_ids, FIRST_PASS)
        runner.enqueue(self.b, self.b_ids, FIRST_PASS)
        self.assertEqual(self.order(), ["A0", "A1", "A2", "B0", "B1", "B2", "B3", "B4"])

    def test_a_rerecord_overtakes_the_other_book(self):
        """Priority is compared before the project, so a re-record anywhere
        jumps the whole first-pass queue everywhere. Surprising, but right: a
        re-record is what someone is sitting and waiting for."""
        runner.enqueue(self.a, self.a_ids, FIRST_PASS)
        runner.enqueue(self.b, self.b_ids, FIRST_PASS)
        runner.enqueue(self.b, [self.b_ids[1]], RERECORD)
        self.assertEqual(self.order(),
                         ["B1", "A0", "A1", "A2", "B0", "B2", "B3", "B4"])

    def test_each_book_sees_only_its_own_queue(self):
        runner.enqueue(self.a, self.a_ids, FIRST_PASS)
        runner.enqueue(self.b, self.b_ids, FIRST_PASS)
        self.assertEqual(runner.queued_ids(self.a["id"]), self.a_ids)
        self.assertEqual(runner.queued_ids(self.b["id"]), self.b_ids)

    def test_the_global_queue_endpoint_shows_both(self):
        runner.enqueue(self.a, self.a_ids, FIRST_PASS)
        runner.enqueue(self.b, self.b_ids, FIRST_PASS)
        rows = self.client.get("/api/queue").json()["queue"]
        self.assertEqual([self.name[row["id"]] for row in rows],
                         ["A0", "A1", "A2", "B0", "B1", "B2", "B3", "B4"])
        self.assertEqual({row["project_title"] for row in rows}, {"book A", "book B"})
        self.assertTrue(all(row["text"] for row in rows), "rows carry their text")

    # --- stop is per project ------------------------------------------------

    def test_stopping_one_book_leaves_the_other_queued(self):
        runner.enqueue(self.a, self.a_ids, FIRST_PASS)
        runner.enqueue(self.b, self.b_ids, FIRST_PASS)
        runner.stop(self.b["id"])

        self.assertEqual(runner.state()["paused"], [self.b["id"]])
        # Paused work is skipped, not dropped.
        self.assertEqual(self.order(), ["A0", "A1", "A2", "B0", "B1", "B2", "B3", "B4"])
        self.assertEqual([job["paused"] for job in runner.all_jobs()],
                         [False, False, False, True, True, True, True, True])

    def test_a_paused_book_is_not_recorded(self):
        self.client.post(f"/api/projects/{self.b['id']}/record/start", json={"scope": "all"})
        self.client.post(f"/api/projects/{self.b['id']}/record/stop")
        # Stop returns as soon as the kill is sent; the segment that was in the
        # model is put back by the runner thread a moment later. Whatever B
        # finished before the pause landed is its own business — the claim is
        # that nothing is added to it afterwards.
        wait_until(lambda: runner.state()["current"] is None, timeout=10)
        frozen = self.done(self.b)
        self.assertTrue(runner.queued_ids(self.b["id"]), "B still has work waiting")

        self.client.post(f"/api/projects/{self.a['id']}/record/start", json={"scope": "all"})
        self.assertTrue(wait_until(lambda: self.done(self.a) == 3, timeout=60),
                        "the running book must finish")
        self.assertEqual(self.done(self.b), frozen, "the paused book gained nothing")
        self.assertEqual(runner.state()["paused"], [self.b["id"]])

    def test_resuming_records_what_was_paused(self):
        self.client.post(f"/api/projects/{self.b['id']}/record/start", json={"scope": "all"})
        self.client.post(f"/api/projects/{self.b['id']}/record/stop")
        self.assertEqual(runner.state()["paused"], [self.b["id"]])

        self.client.post(f"/api/projects/{self.b['id']}/record/start", json={"scope": "all"})
        self.assertEqual(runner.state()["paused"], [])
        self.assertTrue(wait_until(lambda: self.done(self.b) == 5, timeout=60))

    def test_stopping_everything_still_works(self):
        runner.enqueue(self.a, self.a_ids, FIRST_PASS)
        runner.enqueue(self.b, self.b_ids, FIRST_PASS)
        runner.start()
        runner.stop()                       # no project: the old global stop
        self.assertFalse(runner.state()["running"])
        self.assertEqual(runner.state()["paused"], [])

    # --- the scheduler order is the user's to set ---------------------------

    def test_the_book_order_can_be_set(self):
        runner.enqueue(self.a, self.a_ids, FIRST_PASS)
        runner.enqueue(self.b, self.b_ids, FIRST_PASS)
        runner.set_project_order([self.b["id"], self.a["id"]])
        self.assertEqual(self.order(),
                         ["B0", "B1", "B2", "B3", "B4", "A0", "A1", "A2"])

    def test_a_rerecord_still_wins_over_the_book_order(self):
        """Priority is compared first, so re-recording keeps overtaking
        whatever book the user put on top."""
        runner.enqueue(self.a, self.a_ids, FIRST_PASS)
        runner.enqueue(self.b, self.b_ids, FIRST_PASS)
        runner.set_project_order([self.b["id"], self.a["id"]])
        runner.enqueue(self.a, [self.a_ids[2]], RERECORD)
        self.assertEqual(self.order()[0], "A2")

    def test_two_rerecords_follow_the_book_order(self):
        """The case the book order exists to answer: both books want a segment
        re-recorded, so whichever book stands higher goes first."""
        runner.enqueue(self.a, self.a_ids, FIRST_PASS)
        runner.enqueue(self.b, self.b_ids, FIRST_PASS)
        runner.enqueue(self.a, [self.a_ids[0]], RERECORD)
        runner.enqueue(self.b, [self.b_ids[0]], RERECORD)

        runner.set_project_order([self.a["id"], self.b["id"]])
        self.assertEqual(self.order()[:2], ["A0", "B0"])
        runner.set_project_order([self.b["id"], self.a["id"]])
        self.assertEqual(self.order()[:2], ["B0", "A0"])

    def test_the_order_endpoint_reports_progress_per_book(self):
        runner.enqueue(self.a, self.a_ids, FIRST_PASS)
        runner.enqueue(self.b, self.b_ids, FIRST_PASS)
        rows = self.client.get("/api/queue/projects").json()["projects"]
        self.assertEqual([row["title"] for row in rows], ["book A", "book B"])
        self.assertEqual([row["queued"] for row in rows], [3, 5])
        self.assertEqual([row["segments"] for row in rows], [3, 5])

        moved = self.client.post("/api/queue/projects/order",
                                 json={"ids": [self.b["id"], self.a["id"]]})
        self.assertEqual(moved.json()["order"], [self.b["id"], self.a["id"]])
        rows = self.client.get("/api/queue/projects").json()["projects"]
        self.assertEqual([row["title"] for row in rows], ["book B", "book A"])

    def test_stop_all_stops_every_book(self):
        runner.enqueue(self.a, self.a_ids, FIRST_PASS)
        runner.enqueue(self.b, self.b_ids, FIRST_PASS)
        runner.start()
        state = self.client.post("/api/record/stop-all").json()["state"]
        self.assertFalse(state["running"])
        self.assertEqual(state["paused"], [])

    def done(self, project):
        return self.client.get(f"/api/projects/{project['id']}").json()["stats"]["done"]


if __name__ == "__main__":
    unittest.main()
