import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { api, type Project } from "../api";
import { markParts } from "../find";
import { useHistory } from "../history";
import { useI18n } from "../i18n";
import { selectAndReveal } from "../textarea";
import { useFind } from "../useFind";
import { FindBar } from "./FindBar";
import { FormatDiffModal } from "./FormatDiffModal";
import { Button, Segmented } from "./ui";

type View = "original" | "formatted";

/** How many matches get a highlight node. See markParts for why there is a cap. */
const MARK_LIMIT = 2000;

interface Props {
  project: Project;
  selected: string | null;
  onSelect: (id: string) => void;
  onPlay: (id: string) => void;
  onReformat: (text: string | null, origin: View) => void;
}

/**
 * Highlighting is segment-granular by design: there is no word-level
 * audio-to-text alignment, and pretending otherwise would mean forced
 * alignment. Paragraphs are the visible unit so the granularity reads as
 * intentional rather than as a limitation.
 *
 * Both views are editable, and both save through the same path: the text goes
 * to the reformat preview, which is where segments are matched up, takes are
 * carried over and the ones that no longer match their audio go stale. Editing
 * the formatted text is not a shortcut around that — it is the same commit.
 */
export function TextPanel(props: Props) {
  const { t } = useI18n();
  const [view, setView] = useState<View>("formatted");
  const [source, setSource] = useState<string | null>(null);

  // formatted-view editing
  const [editing, setEditing] = useState(false);
  const [compare, setCompare] = useState(false);
  const [findOpen, setFindOpen] = useState(false);
  const [formatDiff, setFormatDiff] = useState(false);
  const [baseline, setBaseline] = useState("");     // formatted text as saved
  const [formattedDraft, setFormattedDraft] = useState("");
  const [jumpTo, setJumpTo] = useState<{ start: number; end: number } | null>(null);
  const [restoreCaret, setRestoreCaret] = useState<number | null>(null);
  const formattedRef = useRef<HTMLDivElement>(null);
  const editorRef = useRef<HTMLTextAreaElement>(null);
  const marksRef = useRef<HTMLDivElement>(null);

  const history = useHistory();
  const find = useFind(
    formattedDraft,
    editorRef,
    (next) => commit(next, false),
    editing && findOpen,
  );
  // Set when the selection change came from a click in here, so the reveal
  // below can sit it out.
  const selectedFromHere = useRef(false);

  useEffect(() => {
    let live = true;
    setSource(null);
    setEditing(false);
    setCompare(false);
    setFindOpen(false);
    api.source(props.project.id).then((result) => {
      if (live) setSource(result.text);
    });
    return () => { live = false; };
  }, [props.project.id]);

  // Selection -> highlight -> scroll. Runs on selection alone; the user should
  // not have to press play to find where they are.
  //
  // Except when the click was in this panel. Scrolling then moved the paragraph
  // out from under the cursor, so the second click of a double-click landed
  // somewhere else and never became a dblclick — and the scroll was pointless
  // anyway, since the text the user just clicked is by definition in view.
  useEffect(() => {
    if (selectedFromHere.current) {
      selectedFromHere.current = false;
      return;
    }
    if (view !== "formatted" || editing || !props.selected) return;
    const node = formattedRef.current?.querySelector(`[data-seg="${props.selected}"]`);
    node?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [props.selected, view, editing]);

  const paragraphs = useMemo(() => {
    // Group segments into paragraphs so the rendered text keeps its shape.
    const groups: { key: string; segments: { id: string; text: string }[] }[] = [];
    let line = -1;
    for (const item of props.project.timeline) {
      if (item.kind !== "segment") continue;
      if (item.line !== line || groups.length === 0) {
        groups.push({ key: `${item.line}-${item.id}`, segments: [] });
        line = item.line;
      }
      groups[groups.length - 1].segments.push({
        id: item.id,
        text: item.text_override || item.text,
      });
    }
    return groups;
  }, [props.project.timeline]);

  async function startEditing() {
    const current = await api.formatted(props.project.id);
    setBaseline(current.text);
    setFormattedDraft(current.text);
    history.reset();
    // Land on whatever the user was looking at, not at the top of the book.
    const span = current.spans.find((item) => item.id === props.selected);
    setJumpTo(span ? { start: span.start, end: span.end } : null);
    setEditing(true);
  }

  // Runs after the textarea exists, which is why it cannot live in startEditing.
  useEffect(() => {
    if (!editing || !jumpTo || !editorRef.current) return;
    selectAndReveal(editorRef.current, jumpTo.start, jumpTo.end);
    setJumpTo(null);
  }, [editing, jumpTo]);

  function cancelEditing() {
    setEditing(false);
    setCompare(false);
    setFindOpen(false);
    setFormattedDraft(baseline);
    history.reset();
  }

  // --- editing the draft --------------------------------------------------

  /**
   * Every change to the draft goes through here, which is what makes ⌘Z whole:
   * a replace-all and a keystroke are the same kind of event to the history,
   * and only typing coalesces.
   */
  function commit(next: string, typing: boolean) {
    history.record({ text: formattedDraft, caret: caretNow() }, typing);
    setFormattedDraft(next);
  }

  function caretNow() {
    return editorRef.current?.selectionStart ?? 0;
  }

  function undo() {
    const previous = history.undo({ text: formattedDraft, caret: caretNow() });
    if (!previous) return;
    setFormattedDraft(previous.text);
    setRestoreCaret(previous.caret);
  }

  function redo() {
    const next = history.redo({ text: formattedDraft, caret: caretNow() });
    if (!next) return;
    setFormattedDraft(next.text);
    setRestoreCaret(next.caret);
  }

  // Put the caret back where the undone edit happened, after React has written
  // the restored text into the textarea.
  useEffect(() => {
    if (restoreCaret === null || !editorRef.current) return;
    selectAndReveal(editorRef.current, restoreCaret, restoreCaret);
    setRestoreCaret(null);
  }, [restoreCaret]);

  // Site shortcuts, not the browser's. ⌘Z has to be ours because Replace all
  // rewrites the value from React and wipes the native undo stack; ⌘F has to be
  // ours because the browser's find bar cannot see into a textarea.
  //
  // Bound to the window rather than to the editor, so that ⌘Z still undoes a
  // replace-all while the caret is in the find field — which is exactly when
  // one wants to take it back. Any modal on top owns the keyboard instead;
  // asking the DOM is how this learns about the ones App.tsx opens.
  useEffect(() => {
    if (!editing) return;
    function onKey(event: KeyboardEvent) {
      if (!event.metaKey && !event.ctrlKey) return;
      if (document.querySelector(".modal-backdrop")) return;
      const key = event.key.toLowerCase();
      if (key === "f") {
        event.preventDefault();
        setFindOpen(true);
      } else if (key === "z" && !event.shiftKey) {
        event.preventDefault();
        undo();
      } else if (key === "y" || (key === "z" && event.shiftKey)) {
        event.preventDefault();
        redo();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const formattedDirty = editing && formattedDraft !== baseline;

  // Highlights for every match, drawn on a layer under the textarea.
  //
  // Null while the bar is closed, and the layer is then not rendered at all:
  // it holds a second copy of the book, and leaving it in would make every
  // keystroke lay out a megabyte of text twice for nothing.
  const marks = useMemo(
    () => (findOpen ? markParts(formattedDraft, find.matches, find.index, MARK_LIMIT) : null),
    [findOpen, formattedDraft, find.matches, find.index],
  );

  // The layer scrolls with the textarea, and has to be re-synced after a render
  // changed the text under it.
  useLayoutEffect(syncMarkScroll);

  function syncMarkScroll() {
    const el = editorRef.current;
    const layer = marksRef.current;
    if (!el || !layer) return;
    layer.scrollTop = el.scrollTop;
    layer.scrollLeft = el.scrollLeft;
  }

  return (
    <section className="panel text-panel">
      <header className="panel-head">
        <Segmented
          value={view}
          onChange={(next) => {
            setView(next);
            setEditing(false);
            setCompare(false);
            setFindOpen(false);
          }}
          options={[
            { value: "original", label: t("text.original") },
            { value: "formatted", label: t("text.formatted") },
          ]}
        />

        {view === "original" && (
          <div className="head-actions">
            <Button
              onClick={() => props.onReformat(null, "original")}
              title={t("text.rederiveTitle")}
            >
              {t("text.rederive")}
            </Button>
          </div>
        )}

        {view === "formatted" && (
          <div className="head-actions">
            {editing
              ? (
                <>
                  <button
                    className="icon step"
                    disabled={!history.canUndo}
                    onClick={undo}
                    title={t("text.undo")}
                  >
                    ↺
                  </button>
                  <button
                    className="icon step"
                    disabled={!history.canRedo}
                    onClick={redo}
                    title={t("text.redo")}
                  >
                    ↻
                  </button>
                  <button
                    className="icon step"
                    onClick={() => setFindOpen(true)}
                    title={t("text.findTitle")}
                  >
                    ⌕
                  </button>
                  <Button
                    onClick={() => setCompare(!compare)}
                    className={compare ? "on" : ""}
                    title={t("text.compareTitle")}
                  >
                    {t("text.compare")}
                  </Button>
                  <Button onClick={cancelEditing}>{t("common.cancel")}</Button>
                  <Button
                    primary
                    disabled={!formattedDirty}
                    onClick={() => setFormatDiff(true)}
                  >
                    {t("text.save")}
                  </Button>
                </>
              )
              : (
                <button className="icon pencil" onClick={startEditing} title={t("text.edit")}>
                  ✎
                </button>
              )}
          </div>
        )}
      </header>

      {view === "original" && (
        <>
          <p className="notice ro">{t("text.originalReadOnly")}</p>
          <textarea
            className="source-editor"
            value={source === null ? t("text.loading") : source}
            spellCheck={false}
            readOnly
          />
        </>
      )}

      {view === "formatted" && !editing && (
        <div className="formatted" ref={formattedRef}>
          {paragraphs.map((group) => (
            <p
              key={group.key}
              className={group.segments.length === 1 ? "single" : undefined}
              onClick={(event) => {
                const id = segmentAtPoint(event, group.segments);
                if (!id) return;
                // Only when this actually re-renders, or the flag would go
                // stale and swallow the next reveal from outside.
                if (id !== props.selected) selectedFromHere.current = true;
                props.onSelect(id);
              }}
              onDoubleClick={(event) => {
                const id = segmentAtPoint(event, group.segments);
                if (!id) return;
                // Double-click selects a word by default; the intent here is to
                // hear the paragraph, so drop the selection.
                window.getSelection()?.removeAllRanges();
                props.onPlay(id);
              }}
            >
              {group.segments.map((segment, index) => (
                <span
                  key={segment.id}
                  data-seg={segment.id}
                  className={props.selected === segment.id ? "seg on" : "seg"}
                >
                  {index > 0 ? " " : ""}{segment.text}
                </span>
              ))}
            </p>
          ))}
        </div>
      )}

      {view === "formatted" && editing && findOpen && (
        <FindBar find={find} onClose={() => { setFindOpen(false); editorRef.current?.focus(); }} />
      )}

      {view === "formatted" && editing && (
        <div className={compare ? "compare" : "compare single"}>
          {compare && (
            <div className="compare-side">
              <div className="compare-head">{t("text.original")}</div>
              <pre className="compare-text">
                {source === null ? t("text.loading") : source}
              </pre>
            </div>
          )}
          <div className="compare-side">
            {compare && <div className="compare-head">{t("text.formatted")}</div>}
            {/* The textarea sits on top, transparent; the layer under it holds
                nothing but the same text with the matches marked. Their metrics
                have to agree to the pixel, which is why both use .source-editor. */}
            <div className="editor-stack">
              {marks && (
                <div className="editor-marks source-editor" ref={marksRef} aria-hidden="true">
                  {marks.map((part, at) =>
                    part.hit === "none"
                      ? part.text
                      : (
                        <mark key={at} className={part.hit === "current" ? "hit on" : "hit"}>
                          {part.text}
                        </mark>
                      ))}
                  {/* Keeps the layer as tall as the textarea, which scrolls one
                      line past the end of its text. */}
                  {"\n"}
                </div>
              )}
              <textarea
                ref={editorRef}
                className="source-editor"
                value={formattedDraft}
                spellCheck={false}
                onChange={(event) => commit(event.target.value, true)}
                onScroll={syncMarkScroll}
              />
            </div>
          </div>
        </div>
      )}

      {formatDiff && (
        <FormatDiffModal
          projectId={props.project.id}
          text={formattedDraft}
          onClose={() => setFormatDiff(false)}
          onUse={(text) => {
            setFormatDiff(false);
            setFormattedDraft(text);
            // Either version is final by the time it leaves here, so the
            // re-index must not format it a second time.
            props.onReformat(text, "formatted");
          }}
        />
      )}
    </section>
  );
}

/**
 * Which segment a click inside a paragraph belongs to.
 *
 * The handler sits on the <p> rather than on the spans, because the spans are
 * inline: the gaps between wrapped lines belong to the block, not to any span,
 * so half of a paragraph's visible area was dead to clicks. The <p> box covers
 * the lines and their leading but stops short of the margins, which is why the
 * zone does not grow above the first or below the last line.
 */
function segmentAtPoint(
  event: React.MouseEvent<HTMLParagraphElement>,
  segments: { id: string; text: string }[],
): string | null {
  const direct = (event.target as HTMLElement).closest?.("[data-seg]") as HTMLElement | null;
  if (direct?.dataset.seg) return direct.dataset.seg;
  if (segments.length === 1) return segments[0].id;

  // A multi-segment paragraph and a click that landed between lines: pick the
  // span with a line box nearest the pointer, vertically first.
  const { clientX, clientY } = event;
  let best: { id: string; dy: number; dx: number } | null = null;
  for (const span of event.currentTarget.querySelectorAll<HTMLElement>("[data-seg]")) {
    const id = span.dataset.seg;
    if (!id) continue;
    for (const rect of span.getClientRects()) {
      const dy = clientY < rect.top ? rect.top - clientY
        : clientY > rect.bottom ? clientY - rect.bottom : 0;
      const dx = clientX < rect.left ? rect.left - clientX
        : clientX > rect.right ? clientX - rect.right : 0;
      if (!best || dy < best.dy || (dy === best.dy && dx < best.dx)) {
        best = { id, dy, dx };
      }
    }
  }
  return best?.id ?? segments[0]?.id ?? null;
}

