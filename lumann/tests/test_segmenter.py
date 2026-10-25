"""The segmenter: where paragraphs start, how long ones split, exact offsets."""
import unittest

from base import ProjectTest, para
from server.core import projects
from server.core.segmenter import build_segments, read_paragraphs_text, split_paragraph

WRAPPED = (
    "    Первая строка абзаца, которая была свёрнута по ширине\n"
    "страницы и продолжается на следующей строке без отступа.\n"
    "\n"
    "    Второй абзац начинается с отступа.\n"
    "    Третий абзац тоже, без пустой строки между ними.\n"
)


class ParagraphTest(unittest.TestCase):

    def test_continuation_lines_join_the_paragraph(self):
        paras = read_paragraphs_text(WRAPPED)
        self.assertEqual(len(paras), 3)
        self.assertEqual(paras[0][0], 1)
        self.assertIn("свёрнута по ширине страницы", paras[0][1])

    def test_indented_line_starts_a_new_paragraph_without_a_blank_line(self):
        paras = read_paragraphs_text(WRAPPED)
        self.assertEqual(paras[1][1], "Второй абзац начинается с отступа.")
        self.assertEqual(paras[2][1], "Третий абзац тоже, без пустой строки между ними.")

    def test_a_blank_line_ends_a_paragraph_even_without_indents(self):
        paras = read_paragraphs_text("First paragraph.\n\nSecond paragraph.\n")
        self.assertEqual([p[1] for p in paras], ["First paragraph.", "Second paragraph."])
        self.assertEqual([p[0] for p in paras], [1, 3])


class LanguageTest(unittest.TestCase):
    """The Russian-only steps must not touch other languages."""

    def test_an_english_book_keeps_its_digits_and_semicolons(self):
        _formatted, segs = build_segments(para("In 1984 he bought 3 apples; it was cheap."))
        self.assertEqual(segs[0]["text"], "In 1984 he bought 3 apples; it was cheap.")

    def test_a_russian_book_gets_number_words_and_yo(self):
        _formatted, segs = build_segments(para("Он купил 3 яблока и еще пришел."))
        self.assertEqual(segs[0]["text"], "Он купил три яблока и ещё пришёл.")

    def test_a_digits_only_paragraph_follows_the_book(self):
        _formatted, segs = build_segments(para("Глава первая, в которой всё начинается.", "1984."))
        self.assertEqual(segs[1]["text"], "Тысяча девятьсот восемьдесят четыре.")


class SplitTest(unittest.TestCase):

    def test_a_short_paragraph_stays_whole(self):
        self.assertEqual(split_paragraph("One. Two.", 350, 600), ["One. Two."])

    def test_a_long_paragraph_breaks_on_sentence_ends(self):
        text = " ".join(f"Sentence number {i} is here." for i in range(40))
        pieces = split_paragraph(text, 200, 300)
        self.assertGreater(len(pieces), 1)
        self.assertTrue(all(len(p) <= 300 for p in pieces))
        self.assertTrue(all(p.endswith(".") for p in pieces))
        self.assertEqual(" ".join(pieces), text)


class OffsetTest(ProjectTest):

    def test_offsets_index_the_formatted_text_exactly(self):
        formatted, segs = build_segments(para(
            "Короткий первый абзац.",
            "Второй абзац, чуть длиннее, но всё ещё один кусок.",
            "Третий."))
        self.assertEqual(len(segs), 3)
        for seg in segs:
            self.assertEqual(formatted[seg["char_start"]:seg["char_end"]], seg["text"])

    def test_a_long_paragraph_splits_and_stays_contiguous(self):
        sentence = "Это довольно длинное предложение, которое повторяется много раз. "
        formatted, segs = build_segments(para(sentence * 20), target=350, hard_max=600)
        self.assertGreater(len(segs), 1)
        for seg in segs:
            self.assertEqual(formatted[seg["char_start"]:seg["char_end"]], seg["text"])
            self.assertLessEqual(len(seg["text"]), 600)
        self.assertTrue(all(s["para"] == 0 for s in segs))

    def test_offsets_survive_a_round_trip_through_a_project(self):
        project = self.make(para("Первый абзац.", "Второй абзац, немного длиннее."))
        from server.core import paths
        formatted = open(paths.formatted_txt(project["id"]), encoding="utf-8").read()
        for seg in projects.segments(project):
            self.assertEqual(formatted[seg["char_start"]:seg["char_end"]], seg["text"])

    def test_numbers_are_expanded_by_adapt_text(self):
        _formatted, segs = build_segments(para("В комнате было 25 человек."))
        self.assertIn("двадцать пять", segs[0]["text"])


if __name__ == "__main__":
    unittest.main()
