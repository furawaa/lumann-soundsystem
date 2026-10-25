"""Moving an insert around the timeline.

This is what the grip in the track list drags: the row goes somewhere else and
PATCH /inserts/{id} with `after_id` is the whole move. The order it produces is
the order compose will splice in, so the cases below are about the order and
about the one call shape the UI has to avoid.
"""
import os
import unittest

os.environ["LUMANN_FAKE_TTS"] = "1"

from base import ProjectTest, para                              # noqa: E402
from fastapi.testclient import TestClient                       # noqa: E402

from server.main import app                                     # noqa: E402

TEXT = para(
    "Первый абзац этой небольшой главы.",
    "Второй абзац, чуть подлиннее первого.",
    "Третий и последний абзац.",
)


class InsertMoveTest(ProjectTest):

    def setUp(self):
        super().setUp()
        self.client = TestClient(app)
        self.pid = self.client.post(
            "/api/projects", json={"title": "inserts", "text": TEXT}).json()["id"]
        self.segments = [item["id"] for item in self.timeline()]
        self.assertEqual(len(self.segments), 3)

        created = self.client.post(
            f"/api/projects/{self.pid}/inserts",
            json={"after_id": self.segments[0], "insert_type": "silence", "seconds": 2.0})
        self.assertEqual(created.status_code, 200, created.text)
        self.insert_id = created.json()["insert"]["id"]

    def timeline(self):
        return self.client.get(f"/api/projects/{self.pid}").json()["timeline"]

    def order(self):
        """-> ids in timeline order, the insert shown as 'X'."""
        return ["X" if item["id"] == getattr(self, "insert_id", None) else item["id"]
                for item in self.timeline()]

    def move(self, after_id):
        return self.client.patch(f"/api/inserts/{self.insert_id}",
                                 json={"after_id": after_id})

    def test_starts_after_the_first_segment(self):
        a, b, c = self.segments
        self.assertEqual(self.order(), [a, "X", b, c])

    def test_moves_further_down(self):
        a, b, c = self.segments
        self.assertEqual(self.move(c).status_code, 200)
        self.assertEqual(self.order(), [a, b, c, "X"])

    def test_moves_back_up(self):
        a, b, c = self.segments
        self.move(c)
        self.assertEqual(self.move(a).status_code, 200)
        self.assertEqual(self.order(), [a, "X", b, c])

    def test_moves_to_the_very_top(self):
        """Dropping above the first row: the UI sends an empty anchor."""
        a, b, c = self.segments
        self.assertEqual(self.move("").status_code, 200)
        self.assertEqual(self.order(), ["X", a, b, c])

    def test_moving_keeps_what_the_insert_is(self):
        self.move(self.segments[2])
        insert = next(item for item in self.timeline() if item["id"] == self.insert_id)
        self.assertEqual(insert["insert_type"], "silence")
        self.assertEqual(insert["seconds"], 2.0)
        self.assertEqual(insert["duration"], 2.0)

    def test_anchoring_an_insert_to_itself_is_refused(self):
        """The row is lifted out before the anchor is looked up, so its own id
        is no longer there to anchor to. The drag guards against this; if that
        guard ever goes, the timeline must still survive the request."""
        before = self.order()
        self.assertEqual(self.move(self.insert_id).status_code, 404)
        self.assertEqual(self.order(), before)

    def test_an_unknown_anchor_changes_nothing(self):
        before = self.order()
        self.assertEqual(self.move("no-such-id").status_code, 404)
        self.assertEqual(self.order(), before)


if __name__ == "__main__":
    unittest.main()
