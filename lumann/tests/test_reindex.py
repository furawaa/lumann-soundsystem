"""Re-indexing must not lose work. Every case here is a way it could.

Synthetic edits against a five-paragraph project: insert, delete, reword, swap,
whitespace-only. What is asserted throughout is that ids, tags and takes travel
with the *text*, never with the position.
"""
import os
import unittest

from base import ProjectTest, para
from server.core import paths, projects, reindex

P1 = "Первый абзац про Эдди Виллерса и длинную тень небоскрёба."
P2 = "Второй абзац, в котором бродяга задаёт свой вопрос."
P3 = "Третий абзац описывает вечерний город и жёлтое небо."
P4 = "Четвёртый абзац о том, как закрывались магазины на улице."
P5 = "Пятый абзац завершает сцену и оставляет вопрос без ответа."

SOURCE = para(P1, P2, P3, P4, P5)


class ReindexTest(ProjectTest):

    def setUp(self):
        super().setUp()
        self.project = self.make(SOURCE, "reindex")
        self.segs = projects.segments(self.project)
        self.assertEqual(len(self.segs), 5)
        for seg in self.segs:
            self.give_take(self.project, seg)
        self.ids = [s["id"] for s in self.segs]

    def plan(self, new_source):
        return reindex.plan_reindex(self.project, new_source)

    def kinds(self, preview):
        return [e["kind"] for e in preview["segments"]]

    # --- the five synthetic edits ------------------------------------------

    def test_unchanged_source_changes_nothing(self):
        preview, staged = self.plan(SOURCE)
        self.assertEqual(preview["counts"]["unchanged"], 5)
        self.assertEqual(preview["counts"]["changed"], 0)
        self.assertEqual(preview["counts"]["moved"], 0)
        self.assertEqual([i["id"] for i in staged["timeline"]], self.ids)

    def test_whitespace_only_edit_is_not_a_change(self):
        # Re-wrapping the file must not cost 5 re-recordings. Wrap on a word
        # boundary, as a real editor would.
        def rewrap(p):
            cut = p.index(" ", 20)
            return "    " + p[:cut] + "\n" + p[cut + 1:]

        rewrapped = "\n\n".join(rewrap(p) for p in (P1, P2, P3, P4, P5)) + "\n"
        preview, staged = self.plan(rewrapped)
        self.assertEqual(preview["counts"]["changed"], 0)
        self.assertEqual(preview["counts"]["deleted"], 0)
        self.assertEqual([i["id"] for i in staged["timeline"]], self.ids)

    def test_insert_paragraph_in_the_middle(self):
        new = para(P1, P2, "Совершенно новый абзац посередине текста.", P3, P4, P5)
        preview, staged = self.plan(new)
        self.assertEqual(preview["counts"]["new"], 1)
        self.assertEqual(preview["counts"]["changed"], 0)
        self.assertEqual(preview["counts"]["deleted"], 0)
        self.assertEqual(preview["counts"]["moved"], 3)      # P3, P4, P5 shifted

        new_ids = [i["id"] for i in staged["timeline"]]
        self.assertEqual(new_ids[:2], self.ids[:2])
        self.assertEqual(new_ids[3:], self.ids[2:])          # audio survives the shift
        moved = [i for i in staged["timeline"] if i.get("moved")]
        self.assertEqual(len(moved), 3)
        for item in moved:
            self.assertEqual(item["status"], "done")         # moved audio is still valid

    def test_delete_paragraph_keeps_the_others(self):
        new = para(P1, P2, P4, P5)
        preview, staged = self.plan(new)
        self.assertEqual(preview["counts"]["deleted"], 1)
        self.assertEqual(preview["counts"]["changed"], 0)
        self.assertEqual(staged["deleted"], [self.ids[2]])
        self.assertEqual([i["id"] for i in staged["timeline"]],
                         [self.ids[0], self.ids[1], self.ids[3], self.ids[4]])

    def test_reword_one_paragraph_stales_exactly_one(self):
        new = para(P1, P2, "Третий абзац теперь описывает совсем другое: серый дождь.", P4, P5)
        preview, staged = self.plan(new)
        self.assertEqual(preview["counts"]["changed"], 1)
        self.assertEqual(preview["counts"]["new"], 0)
        self.assertEqual(preview["counts"]["deleted"], 0)

        by_id = {i["id"]: i for i in staged["timeline"]}
        target = by_id[self.ids[2]]
        self.assertEqual(target["status"], "stale")
        self.assertEqual(len(target["takes"]), 1)            # the old take survives
        self.assertIsNotNone(target["active_take"])          # and stays playable
        for other in (0, 1, 3, 4):
            self.assertEqual(by_id[self.ids[other]]["status"], "done")

    def test_swap_two_paragraphs(self):
        new = para(P1, P3, P2, P4, P5)
        preview, staged = self.plan(new)
        self.assertEqual(preview["counts"]["changed"], 0)
        self.assertEqual(preview["counts"]["new"], 0)
        self.assertEqual(preview["counts"]["deleted"], 0)
        order = [i["id"] for i in staged["timeline"]]
        self.assertEqual(order, [self.ids[0], self.ids[2], self.ids[1], self.ids[3], self.ids[4]])
        for item in staged["timeline"]:
            self.assertEqual(item["status"], "done")         # nothing needs re-recording

    # --- tags, takes and overrides -----------------------------------------

    def test_tags_and_takes_survive_an_edit_elsewhere(self):
        favourite = self.segs[4]
        favourite["favorite"] = True
        self.give_take(self.project, favourite)              # now has two takes
        projects.save(self.project)

        new = para(P1, "Второй абзац переписан полностью, другими словами.", P3, P4, P5)
        _preview, staged = self.plan(new)

        kept = {i["id"]: i for i in staged["timeline"]}[favourite["id"]]
        self.assertTrue(kept["favorite"])
        self.assertEqual(len(kept["takes"]), 2)
        self.assertEqual(kept["active_take"], favourite["active_take"])
        self.assertEqual(kept["status"], "done")

    def test_take_history_survives_a_reword(self):
        seg = self.segs[1]
        self.give_take(self.project, seg)
        self.give_take(self.project, seg)                    # three takes total
        new = para(P1, "Второй абзац переписан полностью, другими словами.", P3, P4, P5)
        _preview, staged = self.plan(new)

        kept = {i["id"]: i for i in staged["timeline"]}[seg["id"]]
        self.assertEqual(len(kept["takes"]), 3)
        self.assertEqual([t["n"] for t in kept["takes"]], [1, 2, 3])
        self.assertEqual(kept["status"], "stale")
        for take in kept["takes"]:                           # all three now outdated
            self.assertTrue(projects.take_is_outdated(kept, take))

    def test_override_survives_and_is_flagged(self):
        seg = self.segs[3]
        seg["text_override"] = "Ручная правка этого абзаца."
        projects.refresh_hash(seg)
        self.give_take(self.project, seg)
        projects.save(self.project)

        new = para(P1, P2, P3, "Четвёртый абзац в источнике переписан заново.", P5)
        preview, staged = self.plan(new)

        kept = {i["id"]: i for i in staged["timeline"]}[seg["id"]]
        self.assertEqual(kept["text_override"], "Ручная правка этого абзаца.")
        self.assertEqual(kept["status"], "done")             # override wins, audio matches
        self.assertEqual(preview["counts"]["override_conflict"], 1)

    # --- inserts ------------------------------------------------------------

    def _add_insert(self, after_id, name="door.wav"):
        item = {"kind": "insert", "id": projects.new_id(), "insert_type": "sample",
                "sample": name, "seconds": None, "duration": 1.5}
        idx, _ = projects.find_item(self.project, after_id)
        self.project["timeline"].insert(idx + 1, item)
        projects.save(self.project)
        return item

    def test_insert_follows_its_segment(self):
        item = self._add_insert(self.ids[3])
        new = para(P1, "Новый абзац в начале.", P2, P3, P4, P5)
        _preview, staged = self.plan(new)
        order = [i["id"] for i in staged["timeline"]]
        self.assertEqual(order[order.index(self.ids[3]) + 1], item["id"])

    def test_insert_reattaches_when_its_segment_is_deleted(self):
        item = self._add_insert(self.ids[2])
        new = para(P1, P2, P4, P5)
        preview, staged = self.plan(new)

        note = next(n for n in preview["inserts"] if n["id"] == item["id"])
        self.assertTrue(note["review"])
        self.assertEqual(note["reattached_to"], self.ids[1])
        order = [i["id"] for i in staged["timeline"]]
        self.assertEqual(order[order.index(self.ids[1]) + 1], item["id"])

    def test_insert_at_the_very_start_stays_at_the_start(self):
        item = {"kind": "insert", "id": projects.new_id(), "insert_type": "silence",
                "seconds": 2.0, "sample": None, "duration": 2.0}
        self.project["timeline"].insert(0, item)
        projects.save(self.project)
        _preview, staged = self.plan(para(P1, P2, P3, P4, P5))
        self.assertEqual(staged["timeline"][0]["id"], item["id"])

    def test_inserts_are_never_marked_changed(self):
        self._add_insert(self.ids[0])
        new = para("Совсем другой первый абзац, переписанный целиком.", P2, P3, P4, P5)
        preview, _staged = self.plan(new)
        self.assertTrue(all(e["kind"] != "insert" for e in preview["segments"]))
        self.assertEqual(len(preview["inserts"]), 1)

    # --- applying -----------------------------------------------------------

    def test_apply_moves_deleted_audio_to_trash(self):
        gone = self.ids[2]
        audio = paths.segment_dir(self.project["id"], gone)
        self.assertTrue(os.path.isdir(audio))

        _preview, staged = self.plan(para(P1, P2, P4, P5))
        reindex.apply_reindex(self.project, staged)

        self.assertFalse(os.path.isdir(audio))
        self.assertTrue(os.path.isdir(os.path.join(paths.trash_dir(self.project["id"]), gone)))

        reloaded = projects.load(self.project["id"])
        self.assertEqual(len(projects.segments(reloaded)), 4)
        self.assertNotIn(gone, [s["id"] for s in projects.segments(reloaded)])

    def test_apply_rewrites_offsets_to_match_formatted_text(self):
        new = para(P1, "Совершенно новый абзац.", P2, P3, P4, P5)
        _preview, staged = self.plan(new)
        reindex.apply_reindex(self.project, staged)

        formatted = open(paths.formatted_txt(self.project["id"]), encoding="utf-8").read()
        for seg in projects.segments(projects.load(self.project["id"])):
            self.assertEqual(formatted[seg["char_start"]:seg["char_end"]], seg["text"])

    # --- editing the formatted text ----------------------------------------

    def test_per_segment_edit_lands_in_formatted_txt(self):
        """formatted.txt is what gets spoken; an override has to show up in it."""
        seg = self.segs[2]
        seg["text_override"] = "Полностью переписанный третий абзац."
        projects.refresh_hash(seg)
        projects.rebuild_formatted(self.project)
        projects.save(self.project)

        formatted = open(paths.formatted_txt(self.project["id"]), encoding="utf-8").read()
        self.assertIn("Полностью переписанный третий абзац.", formatted)
        self.assertNotIn(P3, formatted)
        for s in projects.segments(projects.load(self.project["id"])):
            self.assertEqual(formatted[s["char_start"]:s["char_end"]],
                             projects.effective_text(s),
                             "offsets must follow the rebuilt text")

    def test_editing_formatted_text_leaves_the_original_alone(self):
        before = open(paths.source_txt(self.project["id"]), encoding="utf-8").read()
        edited = open(paths.formatted_txt(self.project["id"]), encoding="utf-8").read()
        edited = edited.replace(P2, "Второй абзац теперь звучит иначе.")

        _preview, staged = reindex.plan_reindex(self.project, edited, preformatted=True)
        reindex.apply_reindex(self.project, staged)

        after = open(paths.source_txt(self.project["id"]), encoding="utf-8").read()
        self.assertEqual(after, before, "the original is the record of what was imported")
        formatted = open(paths.formatted_txt(self.project["id"]), encoding="utf-8").read()
        self.assertIn("Второй абзац теперь звучит иначе.", formatted)

    def test_formatted_edit_changes_exactly_one_segment(self):
        edited = open(paths.formatted_txt(self.project["id"]), encoding="utf-8").read()
        edited = edited.replace(P4, "Четвёртый абзац переписан целиком, другими словами.")
        preview, staged = reindex.plan_reindex(self.project, edited, preformatted=True)

        self.assertEqual(preview["counts"]["changed"], 1)
        self.assertEqual(preview["counts"]["new"], 0)
        self.assertEqual(preview["counts"]["deleted"], 0)
        by_id = {i["id"]: i for i in staged["timeline"]}
        self.assertEqual(by_id[self.ids[3]]["status"], "stale")
        self.assertEqual(len(by_id[self.ids[3]]["takes"]), 1)

    def test_formatted_edit_folds_an_override_in_and_clears_it(self):
        """The edited text already contains the override, so keeping it would
        make the override win over the very edit that produced it."""
        seg = self.segs[1]
        seg["text_override"] = "Ручная правка второго абзаца."
        projects.refresh_hash(seg)
        projects.rebuild_formatted(self.project)
        projects.save(self.project)

        edited = open(paths.formatted_txt(self.project["id"]), encoding="utf-8").read()
        edited = edited.replace("Ручная правка второго абзаца.",
                                "Правка, изменённая ещё раз в обработанном тексте.")
        _preview, staged = reindex.plan_reindex(self.project, edited, preformatted=True)

        kept = {i["id"]: i for i in staged["timeline"]}[seg["id"]]
        self.assertIsNone(kept["text_override"])
        self.assertEqual(kept["text"], "Правка, изменённая ещё раз в обработанном тексте.")

    def test_preformatted_does_not_reformat_the_text_again(self):
        edited = open(paths.formatted_txt(self.project["id"]), encoding="utf-8").read()
        edited = edited.replace(P1, "В комнате было 25 человек; это факт.")

        _preview, staged = reindex.plan_reindex(self.project, edited, preformatted=True)
        text = staged["timeline"][0]["text"]
        self.assertIn("25", text, "adapt() must not run over already-formatted text")
        self.assertIn(";", text)

    def test_plan_writes_nothing(self):
        before = open(paths.project_json(self.project["id"]), encoding="utf-8").read()
        self.plan(para(P1))
        after = open(paths.project_json(self.project["id"]), encoding="utf-8").read()
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
