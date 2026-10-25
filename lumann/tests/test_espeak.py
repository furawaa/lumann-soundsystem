"""The default engine for real: queue, worker, eSpeak NG, takes and compose.

Every other recording test runs the fake worker. This one does not, so it is
skipped on machines without espeak-ng.
"""
import os
import unittest
from unittest import mock

from base import ProjectTest, para
from fastapi.testclient import TestClient

from server.core import compose, espeak, paths
from server.jobs.runner import runner
from server.main import app
from test_recording import wait_until

TEXT = para(
    "The first paragraph of a very short book.",
    "-A second one, which starts with a dash, as dialogue often does.",
)


@unittest.skipUnless(espeak.available(), "espeak-ng not installed")
class EspeakRecordingTest(ProjectTest):

    def setUp(self):
        super().setUp()
        runner.shutdown()                   # a fake worker from another test must go
        env = {k: v for k, v in os.environ.items() if k != "LUMANN_FAKE_TTS"}
        patcher = mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = TestClient(app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.addCleanup(runner.shutdown)

    def test_a_book_is_spoken_by_espeak_and_composed(self):
        pid = self.client.post("/api/projects", json={"title": "es", "text": TEXT}).json()["id"]
        self.client.post(f"/api/projects/{pid}/record/start", json={"scope": "all"})

        def done():
            return self.client.get(f"/api/projects/{pid}").json()["stats"]["done"] == 2
        self.assertTrue(wait_until(done, timeout=60),
                        self.client.get(f"/api/projects/{pid}").json()["stats"])

        project = self.client.get(f"/api/projects/{pid}").json()
        for seg in project["timeline"]:
            path = paths.take_path(pid, seg["id"], seg["active_take"])
            self.assertEqual(compose.probe_rate(path), "24000")
            self.assertGreater(compose.probe_duration(path), 1.0, "silence, not speech")
            take = seg["takes"][0]
            self.assertEqual(take["voice"], "espeak-en")
            self.assertIsNone(take["temperature"], "temperature is a Qwen setting")

        started = self.client.post(f"/api/projects/{pid}/compose", json={"format": "wav"})
        self.assertEqual(started.status_code, 200, started.text)
        cid = started.json()["id"]

        def composed():
            return self.client.get(f"/api/composes/{cid}").json()["status"] == "done"
        self.assertTrue(wait_until(composed, timeout=60))


if __name__ == "__main__":
    unittest.main()
