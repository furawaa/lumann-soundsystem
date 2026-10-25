// Undo/redo for the formatted-text editor.
//
// The browser's own undo stack cannot be used here: Replace all rewrites the
// textarea through React state, and a programmatic value change wipes the
// native stack — ⌘Z after a replace-all would either do nothing or undo the
// keystroke before it, having silently dropped the replacement from history.
// So the history is ours, and ⌘Z is a site shortcut, not the browser's.
//
// Snapshots are whole copies of the text. A book is under a megabyte and an
// edit session is a few dozen steps, so a diff-based stack would buy nothing
// but a class of bugs — but "a few dozen" is not enforced by anything, hence
// the budget below.
import { useCallback, useRef, useState } from "react";

export interface Snapshot {
  text: string;
  caret: number;
}

/** Roughly 16 MB of text, whichever limit is reached first. */
const MAX_ENTRIES = 100;
const MAX_CHARS = 8_000_000;

function prune(stack: Snapshot[]): Snapshot[] {
  let chars = stack.reduce((sum, item) => sum + item.text.length, 0);
  let from = 0;
  while (from < stack.length - 1 && (stack.length - from > MAX_ENTRIES || chars > MAX_CHARS)) {
    chars -= stack[from].text.length;
    from++;
  }
  return from ? stack.slice(from) : stack;
}

/**
 * Typing coalesces: a burst of keystrokes collapses into the state before the
 * burst started, so ⌘Z removes a word, not a letter. Anything else — replace,
 * replace all — is always its own step.
 */
const COALESCE_MS = 600;

export interface History {
  /** Call with the state *before* the change. */
  record(before: Snapshot, coalesce: boolean): void;
  /** Pass the current state, get the one to go back to, or null. */
  undo(current: Snapshot): Snapshot | null;
  redo(current: Snapshot): Snapshot | null;
  reset(): void;
  canUndo: boolean;
  canRedo: boolean;
}

export function useHistory(): History {
  // Refs, not state: undo() has to hand back the snapshot synchronously, and a
  // state updater in React 19 does not run when it is called. The counters
  // exist only so the toolbar buttons can re-render.
  const past = useRef<Snapshot[]>([]);
  const future = useRef<Snapshot[]>([]);
  const lastAt = useRef(0);
  const [depth, setDepth] = useState({ undo: 0, redo: 0 });

  const sync = useCallback(() => {
    setDepth({ undo: past.current.length, redo: future.current.length });
  }, []);

  const record = useCallback((before: Snapshot, coalesce: boolean) => {
    const now = Date.now();
    const merge = coalesce && past.current.length > 0 && now - lastAt.current < COALESCE_MS;
    lastAt.current = now;
    // A fresh edit forks the timeline; whatever was undone is gone.
    future.current = [];
    if (!merge) past.current = prune([...past.current, before]);
    sync();
  }, [sync]);

  const undo = useCallback((current: Snapshot): Snapshot | null => {
    const previous = past.current.pop();
    if (!previous) return null;
    future.current.push(current);
    // The next keystroke must not merge into a step from before the undo.
    lastAt.current = 0;
    sync();
    return previous;
  }, [sync]);

  const redo = useCallback((current: Snapshot): Snapshot | null => {
    const next = future.current.pop();
    if (!next) return null;
    past.current.push(current);
    lastAt.current = 0;
    sync();
    return next;
  }, [sync]);

  const reset = useCallback(() => {
    past.current = [];
    future.current = [];
    lastAt.current = 0;
    sync();
  }, [sync]);

  return { record, undo, redo, reset, canUndo: depth.undo > 0, canRedo: depth.redo > 0 };
}
