#!/usr/bin/env python3
"""Normalize text for text-to-speech. Most of it is Russian-specific.

This is the "Format" step of the web app, also usable on its own. Clean-up of
quotes, dashes, invisible characters, URLs and markdown applies to any text;
numbers to words, ё, particles, semicolons and clause splitting apply only
to Russian text, and are skipped otherwise. It handles only the mechanical parts — the things that are the same edit every time.
Prosody (where to breathe, which word to lean on) is a judgment call and
deliberately stays out of here; see "Tips for better audio" in the README.

    python adapt_text.py input.txt              # -> stdout
    python adapt_text.py input.txt --report     # + list of what changed
    cat x.txt | python adapt_text.py -
"""
import argparse
import os
import re
import sys
import unicodedata

# --- 1. character-level normalization ---------------------------------------

QUOTES = {"“": '"', "”": '"', "„": '"', "«": '"', "»": '"',
          "‘": "'", "’": "'"}
DASHES = {"–": "—", "‒": "—", "―": "—"}


def normalize_chars(text, log):
    for src, dst in {**QUOTES, **DASHES}.items():
        if src in text:
            text = text.replace(src, dst)
    # non-breaking hyphen / soft hyphen / NBSP: invisible, model may choke
    for src, dst in {"‑": "-", "­": "", " ": " ", " ": " "}.items():
        if src in text:
            log.append(f"removed invisible char U+{ord(src):04X}")
            text = text.replace(src, dst)
    text = unicodedata.normalize("NFC", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def strip_junk(text, log):
    """Remove things that are read aloud literally and shouldn't be."""
    patterns = [
        (r"https?://\S+", "", "URLs"),
        (r"#[\wЀ-ӿ_]+", "", "hashtags"),
        (r"[*_`]{1,3}(?=\S)(.+?)(?<=\S)[*_`]{1,3}", r"\1", "markdown emphasis"),
        (r"^\s*[-*+]\s+", "", "list bullets"),
        (r"\[(.+?)\]\(.+?\)", r"\1", "markdown links"),
    ]
    for pat, repl, name in patterns:
        new = re.sub(pat, repl, text, flags=re.MULTILINE)
        if new != text:
            log.append(f"stripped {name}")
            text = new
    # emoji & pictographs
    new = "".join(c for c in text if unicodedata.category(c) != "So")
    if new != text:
        log.append("stripped emoji/symbols")
        text = new
    return re.sub(r"[ \t]+", " ", text)


# --- 2. hyphenated particles ------------------------------------------------
# -то/-либо/-нибудь/-ка/-таки are one phonetic word; the hyphen is a boundary
# the model may honor. Joining them is safe (verified by ear on "какойто").

PARTICLE_RE = re.compile(r"(?<=[а-яё])-(то|либо|нибудь|ка|таки)\b", re.IGNORECASE)


def join_particles(text, log):
    hits = PARTICLE_RE.findall(text)
    if hits:
        log.append(f"joined {len(hits)} hyphenated particle(s): {', '.join(sorted(set(h.lower() for h in hits)))}")
    return PARTICLE_RE.sub(r"\1", text)


# --- 3. numbers -------------------------------------------------------------

ONES = ["", "один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять",
        "десять", "одиннадцать", "двенадцать", "тринадцать", "четырнадцать", "пятнадцать",
        "шестнадцать", "семнадцать", "восемнадцать", "девятнадцать"]
TENS = ["", "", "двадцать", "тридцать", "сорок", "пятьдесят", "шестьдесят", "семьдесят",
        "восемьдесят", "девяносто"]
HUNDREDS = ["", "сто", "двести", "триста", "четыреста", "пятьсот", "шестьсот", "семьсот",
            "восемьсот", "девятьсот"]
SCALES = [("", "", "", 0), ("тысяча", "тысячи", "тысяч", 1),
          ("миллион", "миллиона", "миллионов", 0), ("миллиард", "миллиарда", "миллиардов", 0)]


def _triplet(n, feminine):
    words = []
    if n >= 100:
        words.append(HUNDREDS[n // 100])
        n %= 100
    if n >= 20:
        words.append(TENS[n // 10])
        n %= 10
    if n:
        if feminine and n in (1, 2):
            words.append({1: "одна", 2: "две"}[n])
        else:
            words.append(ONES[n])
    return words


def _plural(n, forms):
    n100, n10 = n % 100, n % 10
    if 11 <= n100 <= 14:
        return forms[2]
    return forms[0] if n10 == 1 else forms[1] if 2 <= n10 <= 4 else forms[2]


def int_to_ru(n):
    """Cardinal, nominative case only. Oblique cases are the caller's problem."""
    if n == 0:
        return "ноль"
    parts, groups = [], []
    while n:
        groups.append(n % 1000)
        n //= 1000
    for idx in range(len(groups) - 1, -1, -1):
        g = groups[idx]
        if not g:
            continue
        one, few, many, fem = SCALES[idx]
        parts.extend(_triplet(g, bool(fem)))
        if one:
            parts.append(_plural(g, (one, few, many)))
    words = [p for p in parts if p]
    # "одна тысяча двести" -> "тысяча двести", as it is actually said
    if len(words) > 1 and words[0] == "одна" and words[1] == "тысяча":
        words.pop(0)
    return " ".join(words)


# Integers only. Decimals are left alone (and flagged) because "3.5" needs a
# case-aware reading the script can't infer. Lookarounds keep it off both
# halves of a decimal and out of the middle of a longer digit run.
NUM_RE = re.compile('(?<![\\d.,])\\d+(?:[\u00a0\u2009]\\d{3})*(?!\\d|[.,]\\d)')


def expand_numbers(text, log):
    found = []

    def repl(m):
        raw = m.group(0)
        digits = re.sub('[\u00a0\u2009]', '', raw)
        try:
            words = int_to_ru(int(digits))
        except (ValueError, IndexError):
            return raw
        found.append(raw)
        return words

    new = NUM_RE.sub(repl, text)
    if found:
        log.append(f"expanded {len(found)} number(s) to NOMINATIVE case — CHECK: {', '.join(found[:5])}")
    return new


# --- 4. ё -------------------------------------------------------------------
# Most Russian books spell ё as е throughout. That is a
# real reading risk — "все"/"всё" and "пришел"/"пришёл" are different words —
# but only some of it is mechanical. Two dictionaries split it: `dicts/` holds
# the words where е-spelling does not exist as another word (safe to replace)
# and the homographs (flag, never touch). See dicts/README.md for the format.

DICT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dicts")
_YO_CACHE = {}


def _entries(path):
    """eyo dictionary file -> word forms, alternations expanded."""
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.split("#", 1)[0].strip()
            if not line or line.startswith("_"):     # disabled entry
                continue
            stem, paren, rest = line.partition("(")
            if not paren:
                yield line
                continue
            for suffix in rest.rstrip(")").split("|"):
                yield stem + suffix


def _deyo(word):
    return word.replace("ё", "е").replace("Ё", "Е")


def _load(name):
    """-> ({lowercase-entry key: form}, {capitalized-entry key: form}).

    Keys are the е-spelling, i.e. what we look up in the text. A dictionary
    entry starting lowercase matches both cases in the text; one starting
    uppercase matches only the capitalized word (README's rule, and it is what
    keeps the surname "Аксёнов" from eating "аксенов").
    """
    if name not in _YO_CACHE:
        lower, upper = {}, {}
        for form in _entries(os.path.join(DICT_DIR, name)):
            key = _deyo(form)
            if form[:1].isupper():
                upper[key] = form
            else:
                lower[key.lower()] = form
        _YO_CACHE[name] = (lower, upper)
    return _YO_CACHE[name]


WORD_RE = re.compile(r"[А-Яа-яЁё]+")


def _restore_case(word, form):
    if word.isupper() and len(word) > 1:
        return form.upper()
    if word[:1].isupper():
        return form[:1].upper() + form[1:]
    return form


def yoficate(text, log):
    lower, upper = _load("yo_safe.txt")
    hits = []

    def repl(m):
        word = m.group(0)
        form = upper.get(word) or lower.get(word.lower())
        if form is None or form == word:
            return word
        hits.append(word)
        return _restore_case(word, form)

    new = WORD_RE.sub(repl, text)
    if hits:
        uniq = sorted(set(hits))
        log.append(f"ё restored in {len(hits)} word(s): {', '.join(uniq[:5])}"
                   + (" …" if len(uniq) > 5 else ""))
    return new


def yo_ambiguous(text):
    """Words left over that are homographs — a human has to read the sentence."""
    lower, upper = _load("yo_not_safe.txt")
    return [w for w in WORD_RE.findall(text) if w in upper or w.lower() in lower]


# --- 5. sentence structure --------------------------------------------------

CLAUSE_BREAKS = [r",\s+(но)\s+", r",\s+(однако)\s+", r",\s+(и всё же|и все же)\s+",
                 r",\s+(а)\s+", r",\s+(более того)\s*,\s*"]


def semicolons_to_periods(text, log):
    if ";" in text:
        log.append("semicolons -> sentence breaks")
        text = re.sub(r"\s*;\s*", ". ", text)
    return text


def split_long_sentences(text, max_words, log):
    out, splits = [], 0
    for sent in re.split(r"(?<=[.!?])\s+", text):
        if len(sent.split()) <= max_words:
            out.append(sent)
            continue
        piece = sent
        for pat in CLAUSE_BREAKS:
            m = re.search(pat, piece)
            if m and len(piece[:m.start()].split()) >= 4:
                head, tail = piece[:m.start()], piece[m.start():]
                tail = re.sub(r"^,\s*", "", tail).strip()
                out.append(head.rstrip(",. ") + ".")
                piece = tail[0].upper() + tail[1:] if tail else ""
                splits += 1
        if piece:
            out.append(piece)
    if splits:
        log.append(f"split {splits} long sentence(s) at clause boundaries")
    return " ".join(out)


def capitalize_sentences(text):
    return re.sub(r"(^|[.!?]\s+)([а-яё])",
                  lambda m: m.group(1) + m.group(2).upper(), text)


# --- 6. things a script must not guess at -----------------------------------

FLAG_PATTERNS = [
    (r"[A-Za-z]{2,}", "Latin text — model reads it as English; transliterate or set language"),
    (r"\b(т\.\s?е\.|т\.\s?д\.|т\.\s?п\.|др\.|г\.|стр\.)", "abbreviation — expand by hand"),
    (r"\d+[.,]\d+", "decimal — expand by hand"),
    (r"[%№§+=<>]", "symbol read unpredictably"),
]


def is_russian(text):
    """Mostly Cyrillic letters. The Russian-only steps hinge on this."""
    letters = [c for c in text if c.isalpha()]
    cyrillic = sum(1 for c in letters if "\u0400" <= c <= "\u04ff")
    return bool(letters) and cyrillic * 2 > len(letters)


# Flags that only make sense in Russian text: in an English book every word is
# "Latin text".
RUSSIAN_ONLY_FLAGS = 2


def flag_issues(text, russian=None):
    if russian is None:
        russian = is_russian(text)
    out = []
    for pat, msg in FLAG_PATTERNS[0 if russian else RUSSIAN_ONLY_FLAGS:]:
        hits = re.findall(pat, text, flags=re.IGNORECASE)
        if hits:
            uniq = sorted(set(h if isinstance(h, str) else h[0] for h in hits))[:6]
            out.append(f"  ! {msg}: {', '.join(uniq)}")
    ambiguous = sorted(set(yo_ambiguous(text)))
    if ambiguous:
        out.append(f"  ! ё/е homograph — read the sentence and decide: {', '.join(ambiguous[:6])}")
    return out


def adapt(text, max_words=18, yo=True, russian=None):
    """`russian` None means: decide from this text. Pass it when formatting a
    book piece by piece, so a paragraph like "1984." follows the book."""
    if russian is None:
        russian = is_russian(text)
    log = []
    text = normalize_chars(text, log)
    text = strip_junk(text, log)
    if russian:
        text = join_particles(text, log)
        if yo:
            text = yoficate(text, log)
        # eSpeak and Qwen read digits in other languages well enough; Russian
        # number words are what would break an English sentence.
        text = expand_numbers(text, log)
        text = semicolons_to_periods(text, log)
        text = split_long_sentences(text, max_words, log)
    text = capitalize_sentences(text)
    text = re.sub(r"\s+([.,!?])", r"\1", text)
    text = re.sub(r"[ \t]+", " ", text).strip()
    return text, log


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help="text file, or - for stdin")
    ap.add_argument("--report", action="store_true", help="print changes + manual-review flags to stderr")
    ap.add_argument("--max-words", type=int, default=18, help="split sentences longer than this (default 18)")
    ap.add_argument("--no-yo", dest="yo", action="store_false", help="leave е as written; skip ё restoration")
    args = ap.parse_args()

    raw = sys.stdin.read() if args.input == "-" else open(args.input, encoding="utf-8").read()
    result, log = adapt(raw, args.max_words, yo=args.yo)
    print(result)

    if args.report:
        print("\n--- changes ---", file=sys.stderr)
        for line in log or ["  (none)"]:
            print(f"  - {line}" if log else line, file=sys.stderr)
        flags = flag_issues(result)
        if flags:
            print("--- needs a human ---", file=sys.stderr)
            print("\n".join(flags), file=sys.stderr)


if __name__ == "__main__":
    main()
