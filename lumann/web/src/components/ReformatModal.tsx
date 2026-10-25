import { useEffect, useState } from "react";
import { api, type Preview, type PreviewRow } from "../api";
import { useI18n, type Key } from "../i18n";
import { Button, Modal } from "./ui";

type Filter = "all" | "changed" | "new" | "deleted" | "moved";

const LABEL: Record<PreviewRow["kind"], Key> = {
  unchanged: "reformat.kindUnchanged",
  moved: "reformat.kindMoved",
  changed: "reformat.kindChanged",
  new: "reformat.kindNew",
  deleted: "reformat.kindDeleted",
};

/**
 * Mandatory before any re-index is written. Editing text after two hours of
 * narration is exactly where a silent mistake costs the most, so the counts and
 * the per-segment list are shown before anything is committed.
 */
export function ReformatModal(props: {
  projectId: string;
  text: string | null;
  fromFormatted?: boolean;
  onClose: () => void;
  onApplied: () => void;
}) {
  const { t } = useI18n();
  const [preview, setPreview] = useState<Preview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    api.preview(props.projectId, props.text, !!props.fromFormatted)
      .then((result) => live && setPreview(result))
      .catch((exc) => live && setError(String(exc.message ?? exc)));
    return () => { live = false; };
  }, [props.projectId, props.text, props.fromFormatted]);

  async function apply() {
    setBusy(true);
    try {
      await api.applyReformat(props.projectId);
      props.onApplied();
      props.onClose();
    } catch (exc) {
      setError(String((exc as Error).message));
      setBusy(false);
    }
  }

  const counts = preview?.counts ?? {};
  const rows = (preview?.segments ?? []).filter((row) => {
    if (filter === "all") return true;
    return row.kind === filter;
  });
  const needsReview = (preview?.inserts ?? []).filter((note) => note.review);

  return (
    <Modal
      title={t("reformat.title")}
      wide
      onClose={props.onClose}
      footer={
        <>
          <span className="hint">
            {counts.changed_with_audio
              ? t("reformat.willRerecord", { n: counts.changed_with_audio })
              : t("reformat.noHarm")}
          </span>
          <div className="spacer" />
          <Button onClick={props.onClose}>{t("common.cancel")}</Button>
          <Button primary disabled={!preview || busy} onClick={apply}>
            {busy ? t("reformat.applying") : t("reformat.apply")}
          </Button>
        </>
      }
    >
      {error && <div className="error">{error}</div>}
      {props.fromFormatted && <p className="notice">{t("reformat.fromFormatted")}</p>}
      {!preview && !error && <div className="hint">{t("reformat.computing")}</div>}

      {preview && (
        <>
          <div className="counts">
            <Count label={t("reformat.unchanged")} value={counts.unchanged ?? 0}
                   onClick={() => setFilter("all")} />
            <Count label={t("reformat.moved")} value={counts.moved ?? 0} tone="moved"
                   onClick={() => setFilter("moved")} />
            <Count label={t("reformat.changed")} value={counts.changed ?? 0} tone="stale"
                   onClick={() => setFilter("changed")} />
            <Count label={t("reformat.new")} value={counts.new ?? 0}
                   onClick={() => setFilter("new")} />
            <Count label={t("reformat.deleted")} value={counts.deleted ?? 0} tone="danger"
                   onClick={() => setFilter("deleted")} />
          </div>

          {(counts.deleted_with_audio ?? 0) > 0 && (
            <p className="notice">
              {t("reformat.deletedWithAudio", { n: counts.deleted_with_audio })}
              <code>audio/_trash/</code>
            </p>
          )}
          {(counts.override_conflict ?? 0) > 0 && (
            <p className="notice">
              {t("reformat.overrideConflict", { n: counts.override_conflict })}
            </p>
          )}
          {needsReview.length > 0 && (
            <p className="notice">
              {t("reformat.insertReview", { n: needsReview.length })}
            </p>
          )}

          <div className="preview-list">
            {rows.map((row) => (
              <div key={`${row.kind}-${row.id}`} className={`row preview ${row.kind}`}>
                <span className="idx">
                  {row.new_index != null ? String(row.new_index + 1).padStart(4, "0") : "—"}
                </span>
                <span className={`tag ${row.kind}`}>{t(LABEL[row.kind])}</span>
                <span className="track-text">{row.text}</span>
                <span className="track-meta">
                  {row.favorite && <span className="icon fav on">♥</span>}
                  {row.takes > 0 && (
                    <span className="takes-count">{t("track.takes", { n: row.takes })}</span>
                  )}
                  {row.override_conflict && (
                    <span className="tag override">{t("track.overrideTag")}</span>
                  )}
                </span>
              </div>
            ))}
            {rows.length === 0 && (
              <div className="hint">{t("reformat.emptyFilter")}</div>
            )}
          </div>
        </>
      )}
    </Modal>
  );
}

function Count(props: { label: string; value: number; tone?: string; onClick: () => void }) {
  return (
    <button className={`count ${props.tone ?? ""}`} onClick={props.onClick}>
      <span className="count-value">{props.value}</span>
      <span className="count-label">{props.label}</span>
    </button>
  );
}
