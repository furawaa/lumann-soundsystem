import { useEffect, useState } from "react";
import { api, type Estimate, type GlobalQueueRow, type QueueProject, type QueueRow } from "../api";
import { humanDuration } from "../format";
import { useI18n } from "../i18n";
import { BookOrder } from "./BookOrder";
import { GlobalQueueList } from "./GlobalQueue";
import { Button, Empty, Segmented } from "./ui";

type Scope = "project" | "global";

/**
 * Queue rows show the text, not just the index — when 400 chunks are waiting,
 * "0187" tells you nothing about what is about to be spoken.
 *
 * Two groups, because they are different work: re-recording something already
 * voiced runs first, in the order the segments appear in the book rather than
 * the order they were clicked. The heading is absent when the group is empty.
 *
 * The second scope shows the queue of every book at once. That view exists
 * because the per-book queue quietly lies about when work will happen: one
 * worker serves all books, so a second book waits for the first, and a
 * re-record anywhere overtakes first-pass work everywhere. Only the global
 * list has the true order, so it is not grouped — the order is the point.
 */
export function QueuePanel(props: {
  rows: QueueRow[];
  estimate: Estimate | null;
  projectId: string;
  onSelect: (id: string) => void;
  onOpenProject: (projectId: string, segmentId: string) => void;
  onChanged: () => void;
}) {
  const { t } = useI18n();
  const [scope, setScope] = useState<Scope>("project");
  const [global, setGlobal] = useState<GlobalQueueRow[] | null>(null);
  const [books, setBooks] = useState<QueueProject[]>([]);
  const [reloads, setReloads] = useState(0);

  // props.rows changes whenever the server told us something moved, which is
  // the same moment the global list goes stale.
  useEffect(() => {
    if (scope !== "global") return;
    let live = true;
    Promise.all([api.globalQueue(), api.queueProjects()]).then(([queue, summary]) => {
      if (!live) return;
      setGlobal(queue.queue);
      setBooks(summary.projects);
    });
    return () => { live = false; };
  }, [scope, props.rows, reloads]);

  const empty = scope === "project" ? props.rows.length === 0 : global?.length === 0;

  const head = (
    <div className="queue-head">
      <Segmented
        value={scope}
        onChange={setScope}
        options={[
          { value: "project" as Scope, label: t("queue.scopeProject") },
          { value: "global" as Scope, label: t("queue.scopeGlobal") },
        ]}
      />
      <span>
        {scope === "project"
          ? (
            <>
              {t("queue.count", { n: props.rows.length })}
              {props.estimate && props.estimate.eta_seconds > 0 && (
                <> · {t("stats.left", { time: humanDuration(props.estimate.eta_seconds, t) })}</>
              )}
              {props.estimate && !props.estimate.measured && (
                <span className="hint">{t("queue.fallbackRate")}</span>
              )}
            </>
          )
          : global && t("queue.countBooks", { n: global.length, books: booksIn(global) })}
      </span>
      <div className="spacer" />
      {scope === "project" && (
        <Button
          onClick={() => api.recordClear(props.projectId).then(props.onChanged)}
          title={t("queue.clearTitle")}
        >
          {t("queue.clear")}
        </Button>
      )}
    </div>
  );

  if (empty) {
    return (
      <div className="queue">
        {head}
        <Empty
          title={t(scope === "project" ? "queue.empty" : "queue.emptyGlobal")}
          hint={t("queue.emptyHint")}
        />
      </div>
    );
  }

  if (scope === "global") {
    return (
      <div className="queue">
        {head}
        {/* The book order is editable here too: it is the same order, and
            having to leave the book to change it made no sense. */}
        <BookOrder
          books={books}
          activeProject={props.projectId}
          onChanged={() => { setReloads((n) => n + 1); props.onChanged(); }}
          onOpen={(pid) => props.onOpenProject(pid, "")}
        />
        <div className="group-head">{t("queue.theOrder")}</div>
        <GlobalQueueList
          rows={global ?? []}
          mine={props.projectId}
          onOpen={props.onOpenProject}
        />
      </div>
    );
  }

  const rerecord = props.rows.filter((row) => row.rerecord);
  const firstPass = props.rows.filter((row) => !row.rerecord);

  return (
    <div className="queue">
      {head}

      {rerecord.length > 0 && firstPass.length > 0 && (
        <div className="group-head">{t("queue.rerecordGroup")}</div>
      )}
      {rerecord.map((row) => <QueueRowView key={row.id} row={row} {...props} />)}

      {rerecord.length > 0 && firstPass.length > 0 && (
        <div className="group-head">{t("queue.firstPassGroup")}</div>
      )}
      {firstPass.map((row) => <QueueRowView key={row.id} row={row} {...props} />)}
    </div>
  );
}

function QueueRowView(props: {
  row: QueueRow;
  onSelect: (id: string) => void;
  onChanged: () => void;
}) {
  const { t } = useI18n();
  const row = props.row;
  return (
    <div
      className={`row queue-row ${row.status}`}
      onClick={() => props.onSelect(row.id)}
    >
      <span className="idx">{String(row.index).padStart(4, "0")}</span>
      <span className="track-text">{row.text}</span>
      <span className="track-meta">
        {row.favorite && <span className="icon fav on">♥</span>}
        {row.rerecord && <span className="tag rerecord">⟳</span>}
        {row.status === "recording" && (
          <span className="tag recording">{t("track.recording")}</span>
        )}
        <span className="chars">{row.chars}</span>
      </span>
      <button
        className="icon"
        title={t("queue.remove")}
        disabled={row.status === "recording"}
        onClick={(event) => {
          event.stopPropagation();
          api.dequeue(row.id).then(props.onChanged);
        }}
      >
        ✕
      </button>
    </div>
  );
}

function booksIn(rows: GlobalQueueRow[]): number {
  return new Set(rows.map((row) => row.project)).size;
}
