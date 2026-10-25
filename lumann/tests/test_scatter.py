"""Scattering random samples across a book.

The interesting part is the minimum gap: it is measured in seconds of the
finished audio, not in segments, so the placement has to know how long each
segment will be — including the ones that have not been recorded yet.
"""
import os
import unittest

os.environ["LUMANN_FAKE_TTS"] = "1"

from base import ProjectTest, para                              # noqa: E402
from fastapi.testclient import TestClient                       # noqa: E402

from server.core import paths, projects                         # noqa: E402
from server.main import app                                     # noqa: E402

# Twelve paragraphs of a similar length, so the audio estimate is even.
TEXT = para(*[f"Абзац номер {n}, довольно обычной длины для книги." for n in range(1, 13)])


class ScatterTest(ProjectTest):

    def setUp(self):
        super().setUp()
        self.client = TestClient(app)
        self.pid = self.client.post(
            "/api/projects", json={"title": "scatter", "text": TEXT}).json()["id"]

        paths.ensure_dirs()
        self.samples = ["door.wav", "steps.wav"]
        for name in self.samples:
            with open(paths.sample_path(name), "wb") as fh:
                fh.write(b"RIFF____WAVEfake")

    def scatter(self, **body):
        return self.client.post(f"/api/projects/{self.pid}/inserts/scatter",
                                json={"samples": self.samples, **body})

    def inserts(self):
        project = self.client.get(f"/api/projects/{self.pid}").json()
        return [item for item in project["timeline"] if item["kind"] == "insert"]

    def positions(self):
        """Index of every insert in the timeline."""
        project = self.client.get(f"/api/projects/{self.pid}").json()
        return [i for i, item in enumerate(project["timeline"]) if item["kind"] == "insert"]

    def test_places_the_number_asked_for(self):
        r = self.scatter(count=4)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["placed"], 4)
        self.assertEqual(len(self.inserts()), 4)

    def test_only_the_chosen_samples_are_used(self):
        self.scatter(count=6, samples=["door.wav"])
        self.assertEqual({item["sample"] for item in self.inserts()}, {"door.wav"})

    def test_they_do_not_all_land_in_one_place(self):
        self.scatter(count=5)
        self.assertEqual(len(set(self.positions())), 5, "each insert has its own slot")

    def test_a_gap_thins_them_out(self):
        """A gap longer than the whole book leaves room for exactly one."""
        r = self.scatter(count=8, min_gap_seconds=10_000)
        self.assertEqual(r.json()["placed"], 1)

    def test_placing_fewer_than_asked_is_not_an_error(self):
        r = self.scatter(count=99, min_gap_seconds=10_000)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["asked"], 99)
        self.assertEqual(r.json()["placed"], 1)

    def test_a_gap_is_kept_between_placed_samples(self):
        """Segments here are ~2.7 s of estimated audio, so a 5 s gap must leave
        at least one segment between any two inserts."""
        self.scatter(count=6, min_gap_seconds=5)
        spots = self.positions()
        gaps = [b - a for a, b in zip(spots, spots[1:])]
        self.assertTrue(all(gap >= 2 for gap in gaps), f"too close: {spots}")

    def test_existing_inserts_are_respected(self):
        first = self.client.get(f"/api/projects/{self.pid}").json()["timeline"][0]["id"]
        self.client.post(f"/api/projects/{self.pid}/inserts",
                         json={"after_id": first, "insert_type": "sample",
                               "sample": "door.wav"})
        before = self.positions()
        self.scatter(count=1, min_gap_seconds=10_000)
        self.assertEqual(self.positions(), before,
                         "no room left next to the insert already there")

    # --- undoing a scatter --------------------------------------------------

    def test_a_scatter_comes_back_as_one_batch(self):
        batch = self.scatter(count=4).json()["batch"]
        self.assertTrue(batch)
        self.assertEqual({item["batch"] for item in self.inserts()}, {batch})

    def test_a_batch_can_be_taken_back(self):
        batch = self.scatter(count=4).json()["batch"]
        r = self.client.delete(f"/api/projects/{self.pid}/inserts/batch/{batch}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["removed"], 4)
        self.assertEqual(self.inserts(), [])

    def test_undo_touches_only_its_own_batch(self):
        first = self.scatter(count=3).json()["batch"]
        second = self.scatter(count=3).json()["batch"]
        self.assertNotEqual(first, second)
        self.client.delete(f"/api/projects/{self.pid}/inserts/batch/{first}")
        self.assertEqual({item["batch"] for item in self.inserts()}, {second})

    def test_undo_leaves_hand_made_inserts_alone(self):
        anchor = self.client.get(f"/api/projects/{self.pid}").json()["timeline"][0]["id"]
        self.client.post(f"/api/projects/{self.pid}/inserts",
                         json={"after_id": anchor, "insert_type": "silence", "seconds": 2})
        batch = self.scatter(count=3).json()["batch"]
        self.client.delete(f"/api/projects/{self.pid}/inserts/batch/{batch}")
        left = self.inserts()
        self.assertEqual(len(left), 1)
        self.assertEqual(left[0]["insert_type"], "silence")

    def test_undoing_twice_is_harmless(self):
        batch = self.scatter(count=2).json()["batch"]
        self.client.delete(f"/api/projects/{self.pid}/inserts/batch/{batch}")
        again = self.client.delete(f"/api/projects/{self.pid}/inserts/batch/{batch}")
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.json()["removed"], 0)

    def test_an_unknown_sample_is_refused(self):
        r = self.scatter(count=1, samples=["nope.wav"])
        self.assertEqual(r.status_code, 404)
        self.assertEqual(self.inserts(), [])

    def test_no_samples_is_refused(self):
        self.assertEqual(self.scatter(count=1, samples=[]).status_code, 400)

    def test_zero_is_refused(self):
        self.assertEqual(self.scatter(count=0).status_code, 400)


if __name__ == "__main__":
    unittest.main()
