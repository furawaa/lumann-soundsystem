#!/usr/bin/env python3
"""EPUB -> TXT. One paragraph per line, no line breaks mid-sentence.

    python epub2txt.py book.epub                 # -> book.txt
    python epub2txt.py book.epub -o out/book.txt
    python epub2txt.py book.epub --split out/    # one file per chapter
    python epub2txt.py book.epub --list          # list chapters and exit

Standard library only, no dependencies.
"""

import argparse
import html
import posixpath
import re
import sys
import unicodedata
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree as ET

# Block tags: each one closes the current paragraph.
BLOCK_TAGS = {
    "p", "div", "section", "article", "blockquote", "pre",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "li", "dt", "dd", "td", "tr", "table", "ul", "ol", "dl",
    "figure", "figcaption", "hr", "header", "footer", "aside", "nav",
}
SKIP_TAGS = {"script", "style", "head", "title"}

# Invisible and typographic characters that trip up TTS.
INVISIBLE = dict.fromkeys(map(ord, "­​‌‍﻿⁠"), None)
TRANSLATE = {
    ord(" "): " ",   # NBSP
    ord("‑"): "-",   # non-breaking hyphen
    ord("–"): "—",  # en dash -> em dash
}


def clean(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = text.translate(INVISIBLE).translate(TRANSLATE)
    text = re.sub(r"[ \t\r\n\f\v]+", " ", text)
    return text.strip()


class BlockExtractor(HTMLParser):
    """Collects text block by block: inside a block every line break becomes a space."""

    def __init__(self, keep_br: bool = False):
        super().__init__(convert_charrefs=True)
        self.keep_br = keep_br
        self.blocks: list[str] = []
        self._buf: list[str] = []
        self._skip = 0

    def _flush(self) -> None:
        text = clean("".join(self._buf))
        self._buf.clear()
        if text:
            self.blocks.append(text)

    def handle_starttag(self, tag, attrs):
        if tag in SKIP_TAGS:
            self._skip += 1
        elif tag == "br":
            self._buf.append("\n" if self.keep_br else " ")
        elif tag in BLOCK_TAGS:
            self._flush()

    def handle_startendtag(self, tag, attrs):
        if tag == "br":
            self._buf.append("\n" if self.keep_br else " ")

    def handle_endtag(self, tag):
        if tag in SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
        elif tag in BLOCK_TAGS:
            self._flush()

    def handle_data(self, data):
        if not self._skip:
            self._buf.append(data)

    def close(self):
        super().close()
        self._flush()


def _ns(tag: str) -> str:
    return tag.split("}")[-1]


def spine_documents(zf: zipfile.ZipFile) -> list[str]:
    """XHTML file paths in reading order (the OPF spine)."""
    container = ET.fromstring(zf.read("META-INF/container.xml"))
    opf_path = next(
        el.attrib["full-path"]
        for el in container.iter()
        if _ns(el.tag) == "rootfile"
    )
    opf = ET.fromstring(zf.read(opf_path))
    base = posixpath.dirname(opf_path)

    manifest: dict[str, str] = {}
    for el in opf.iter():
        if _ns(el.tag) == "item":
            href = html.unescape(el.attrib["href"]).split("#")[0]
            manifest[el.attrib["id"]] = posixpath.normpath(
                posixpath.join(base, href) if base else href
            )

    names = set(zf.namelist())
    docs = []
    for el in opf.iter():
        if _ns(el.tag) == "itemref":
            path = manifest.get(el.attrib.get("idref", ""))
            if path and path in names and path not in docs:
                docs.append(path)

    if not docs:  # broken OPF: take everything that looks like text
        docs = sorted(n for n in names if n.lower().endswith((".xhtml", ".html", ".htm")))
    return docs


def extract(zf: zipfile.ZipFile, path: str, keep_br: bool) -> list[str]:
    raw = zf.read(path)
    for encoding in ("utf-8", "utf-16", "cp1251", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", "replace")

    parser = BlockExtractor(keep_br=keep_br)
    parser.feed(text)
    parser.close()
    return parser.blocks


def chapter_title(blocks: list[str], fallback: str) -> str:
    for block in blocks[:3]:
        if 2 <= len(block) <= 80:
            return block
    return fallback


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("epub", type=Path)
    ap.add_argument("-o", "--output", type=Path, help="output file (default: next to the epub)")
    ap.add_argument("--split", type=Path, metavar="DIR", help="one file per chapter in DIR")
    ap.add_argument("--list", action="store_true", help="list chapters and exit")
    ap.add_argument("--keep-br", action="store_true", help="<br> -> line break (for poetry)")
    ap.add_argument("--min-chars", type=int, default=0,
                    help="skip chapters shorter than N characters (covers, copyright pages)")
    ap.add_argument("--separator", default="", help="separator line between chapters")
    args = ap.parse_args()

    if not args.epub.is_file():
        print(f"no such file: {args.epub}", file=sys.stderr)
        return 1

    with zipfile.ZipFile(args.epub) as zf:
        docs = spine_documents(zf)
        chapters = [(path, extract(zf, path, args.keep_br)) for path in docs]

    chapters = [(p, b) for p, b in chapters
                if b and sum(map(len, b)) >= args.min_chars]

    if args.list:
        for i, (path, blocks) in enumerate(chapters, 1):
            chars = sum(map(len, blocks))
            print(f"{i:3}. {chapter_title(blocks, path)[:60]:<62} {chars:>7} chars  {path}")
        return 0

    if args.split:
        args.split.mkdir(parents=True, exist_ok=True)
        for i, (path, blocks) in enumerate(chapters, 1):
            title = re.sub(r"[^\w\s-]", "", chapter_title(blocks, f"chapter_{i}"))[:50].strip()
            slug = re.sub(r"\s+", "_", title) or "chapter"
            out = args.split / f"{i:03d}_{slug}.txt"
            out.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
        print(f"{len(chapters)} chapters -> {args.split}/")
        return 0

    out = args.output or args.epub.with_suffix(".txt")
    out.parent.mkdir(parents=True, exist_ok=True)
    joiner = f"\n\n{args.separator}\n\n" if args.separator else "\n\n"
    text = joiner.join("\n\n".join(blocks) for _, blocks in chapters) + "\n"
    out.write_text(text, encoding="utf-8")

    paragraphs = text.count("\n\n") + 1
    print(f"{out}  —  {len(chapters)} chapters, {paragraphs} paragraphs, {len(text)} characters")
    return 0


if __name__ == "__main__":
    sys.exit(main())
