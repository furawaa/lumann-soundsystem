// State behind the find bar.
//
// It lives here rather than inside FindBar because the matches are needed in
// two places: the bar draws the counter and steps through them, and the editor
// draws a highlight layer under the textarea for every one of them. A hook
// keeps that single source without FindBar having to push state upward.
import { useCallback, useEffect, useMemo, useRef, useState, type RefObject } from "react";
import {
  DEFAULT_OPTIONS, findAll, matchAfter, replaceAll, replaceOne,
  type FindOptions, type Match,
} from "./find";
import { selectAndReveal } from "./textarea";

export interface Find {
  query: string;
  setQuery: (value: string) => void;
  replacement: string;
  setReplacement: (value: string) => void;
  opts: FindOptions;
  toggle: (key: keyof FindOptions) => void;
  matches: Match[];
  index: number;
  current: Match | null;
  step: (delta: number) => void;
  /** The query is meant as a regex and is not one yet. */
  broken: boolean;
  /** How many Replace all just did; cleared by the next interaction. */
  replaced: number | null;
  replaceCurrent: () => void;
  replaceEvery: () => void;
  /** Prefill from the editor's selection, the way every editor does on ⌘F. */
  seed: () => void;
}

export function useFind(
  text: string,
  editor: RefObject<HTMLTextAreaElement | null>,
  onReplace: (next: string) => void,
  open: boolean,
): Find {
  const [query, setQuery] = useState("");
  const [replacement, setReplacement] = useState("");
  const [opts, setOpts] = useState<FindOptions>(DEFAULT_OPTIONS);
  const [index, setIndex] = useState(0);
  const [replaced, setReplaced] = useState<number | null>(null);
  // Set by a replace so the reveal below knows to follow the text, not to fight
  // the caret the user just moved.
  const follow = useRef(false);

  const matches = useMemo(
    () => (open ? findAll(text, query, opts) : []),
    [open, text, query, opts],
  );
  const broken = open && opts.regex && query !== "" && !isRegex(query, opts);
  const current = matches[index] ?? null;

  // A changed query restarts from the caret, not from the top of the book.
  useEffect(() => {
    if (!open) return;
    const caret = follow.current ? -1 : editor.current?.selectionStart ?? 0;
    follow.current = false;
    if (caret >= 0) setIndex(matchAfter(matches, caret));
    setReplaced(null);
  }, [query, opts, open]);

  // Replacing the last match shortens the list under the cursor.
  useEffect(() => {
    if (index >= matches.length) setIndex(0);
  }, [matches.length, index]);

  // Show whichever match is current — including after an edit moved it. The
  // textarea is selected but never focused: the caret has to stay in the query
  // field for Enter to keep stepping.
  useEffect(() => {
    const el = editor.current;
    if (!open || !el || !current) return;
    selectAndReveal(el, current.start, current.end, false);
  }, [open, current?.start, current?.end]);

  const step = useCallback((delta: number) => {
    setReplaced(null);
    setIndex((was) => {
      if (matches.length === 0) return 0;
      return (was + delta + matches.length) % matches.length;
    });
  }, [matches.length]);

  const replaceCurrent = useCallback(() => {
    if (!current) return;
    follow.current = true;
    setReplaced(null);
    // Staying on this index lands on what was the next match once the list is
    // rebuilt — which is what replace-then-next means.
    onReplace(replaceOne(text, current, replacement, opts));
  }, [current, text, replacement, opts, onReplace]);

  const replaceEvery = useCallback(() => {
    const result = replaceAll(text, query, replacement, opts);
    follow.current = true;
    if (result.count) onReplace(result.text);
    setReplaced(result.count);
  }, [text, query, replacement, opts, onReplace]);

  const seed = useCallback(() => {
    const el = editor.current;
    const picked = el ? el.value.slice(el.selectionStart, el.selectionEnd) : "";
    if (picked && !picked.includes("\n")) setQuery(picked);
  }, [editor]);

  const toggle = useCallback((key: keyof FindOptions) => {
    setOpts((was) => ({ ...was, [key]: !was[key] }));
  }, []);

  return {
    query, setQuery, replacement, setReplacement, opts, toggle,
    matches, index, current, step, broken, replaced,
    replaceCurrent, replaceEvery, seed,
  };
}

function isRegex(query: string, opts: FindOptions): boolean {
  try {
    new RegExp(query, opts.caseSensitive ? "gu" : "giu");
    return true;
  } catch {
    return false;
  }
}
