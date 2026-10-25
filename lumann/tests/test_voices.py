"""The voice library, and the one rule that matters: recording never breaks.

A voice is either a set of eSpeak settings or one or more reference clips, each
with its transcript. Projects point at a voice by id, so every way that pointer
can go bad — voice deleted, clip file gone, nothing configured at all — has to
end in a usable voice rather than a failed job.
"""
import math
import os
import shutil
import struct
import tempfile
import unittest
import wave
from unittest import mock

from base import ProjectTest, para
from fastapi.testclient import TestClient

from server.core import espeak, paths, projects, voices
from server.main import app

_CLIPS = tempfile.mkdtemp(prefix="lumann-clips-")


def _tone(name, seconds, hz):
    """A short sine wave: any real audio will do as a stand-in reference."""
    path = os.path.join(_CLIPS, name)
    rate = 24000
    with wave.open(path, "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(rate)
        fh.writeframes(b"".join(
            struct.pack("<h", int(8000 * math.sin(2 * math.pi * hz * i / rate)))
            for i in range(int(seconds * rate))))
    return path


CLIP = _tone("one.wav", 1.5, 220)
CLIP2 = _tone("two.wav", 2.0, 330)


def clip(name="second.wav", text="Текст второй записи.", source=CLIP):
    """One (filename, transcript, writer) triple, as `voices.create` wants."""
    return (name, text, lambda destination: shutil.copyfile(source, destination))


class VoiceStoreTest(ProjectTest):

    def setUp(self):
        super().setUp()
        shutil.rmtree(paths.VOICES_DIR, ignore_errors=True)
        paths.ensure_dirs()

    def test_the_built_in_espeak_voices_are_seeded_on_first_listing(self):
        listing = voices.list_all()
        self.assertEqual(sorted(v["id"] for v in listing), sorted(voices.BUILTINS))
        for voice in listing:
            self.assertEqual(voice["engine"], "espeak")
            self.assertTrue(voice["builtin"])
            self.assertEqual(voice["clips"], [])
            self.assertTrue(voice["espeak"]["voice"])

    def test_a_new_project_gets_the_built_in_voice_that_fits_its_text(self):
        russian = projects.create("ru", para("Первый абзац книги."))
        english = projects.create("en", para("The first paragraph of the book."))
        self.assertEqual(russian["voice"], voices.CYRILLIC_ID)
        self.assertEqual(english["voice"], voices.BUILTIN_ID)

        request = voices.request_for(russian)
        self.assertEqual(request["engine"], "espeak")
        self.assertEqual(request["espeak"]["voice"], "ru")

    def test_an_added_voice_supplies_its_own_clip_and_transcript(self):
        voice = voices.create("Вторая", [clip()])
        self.assertEqual(voice["engine"], "qwen")
        project = projects.create("two", para("Первый абзац книги."))
        project["voice"] = voice["id"]
        projects.save(project)

        request = voices.request_for(project)
        self.assertEqual(request["engine"], "qwen")
        self.assertEqual(os.path.basename(request["ref_audio"]), "second.wav")
        self.assertEqual(request["ref_text"], "Текст второй записи.")
        self.assertEqual(request["language"], "Auto")

    def test_a_transcript_is_required(self):
        with self.assertRaises(ValueError):
            voices.create("Без текста", [clip(text="   ")])

    def test_a_rejected_upload_leaves_nothing_behind(self):
        before = set(os.listdir(paths.VOICES_DIR))
        with self.assertRaises(ValueError):
            voices.create("半", [clip("one.wav", "Есть текст."), clip("two.wav", "  ")])
        self.assertEqual(set(os.listdir(paths.VOICES_DIR)), before)

    def test_deleting_the_voice_a_project_uses_still_leaves_it_recordable(self):
        voice = voices.create("Временная", [clip("temp.wav", "Текст.")])
        project = projects.create("orphan", para("Первый абзац книги."))
        project["voice"] = voice["id"]
        projects.save(project)
        voices.delete(voice["id"])

        request = voices.request_for(projects.load(project["id"]))
        self.assertEqual(request["engine"], "espeak",
                         "a deleted voice must fall back, not stop recording")
        self.assertEqual(request["espeak"]["voice"], "ru", "the fallback fits the text")

    def test_a_clone_voice_with_no_files_left_falls_back_to_espeak(self):
        voice = voices.create("Пропажа", [clip("gone.wav", "Текст.")])
        os.remove(voices.clip_path(voice["id"], voice["clips"][0]))
        project = projects.create("lost", para("The first paragraph."))
        project["voice"] = voice["id"]
        self.assertEqual(voices.request_for(project)["engine"], "espeak")

    # --- eSpeak voices -------------------------------------------------------

    def test_espeak_settings_are_filled_and_clamped(self):
        voice = voices.create_espeak("", {"voice": "de", "speed": 9999, "pitch": -5})
        self.assertEqual(voice["engine"], "espeak")
        self.assertEqual(voice["espeak"]["voice"], "de")
        self.assertEqual(voice["espeak"]["speed"], espeak.SPEED_RANGE[1])
        self.assertEqual(voice["espeak"]["pitch"], espeak.PITCH_RANGE[0])
        self.assertEqual(voice["espeak"]["variant"], "")
        self.assertTrue(voice["name"])

    def test_retuning_an_espeak_voice_changes_only_what_was_sent(self):
        voice = voices.create_espeak("Tuned", {"voice": "en-gb", "variant": "f3"})
        voice = voices.update(voice["id"], espeak_options={"speed": 120})
        self.assertEqual(voice["espeak"]["speed"], 120)
        self.assertEqual(voice["espeak"]["voice"], "en-gb")
        self.assertEqual(voice["espeak"]["variant"], "f3")

    def test_an_espeak_voice_takes_no_clips_and_a_clone_voice_no_settings(self):
        tuned = voices.create_espeak("Tuned", {})
        with self.assertRaises(ValueError):
            voices.add_clips(tuned["id"], [clip()])
        cloned = voices.create("Clone", [clip()])
        with self.assertRaises(ValueError):
            voices.update(cloned["id"], espeak_options={"speed": 120})

    # --- names --------------------------------------------------------------

    def test_an_espeak_voice_is_named_after_its_settings_until_renamed(self):
        voice = voices.create_espeak("", {"voice": "de", "variant": "", "speed": 140})
        self.assertFalse(voice["custom_name"])
        self.assertIn("140 wpm", voice["name"])
        if espeak.available():
            self.assertTrue(voice["name"].startswith("German"), voice["name"])

        retuned = voices.update(voice["id"], espeak_options={"speed": 120})
        self.assertIn("120 wpm", retuned["name"], "the name follows the settings")

        renamed = voices.update(voice["id"], name="  Reader Klaus ")
        self.assertEqual(renamed["name"], "Reader Klaus")
        self.assertTrue(renamed["custom_name"])
        retuned = voices.update(voice["id"], espeak_options={"speed": 200})
        self.assertEqual(retuned["name"], "Reader Klaus", "a chosen name stays put")

        reset = voices.update(voice["id"], name="")
        self.assertFalse(reset["custom_name"])
        self.assertIn("200 wpm", reset["name"])

    def test_names_the_app_wrote_itself_turn_back_into_automatic_ones(self):
        import json
        voices.list_all()
        mine = voices.create_espeak("", {"voice": "uk", "variant": "announcer"})
        kept = voices.create_espeak("", {"voice": "de"})
        for vid, old in ((voices.BUILTIN_ID, "eSpeak · English"),
                         (mine["id"], "eSpeak · en-us"),     # since switched to uk
                         (kept["id"], "eSpeak · my German")):
            with open(paths.voice_json(vid), encoding="utf-8") as fh:
                stored = json.load(fh)
            stored["name"] = old
            with open(paths.voice_json(vid), "w", encoding="utf-8") as fh:
                json.dump(stored, fh)
        self.assertFalse(voices.load(voices.BUILTIN_ID)["custom_name"])
        self.assertFalse(voices.load(mine["id"])["custom_name"])
        self.assertTrue(voices.load(kept["id"])["custom_name"], "a name the user typed stays")

    def test_the_built_in_voices_can_be_renamed_and_reset(self):
        voices.list_all()
        renamed = voices.update(voices.BUILTIN_ID, name="Mine")
        self.assertEqual(renamed["name"], "Mine")
        self.assertFalse(voices.update(voices.BUILTIN_ID, name="")["custom_name"])

    def test_a_clone_voice_without_a_name_is_named_after_its_first_clip(self):
        voice = voices.create("", [clip("reading.wav", "Текст.")])
        self.assertEqual(voice["name"], "reading.wav")
        self.assertEqual(voices.update(voice["id"], name="Anna")["name"], "Anna")

    def test_takes_record_the_name_the_voice_has_now(self):
        project = projects.create("named", para("Абзац."))
        voices.update(project["voice"], name="Чтец")
        self.assertEqual(voices.label(project), (project["voice"], "Чтец"))

    def test_an_espeak_voice_is_missing_only_without_the_binary(self):
        voice = voices.create_espeak("Tuned", {})
        with mock.patch.dict(os.environ, {"ESPEAK_NG": "/nonexistent/espeak-ng"}):
            self.assertTrue(voices.load(voice["id"])["missing"])

    # --- several clips ------------------------------------------------------

    def test_clips_keep_their_own_transcripts(self):
        voice = voices.create("Набор", [clip("one.wav", "Текст один."),
                                        clip("two.wav", "Текст два.", CLIP2)])
        self.assertEqual([c["ref_text"] for c in voice["clips"]],
                         ["Текст один.", "Текст два."])
        self.assertEqual(voice["active"], 0)
        self.assertTrue(all(c["duration"] > 0 for c in voice["clips"]))

    def test_the_active_clip_is_what_the_worker_gets(self):
        voice = voices.create("Набор", [clip("one.wav", "Текст один."),
                                        clip("two.wav", "Текст два.", CLIP2)])
        voices.update(voice["id"], active=1)
        audio, text = voices.reference_of(voices.load(voice["id"]))
        self.assertEqual(os.path.basename(audio), "two.wav")
        self.assertEqual(text, "Текст два.")

    def test_all_together_concatenates_clips_and_transcripts(self):
        from server.core import compose
        voice = voices.create("Набор", [clip("one.wav", "Текст один."),
                                        clip("two.wav", "Текст два.", CLIP2)])
        parts = sum(c["duration"] for c in voice["clips"])
        voices.update(voice["id"], active="all")

        audio, text = voices.reference_of(voices.load(voice["id"]))
        self.assertEqual(os.path.basename(audio), voices.JOINED_AUDIO)
        self.assertAlmostEqual(compose.probe_duration(audio), parts, delta=0.2)
        self.assertEqual(text, "Текст один. Текст два.")

    def test_the_join_is_cached_until_a_clip_changes(self):
        voice = voices.create("Набор", [clip("one.wav", "Текст один."),
                                        clip("two.wav", "Текст два.", CLIP2)])
        vid = voice["id"]
        voices.update(vid, active="all")
        first = voices.reference_of(voices.load(vid))
        stamp = paths.voice_audio(vid, voices.JOINED_STAMP)
        self.assertTrue(os.path.exists(stamp))
        mtime = os.path.getmtime(first[0])

        self.assertEqual(voices.reference_of(voices.load(vid))[0], first[0])
        self.assertEqual(os.path.getmtime(first[0]), mtime, "rebuilt when it did not need to")

        voices.update(vid, clip=0, ref_text="Переписанный текст.")
        self.assertFalse(os.path.exists(stamp), "retyping a clip must invalidate the join")
        audio, text = voices.reference_of(voices.load(vid))
        self.assertEqual(text, "Переписанный текст. Текст два.")

    def test_joining_leaves_no_working_files_behind(self):
        voice = voices.create("Набор", [clip("one.wav", "Текст один."),
                                        clip("two.wav", "Текст два.", CLIP2)])
        voices.update(voice["id"], active="all")
        voices.reference_of(voices.load(voice["id"]))
        left = sorted(f for f in os.listdir(paths.voice_dir(voice["id"]))
                      if f.startswith("_part") or f.endswith((".txt", ".tmp")))
        self.assertEqual(left, [])

    def test_adding_and_removing_clips(self):
        voice = voices.create("Набор", [clip("one.wav", "Текст один.")])
        vid = voice["id"]
        voice = voices.add_clips(vid, [clip("two.wav", "Текст два.", CLIP2)])
        self.assertEqual(len(voice["clips"]), 2)

        voice = voices.remove_clip(vid, 0)
        self.assertEqual([c["audio"] for c in voice["clips"]], ["two.wav"])
        self.assertFalse(os.path.exists(paths.voice_audio(vid, "one.wav")))

    def test_the_last_clip_cannot_be_removed(self):
        voice = voices.create("Одна", [clip("one.wav", "Текст один.")])
        with self.assertRaises(ValueError):
            voices.remove_clip(voice["id"], 0)

    def test_removing_the_active_clip_moves_the_choice(self):
        voice = voices.create("Набор", [clip("one.wav", "Текст один."),
                                        clip("two.wav", "Текст два.", CLIP2)])
        vid = voice["id"]
        voices.update(vid, active=1)
        voice = voices.remove_clip(vid, 1)
        self.assertEqual(voice["active"], 0)
        self.assertEqual(os.path.basename(voices.reference_of(voices.load(vid))[0]), "one.wav")

    def test_a_clip_whose_file_vanished_is_skipped_not_fatal(self):
        voice = voices.create("Набор", [clip("one.wav", "Текст один."),
                                        clip("two.wav", "Текст два.", CLIP2)])
        vid = voice["id"]
        os.remove(paths.voice_audio(vid, "one.wav"))
        audio, text = voices.reference_of(voices.load(vid))
        self.assertEqual(os.path.basename(audio), "two.wav")
        self.assertFalse(voices.load(vid)["missing"])

    def test_two_uploads_of_the_same_filename_do_not_overwrite(self):
        voice = voices.create("Набор", [clip("same.wav", "Первый."),
                                        clip("same.wav", "Второй.", CLIP2)])
        names = [c["audio"] for c in voice["clips"]]
        self.assertEqual(len(set(names)), 2, names)

    def test_a_voice_whose_only_file_vanished_is_reported_missing(self):
        voice = voices.create("Пропажа", [clip("gone.wav", "Текст.")])
        os.remove(voices.clip_path(voice["id"], voice["clips"][0]))
        reloaded = voices.load(voice["id"])
        self.assertTrue(reloaded["missing"])
        self.assertTrue(reloaded["clips"][0]["missing"])


class VoiceApiTest(ProjectTest):

    def setUp(self):
        super().setUp()
        shutil.rmtree(paths.VOICES_DIR, ignore_errors=True)
        paths.ensure_dirs()
        self.client = TestClient(app)

    def add(self, name="Вторая", texts=("Текст второй записи.",), sources=(CLIP,)):
        files = []
        for i, src in enumerate(sources):
            with open(src, "rb") as fh:
                files.append(("files", (f"clip{i}.wav", fh.read(), "audio/wav")))
        return self.client.post("/api/voices",
                                data={"name": name, "ref_texts": list(texts)},
                                files=files)

    def test_upload_lists_and_assign(self):
        created = self.add()
        self.assertEqual(created.status_code, 200)
        vid = created.json()["id"]
        self.assertIn(vid, [v["id"] for v in self.client.get("/api/voices").json()])

        project = projects.create("api", para("Первый абзац книги."))
        response = self.client.patch(f"/api/projects/{project['id']}", json={"voice": vid})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["voice"], vid)

    def test_assigning_a_voice_that_does_not_exist_is_rejected(self):
        project = projects.create("api", para("Первый абзац книги."))
        response = self.client.patch(f"/api/projects/{project['id']}",
                                     json={"voice": "nope"})
        self.assertEqual(response.status_code, 404)

    def test_the_built_in_voices_cannot_be_deleted(self):
        for vid in voices.BUILTINS:
            self.assertEqual(self.client.delete(f"/api/voices/{vid}").status_code, 400)
            self.assertIsNotNone(voices.load(vid))

    def test_engines_report_what_is_installed(self):
        body = self.client.get("/api/engines").json()
        self.assertEqual(body["espeak"]["available"], espeak.available())
        self.assertIn("available", body["qwen"])
        if espeak.available():
            codes = [lang["code"] for lang in body["espeak"]["languages"]]
            self.assertIn("ru", codes)
            self.assertTrue(body["espeak"]["variants"])

    def test_an_espeak_voice_is_created_retuned_and_assigned(self):
        created = self.client.post("/api/voices/espeak",
                                   json={"name": "Deep", "voice": "en-gb", "pitch": 20})
        self.assertEqual(created.status_code, 200)
        vid = created.json()["id"]
        self.assertEqual(created.json()["espeak"]["pitch"], 20)

        patched = self.client.patch(f"/api/voices/{vid}", json={"espeak": {"speed": 130}})
        self.assertEqual(patched.status_code, 200)
        self.assertEqual(patched.json()["espeak"]["speed"], 130)
        self.assertEqual(patched.json()["espeak"]["pitch"], 20)

        project = projects.create("api", para("A paragraph."))
        response = self.client.patch(f"/api/projects/{project['id']}", json={"voice": vid})
        self.assertEqual(response.json()["voice"], vid)

    @unittest.skipUnless(espeak.available(), "espeak-ng not installed")
    def test_an_espeak_voice_previews_and_rebuilds_after_retuning(self):
        vid = self.client.post("/api/voices/espeak", json={"voice": "ru"}).json()["id"]
        first = self.client.get(f"/api/voices/{vid}/audio")
        self.assertEqual(first.status_code, 200)
        self.assertTrue(first.content.startswith(b"RIFF"))

        self.client.patch(f"/api/voices/{vid}", json={"espeak": {"speed": 90}})
        slower = self.client.get(f"/api/voices/{vid}/audio")
        self.assertGreater(len(slower.content), len(first.content))

    def test_upload_without_a_transcript_is_rejected(self):
        self.assertEqual(self.add(texts=("   ",)).status_code, 400)

    def test_one_transcript_short_is_rejected(self):
        response = self.add(texts=("Только один текст.",), sources=(CLIP, CLIP2))
        self.assertEqual(response.status_code, 400)

    def test_an_espeak_voice_is_renamed_over_the_api(self):
        vid = self.client.post("/api/voices/espeak", json={"voice": "en-gb"}).json()["id"]
        renamed = self.client.patch(f"/api/voices/{vid}", json={"name": "Reader"}).json()
        self.assertEqual(renamed["name"], "Reader")
        reset = self.client.patch(f"/api/voices/{vid}", json={"name": ""}).json()
        self.assertFalse(reset["custom_name"])
        self.assertNotEqual(reset["name"], "Reader")

    def test_renaming_keeps_the_clip(self):
        vid = self.add().json()["id"]
        response = self.client.patch(f"/api/voices/{vid}", json={"name": "Переименована"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["name"], "Переименована")
        self.assertFalse(response.json()["missing"])

    def test_the_clip_is_served_for_preview(self):
        vid = self.add().json()["id"]
        response = self.client.get(f"/api/voices/{vid}/audio")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content)

    def test_several_clips_upload_in_one_request(self):
        response = self.add(texts=("Текст один.", "Текст два."), sources=(CLIP, CLIP2))
        self.assertEqual(response.status_code, 200)
        voice = response.json()
        self.assertEqual(len(voice["clips"]), 2)
        self.assertEqual([c["ref_text"] for c in voice["clips"]],
                         ["Текст один.", "Текст два."])

    def test_each_clip_and_the_join_can_be_previewed(self):
        vid = self.add(texts=("Текст один.", "Текст два."), sources=(CLIP, CLIP2)).json()["id"]
        self.assertEqual(self.client.get(f"/api/voices/{vid}/audio?clip=1").status_code, 200)
        self.assertEqual(self.client.get(f"/api/voices/{vid}/audio?clip=-1").status_code, 200)
        self.assertEqual(self.client.get(f"/api/voices/{vid}/audio?clip=9").status_code, 404)

    def test_clips_can_be_added_to_an_existing_voice(self):
        vid = self.add().json()["id"]
        with open(CLIP2, "rb") as fh:
            response = self.client.post(
                f"/api/voices/{vid}/clips",
                data={"ref_texts": ["Добавленный текст."]},
                files=[("files", ("extra.wav", fh.read(), "audio/wav"))])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["clips"]), 2)

    def test_choosing_a_clip_that_does_not_exist_is_rejected(self):
        vid = self.add().json()["id"]
        self.assertEqual(self.client.patch(f"/api/voices/{vid}",
                                           json={"active": 5}).status_code, 400)


if __name__ == "__main__":
    unittest.main()
