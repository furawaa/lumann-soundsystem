import type { GlobalQueueRow } from "../api";
import { useI18n } from "../i18n";

/**
 * The queue of every book as one list — shared by the queue tab of a project
 * and by the all-books section, because it is the same thing seen from two
 * places and the order in it is the actual recording order.
 */
export function GlobalQueueList(props: {
  rows: GlobalQueueRow[];
  /** Which book the reader is looking at, marked so it can be found. */
  mine?: string | null;
  onOpen: (projectId: string, segmentId: string) => void;
}) {
  return (
    <>
      {props.rows.map((row, at) => (
        <GlobalQueueRowView
          key={`${row.project}-${row.id}`}
          row={row}
          first={at === 0 || props.rows[at - 1].project !== row.project}
          mine={row.project === props.mine}
          onOpen={() => props.onOpen(row.project, row.id)}
        />
      ))}
    </>
  );
}

/**
 * A row of somebody else's book, or of this one.
 *
 * The colour is the book's identity, derived from its id so it survives
 * refetching and does not shuffle when a book ahead finishes. The title is
 * printed only on the first row of each run, the way a date is printed once
 * over a day's worth of messages.
 */
function GlobalQueueRowView(props: {
  row: GlobalQueueRow;
  first: boolean;
  mine: boolean;
  onOpen: () => void;
}) {
  const { t } = useI18n();
  const row = props.row;
  const colour = bookColour(row.project);
  return (
    <div
      className={`row queue-row global ${row.status} ${row.paused ? "paused" : ""}`}
      style={{ boxShadow: `inset 3px 0 0 ${colour}` }}
      onClick={props.onOpen}
      title={t("queue.openBook", { title: row.project_title })}
    >
      <span className="book" style={{ color: colour }}>
        {props.first ? row.project_title : "·"}
      </span>
      <span className="idx">{String(row.index).padStart(4, "0")}</span>
      <span className="track-text">{row.text}</span>
      <span className="track-meta">
        {props.mine && <span className="tag mine">{t("queue.thisBook")}</span>}
        {row.paused && <span className="tag paused">{t("queue.pausedTag")}</span>}
        {row.rerecord && <span className="tag rerecord">⟳</span>}
        {row.status === "recording" && (
          <span className="tag recording">{t("track.recording")}</span>
        )}
        <span className="chars">{row.chars}</span>
      </span>
    </div>
  );
}

/** Distinct, and the same colour for the same book every time. */
const BOOK_COLOURS = [
  "#007AFF", "#4CD964", "#FF9500", "#FF2D55", "#5856D6", "#34AADC", "#8E8E93",
];

export function bookColour(projectId: string): string {
  let hash = 0;
  for (const char of projectId) hash = (hash * 31 + char.codePointAt(0)!) >>> 0;
  return BOOK_COLOURS[hash % BOOK_COLOURS.length];
}
