"""End-to-end over HTTP, with LUMANN_FAKE_TTS so no model is loaded.

Covers the acceptance checks that do not need real audio: record a project,
stop mid-run, resume, append takes without overwriting, promote, and refuse to
delete the active take.
"""
import os
import time
import unittest

os.environ["LUMANN_FAKE_TTS"] = "1"

from base import ProjectTest, para                              # noqa: E402
from fastapi.testclient import TestClient                       # noqa: E402

from server.core import paths, projects                         # noqa: E402
from server.jobs.runner import runner                           # noqa: E402
from server.main import app                                     # noqa: E402

TEXT = para(
    "Первый абзац книги, который надо озвучить целиком.",
    "Второй абзац, тоже довольно короткий и простой.",
    "Третий абзац завершает эту небольшую главу.",
)


def wait_until(predicate, timeout=60, interval=0.1):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


class RecordingTest(ProjectTest):

    def setUp(self):
        super().setUp()
        self.client = TestClient(app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.addCleanup(runner.shutdown)

    def create(self, text=TEXT, title="rec"):
        r = self.client.post("/api/projects", json={"title": title, "text": text})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def project(self, pid):
        return self.client.get(f"/api/projects/{pid}").json()

    def record_all(self, pid):
        r = self.client.post(f"/api/projects/{pid}/record/start", json={"scope": "all"})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def done_count(self, pid):
        return self.project(pid)["stats"]["done"]

    # --- the happy path -----------------------------------------------------

    def test_records_every_segment_and_writes_takes(self):
        pid = self.create()["id"]
        self.record_all(pid)
        self.assertTrue(wait_until(lambda: self.done_count(pid) == 3),
                        f"stuck at {self.project(pid)['stats']}")

        for seg in self.project(pid)["timeline"]:
            self.assertEqual(seg["status"], "done")
            self.assertEqual(seg["take_count"], 1)
            path = paths.take_path(pid, seg["id"], seg["active_take"])
            self.assertTrue(os.path.exists(path))
            self.assertGreater(os.path.getsize(path), 0)

    def test_no_tmp_files_are_left_behind(self):
        pid = self.create()["id"]
        self.record_all(pid)
        wait_until(lambda: self.done_count(pid) == 3)
        leftovers = [name
                     for _root, _dirs, files in os.walk(paths.audio_dir(pid))
                     for name in files if name.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_audio_endpoint_supports_range_requests(self):
        pid = self.create()["id"]
        self.record_all(pid)
        wait_until(lambda: self.done_count(pid) == 3)
        seg = self.project(pid)["timeline"][0]

        full = self.client.get(f"/api/segments/{seg['id']}/audio")
        self.assertEqual(full.status_code, 200)
        self.assertEqual(full.headers["accept-ranges"], "bytes")

        part = self.client.get(f"/api/segments/{seg['id']}/audio",
                               headers={"Range": "bytes=0-99"})
        self.assertEqual(part.status_code, 206)
        self.assertEqual(len(part.content), 100)
        self.assertTrue(part.headers["content-range"].startswith("bytes 0-99/"))

    # --- stop and resume ----------------------------------------------------

    def test_stop_is_immediate_and_resume_continues(self):
        long_text = para(*[f"Абзац номер {i}, довольно длинный текст для озвучки." * 3
                           for i in range(1, 13)])
        pid = self.create(long_text, "stoppable")["id"]
        total = self.project(pid)["stats"]["segments"]
        self.assertGreaterEqual(total, 12)

        self.record_all(pid)
        self.assertTrue(wait_until(lambda: self.done_count(pid) >= 2, timeout=90))

        started = time.time()
        r = self.client.post(f"/api/projects/{pid}/record/stop")
        elapsed = time.time() - started
        self.assertEqual(r.status_code, 200)
        self.assertLess(elapsed, 3.0, "stop must not wait for the model")

        time.sleep(0.5)
        after_stop = self.done_count(pid)
        self.assertLess(after_stop, total, "should not have finished everything")

        # nothing half-written, nothing stuck mid-generation
        leftovers = [name
                     for _root, _dirs, files in os.walk(paths.audio_dir(pid))
                     for name in files if name.endswith(".tmp")]
        self.assertEqual(leftovers, [])
        for seg in self.project(pid)["timeline"]:
            self.assertNotEqual(seg["status"], "recording")

        self.record_all(pid)
        self.assertTrue(wait_until(lambda: self.done_count(pid) == total, timeout=120),
                        f"resume stalled at {self.project(pid)['stats']}")

    def test_completed_segments_are_not_regenerated_on_resume(self):
        pid = self.create()["id"]
        self.record_all(pid)
        wait_until(lambda: self.done_count(pid) == 3)
        before = {s["id"]: s["active_take"] for s in self.project(pid)["timeline"]}

        r = self.client.post(f"/api/projects/{pid}/record/start",
                             json={"scope": "remaining"})
        self.assertEqual(r.json()["added"], 0)
        time.sleep(0.5)
        after = {s["id"]: s["active_take"] for s in self.project(pid)["timeline"]}
        self.assertEqual(before, after)

    # --- takes --------------------------------------------------------------

    def test_rerecord_appends_a_take_and_keeps_the_old_one(self):
        pid = self.create()["id"]
        self.record_all(pid)
        wait_until(lambda: self.done_count(pid) == 3)

        seg = self.project(pid)["timeline"][0]
        first_take = seg["active_take"]

        self.client.post(f"/api/segments/{seg['id']}/requeue")
        self.assertTrue(wait_until(
            lambda: len(self.client.get(f"/api/segments/{seg['id']}/takes").json()) == 2))

        takes_list = self.client.get(f"/api/segments/{seg['id']}/takes").json()
        self.assertEqual([t["n"] for t in takes_list], [2, 1])       # newest first
        new_take = takes_list[0]
        self.assertTrue(new_take["active"])
        self.assertFalse(new_take["outdated"])

        # the previous take still exists on disk and still plays
        self.assertTrue(os.path.exists(paths.take_path(pid, seg["id"], first_take)))
        r = self.client.get(f"/api/takes/{first_take}/audio")
        self.assertEqual(r.status_code, 200)

    def test_promote_moves_only_the_pointer(self):
        pid = self.create()["id"]
        self.record_all(pid)
        wait_until(lambda: self.done_count(pid) == 3)
        seg_id = self.project(pid)["timeline"][0]["id"]

        for _ in range(2):
            count = len(self.client.get(f"/api/segments/{seg_id}/takes").json())
            self.client.post(f"/api/segments/{seg_id}/requeue")
            wait_until(lambda: len(
                self.client.get(f"/api/segments/{seg_id}/takes").json()) == count + 1)

        listing = self.client.get(f"/api/segments/{seg_id}/takes").json()
        self.assertEqual(len(listing), 3)
        take_one = next(t for t in listing if t["n"] == 1)

        r = self.client.post(f"/api/segments/{seg_id}/takes/{take_one['id']}/promote")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["segment"]["active_take"], take_one["id"])
        self.assertEqual(r.json()["segment"]["status"], "done")

        after = self.client.get(f"/api/segments/{seg_id}/takes").json()
        self.assertEqual(len(after), 3, "promoting must not delete anything")
        for take in after:
            self.assertTrue(os.path.exists(paths.take_path(pid, seg_id, take["id"])))

    def test_deleting_the_active_take_is_refused(self):
        pid = self.create()["id"]
        self.record_all(pid)
        wait_until(lambda: self.done_count(pid) == 3)
        seg = self.project(pid)["timeline"][0]

        r = self.client.delete(f"/api/segments/{seg['id']}/takes/{seg['active_take']}")
        self.assertEqual(r.status_code, 409)
        self.assertTrue(os.path.exists(paths.take_path(pid, seg["id"], seg["active_take"])))

    def test_deleting_a_take_does_not_reuse_its_number(self):
        pid = self.create()["id"]
        self.record_all(pid)
        wait_until(lambda: self.done_count(pid) == 3)
        seg_id = self.project(pid)["timeline"][0]["id"]

        self.client.post(f"/api/segments/{seg_id}/requeue")
        wait_until(lambda: len(self.client.get(f"/api/segments/{seg_id}/takes").json()) == 2)

        take_one = next(t for t in self.client.get(f"/api/segments/{seg_id}/takes").json()
                        if t["n"] == 1)
        r = self.client.delete(f"/api/segments/{seg_id}/takes/{take_one['id']}")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(os.path.exists(paths.take_path(pid, seg_id, take_one["id"])))

        self.client.post(f"/api/segments/{seg_id}/requeue")
        wait_until(lambda: len(self.client.get(f"/api/segments/{seg_id}/takes").json()) == 2)
        numbers = [t["n"] for t in self.client.get(f"/api/segments/{seg_id}/takes").json()]
        self.assertEqual(sorted(numbers), [2, 3], "n must never be reused")

    def test_editing_text_marks_takes_outdated_and_segment_stale(self):
        pid = self.create()["id"]
        self.record_all(pid)
        wait_until(lambda: self.done_count(pid) == 3)
        seg_id = self.project(pid)["timeline"][0]["id"]

        r = self.client.patch(f"/api/segments/{seg_id}",
                              json={"text_override": "Совсем другой текст этого куска."})
        self.assertEqual(r.status_code, 200)
        # The edit invalidated the audio, so the segment queued itself for
        # re-recording; "queued" is the visible consequence of going stale.
        self.assertEqual(r.json()["segment"]["status"], "queued")

        listing = self.client.get(f"/api/segments/{seg_id}/takes").json()
        self.assertTrue(all(t["outdated"] for t in listing))
        # still playable — the user should be able to hear what it used to say
        self.assertEqual(self.client.get(f"/api/segments/{seg_id}/audio").status_code, 200)

    def test_promoting_an_outdated_take_leaves_the_segment_stale(self):
        pid = self.create()["id"]
        self.record_all(pid)
        wait_until(lambda: self.done_count(pid) == 3)
        seg_id = self.project(pid)["timeline"][0]["id"]
        old_take = self.project(pid)["timeline"][0]["active_take"]

        self.client.patch(f"/api/segments/{seg_id}", json={"text_override": "Новый текст."})
        self.client.post(f"/api/segments/{seg_id}/requeue")
        self.assertTrue(wait_until(
            lambda: self.client.get(f"/api/projects/{pid}").json()["timeline"][0]["status"] == "done",
            timeout=60))

        r = self.client.post(f"/api/segments/{seg_id}/takes/{old_take}/promote")
        self.assertEqual(r.json()["segment"]["status"], "stale")

    # --- tags ---------------------------------------------------------------

    def test_favorites_are_listed_across_projects(self):
        a = self.create(TEXT, "book a")["id"]
        b = self.create(TEXT, "book b")["id"]
        for pid in (a, b):
            seg = self.project(pid)["timeline"][1]
            self.client.patch(f"/api/segments/{seg['id']}", json={"favorite": True})

        groups = self.client.get("/api/favorites").json()
        self.assertEqual(len(groups), 2)
        self.assertEqual({g["project"] for g in groups}, {a, b})
        for group in groups:
            self.assertEqual(len(group["segments"]), 1)

    def queue(self, pid):
        return self.client.get(f"/api/projects/{pid}/queue").json()["queue"]

    def test_marking_for_rerecord_queues_the_segment(self):
        """The mark is not a sticky note — it is the thing that queues work."""
        pid = self.create()["id"]
        seg = self.project(pid)["timeline"][2]
        self.client.patch(f"/api/segments/{seg['id']}", json={"rerecord": True})

        rows = self.queue(pid)
        self.assertEqual([r["id"] for r in rows], [seg["id"]])
        self.assertTrue(rows[0]["rerecord"])
        self.assertEqual(rows[0]["status"], "queued")

    def test_unmarking_takes_it_back_out_of_the_queue(self):
        pid = self.create()["id"]
        seg = self.project(pid)["timeline"][1]
        self.client.patch(f"/api/segments/{seg['id']}", json={"rerecord": True})
        self.assertEqual(len(self.queue(pid)), 1)

        self.client.patch(f"/api/segments/{seg['id']}", json={"rerecord": False})
        self.assertEqual(self.queue(pid), [])
        self.assertEqual(self.project(pid)["timeline"][1]["status"], "pending")

    def test_dequeue_removes_one_segment_without_recording_it(self):
        pid = self.create()["id"]
        self.client.post(f"/api/projects/{pid}/record/start", json={"scope": "all"})
        self.client.post(f"/api/projects/{pid}/record/stop")

        rows = self.queue(pid)
        self.assertGreaterEqual(len(rows), 1)
        victim = rows[-1]["id"]
        before = self.done_count(pid)

        r = self.client.post(f"/api/segments/{victim}/dequeue")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["removed"], 1)
        self.assertNotIn(victim, [row["id"] for row in self.queue(pid)])
        self.assertEqual(self.done_count(pid), before, "dequeue must not count as recorded")

    def test_rerecords_are_queued_ahead_and_in_text_order(self):
        pid = self.create()["id"]
        segs = self.project(pid)["timeline"]
        # Queue all three as first-pass work without waking the worker, so the
        # ordering can be inspected without racing a consumer.
        runner.enqueue(projects.load(pid), [s["id"] for s in segs])
        self.assertEqual(len(self.queue(pid)), 3)

        # mark the last one first, then the middle one: click order must not win
        for index in (2, 1):
            self.client.patch(f"/api/segments/{segs[index]['id']}", json={"rerecord": True})

        order = [r["id"] for r in self.queue(pid)]
        self.assertEqual(order, [segs[1]["id"], segs[2]["id"], segs[0]["id"]],
                         "re-records first, in text order, then first-pass work")
        self.assertEqual([r["rerecord"] for r in self.queue(pid)], [True, True, False])

    def test_worker_goes_idle_when_the_queue_drains(self):
        """Running means "chewing through a queue" — it ends when the queue does."""
        pid = self.create()["id"]
        self.record_all(pid)
        self.assertTrue(wait_until(lambda: self.done_count(pid) == 3))
        self.assertTrue(wait_until(
            lambda: not self.client.get("/api/worker").json()["running"], timeout=30),
            "should stop claiming to run once there is nothing left")
        self.assertEqual(self.queue(pid), [])

    def test_work_marked_mid_run_is_picked_up_without_pressing_record(self):
        long_text = para(*[f"Абзац номер {i}, довольно длинный текст для озвучки." * 3
                           for i in range(1, 9)])
        pid = self.create(long_text, "midrun")["id"]
        total = self.project(pid)["stats"]["segments"]
        self.record_all(pid)
        self.assertTrue(wait_until(lambda: self.done_count(pid) >= 1, timeout=90))

        # edit a segment that is already done, while the run is still going
        done = next(s for s in self.project(pid)["timeline"] if s["status"] == "done")
        self.client.patch(f"/api/segments/{done['id']}",
                          json={"text_override": "Совсем другой текст этого куска."})

        # it went stale, so it queued itself, and the running worker takes it
        self.assertTrue(wait_until(
            lambda: len(self.client.get(f"/api/segments/{done['id']}/takes").json()) == 2,
            timeout=120), "a stale segment should be re-recorded by the running worker")
        self.assertTrue(wait_until(lambda: self.done_count(pid) == total, timeout=180))

    def test_editing_text_queues_the_segment(self):
        pid = self.create()["id"]
        self.record_all(pid)
        wait_until(lambda: self.done_count(pid) == 3)
        wait_until(lambda: not self.client.get("/api/worker").json()["running"], timeout=30)

        seg = self.project(pid)["timeline"][1]
        self.client.patch(f"/api/segments/{seg['id']}",
                          json={"text_override": "Другой текст, звук больше не подходит."})

        rows = self.queue(pid)
        self.assertEqual([r["id"] for r in rows], [seg["id"]])
        self.assertTrue(rows[0]["rerecord"])

    def test_download_serves_an_attachment_with_an_export_name(self):
        pid = self.create()["id"]
        self.record_all(pid)
        wait_until(lambda: self.done_count(pid) == 3)
        seg = self.project(pid)["timeline"][1]

        r = self.client.get(f"/api/segments/{seg['id']}/audio?download=1")
        self.assertEqual(r.status_code, 200)
        disposition = r.headers["content-disposition"]
        self.assertIn("attachment", disposition)
        self.assertIn(f"0002_L{seg['line']:04d}.wav", disposition)

        # streaming playback must stay inline, not become a download
        plain = self.client.get(f"/api/segments/{seg['id']}/audio")
        self.assertNotIn("attachment", plain.headers.get("content-disposition", ""))

    def test_rerecord_scope_only_records_marked_segments(self):
        pid = self.create()["id"]
        seg = self.project(pid)["timeline"][2]
        self.client.patch(f"/api/segments/{seg['id']}", json={"rerecord": True})

        self.client.post(f"/api/projects/{pid}/record/start", json={"scope": "rerecord"})
        self.assertTrue(wait_until(lambda: self.done_count(pid) == 1))
        statuses = {s["id"]: s["status"] for s in self.project(pid)["timeline"]}
        self.assertEqual(statuses[seg["id"]], "done")

    def test_recording_clears_the_rerecord_mark(self):
        pid = self.create()["id"]
        seg = self.project(pid)["timeline"][0]
        self.client.patch(f"/api/segments/{seg['id']}", json={"rerecord": True})
        self.client.post(f"/api/projects/{pid}/record/start", json={"scope": "rerecord"})
        wait_until(lambda: self.done_count(pid) == 1)
        self.assertFalse(self.project(pid)["timeline"][0]["rerecord"])


if __name__ == "__main__":
    unittest.main()
