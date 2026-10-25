import { useCallback, useEffect, useState } from "react";
import { api, type GlobalQueueRow, type QueueProject } from "../api";
import { useI18n } from "../i18n";
import { BookOrder } from "./BookOrder";
import { GlobalQueueList } from "./GlobalQueue";
import { Button, Empty } from "./ui";

/**
 * Every book that has work waiting, and the one list they are actually
 * recorded from.
 *
 * The books at the top are the scheduling order and can be dragged. That order
 * is the middle term of the sort key, so it answers the question a queue of
 * several books raises and a single book never does: two books each have a
 * segment marked for re-recording — whose goes first? The one standing higher
 * here. Re-records still overtake all first-pass work regardless, in every
 * book: that is the segment somebody is sitting and waiting to hear.
 */
export function QueueOverview(props: {
  activeProject: string | null;
  onOpen: (projectId: string, segmentId: string) => void;
  onChanged: () => void;
}) {
  const { t } = useI18n();
  const [books, setBooks] = useState<QueueProject[] | null>(null);
  const [rows, setRows] = useState<GlobalQueueRow[]>([]);

  const load = useCallback(async () => {
    const [summary, queue] = await Promise.all([api.queueProjects(), api.globalQueue()]);
    setBooks(summary.projects);
    setRows(queue.queue);
  }, []);

  // No events for "the queue changed globally", and this view is open only
  // while somebody is watching it — a poll is the honest tool here.
  useEffect(() => {
    load();
    const timer = window.setInterval(load, 2000);
    return () => window.clearInterval(timer);
  }, [load]);

  if (books && books.length === 0) {
    return <Empty title={t("queue.emptyGlobal")} hint={t("queue.overviewHint")} />;
  }

  return (
    <div className="queue overview">
      <div className="queue-head">
        <span className="panel-title">{t("queue.overviewTitle")}</span>
        <div className="spacer" />
        <Button
          danger
          onClick={() => api.stopAll().then(() => { load(); props.onChanged(); })}
          title={t("queue.stopAllTitle")}
        >
          {t("queue.stopAll")}
        </Button>
      </div>

      <p className="notice ro">{t("queue.rule")}</p>

      <BookOrder
        books={books ?? []}
        activeProject={props.activeProject}
        onChanged={() => { load(); props.onChanged(); }}
        onOpen={(pid) => props.onOpen(pid, "")}
      />

      <div className="group-head">{t("queue.theOrder")}</div>
      <GlobalQueueList rows={rows} mine={props.activeProject} onOpen={props.onOpen} />
    </div>
  );
}
