import { useEffect, useState } from "react";
import { api, type Sample, type Segment } from "../api";
import { useI18n } from "../i18n";
import { Button, Modal, Segmented } from "./ui";

export function NewProjectModal(props: {
  onClose: () => void;
  onCreated: (id: string) => void;
}) {
  const { t } = useI18n();
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function create() {
    setBusy(true);
    setError(null);
    try {
      const project = await api.createProject(title, text);
      props.onCreated(project.id);
      props.onClose();
    } catch (exc) {
      setError(String((exc as Error).message));
      setBusy(false);
    }
  }

  return (
    <Modal
      title={t("new.title")}
      wide
      onClose={props.onClose}
      footer={
        <>
          <span className="hint">
            {text
              ? t("new.size", {
                  chars: text.length,
                  minutes: Math.round(text.length * 0.0655 / 60),
                })
              : ""}
          </span>
          <div className="spacer" />
          <Button onClick={props.onClose}>{t("common.cancel")}</Button>
          <Button primary disabled={!text.trim() || busy} onClick={create}>
            {busy ? t("new.creating") : t("new.create")}
          </Button>
        </>
      }
    >
      {error && <div className="error">{error}</div>}
      <label className="field">
        <span>{t("new.name")}</span>
        <input value={title} onChange={(event) => setTitle(event.target.value)}
               placeholder={t("new.namePlaceholder")} />
      </label>
      <label className="field">
        <span>{t("new.text")}</span>
        <textarea
          value={text}
          onChange={(event) => setText(event.target.value)}
          placeholder={t("new.textPlaceholder")}
          rows={14}
          spellCheck={false}
          onDrop={async (event) => {
            const file = event.dataTransfer.files?.[0];
            if (file) {
              event.preventDefault();
              setText(await file.text());
              if (!title) setTitle(file.name.replace(/\.txt$/i, ""));
            }
          }}
        />
      </label>
      <p className="hint">{t("new.hint")}</p>
    </Modal>
  );
}

export function EditTextModal(props: {
  segment: Segment;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useI18n();
  const [text, setText] = useState(props.segment.text_override ?? props.segment.text);
  const hasAudio = !!props.segment.active_take;
  const changed = text !== (props.segment.text_override ?? props.segment.text);

  async function save() {
    await api.patchSegment(props.segment.id, { text_override: text });
    props.onSaved();
    props.onClose();
  }

  async function reset() {
    await api.patchSegment(props.segment.id, { clear_override: true });
    props.onSaved();
    props.onClose();
  }

  return (
    <Modal
      title={t("edit.title", { index: String(props.segment.index).padStart(4, "0") })}
      onClose={props.onClose}
      footer={
        <>
          {props.segment.text_override && (
            <Button onClick={reset}>{t("edit.reset")}</Button>
          )}
          <div className="spacer" />
          <Button onClick={props.onClose}>{t("common.cancel")}</Button>
          <Button primary disabled={!changed} onClick={save}>{t("text.save")}</Button>
        </>
      }
    >
      <textarea
        className="segment-editor"
        value={text}
        rows={8}
        spellCheck={false}
        onChange={(event) => setText(event.target.value)}
      />
      {hasAudio && changed && <p className="notice">{t("edit.notice")}</p>}
      <p className="hint">{t("edit.hint")}</p>
    </Modal>
  );
}

export function InsertModal(props: {
  projectId: string;
  afterId: string;
  samples: Sample[];
  onClose: () => void;
  onAdded: () => void;
}) {
  const { t } = useI18n();
  const [type, setType] = useState<"silence" | "sample">("silence");
  const [seconds, setSeconds] = useState("1.5");
  const [sample, setSample] = useState(props.samples[0]?.name ?? "");

  useEffect(() => {
    if (!sample && props.samples.length) setSample(props.samples[0].name);
  }, [props.samples, sample]);

  async function add() {
    await api.addInsert(props.projectId, {
      after_id: props.afterId,
      insert_type: type,
      seconds: type === "silence" ? Number(seconds) : null,
      sample: type === "sample" ? sample : null,
    });
    props.onAdded();
    props.onClose();
  }

  return (
    <Modal
      title={t("insert.title")}
      onClose={props.onClose}
      footer={
        <>
          <div className="spacer" />
          <Button onClick={props.onClose}>{t("common.cancel")}</Button>
          <Button
            primary
            disabled={type === "sample" && !sample}
            onClick={add}
          >
            {t("insert.add")}
          </Button>
        </>
      }
    >
      <Segmented
        value={type}
        onChange={setType}
        options={[
          { value: "silence", label: t("insert.typeSilence") },
          { value: "sample", label: t("insert.typeSample") },
        ]}
      />
      {type === "silence"
        ? (
          <label className="field">
            <span>{t("insert.duration")}</span>
            <input type="number" min="0" step="0.1" value={seconds}
                   onChange={(event) => setSeconds(event.target.value)} />
          </label>
        )
        : props.samples.length === 0
          ? <p className="notice">{t("insert.noSamples")}</p>
          : (
            <label className="field">
              <span>{t("insert.file")}</span>
              <select value={sample} onChange={(event) => setSample(event.target.value)}>
                {props.samples.map((item) => (
                  <option key={item.name} value={item.name}>{item.name}</option>
                ))}
              </select>
            </label>
          )}
    </Modal>
  );
}


/**
 * Drop a handful of random samples across the whole book.
 *
 * Made for atmosphere — a door, footsteps, a clock — where the point is that
 * they land unpredictably rather than where someone placed each one by hand.
 * The gap is in seconds of finished audio rather than in segments, because two
 * samples split by four one-second lines still arrive on top of each other.
 */
export function ScatterModal(props: {
  projectId: string;
  samples: Sample[];
  onClose: () => void;
  onAdded: () => void;
}) {
  const { t } = useI18n();
  const [count, setCount] = useState("5");
  const [gap, setGap] = useState("");
  const [picked, setPicked] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [placed, setPlaced] = useState<{ placed: number; asked: number } | null>(null);

  function toggle(name: string) {
    setPicked((was) =>
      was.includes(name) ? was.filter((item) => item !== name) : [...was, name]);
    setPlaced(null);
  }

  async function scatter() {
    setBusy(true);
    try {
      const result = await api.scatterInserts(props.projectId, {
        count: Number(count),
        samples: picked,
        min_gap_seconds: gap.trim() ? Number(gap) : null,
      });
      setPlaced({ placed: result.placed, asked: result.asked });
      props.onAdded();
    } finally {
      setBusy(false);
    }
  }

  const ready = picked.length > 0 && Number(count) >= 1 && !busy;

  return (
    <Modal
      title={t("scatter.title")}
      onClose={props.onClose}
      footer={
        <>
          {/* Placing fewer than asked is normal, not an error: a short book
              with a long gap simply has fewer places to put them. */}
          {placed && (
            <span className="hint">
              {placed.placed < placed.asked
                ? t("scatter.placedFewer", { n: placed.placed, asked: placed.asked })
                : t("scatter.placed", { n: placed.placed })}
            </span>
          )}
          <div className="spacer" />
          <Button onClick={props.onClose}>{t("common.close")}</Button>
          <Button primary disabled={!ready} onClick={scatter}>
            {busy ? t("scatter.working") : t("scatter.add")}
          </Button>
        </>
      }
    >
      <label className="field">
        <span>{t("scatter.count")}</span>
        <input type="number" min="1" step="1" value={count}
               onChange={(event) => { setCount(event.target.value); setPlaced(null); }} />
      </label>

      <label className="field">
        <span>{t("scatter.gap")}</span>
        <input type="number" min="0" step="1" placeholder={t("scatter.gapAny")}
               value={gap}
               onChange={(event) => { setGap(event.target.value); setPlaced(null); }} />
      </label>

      <div className="field">
        <span>{t("scatter.pool")}</span>
        {props.samples.length === 0
          ? <p className="notice">{t("insert.noSamples")}</p>
          : (
            <div className="pool">
              {props.samples.map((sample) => (
                <label key={sample.name} className="pool-item">
                  <input
                    type="checkbox"
                    checked={picked.includes(sample.name)}
                    onChange={() => toggle(sample.name)}
                  />
                  <span>{sample.name}</span>
                </label>
              ))}
            </div>
          )}
      </div>
    </Modal>
  );
}
