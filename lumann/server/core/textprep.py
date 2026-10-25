"""Thin wrapper over adapt_text.py, plus the two text identities the app needs.

Two different notions of "same text" live here and must not be confused:

  text_hash — is this audio still valid for this text? Whitespace-insensitive
              only. A comma changes it, because a comma changes the reading.
  norm      — is this the same paragraph, moved? Used by the re-indexer for
              diffing, so it also ignores case, punctuation and ё: a retyped
              dash should read as "moved", not as "re-record 400 segments".

Why norm folds ё but text_hash does not: turning on ё-restoration rewrites a
quarter of the paragraphs in a book. Those are the same sentences, so the
re-indexer must pair them by identity and keep their take history; but they do
read differently, so the takes still have to go stale. Folding here and not in
text_hash is exactly that split.
"""
import hashlib
import os
import re
import sys
import unicodedata

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from adapt_text import adapt, flag_issues          # noqa: E402

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)


def canonical(text: str) -> str:
    """Whitespace-collapsed NFC form — the thing we hash."""
    return _WS.sub(" ", unicodedata.normalize("NFC", text or "")).strip()


def text_hash(text: str) -> str:
    return "sha1:" + hashlib.sha1(canonical(text).encode("utf-8")).hexdigest()


def norm(text: str) -> str:
    """Comparison form for diffing: no case, no punctuation, no ё, no extra space."""
    folded = canonical(text).casefold().replace("ё", "е")
    return _WS.sub(" ", _PUNCT.sub(" ", folded)).strip()


def format_text(text: str, max_words: int = 20, yo: bool = True):
    """-> (adapted_text, change_log)"""
    return adapt(text, max_words=max_words, yo=yo)


def issues(text: str):
    """Human-review flags, without adapt_text's leading '  ! ' decoration."""
    return [re.sub(r"^\s*!\s*", "", line).strip() for line in flag_issues(text)]


def review(text: str, max_words: int = 20, yo: bool = True):
    adapted, log = format_text(text, max_words, yo=yo)
    return {"changes": log, "flags": issues(adapted)}
