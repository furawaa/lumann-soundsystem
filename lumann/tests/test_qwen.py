"""Qwen3-TTS is installed only when the user asks, and Delete removes all of it.

A local HTTP server stands in for Hugging Face, so the download, resume and
delete paths run for real without fetching 4.5 GB. The pip step is not run
here: packages are patched in as present.
"""
import json
import os
import shutil
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from base import ProjectTest, para
from fastapi.testclient import TestClient

from server.core import qwen, voices
from server.jobs.runner import runner
from server.main import app
from test_recording import wait_until
from test_voices import clip

FILES = {
    "config.json": b'{"model_type": "qwen3_tts"}',
    "model.safetensors": bytes(range(256)) * 4096,           # 1 MB
    "speech_tokenizer/model.safetensors": b"tokenizer" * 1000,
}


class FakeHub(BaseHTTPRequestHandler):
    """The two Hugging Face endpoints the downloader uses, with Range support."""
    status = 200
    ranges = []

    def do_GET(self):                                   # noqa: N802 - stdlib name
        if FakeHub.status != 200:
            self.send_error(FakeHub.status)
            return
        if self.path.startswith(f"/api/models/{qwen.REPO}"):
            body = json.dumps({"sha": "rev1", "siblings": [
                {"rfilename": name, "size": len(data)} for name, data in FILES.items()
            ] + [{"rfilename": ".gitattributes", "size": 10}]}).encode()
            self._send(200, body)
            return
        prefix = f"/{qwen.REPO}/resolve/rev1/"
        name = self.path[len(prefix):] if self.path.startswith(prefix) else None
        if name not in FILES:
            self.send_error(404)
            return
        data = FILES[name]
        wanted = self.headers.get("Range")
        if wanted:
            FakeHub.ranges.append((name, wanted))
            start = int(wanted.split("=")[1].split("-")[0])
            self._send(206, data[start:])
        else:
            self._send(200, data)

    def _send(self, code, body):
        self.send_response(code)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class QwenInstallTest(ProjectTest):

    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeHub)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        super().setUp()
        shutil.rmtree(qwen.ROOT, ignore_errors=True)
        qwen.delete()
        FakeHub.status, FakeHub.ranges = 200, []
        for patcher in (
            mock.patch.object(qwen, "HUB", f"http://127.0.0.1:{self.server.server_port}"),
            # The pip step is out of scope here; the model download is not.
            mock.patch.object(qwen, "packages_ready", lambda: True),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def install(self):
        self.assertTrue(qwen.install())
        self.assertTrue(wait_until(lambda: qwen.status()["step"] is None, timeout=30))
        return qwen.status()

    def test_nothing_is_there_until_asked_for(self):
        status = qwen.status()
        self.assertFalse(status["model"])
        self.assertIsNone(status["step"])
        self.assertEqual(status["disk_bytes"], 0)
        self.assertIsNone(qwen.model_path())
        self.assertFalse(os.path.exists(qwen.ROOT), "nothing may be created before Download")

    def test_download_fetches_every_file_and_marks_the_model_complete(self):
        status = self.install()
        self.assertIsNone(status["error"])
        self.assertTrue(status["available"])
        self.assertEqual(qwen.model_path(), qwen.MODEL_DIR)
        for name, data in FILES.items():
            with open(os.path.join(qwen.MODEL_DIR, name), "rb") as fh:
                self.assertEqual(fh.read(), data, name)
        self.assertFalse(os.path.exists(os.path.join(qwen.MODEL_DIR, ".gitattributes")))
        self.assertFalse(os.path.exists(qwen.MODEL_DIR + ".part"))
        self.assertEqual(status["downloaded"], sum(len(d) for d in FILES.values()))
        self.assertGreater(status["disk_bytes"], 0)

    def test_an_interrupted_download_resumes_where_it_stopped(self):
        part = os.path.join(qwen.MODEL_DIR + ".part", "model.safetensors")
        os.makedirs(os.path.dirname(part))
        half = len(FILES["model.safetensors"]) // 2
        with open(part, "wb") as fh:
            fh.write(FILES["model.safetensors"][:half])

        self.install()
        self.assertIn(("model.safetensors", f"bytes={half}-"), FakeHub.ranges)
        with open(os.path.join(qwen.MODEL_DIR, "model.safetensors"), "rb") as fh:
            self.assertEqual(fh.read(), FILES["model.safetensors"])

    def test_a_failed_download_is_reported_and_leaves_no_model(self):
        FakeHub.status = 503
        status = self.install()
        self.assertTrue(status["error"])
        self.assertFalse(status["model"])
        self.assertIsNone(qwen.model_path())

    def test_delete_removes_everything_including_a_half_download(self):
        self.install()
        os.makedirs(qwen.PACKAGES_DIR + ".part")
        qwen.delete()
        self.assertFalse(os.path.exists(qwen.ROOT))
        self.assertIsNone(qwen.model_path())
        self.assertEqual(qwen.status()["disk_bytes"], 0)

    def test_the_api_installs_and_deletes_on_request(self):
        with TestClient(app) as client:
            self.assertFalse(client.get("/api/engines").json()["qwen"]["model"])
            self.assertEqual(client.post("/api/engines/qwen/install").status_code, 200)
            self.assertTrue(wait_until(
                lambda: client.get("/api/engines").json()["qwen"]["step"] is None, timeout=30))
            self.assertTrue(client.get("/api/engines").json()["qwen"]["available"])

            deleted = client.delete("/api/engines/qwen")
            self.assertEqual(deleted.status_code, 200)
            self.assertFalse(deleted.json()["model"])
            self.assertFalse(os.path.exists(qwen.ROOT))


class CloneWithoutModelTest(ProjectTest):
    """A cloned voice with no model must fail with a message, never download."""

    def setUp(self):
        super().setUp()
        runner.shutdown()
        qwen.delete()
        env = {k: v for k, v in os.environ.items() if k != "LUMANN_FAKE_TTS"}
        patcher = mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = TestClient(app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.addCleanup(runner.shutdown)

    def test_recording_fails_fast_and_says_what_to_do(self):
        voice = voices.create("Clone", [clip()])
        pid = self.client.post("/api/projects",
                               json={"title": "c", "text": para("Первый абзац.")}).json()["id"]
        self.client.patch(f"/api/projects/{pid}", json={"voice": voice["id"]})
        started = time.time()
        self.client.post(f"/api/projects/{pid}/record/start", json={"scope": "all"})

        def failed():
            return self.client.get(f"/api/projects/{pid}").json()["stats"]["failed"] == 1
        self.assertTrue(wait_until(failed, timeout=30))
        self.assertLess(time.time() - started, 15, "no retries for a missing install")
        error = self.client.get(f"/api/projects/{pid}").json()["timeline"][0]["error"]
        self.assertIn("not downloaded", error)
        self.assertFalse(os.path.exists(qwen.ROOT), "recording must never start a download")


if __name__ == "__main__":
    unittest.main()
