"""Source text -> ordered segments, with exact offsets into formatted.txt.

Paragraphs are kept whole when short and broken on sentence ends when long.
Offsets matter: the UI highlights text by character range, so `formatted.txt`
has to be reconstructible from the segments and vice versa.
"""
import os
import re
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from adapt_text import adapt, flag_issues, is_russian      # noqa: E402

# Separator between segments of the same paragraph, and between paragraphs.
# formatted.txt is assembled from these, so offsets are exact by construction.
INTRA = " "
INTER = "\n\n"

DEFAULT_FORMAT_OPTIONS = {
    "max_words": 20,
    "target": 350,
    "hard_max": 600,
    "skip_short": 3,
    "yo": 1,                               # restore ё; 0 leaves е as written
}


SENT_SPLIT = re.compile(r"(?<=[.!?…])\s+")


def split_paragraph(text, target, hard_max):
    """Keep paragraphs whole when short; otherwise break on sentence ends."""
    if len(text) <= hard_max:
        return [text]
    chunks, cur = [], ""
    for sent in SENT_SPLIT.split(text):
        if cur and len(cur) + len(sent) + 1 > target:
            chunks.append(cur.strip())
            cur = sent
        else:
            cur = f"{cur} {sent}".strip()
    if cur.strip():
        chunks.append(cur.strip())
    # a single sentence longer than hard_max: break on commas as a last resort
    out = []
    for c in chunks:
        if len(c) <= hard_max:
            out.append(c)
            continue
        piece = ""
        for part in c.split(", "):
            if piece and len(piece) + len(part) + 2 > hard_max:
                out.append(piece.strip().rstrip(",") + ",")
                piece = part
            else:
                piece = f"{piece}, {part}".strip(", ") if piece else part
        if piece:
            out.append(piece)
    return out


def read_paragraphs_text(text):
    """-> [(line_number, text)] with hard wrapping undone.

    Books are often hard-wrapped at ~78 columns, so a line is not a
    paragraph: a paragraph starts on an indented line (or after a blank one)
    and lines flush to column 0 continue it.
    """
    lines = text.split("\n")
    paras, cur, start = [], [], None
    for idx, raw in enumerate(lines, start=1):
        if not raw.strip():
            if cur:
                paras.append((start, " ".join(cur)))
                cur, start = [], None
            continue
        indented = raw[:1].isspace()
        if indented and cur:
            paras.append((start, " ".join(cur)))
            cur, start = [], None
        if start is None:
            start = idx
        cur.append(raw.strip())
    if cur:
        paras.append((start, " ".join(cur)))
    return paras


def build_segments(source_text, max_words=20, target=350, hard_max=600, skip_short=3,
                   yo=1, preformatted=False):
    """-> (formatted_text, [{line, text, char_start, char_end, para}])

    char_start/char_end index into the returned formatted_text.

    `preformatted` skips adapt(): the input is already the output of a previous
    pass, so normalising it again would be a second opinion on text the user has
    since edited by hand. Chunking still applies.
    """
    formatted_parts = []
    segments = []
    cursor = 0
    russian = is_russian(source_text[:20000])

    for para_index, (line_no, para) in enumerate(read_paragraphs_text(source_text)):
        adapted = para if preformatted else adapt(para, max_words=max_words, yo=bool(yo),
                                                   russian=russian)[0]
        if len(adapted.strip()) < skip_short:
            continue
        pieces = [p.strip() for p in split_paragraph(adapted, target, hard_max) if p.strip()]
        if not pieces:
            continue
        if segments:                       # paragraph break before this one
            formatted_parts.append(INTER)
            cursor += len(INTER)
        for i, piece in enumerate(pieces):
            if i:
                formatted_parts.append(INTRA)
                cursor += len(INTRA)
            segments.append({
                "line": line_no,
                "text": piece,
                "char_start": cursor,
                "char_end": cursor + len(piece),
                "para": para_index,
            })
            formatted_parts.append(piece)
            cursor += len(piece)

    return "".join(formatted_parts), segments


def build_segments_from_file(path, **opts):
    with open(path, encoding="utf-8") as fh:
        return build_segments(fh.read(), **opts)


def format_options(raw=None):
    """Fill in defaults and drop anything unrecognised."""
    opts = dict(DEFAULT_FORMAT_OPTIONS)
    for key in DEFAULT_FORMAT_OPTIONS:
        if raw and raw.get(key) is not None:
            opts[key] = int(raw[key])
    return opts
