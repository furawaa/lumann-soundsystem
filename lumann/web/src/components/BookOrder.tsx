import { useRef, useState } from "react";
import { api, type QueueProject } from "../api";
import { humanDuration } from "../format";
import { useI18n } from "../i18n";
import { bookColour } from "./GlobalQueue";
import { Button } from "./ui";

/**
 * The books with work waiting, in scheduling order, draggable.
 *
 * Shared by the all-books section and by the global scope of a project's queue
 * tab, because the order is one thing and it should be changeable wherever it
 * is shown. Dragging writes the middle term of the scheduler's sort key, which
 * decides both which book is narrated first and — when two books each have a
 * segment marked for re-recording — whose re-record goes first.
 */
export function BookOrder(props: {
  books: QueueProject[];
  activeProject: string | null;
  /** Reordering is optimistic; this reloads whatever the caller shows. */
  onChanged: () => void;
  onOpen?: (projectId: string) => void;
}) {
  const { t } = useI18n();
  const dragging = useRef<string | null>(null);
  const [over, setOver] = useState<string | null>(null);
  const [order, setOrder] = useState<string[] | null>(null);

  // While a reorder is in flight the server has not caught up yet, so the
  // optimistic order wins; any later fetch replaces it.
  const books = order
    ? order.map((id) => props.books.find((book) => book.project === id)).filter(Boolean) as QueueProject[]
    : props.books;

  async function move(targetId: string) {
    const from = dragging.current;
    dragging.current = null;
    setOver(null);
    if (!from || from === targetId) return;

    const next = books.map((book) => book.project).filter((id) => id !== from);
    next.splice(next.indexOf(targetId), 0, from);
    setOrder(next);
    await api.setQueueOrder(next);
    setOrder(null);
    props.onChanged();
  }

  return (
    <div className="books">
      {books.map((book) => {
        const colour = bookColour(book.project);
        const total = book.segments || 1;
        return (
          <div
            key={book.project}
            className={`book-card ${over === book.project ? "over" : ""} `
              + `${book.paused ? "paused" : ""} ${book.recording ? "recording" : ""}`}
            style={{ boxShadow: `inset 4px 0 0 ${colour}` }}
            onDragOver={(event) => {
              if (!dragging.current) return;
              event.preventDefault();
              setOver(book.project);
            }}
            onDrop={() => move(book.project)}
            onDragEnd={() => { dragging.current = null; setOver(null); }}
          >
            <button
              className="grip"
              title={t("queue.dragBook")}
              draggable
              onDragStart={(event) => {
                dragging.current = book.project;
                event.dataTransfer.effectAllowed = "move";
                event.dataTransfer.setData("text/plain", book.project);
              }}
            >
              ☰
            </button>

            <div
              className="book-main"
              onClick={() => props.onOpen?.(book.project)}
            >
              <div className="book-title" style={{ color: colour }}>
                {book.title}
                {book.recording && <span className="rec-dot live" />}
                {book.paused && <span className="tag paused">{t("queue.pausedTag")}</span>}
                {book.project === props.activeProject && (
                  <span className="tag mine">{t("queue.thisBook")}</span>
                )}
              </div>
              <div className="book-sub">
                {t("queue.bookProgress", {
                  done: book.done, total: book.segments, queued: book.queued,
                })}
                {book.rerecord_queued > 0 && (
                  <span className="tag rerecord">⟳ {book.rerecord_queued}</span>
                )}
                {book.eta_seconds > 0 && (
                  <> · {t("stats.left", { time: humanDuration(book.eta_seconds, t) })}</>
                )}
              </div>
              <div className="side-bar">
                <div style={{ width: `${(book.done / total) * 100}%`, background: colour }} />
              </div>
            </div>

            <div className="book-actions">
              <Button
                onClick={async () => {
                  if (book.paused) await api.recordStart(book.project, "remaining");
                  else await api.recordStop(book.project);
                  props.onChanged();
                }}
                title={book.paused ? t("queue.resumeBookTitle") : t("queue.pauseBookTitle")}
              >
                {book.paused ? t("queue.resumeBook") : t("queue.pauseBook")}
              </Button>
            </div>
          </div>
        );
      })}
    </div>
  );
}
