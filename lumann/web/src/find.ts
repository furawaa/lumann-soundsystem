// Find and replace over the formatted text. Pure string work, no DOM: the bar
// in FindBar.tsx is a thin shell over this.
//
// Two things here are specific to narrating Russian prose and are the reason
// this is not four lines of String.replaceAll:
//
// Whole word cannot use \b. JavaScript's \b is ASCII: in "слово" every letter
// is a non-word character to it, so \bслово\b matches inside "пословица" and
// fails where it should hold. The lookarounds below use \p{L}, which is what
// the flag `u` is for.
//
// ё=е is a real search mode, not a nicety. adapt_text restores ё across a
// quarter of the paragraphs, so the text says "пришёл" while the fingers type
// "пришел". Folding is 1:1 in length — ё→е, Ё→Е — so match offsets computed on
// the folded copy address the original text unchanged, which is what lets the
// rest of this file ignore the option entirely.

export interface FindOptions {
  /** Off: "Оля" finds "оля". */
  caseSensitive: boolean;
  /** On: "он" no longer matches inside "она". */
  wholeWord: boolean;
  /** On: the query is a regular expression, and $1 works in the replacement. */
  regex: boolean;
  /** On: "пришел" finds "пришёл", and the ё in the text survives replacement. */
  foldYo: boolean;
}

export interface Match {
  start: number;
  end: number;
  /** Capture groups, sliced from the original text. Empty unless `regex`. */
  groups: (string | undefined)[];
}

export const DEFAULT_OPTIONS: FindOptions = {
  caseSensitive: false,
  wholeWord: false,
  regex: false,
  foldYo: true,
};

const WORD_BEFORE = "(?<![\\p{L}\\p{N}_])";
const WORD_AFTER = "(?![\\p{L}\\p{N}_])";

function fold(text: string): string {
  return text.replace(/[ёЁ]/g, (char) => (char === "ё" ? "е" : "Е"));
}

/** Escapes the regex metacharacters only — never a letter, so `u` stays safe. */
function quote(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * -> a fresh regex, or null for an empty query or a regex the user is still
 * halfway through typing.
 */
export function compile(query: string, opts: FindOptions): RegExp | null {
  if (!query) return null;

  let source = opts.regex ? query : quote(query);
  if (opts.foldYo) source = fold(source);
  if (opts.wholeWord) source = `${WORD_BEFORE}(?:${source})${WORD_AFTER}`;

  // `u` is always on. It costs the user a few escapes that are legal without it
  // — \- and \/ now throw — and buys \p{L}, which is the only way to write "a
  // letter" and mean Cyrillic: \w is ASCII, so \w+ finds nothing in this book.
  // A pattern that throws surfaces as "no matches", not as a crash.
  const flags = `gd${opts.caseSensitive ? "" : "i"}u`;
  try {
    return new RegExp(source, flags);
  } catch {
    return null;
  }
}

export function findAll(text: string, query: string, opts: FindOptions): Match[] {
  const re = compile(query, opts);
  if (!re) return [];

  const haystack = opts.foldYo ? fold(text) : text;
  const out: Match[] = [];

  for (let hit = re.exec(haystack); hit; hit = re.exec(haystack)) {
    const spans = hit.indices ?? [];
    out.push({
      start: hit.index,
      end: hit.index + hit[0].length,
      // From `text`, not from the match: with ё folded, hit[1] would hand back
      // "пришел" and a $1 replacement would quietly drop the ё.
      groups: spans.slice(1).map((span) => (span ? text.slice(span[0], span[1]) : undefined)),
    });
    // A pattern that can match nothing — "а*" — would otherwise spin here.
    if (hit[0].length === 0) re.lastIndex++;
  }
  return out;
}

/** $&, $1…$99 and $$ in the replacement. Regex mode only; a literal `$` is a `$`. */
export function expand(replacement: string, match: Match, text: string, opts: FindOptions): string {
  if (!opts.regex) return replacement;
  return replacement.replace(/\$(\$|&|\d{1,2})/g, (_all, key: string) => {
    if (key === "$") return "$";
    if (key === "&") return text.slice(match.start, match.end);
    return match.groups[Number(key) - 1] ?? "";
  });
}

export function replaceOne(
  text: string, match: Match, replacement: string, opts: FindOptions,
): string {
  return text.slice(0, match.start)
    + expand(replacement, match, text, opts)
    + text.slice(match.end);
}

/**
 * All of them in one pass, left to right.
 *
 * Built by slicing rather than by String.replace so that a replacement
 * containing the query — "и" -> "или" — cannot be rescanned and replaced again.
 */
export function replaceAll(
  text: string, query: string, replacement: string, opts: FindOptions,
): { text: string; count: number } {
  const matches = findAll(text, query, opts);
  if (matches.length === 0) return { text, count: 0 };

  const parts: string[] = [];
  let at = 0;
  for (const match of matches) {
    parts.push(text.slice(at, match.start), expand(replacement, match, text, opts));
    at = match.end;
  }
  parts.push(text.slice(at));
  return { text: parts.join(""), count: matches.length };
}

/** Index of the first match at or after `caret`, wrapping to 0. */
export function matchAfter(matches: Match[], caret: number): number {
  const found = matches.findIndex((match) => match.start >= caret);
  return found === -1 ? 0 : found;
}

export interface MarkPart {
  text: string;
  hit: "none" | "match" | "current";
}

/**
 * The text cut into runs for the highlight layer.
 *
 * The one invariant that matters: joining the parts must give back the text
 * character for character. The layer is positioned under the textarea, so a
 * single character of drift moves every highlight after it onto the wrong word.
 *
 * `limit` caps how many matches are marked, not how much text comes back —
 * searching "и" in a book finds tens of thousands, and a DOM node per match
 * would stall the panel on every keystroke. The counter in the bar still
 * reports the true total.
 */
export function markParts(
  text: string, matches: Match[], current: number, limit: number,
): MarkPart[] {
  if (matches.length === 0) return [{ text, hit: "none" }];

  const parts: MarkPart[] = [];
  let at = 0;
  for (let i = 0; i < matches.length && i < limit; i++) {
    const match = matches[i];
    if (match.start > at) parts.push({ text: text.slice(at, match.start), hit: "none" });
    parts.push({
      text: text.slice(match.start, match.end),
      hit: i === current ? "current" : "match",
    });
    at = match.end;
  }
  if (at < text.length) parts.push({ text: text.slice(at), hit: "none" });
  return parts;
}
