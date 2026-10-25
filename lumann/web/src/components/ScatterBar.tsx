import { api, isSegment, type Item } from "../api";
import { useI18n } from "../i18n";
import { Button } from "./ui";

/**
 * What the last scatter did, and the two ways out of it.
 *
 * Dropping forty samples into a book at random is only usable if the result can
 * be looked at and taken back, so the bar appears by itself above the tracks
 * whenever a scattered batch exists — including after a reload, since the batch
 * is stored on the inserts rather than remembered by the page.
 *
 * Filtering shows each scattered sample with the segment it follows: the
 * question being asked is "does it belong here", and a lone ◆ row cannot answer
 * it.
 */
export function ScatterBar(props: {
  projectId: string;
  items: Item[];
  filtered: boolean;
  onFilter: (on: boolean) => void;
  onChanged: () => void;
}) {
  const { t } = useI18n();
  const batch = lastBatch(props.items);
  if (!batch) return null;

  const count = props.items.filter(
    (item) => !isSegment(item) && item.batch === batch).length;

  return (
    <div className="scatter-bar">
      <span>{t("scatter.lastBatch", { n: count })}</span>
      <div className="spacer" />
      <Button
        className={props.filtered ? "on" : ""}
        onClick={() => props.onFilter(!props.filtered)}
        title={t("scatter.showOnlyTitle")}
      >
        {props.filtered ? t("scatter.showAll") : t("scatter.showOnly")}
      </Button>
      <Button
        danger
        onClick={async () => {
          await api.deleteInsertBatch(props.projectId, batch);
          props.onFilter(false);
          props.onChanged();
        }}
        title={t("scatter.undoTitle")}
      >
        {t("scatter.undo")}
      </Button>
    </div>
  );
}

/** The newest scattered batch in this book, or null if there is none. */
export function lastBatch(items: Item[]): string | null {
  let best: { batch: string; at: string } | null = null;
  for (const item of items) {
    if (isSegment(item) || !item.batch) continue;
    const at = item.created_at ?? "";
    if (!best || at > best.at) best = { batch: item.batch, at };
  }
  return best?.batch ?? null;
}

/** The scattered inserts of `batch`, each preceded by the segment it follows. */
export function withContext(items: Item[], batch: string): Item[] {
  const out: Item[] = [];
  items.forEach((item, at) => {
    if (isSegment(item) || item.batch !== batch) return;
    for (let back = at - 1; back >= 0; back--) {
      if (isSegment(items[back])) {
        out.push(items[back]);
        break;
      }
    }
    out.push(item);
  });
  return out;
}
