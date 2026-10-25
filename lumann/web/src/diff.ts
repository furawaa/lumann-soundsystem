// Line and word diff for the side-by-side format preview.
//
// Written here rather than pulled in: the whole need is two texts of a few
// thousand lines and a git-shaped answer about them, and a dependency for that
// would be larger than the algorithm.

export interface Part {
  text: string;
  changed: boolean;
}

export type Op = "same" | "add" | "del" | "change";

export interface DiffRow {
  op: Op;
  left: string | null;
  right: string | null;
  leftNo: number | null;
  rightNo: number | null;
  /** Word-level split, only for `change` rows. */
  leftParts?: Part[];
  rightParts?: Part[];
}

export interface Hunk {
  op: Exclude<Op, "same">;
  /** First row of the run, which is what a jump scrolls to. */
  row: number;
}

export interface Diff {
  rows: DiffRow[];
  hunks: Hunk[];
  added: number;
  deleted: number;
  changed: number;
}

// Above this, the O(n·m) table is not worth building: the two sides get paired
// positionally instead. Reached only by a text with thousands of edited lines,
// where a precise alignment would be unreadable anyway.
const MAX_CELLS = 4_000_000;

/** Longest common subsequence, as a pairing {aIndex -> bIndex}. */
function lcsPairs<T>(a: T[], b: T[]): Map<number, number> {
  const pairs = new Map<number, number>();
  if (!a.length || !b.length) return pairs;

  if (a.length * b.length > MAX_CELLS) {
    for (let i = 0; i < Math.min(a.length, b.length); i++) pairs.set(i, i);
    return pairs;
  }

  const width = b.length + 1;
  const table = new Int32Array((a.length + 1) * width);
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      table[i * width + j] = a[i] === b[j]
        ? table[(i + 1) * width + j + 1] + 1
        : Math.max(table[(i + 1) * width + j], table[i * width + j + 1]);
    }
  }

  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      pairs.set(i, j);
      i++;
      j++;
    } else if (table[(i + 1) * width + j] >= table[i * width + j + 1]) {
      i++;
    } else {
      j++;
    }
  }
  return pairs;
}

/**
 * Lines that occur exactly once on each side and are equal there.
 *
 * These are the trustworthy anchors. Plain LCS is not: half the lines in a
 * formatted text are the blank line between paragraphs, they all compare equal,
 * and a maximal subsequence happily pairs the blank *before* an edited
 * paragraph with the blank *after* it — every following line then reads as one
 * unrelated deletion against one unrelated insertion. Anchoring on unique lines
 * is the patience-diff answer to exactly that failure.
 */
function uniqueAnchors(a: string[], b: string[]): [number, number][] {
  const countIn = (lines: string[]) => {
    const counts = new Map<string, number>();
    for (const line of lines) counts.set(line, (counts.get(line) ?? 0) + 1);
    return counts;
  };
  const inA = countIn(a);
  const inB = countIn(b);
  const positionInB = new Map<string, number>();
  b.forEach((line, index) => { if (inB.get(line) === 1) positionInB.set(line, index); });

  const candidates: [number, number][] = [];
  a.forEach((line, index) => {
    if (inA.get(line) !== 1) return;
    const j = positionInB.get(line);
    if (j !== undefined) candidates.push([index, j]);
  });

  // Longest increasing subsequence over the b-side positions: anchors have to
  // be monotonic, or the gaps between them would overlap.
  const tails: number[] = [];          // candidate index with the smallest tail
  const previous: number[] = new Array(candidates.length).fill(-1);
  for (let k = 0; k < candidates.length; k++) {
    let low = 0;
    let high = tails.length;
    while (low < high) {
      const mid = (low + high) >> 1;
      if (candidates[tails[mid]][1] < candidates[k][1]) low = mid + 1;
      else high = mid;
    }
    previous[k] = low > 0 ? tails[low - 1] : -1;
    tails[low] = k;
  }

  const chain: [number, number][] = [];
  for (let k = tails.length ? tails[tails.length - 1] : -1; k >= 0; k = previous[k]) {
    chain.push(candidates[k]);
  }
  return chain.reverse();
}

/**
 * Pair up lines: anchor on the unique ones, then fill each gap with an LCS.
 *
 * The gaps are small — an edited paragraph and the blank lines around it — so
 * the quadratic part stays cheap even on a whole book.
 */
function alignLines(a: string[], b: string[]): Map<number, number> {
  const pairs = new Map<number, number>();
  let ai = 0;
  let bi = 0;

  const anchors: [number, number][] = [...uniqueAnchors(a, b), [a.length, b.length]];
  for (const [i, j] of anchors) {
    for (const [x, y] of lcsPairs(a.slice(ai, i), b.slice(bi, j))) {
      pairs.set(ai + x, bi + y);
    }
    if (i < a.length) pairs.set(i, j);
    ai = i + 1;
    bi = j + 1;
  }
  return pairs;
}

/** Words and the whitespace between them, kept as separate tokens. */
function tokenize(line: string): string[] {
  return line.split(/(\s+)/).filter((token) => token !== "");
}

/**
 * Dice coefficient over character bigrams: 1 is identical, 0 shares nothing.
 *
 * Characters rather than words because of what these edits look like: restoring
 * ё changes every second word of a paragraph without changing the paragraph at
 * all, and a word-level score reads that as two unrelated texts.
 */
function similarity(x: string, y: string): number {
  const bigrams = (text: string) => {
    const counts = new Map<string, number>();
    for (let i = 0; i < text.length - 1; i++) {
      const gram = text.slice(i, i + 2);
      counts.set(gram, (counts.get(gram) ?? 0) + 1);
    }
    return counts;
  };
  const a = bigrams(x);
  const b = bigrams(y);
  if (!a.size || !b.size) return x === y ? 1 : 0;

  let shared = 0;
  let total = 0;
  for (const [gram, n] of a) {
    shared += Math.min(n, b.get(gram) ?? 0);
    total += n;
  }
  for (const n of b.values()) total += n;
  return (2 * shared) / total;
}

// Below this, two paragraphs are not related enough to show as one rewrite.
const MIN_SIMILARITY = 0.3;
// Similarity is quadratic in tokens; a run this long is a wholesale rewrite
// where pairing adds nothing anyway.
const MAX_RUN = 24;

/**
 * Which deletions in a run are rewrites of which insertions.
 *
 * Pairing them off from the start of the run, which is the obvious thing, is
 * wrong whenever the run begins with a genuine deletion: every later pair is
 * then off by one, and the last deleted paragraph gets blamed for a change that
 * happened elsewhere. So pair by similarity instead, keeping order, and leave
 * anything below the threshold as a real delete or insert.
 */
function pairRun(dels: string[], adds: string[]): ("change" | "del" | "add")[] {
  const n = dels.length;
  const m = adds.length;
  if (!n) return adds.map(() => "add");
  if (!m) return dels.map(() => "del");
  if (n > MAX_RUN || m > MAX_RUN) {
    const shared = Math.min(n, m);
    return [
      ...Array<"change">(shared).fill("change"),
      ...Array<"del">(n - shared).fill("del"),
      ...Array<"add">(m - shared).fill("add"),
    ];
  }

  // best[i][j]: score for dels[i..] against adds[j..].
  const best: number[][] = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      const sim = similarity(dels[i], adds[j]);
      const paired = sim >= MIN_SIMILARITY ? sim + best[i + 1][j + 1] : -1;
      best[i][j] = Math.max(paired, best[i + 1][j], best[i][j + 1]);
    }
  }

  const ops: ("change" | "del" | "add")[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    const sim = similarity(dels[i], adds[j]);
    if (sim >= MIN_SIMILARITY && sim + best[i + 1][j + 1] === best[i][j]) {
      ops.push("change");
      i++;
      j++;
    } else if (best[i + 1][j] >= best[i][j + 1]) {
      ops.push("del");
      i++;
    } else {
      ops.push("add");
      j++;
    }
  }
  while (i++ < n) ops.push("del");
  while (j++ < m) ops.push("add");
  return ops;
}

/** Word-level parts for a pair of lines that differ. */
function wordParts(before: string, after: string): { left: Part[]; right: Part[] } {
  const a = tokenize(before);
  const b = tokenize(after);
  const pairs = lcsPairs(a, b);
  const kept = new Set(pairs.values());

  const merge = (tokens: string[], same: (index: number) => boolean): Part[] => {
    const parts: Part[] = [];
    for (let index = 0; index < tokens.length; index++) {
      const changed = !same(index);
      const last = parts[parts.length - 1];
      if (last && last.changed === changed) last.text += tokens[index];
      else parts.push({ text: tokens[index], changed });
    }
    return parts;
  };

  return {
    left: merge(a, (index) => pairs.has(index)),
    right: merge(b, (index) => kept.has(index)),
  };
}

/**
 * Paragraphs, which is the unit this text is actually made of: the formatted
 * text separates them with a blank line and never breaks one across lines.
 *
 * Diffing raw lines instead looks obvious and is a trap. Half of them are the
 * blank separator, they all compare equal, and when a paragraph is dropped the
 * alignment inside the surrounding run is decided by which of five identical
 * blank lines the tie-break happens to drop — which is how a spelling fix two
 * paragraphs away gets reported as a deleted paragraph.
 */
function paragraphs(text: string): string[] {
  return text.split(/\n{2,}/).map((block) => block.trim()).filter(Boolean);
}

/**
 * Side-by-side diff of two texts, paragraph by paragraph.
 *
 * Deletions and insertions that sit next to each other are paired up into
 * `change` rows as far as the shorter run goes: a reformatted paragraph is one
 * paragraph rewritten, and showing it as an unrelated delete above an unrelated
 * insert hides exactly the thing the reader is looking for.
 */
export function diffText(before: string, after: string): Diff {
  const a = paragraphs(before);
  const b = paragraphs(after);
  const pairs = alignLines(a, b);

  const rows: DiffRow[] = [];
  const hunks: Hunk[] = [];
  let added = 0;
  let deleted = 0;
  let changed = 0;

  const flush = (dels: number[], adds: number[]) => {
    if (!dels.length && !adds.length) return;
    const start = rows.length;
    let di = 0;
    let ai = 0;

    for (const op of pairRun(dels.map((k) => a[k]), adds.map((k) => b[k]))) {
      if (op === "change") {
        const left = dels[di++];
        const right = adds[ai++];
        const parts = wordParts(a[left], b[right]);
        rows.push({
          op: "change",
          left: a[left], right: b[right],
          leftNo: left + 1, rightNo: right + 1,
          leftParts: parts.left, rightParts: parts.right,
        });
        changed++;
      } else if (op === "del") {
        const left = dels[di++];
        rows.push({ op: "del", left: a[left], right: null,
                    leftNo: left + 1, rightNo: null });
        deleted++;
      } else {
        const right = adds[ai++];
        rows.push({ op: "add", left: null, right: b[right],
                    leftNo: null, rightNo: right + 1 });
        added++;
      }
    }
    hunks.push({ op: rows[start].op as Exclude<Op, "same">, row: start });
  };

  let i = 0;
  let j = 0;
  let dels: number[] = [];
  let adds: number[] = [];

  while (i < a.length || j < b.length) {
    const matched = pairs.get(i);
    if (matched !== undefined && matched === j) {
      flush(dels, adds);
      dels = [];
      adds = [];
      rows.push({ op: "same", left: a[i], right: b[j], leftNo: i + 1, rightNo: j + 1 });
      i++;
      j++;
      continue;
    }
    // Whichever side is not part of the next common line moves first.
    if (matched === undefined && i < a.length) dels.push(i++);
    else if (j < b.length) adds.push(j++);
    else if (i < a.length) dels.push(i++);
  }
  flush(dels, adds);

  return { rows, hunks, added, deleted, changed };
}
