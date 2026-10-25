"""ё-restoration: what the dictionary may decide, and what it may not.

The rule the whole thing rests on: a word is replaced only if its е-spelling is
not itself a word. Everything else — все/всё, лет/лёт — is a reading decision
and comes back as a flag instead.
"""
import os
import sys
import unittest

from base import ProjectTest, para

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from adapt_text import adapt, flag_issues, yo_ambiguous       # noqa: E402


class YoTest(unittest.TestCase):

    def adapt(self, text, **kw):
        return adapt(text, **kw)[0]

    def test_unambiguous_words_are_restored(self):
        out = self.adapt("Ее еще не было, он пришел и повел счет.")
        self.assertIn("Её ещё", out)
        self.assertIn("пришёл", out)
        self.assertIn("повёл", out)
        self.assertIn("счёт", out)

    def test_homographs_are_left_alone(self):
        out = self.adapt("Все лет пятнадцать смотрели в небо.")
        for word in ("Все", "лет", "небо"):
            self.assertIn(word, out)
        self.assertNotIn("ё", out)

    def test_homographs_come_back_as_a_flag(self):
        flags = " ".join(flag_issues("Все смотрели в небо."))
        self.assertIn("homograph", flags)
        self.assertIn("небо", flags)

    def test_restored_words_are_not_flagged_afterwards(self):
        # "ее"/"еще" used to sit in the hand-written flag list; the dictionary
        # settles them, so they must not come back as work for a human.
        flags = " ".join(flag_issues(self.adapt("Ее еще не было.")))
        self.assertNotIn("её", flags.lower())
        self.assertNotIn("ещё", flags.lower())

    def test_case_is_preserved(self):
        self.assertIn("Ёжик", self.adapt("Ежик шел."))
        self.assertIn("ЁЖИК", self.adapt("ЕЖИК шел."))

    def test_capitalised_dictionary_entries_do_not_match_lowercase_words(self):
        # "Аксёнов" the surname must not reach into a lowercase word.
        self.assertEqual(yo_ambiguous("аксенов"), [])

    def test_text_already_written_with_yo_is_untouched(self):
        source = "Её ещё не было, он пришёл и повёл счёт."
        self.assertEqual(self.adapt(source), source)

    def test_yo_false_leaves_the_text_alone(self):
        out = self.adapt("Ее еще не было.", yo=False)
        self.assertNotIn("ё", out)
        self.assertIn("Ее еще", out)


P_YO = "Ее еще не было, и он пришел один."
P_PLAIN = "Второй абзац без единой спорной буквы в тексте."


class YoReindexTest(ProjectTest):
    """Switching ё on mid-book is a re-record, never a re-import.

    28% of the paragraphs in chapter 1 change spelling the moment this is
    turned on. They are the same sentences, so ids, tags and take history have
    to survive; they do read differently, so the takes have to go stale.
    """

    def test_turning_yo_on_stales_takes_without_losing_them(self):
        from server.core import projects, reindex

        source = para(P_YO, P_PLAIN)
        project = projects.create("yo-off", source, fmt={"yo": 0})
        segs = projects.segments(project)
        self.assertIn("Ее еще", segs[0]["text"])
        for seg in segs:
            self.give_take(project, seg)
        ids = [s["id"] for s in segs]

        preview, staged = reindex.plan_reindex(project, source, fmt={"yo": 1})

        self.assertEqual(preview["counts"]["new"], 0)
        self.assertEqual(preview["counts"]["deleted"], 0)
        self.assertEqual(preview["counts"]["changed"], 1)
        self.assertEqual([i["id"] for i in staged["timeline"]], ids)

        by_id = {i["id"]: i for i in staged["timeline"]}
        touched = by_id[ids[0]]
        self.assertIn("Её ещё", touched["text"])
        self.assertEqual(touched["status"], "stale")
        self.assertEqual(len(touched["takes"]), 1)       # history kept
        self.assertIsNotNone(touched["active_take"])     # old audio still playable
        self.assertEqual(by_id[ids[1]]["status"], "done")

    def test_the_pairing_survives_a_yo_edit_next_to_an_insert(self):
        """difflib must still see the ё-only paragraphs as the backbone.

        If norm did not fold ё, these would land in a `replace` run together
        with the real edit and pair positionally — which is exactly how a
        re-index quietly moves audio onto the wrong sentence.
        """
        from server.core import projects, reindex

        source = para(P_YO, P_PLAIN)
        project = projects.create("yo-insert", source, fmt={"yo": 0})
        segs = projects.segments(project)
        for seg in segs:
            self.give_take(project, seg)
        ids = [s["id"] for s in segs]

        new = para(P_YO, "Совершенно новый абзац между ними.", P_PLAIN)
        _preview, staged = reindex.plan_reindex(project, new, fmt={"yo": 1})

        order = [i["id"] for i in staged["timeline"]]
        self.assertEqual([order[0], order[2]], ids)      # identity, not position
        self.assertEqual(staged["deleted"], [])


if __name__ == "__main__":
    unittest.main()
