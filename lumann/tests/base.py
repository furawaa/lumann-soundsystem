"""Shared test scaffolding: an isolated projects/ dir per test case.

paths.py reads LUMANN_PROJECTS_DIR at import time, so it is set here before
anything under server/ is imported.
"""
import os
import shutil
import sys
import tempfile
import unittest

_LUMANN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _LUMANN not in sys.path:
    sys.path.insert(0, _LUMANN)

_TMP = tempfile.mkdtemp(prefix="lumann-test-")
os.environ.setdefault("LUMANN_PROJECTS_DIR", os.path.join(_TMP, "projects"))
os.environ.setdefault("LUMANN_SAMPLES_DIR", os.path.join(_TMP, "samples"))
os.environ.setdefault("LUMANN_VOICES_DIR", os.path.join(_TMP, "voices"))
# Never a real Qwen install: tests must not see, use or delete one.
os.environ["LUMANN_QWEN_DIR"] = os.path.join(_TMP, "qwen")
os.environ.pop("QWEN_TTS_MODEL", None)

from server.core import paths, projects   # noqa: E402


class ProjectTest(unittest.TestCase):
    """Wipes projects/ between tests so ids and slugs stay predictable."""

    def setUp(self):
        shutil.rmtree(paths.PROJECTS_DIR, ignore_errors=True)
        paths.ensure_dirs()

    def make(self, text, title="test"):
        return projects.create(title, text)

    def give_take(self, project, segment, duration=10.0, text_hash=None):
        """Attach a recorded take, as the runner would, without a model."""
        take_id = projects.new_id()
        path = paths.take_path(project["id"], segment["id"], take_id)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(b"RIFF____WAVEfake")
        segment.setdefault("takes", []).append({
            "id": take_id,
            "n": len(segment.get("takes") or []) + 1,
            "created_at": projects.now(),
            "duration": duration,
            "text_hash": text_hash or segment["text_hash"],
            "temperature": 0.8,
            "note": None,
        })
        segment["active_take"] = take_id
        projects.sync_status(segment)
        projects.save(project)
        return take_id


def para(*lines):
    """Build source text in the app's paragraph shape: indented start line."""
    return "\n\n".join("    " + line for line in lines) + "\n"
