"""Compose runs ffmpeg for real — these tests produce actual audio files.

The point of most of them is ordering and content: the output has to contain
exactly the takes that were active when compose was asked, in timeline order,
with the gaps and inserts in between.
"""
import os
import subprocess
import time
import unittest

os.environ["LUMANN_FAKE_TTS"] = "1"

from base import ProjectTest, para                              # noqa: E402
from fastapi.testclient import TestClient                       # noqa: E402
from test_recording import wait_until                           # noqa: E402

from server.core import compose, paths, projects                # noqa: E402
from server.jobs.runner import runner                           # noqa: E402
from server.main import app                                     # noqa: E402

TEXT = para(
    "Первый абзац этой небольшой главы.",
    "Второй абзац, чуть подлиннее первого.",
    "Третий и последний абзац.",
)


def have_ffmpeg():
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True,
                       stdin=subprocess.DEVNULL, check=True)
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


@unittest.skipUnless(have_ffmpeg(), "ffmpeg not on PATH")
class ComposeTest(ProjectTest):

    def setUp(self):
        super().setUp()
        self.client = TestClient(app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.addCleanup(runner.shutdown)

        self.pid = self.client.post(
            "/api/projects", json={"title": "compose", "text": TEXT}).json()["id"]
        self.client.post(f"/api/projects/{self.pid}/record/start", json={"scope": "all"})
        self.assertTrue(wait_until(lambda: self.stats()["done"] == 3, timeout=60))

    def stats(self):
        return self.client.get(f"/api/projects/{self.pid}").json()["stats"]

    def project(self):
        return self.client.get(f"/api/projects/{self.pid}").json()

    def run_compose(self, fmt="wav", timeout=90):
        record = self.client.post(f"/api/projects/{self.pid}/compose",
                                  json={"format": fmt}).json()
        cid = record["id"]
        self.assertTrue(wait_until(
            lambda: self.client.get(f"/api/composes/{cid}").json()["status"] != "running",
            timeout=timeout), "compose never finished")
        return self.client.get(f"/api/composes/{cid}").json()

    # --- basics -------------------------------------------------------------

    def test_wav_compose_produces_a_playable_file(self):
        record = self.run_compose("wav")
        self.assertEqual(record["status"], "done", record.get("error"))
        path = compose.file_path(record)
        self.assertTrue(os.path.exists(path))
        self.assertGreater(compose.probe_duration(path), 0)

    def test_m4a_compose_reports_determinate_progress(self):
        record = self.run_compose("m4a")
        self.assertEqual(record["status"], "done", record.get("error"))
        self.assertTrue(record["determinate"], "m4a should offer a real progress bar")
        self.assertEqual(record["progress"], 1.0)
        self.assertTrue(compose.file_path(record).endswith(".m4a"))

    def test_wav_is_marked_indeterminate(self):
        # -c copy finishes in about a second; a percentage bar would just flash.
        record = self.run_compose("wav")
        self.assertFalse(record["determinate"])

    def test_duration_matches_takes_plus_gaps(self):
        project = self.project()
        gap = project["gap_seconds"]
        expected = sum(
            next(t["duration"] for t in item["takes"] if t["id"] == item["active_take"])
            for item in project["timeline"] if item["kind"] == "segment"
        ) + gap * 2
        record = self.run_compose("wav")
        actual = compose.probe_duration(compose.file_path(record))
        self.assertAlmostEqual(actual, expected, delta=0.3)

    def test_manifest_records_the_exact_takes_used(self):
        record = self.run_compose("wav")
        import json
        path = os.path.join(paths.composes_dir(self.pid), record["id"] + ".json")
        with open(path, encoding="utf-8") as fh:
            manifest = json.load(fh)

        project = self.project()
        active = [item["active_take"] for item in project["timeline"]
                  if item["kind"] == "segment"]
        used = [step["take"] for step in manifest["timeline"] if step["kind"] == "segment"]
        self.assertEqual(used, active)

    # --- takes --------------------------------------------------------------

    def test_compose_uses_only_the_active_take(self):
        seg_id = self.project()["timeline"][0]["id"]
        self.client.post(f"/api/segments/{seg_id}/requeue")
        self.assertTrue(wait_until(
            lambda: len(self.client.get(f"/api/segments/{seg_id}/takes").json()) == 2,
            timeout=60))

        listing = self.client.get(f"/api/segments/{seg_id}/takes").json()
        take_one = next(t for t in listing if t["n"] == 1)
        self.client.post(f"/api/segments/{seg_id}/takes/{take_one['id']}/promote")

        record = self.run_compose("wav")
        import json
        with open(os.path.join(paths.composes_dir(self.pid), record["id"] + ".json"),
                  encoding="utf-8") as fh:
            manifest = json.load(fh)
        used = next(s["take"] for s in manifest["timeline"] if s["id"] == seg_id)
        self.assertEqual(used, take_one["id"], "compose must read the promoted take")

    # --- inserts ------------------------------------------------------------

    def test_silence_insert_lengthens_the_output(self):
        before = compose.probe_duration(compose.file_path(self.run_compose("wav")))
        first = self.project()["timeline"][0]["id"]
        r = self.client.post(f"/api/projects/{self.pid}/inserts",
                             json={"after_id": first, "insert_type": "silence",
                                   "seconds": 2.0})
        self.assertEqual(r.status_code, 200, r.text)

        after = compose.probe_duration(compose.file_path(self.run_compose("wav")))
        gap = self.project()["gap_seconds"]
        self.assertAlmostEqual(after - before, 2.0 + gap, delta=0.3)

    def test_segments_without_audio_are_skipped_and_counted(self):
        seg_id = self.project()["timeline"][1]["id"]
        take = self.project()["timeline"][1]["active_take"]
        # simulate a segment whose audio never got recorded
        with projects.lock(self.pid):
            project = projects.load(self.pid)
            _idx, segment = projects.find_item(project, seg_id)
            segment["active_take"] = None
            segment["takes"] = []
            segment["status"] = "pending"
            projects.save(project)
        os.remove(paths.take_path(self.pid, seg_id, take))

        record = self.run_compose("wav")
        self.assertEqual(record["status"], "done")
        self.assertEqual(record["skipped"], 1)
        self.assertEqual(record["steps"], 2)

    # --- concurrency --------------------------------------------------------

    def test_compose_snapshots_the_timeline_while_recording_continues(self):
        """Acceptance: output holds exactly what was finished at request time."""
        long_text = para(*[f"Абзац номер {i} этой довольно длинной главы." * 3
                           for i in range(1, 10)])
        pid = self.client.post("/api/projects",
                               json={"title": "parallel", "text": long_text}).json()["id"]

        def done_count():
            return self.client.get(f"/api/projects/{pid}").json()["stats"]["done"]

        self.client.post(f"/api/projects/{pid}/record/start", json={"scope": "all"})
        self.assertTrue(wait_until(lambda: done_count() >= 2, timeout=90))

        finished_before = done_count()
        record = self.client.post(f"/api/projects/{pid}/compose",
                                  json={"format": "wav"}).json()
        self.assertLessEqual(record["steps"], done_count())
        self.assertGreaterEqual(record["steps"], finished_before)

        cid = record["id"]
        self.assertTrue(wait_until(
            lambda: self.client.get(f"/api/composes/{cid}").json()["status"] != "running",
            timeout=90))
        final = self.client.get(f"/api/composes/{cid}").json()
        self.assertEqual(final["status"], "done", final.get("error"))

        # recording was never disturbed by the compose
        self.assertTrue(wait_until(
            lambda: done_count() == self.client.get(f"/api/projects/{pid}").json()["stats"]["segments"],
            timeout=180))

    def test_empty_project_fails_cleanly(self):
        pid = self.client.post("/api/projects",
                               json={"title": "empty", "text": TEXT}).json()["id"]
        record = self.client.post(f"/api/projects/{pid}/compose",
                                  json={"format": "wav"}).json()
        self.assertEqual(record["status"], "failed")
        self.assertIn("nothing recorded", record["error"])


if __name__ == "__main__":
    unittest.main()
