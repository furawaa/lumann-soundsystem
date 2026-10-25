import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { diffText, type DiffRow, type Op } from "../diff";
import { useI18n } from "../i18n";
import { Button, Modal } from "./ui";

type Jump = Exclude<Op, "same">;

/**
 * The step between editing the formatted text and committing it: here is what
 * the formatting rules would do to what you just typed, side by side, and the
 * choice of which version goes to the re-index.
 *
 * Both answers are legitimate. A hand-written pause or a spelling the rules
 * would undo is the reason the un-formatted version has to stay available —
 * running the formatter over an edit is a suggestion, not a correction.
 */
export function FormatDiffModal(props: {
  projectId: string;
  text: string;
  onUse: (text: string) => void;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const [formatted, setFormatted] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  // Where the last jump of each kind landed, so clicking a counter walks its
  // hunks one at a time instead of bouncing back to the first.
  const cursor = useRef<Record<Jump, number>>({ add: -1, del: -1, change: -1 });

  useEffect(() => {
    let live = true;
    api.formatText(props.projectId, props.text)
      .then((result) => live && setFormatted(result.text))
      .catch((exc) => live && setError(String(exc.message ?? exc)));
    return () => { live = false; };
  }, [props.projectId, props.text]);

  const diff = useMemo(
    () => (formatted === null ? null : diffText(props.text, formatted)),
    [props.text, formatted]);

  function jump(op: Jump) {
    if (!diff) return;
    const matching = diff.hunks.filter((hunk) => hunk.op === op);
    if (!matching.length) return;
    const next = (cursor.current[op] + 1) % matching.length;
    cursor.current[op] = next;
    const node = bodyRef.current?.querySelector(`[data-row="${matching[next].row}"]`);
    node?.scrollIntoView({ block: "center", behavior: "smooth" });
  }

  const identical = diff !== null && !diff.added && !diff.deleted && !diff.changed;

  return (
    <Modal
      title={t("format.title")}
      wide
      onClose={props.onClose}
      footer={
        <>
          <span className="hint">
            {identical ? t("format.noChanges") : t("format.pick")}
          </span>
          <div className="spacer" />
          <Button onClick={props.onClose}>{t("common.cancel")}</Button>
          <Button onClick={() => props.onUse(props.text)}>{t("format.keepMine")}</Button>
          <Button
            primary
            disabled={formatted === null}
            onClick={() => props.onUse(formatted ?? props.text)}
          >
            {t("format.useFormatted")}
          </Button>
        </>
      }
    >
      {error && <div className="error">{error}</div>}
      {!diff && !error && <div className="hint">{t("format.computing")}</div>}

      {diff && (
        <>
          <div className="counts">
            <button className="count change" onClick={() => jump("change")}>
              <span className="count-value">{diff.changed}</span>
              <span className="count-label">{t("format.changedLines")}</span>
            </button>
            <button className="count add" onClick={() => jump("add")}>
              <span className="count-value">{diff.added}</span>
              <span className="count-label">{t("format.addedLines")}</span>
            </button>
            <button className="count del" onClick={() => jump("del")}>
              <span className="count-value">{diff.deleted}</span>
              <span className="count-label">{t("format.deletedLines")}</span>
            </button>
          </div>

          <div className="diff-head">
            <span>{t("format.yours")}</span>
            <span>{t("format.formatted")}</span>
          </div>

          <div className="diff" ref={bodyRef}>
            {collapse(diff.rows).map((item) =>
              item.kind === "gap"
                ? (
                  <div key={`gap-${item.at}`} className="diff-gap">
                    {t("format.unchangedLines", { n: item.count })}
                  </div>
                )
                : <DiffLine key={item.at} row={diff.rows[item.at]} index={item.at} />)}
          </div>
        </>
      )}
    </Modal>
  );
}

type Item = { kind: "row"; at: number } | { kind: "gap"; at: number; count: number };

/** Keep CONTEXT lines around every change and fold the rest away.
 *
 *  Without this a whole-book diff is ten thousand rows of DOM, nearly all of
 *  them identical on both sides, and the changes are lost in it. */
function collapse(rows: DiffRow[], context = 2): Item[] {
  const keep = new Set<number>();
  rows.forEach((row, index) => {
    if (row.op === "same") return;
    for (let k = index - context; k <= index + context; k++) {
      if (k >= 0 && k < rows.length) keep.add(k);
    }
  });

  const items: Item[] = [];
  let gap = 0;
  rows.forEach((_row, index) => {
    if (keep.has(index)) {
      if (gap) {
        items.push({ kind: "gap", at: index - gap, count: gap });
        gap = 0;
      }
      items.push({ kind: "row", at: index });
    } else {
      gap++;
    }
  });
  if (gap) items.push({ kind: "gap", at: rows.length - gap, count: gap });
  return items;
}

function DiffLine({ row, index }: { row: DiffRow; index: number }) {
  return (
    <div className={`diff-row ${row.op}`} data-row={index}>
      <span className="diff-no">{row.leftNo ?? ""}</span>
      <span className={`diff-cell left ${row.left === null ? "empty" : ""}`}>
        {row.leftParts
          ? row.leftParts.map((part, i) =>
              part.changed
                ? <mark key={i} className="del">{part.text}</mark>
                : <span key={i}>{part.text}</span>)
          : row.left}
      </span>
      <span className="diff-no">{row.rightNo ?? ""}</span>
      <span className={`diff-cell right ${row.right === null ? "empty" : ""}`}>
        {row.rightParts
          ? row.rightParts.map((part, i) =>
              part.changed
                ? <mark key={i} className="add">{part.text}</mark>
                : <span key={i}>{part.text}</span>)
          : row.right}
      </span>
    </div>
  );
}
