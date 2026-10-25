import { useEffect, useRef, useState } from "react";
import {
  api, voiceAudioUrl, type ClipUpload, type EspeakSettings, type Engines, type QwenStatus,
  type Voice,
} from "../api";
import { bytes, clock } from "../format";
import { useI18n } from "../i18n";
import { Button, Modal } from "./ui";

const ESPEAK_REPO = "https://github.com/espeak-ng/espeak-ng";

/**
 * The voice library. A voice is one of two kinds.
 *
 * eSpeak voices are a handful of settings — language, variant, speed, pitch —
 * edited in place, with a preview that re-renders when they change. They work
 * out of the box and the built-in voices are of this kind.
 *
 * Cloned voices (Qwen3-TTS) are one or more reference clips, each with the
 * words spoken in it, and the transcript is not optional: cloning matches text
 * against audio, so a wrong or empty one degrades every take without ever
 * failing loudly. Hence a transcript field per file, even when several are
 * picked at once.
 *
 * The model takes one reference per generation, so a multi-clip voice still
 * names one thing to use — a clip, or all of them joined into a longer
 * reference. That choice is the radio column.
 *
 * Preview uses plain <audio controls> rather than the app player: this is a
 * settings dialog, and a reference clip is not a track on the timeline.
 */
export function VoicesModal(props: {
  voices: Voice[];
  current: string | null;
  onPick: (id: string) => void;
  onChanged: () => void;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const [addingTo, setAddingTo] = useState<string | "new" | "espeak" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [engines, setEngines] = useState<Engines | null>(null);

  const loadEngines = () => api.engines().then(setEngines).catch(() => {});
  useEffect(() => { loadEngines(); }, []);

  // While Qwen installs, follow its progress. The install runs on the server,
  // so closing this dialog does not stop it; reopening picks it up again.
  const installing = !!engines?.qwen.step;
  useEffect(() => {
    if (!installing) return;
    const timer = window.setInterval(loadEngines, 1000);
    return () => window.clearInterval(timer);
  }, [installing]);

  async function guard(action: () => Promise<unknown>) {
    setError(null);
    try {
      await action();
      props.onChanged();
    } catch (exc) {
      setError(String((exc as Error).message));
    }
  }

  return (
    <Modal
      title={t("voices.title")}
      wide
      onClose={props.onClose}
      footer={
        <>
          <span className="hint">{t("voices.hint")}</span>
          <div className="spacer" />
          <Button onClick={props.onClose}>{t("common.close")}</Button>
        </>
      }
    >
      {error && <div className="error">{error}</div>}
      {engines && !engines.espeak.available && (
        <div className="error">
          {t("voices.espeakMissing")}{" "}
          <a href={ESPEAK_REPO} target="_blank" rel="noreferrer">{ESPEAK_REPO}</a>
        </div>
      )}

      <div className="voice-list">
        {props.voices.map((voice) => voice.engine === "espeak"
          ? (
            <EspeakCard
              key={voice.id}
              voice={voice}
              engines={engines}
              picked={props.current === voice.id}
              onPick={() => props.onPick(voice.id)}
              guard={guard}
            />
          )
          : (
            <VoiceCard
              key={voice.id}
              voice={voice}
              picked={props.current === voice.id}
              adding={addingTo === voice.id}
              onPick={() => props.onPick(voice.id)}
              onAdding={(on) => setAddingTo(on ? voice.id : null)}
              onChanged={props.onChanged}
              onError={setError}
              guard={guard}
            />
          ))}
      </div>

      {addingTo === "espeak" && (
        <EspeakForm
          engines={engines}
          onCancel={() => setAddingTo(null)}
          onSubmit={async (name, settings) => {
            const voice = await api.addEspeakVoice({ name, ...settings });
            setAddingTo(null);
            props.onChanged();
            props.onPick(voice.id);
          }}
          onError={setError}
        />
      )}
      {addingTo === "new" && (
        <>
          {engines && !engines.qwen.available && (
            <p className="hint warn">{t("voices.qwenMissing")}</p>
          )}
          <ClipForm
            withName
            onCancel={() => setAddingTo(null)}
            onSubmit={async (name, entries) => {
              const voice = await api.addVoice(name, entries);
              setAddingTo(null);
              props.onChanged();
              props.onPick(voice.id);
            }}
            onError={setError}
          />
        </>
      )}
      {addingTo !== "new" && addingTo !== "espeak" && (
        <div className="voice-add">
          <Button onClick={() => setAddingTo("espeak")}>{t("voices.addEspeak")}</Button>
          <Button onClick={() => setAddingTo("new")}>{t("voices.addClone")}</Button>
        </div>
      )}

      {engines && (
        <QwenPanel
          status={engines.qwen}
          onStatus={(qwen) => setEngines({ ...engines, qwen })}
          onError={setError}
        />
      )}
    </Modal>
  );
}

function VoiceCard(props: {
  voice: Voice;
  picked: boolean;
  adding: boolean;
  onPick: () => void;
  onAdding: (on: boolean) => void;
  onChanged: () => void;
  onError: (message: string | null) => void;
  guard: (action: () => Promise<unknown>) => Promise<void>;
}) {
  const { t } = useI18n();
  const voice = props.voice;
  const joinedLength = voice.clips.reduce((total, clip) => total + clip.duration, 0);

  return (
    <div className={`voice-card ${props.picked ? "picked" : ""}`}>
      <VoiceHead
        voice={voice}
        picked={props.picked}
        detail={t("voices.clipCount", { n: voice.clips.length })}
        onPick={props.onPick}
        guard={props.guard}
      />

      {voice.clips.map((clip) => (
        <div key={clip.index} className="clip-row">
          <label className="clip-use" title={t("voices.useClip")}>
            <input
              type="radio"
              name={`active-${voice.id}`}
              checked={voice.active === clip.index}
              onChange={() => props.guard(() => api.patchVoice(voice.id, { active: clip.index }))}
            />
          </label>
          <span className="clip-name">
            {clip.audio}
            <span className="clip-dur">
              {clip.missing ? t("voices.missing") : clock(clip.duration)}
            </span>
          </span>
          <textarea
            className="clip-text"
            rows={2}
            defaultValue={clip.ref_text}
            onBlur={(event) => {
              const next = event.target.value.trim();
              if (!next || next === clip.ref_text) return;
              props.guard(() =>
                api.patchVoice(voice.id, { clip: clip.index, ref_text: next }));
            }}
          />
          <audio
            className="voice-audio"
            controls
            preload="none"
            src={voiceAudioUrl(voice.id, clip.index)}
          />
          <button
            className="icon"
            disabled={voice.clips.length === 1}
            title={voice.clips.length === 1 ? t("voices.lastClip") : t("voices.deleteClip")}
            onClick={() => props.guard(() => api.deleteClip(voice.id, clip.index))}
          >
            ✕
          </button>
        </div>
      ))}

      {voice.clips.length > 1 && (
        <div className="clip-row joined">
          <label className="clip-use" title={t("voices.useJoined")}>
            <input
              type="radio"
              name={`active-${voice.id}`}
              checked={voice.active === "all"}
              onChange={() => props.guard(() => api.patchVoice(voice.id, { active: "all" }))}
            />
          </label>
          <span className="clip-name">
            {t("voices.joined")}
            <span className="clip-dur">{clock(joinedLength)}</span>
          </span>
          <span className="clip-text hint">{t("voices.joinedHint")}</span>
          <audio
            className="voice-audio"
            controls
            preload="none"
            src={voiceAudioUrl(voice.id, -1)}
          />
          <span className="icon" />
        </div>
      )}

      {props.adding
        ? (
          <ClipForm
            onCancel={() => props.onAdding(false)}
            onSubmit={async (_name, entries) => {
              await api.addClips(voice.id, entries);
              props.onAdding(false);
              props.onChanged();
            }}
            onError={props.onError}
          />
        )
        : (
          <button className="link small clip-add" onClick={() => props.onAdding(true)}>
            {t("voices.addClips")}
          </button>
        )}
    </div>
  );
}

function VoiceHead(props: {
  voice: Voice;
  picked: boolean;
  detail: string;
  onPick: () => void;
  guard: (action: () => Promise<unknown>) => Promise<void>;
}) {
  const { t } = useI18n();
  const voice = props.voice;
  const [renaming, setRenaming] = useState(false);

  if (renaming) {
    return (
      <div className="voice-head">
        <span className="voice-mark">{props.picked ? "✓" : ""}</span>
        <RenameField
          voice={voice}
          onDone={async (name) => {
            setRenaming(false);
            if (name !== null) await props.guard(() => api.patchVoice(voice.id, { name }));
          }}
        />
      </div>
    );
  }

  return (
    <div className="voice-head">
      <button
        className="voice-pick"
        onClick={props.onPick}
        disabled={voice.missing}
        title={voice.missing
          ? t(voice.engine === "espeak" ? "voices.espeakNotFound" : "voices.missing")
          : t("voices.use")}
      >
        <span className="voice-mark">{props.picked ? "✓" : ""}</span>
        <span className="voice-name">{voice.name}</span>
        <span className="tag">
          {t(voice.engine === "espeak" ? "voices.engineEspeak" : "voices.engineQwen")}
        </span>
        <span className="voice-count">{props.detail}</span>
      </button>
      <button className="icon" title={t("voices.rename")} onClick={() => setRenaming(true)}>
        ✎
      </button>
      <button
        className="icon"
        disabled={voice.builtin}
        title={voice.builtin ? t("voices.builtinKept") : t("voices.delete")}
        onClick={() => {
          if (!window.confirm(t("voices.deleteConfirm", { name: voice.name }))) return;
          props.guard(() => api.deleteVoice(voice.id));
        }}
      >
        ✕
      </button>
    </div>
  );
}

/**
 * Rename in place. Enter or leaving the field saves, Escape cancels. An empty
 * name is allowed on purpose: it gives naming back to the voice, which for an
 * eSpeak voice means a name made from its settings.
 */
function RenameField(props: { voice: Voice; onDone: (name: string | null) => void }) {
  const { t } = useI18n();
  const [draft, setDraft] = useState(props.voice.custom_name ? props.voice.name : "");
  // Enter saves and unmounts the field, which can blur it a second time.
  const settled = useRef(false);

  function finish(name: string | null) {
    if (settled.current) return;
    settled.current = true;
    const original = props.voice.custom_name ? props.voice.name : "";
    props.onDone(name === null || name.trim() === original ? null : name.trim());
  }

  return (
    <input
      className="voice-rename"
      autoFocus
      value={draft}
      placeholder={props.voice.custom_name ? t("voices.renameAuto") : props.voice.name}
      title={t("voices.renameHint")}
      onChange={(event) => setDraft(event.target.value)}
      onBlur={() => finish(draft)}
      onKeyDown={(event) => {
        if (event.key === "Enter") finish(draft);
        if (event.key === "Escape") finish(null);
      }}
    />
  );
}

/**
 * Qwen3-TTS lives outside the app until the user asks for it: nothing is
 * downloaded until Download is pressed, and Delete takes all of it away again
 * — packages and model, one folder.
 */
function QwenPanel(props: {
  status: QwenStatus;
  onStatus: (status: QwenStatus) => void;
  onError: (message: string | null) => void;
}) {
  const { t } = useI18n();
  const status = props.status;
  const busy = status.step !== null;
  // Something of ours is, or is about to be, on disk. Delete stays available
  // mid-download too: it cancels first.
  const deletable = busy || status.disk_bytes > 0 || status.packages_managed
    || (status.model && !status.model_external);

  async function run(action: () => Promise<QwenStatus>) {
    props.onError(null);
    try {
      props.onStatus(await action());
    } catch (exc) {
      props.onError(String((exc as Error).message));
    }
  }

  let line: string;
  if (status.step === "model") {
    line = t("qwen.downloading", {
      done: bytes(status.downloaded, t), total: bytes(status.total, t),
    });
  } else if (busy) {
    line = t("qwen.installingPackages");
  } else if (status.available) {
    line = status.disk_bytes > 0
      ? t("qwen.installed", { size: bytes(status.disk_bytes, t) })
      : t("qwen.installedOutside");
  } else if (status.disk_bytes > 0) {
    line = t("qwen.partial");
  } else if (status.packages) {
    line = t("qwen.needsModel");
  } else {
    line = t("qwen.notInstalled");
  }

  const fraction = status.step === "model" && status.total > 0
    ? status.downloaded / status.total : null;

  return (
    <div className="qwen-panel">
      <div className="qwen-head">
        <span className="voice-name">{t("qwen.title")}</span>
        <span className={`tag ${status.available ? "qwen-ok" : ""}`}>
          {t(status.available ? "qwen.tagReady" : busy ? "qwen.tagBusy" : "qwen.tagOff")}
        </span>
        <div className="spacer" />
        {busy && <Button onClick={() => run(api.cancelQwen)}>{t("common.cancel")}</Button>}
        {!busy && !status.available && (
          <Button primary onClick={() => run(api.installQwen)}>
            {t(status.disk_bytes > 0 ? "qwen.resume" : "qwen.download")}
          </Button>
        )}
        {deletable && (
          <Button
            danger
            onClick={() => {
              if (!window.confirm(t("qwen.deleteConfirm"))) return;
              run(api.deleteQwen);
            }}
          >
            {t("qwen.delete")}
          </Button>
        )}
      </div>
      <p className="hint">{line}</p>
      {busy && (
        <div className={`progress ${fraction === null ? "indeterminate" : ""}`}>
          <div className="fill" style={fraction === null ? undefined : { width: `${fraction * 100}%` }} />
        </div>
      )}
      {status.error && <div className="error">{status.error}</div>}
      {!busy && !status.available && !status.packages && status.disk_bytes === 0 && (
        <p className="hint">{t("qwen.what")}</p>
      )}
      {status.available && !status.packages_managed && (
        <p className="hint">{t("qwen.outsideNote")}</p>
      )}
    </div>
  );
}

/**
 * An eSpeak voice: its settings, saved as soon as they change, and a preview.
 * The preview URL carries the settings so the browser fetches a fresh sample
 * after each change instead of replaying the cached one.
 */
function EspeakCard(props: {
  voice: Voice;
  engines: Engines | null;
  picked: boolean;
  onPick: () => void;
  guard: (action: () => Promise<unknown>) => Promise<void>;
}) {
  const voice = props.voice;
  const settings = voice.espeak!;
  const version = [settings.voice, settings.variant, settings.speed, settings.pitch].join("-");

  return (
    <div className={`voice-card ${props.picked ? "picked" : ""}`}>
      <VoiceHead
        voice={voice}
        picked={props.picked}
        // The automatic name already says this; a chosen one may not.
        detail={!voice.custom_name ? ""
          : settings.variant ? `${settings.voice}+${settings.variant}` : settings.voice}
        onPick={props.onPick}
        guard={props.guard}
      />
      <div className="espeak-row">
        <EspeakFields
          value={settings}
          engines={props.engines}
          onChange={(patch) => props.guard(() => api.patchVoice(voice.id, { espeak: patch }))}
        />
        {!voice.missing && (
          <audio
            key={version}
            className="voice-audio"
            controls
            preload="none"
            src={`${voiceAudioUrl(voice.id)}&v=${encodeURIComponent(version)}`}
          />
        )}
      </div>
    </div>
  );
}

function EspeakForm(props: {
  engines: Engines | null;
  onCancel: () => void;
  onSubmit: (name: string, settings: EspeakSettings) => Promise<void>;
  onError: (message: string | null) => void;
}) {
  const { t } = useI18n();
  const [name, setName] = useState("");
  const [settings, setSettings] = useState<EspeakSettings>({
    voice: "en-us", variant: "m3", speed: 160, pitch: 50,
  });
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true);
    props.onError(null);
    try {
      await props.onSubmit(name, settings);
    } catch (exc) {
      props.onError(String((exc as Error).message));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="voice-form">
      <label>
        {t("voices.name")}
        <input value={name} onChange={(event) => setName(event.target.value)}
               placeholder={t("voices.namePlaceholder")} />
      </label>
      <EspeakFields
        value={settings}
        engines={props.engines}
        onChange={(patch) => setSettings({ ...settings, ...patch })}
      />
      <p className="hint">{t("voices.espeakHint")}</p>
      <div className="voice-form-actions">
        <Button onClick={props.onCancel}>{t("common.cancel")}</Button>
        <Button primary disabled={busy} onClick={submit}>
          {busy ? t("voices.adding") : t("voices.add")}
        </Button>
      </div>
    </div>
  );
}

function EspeakFields(props: {
  value: EspeakSettings;
  engines: Engines | null;
  onChange: (patch: Partial<EspeakSettings>) => void;
}) {
  const { t } = useI18n();
  const value = props.value;
  const espeak = props.engines?.espeak;
  const languages = espeak?.languages ?? [];
  const variants = espeak?.variants ?? [];
  const [speedMin, speedMax] = espeak?.speed_range ?? [80, 450];
  const [pitchMin, pitchMax] = espeak?.pitch_range ?? [0, 99];

  return (
    <div className="espeak-fields">
      <label>
        {t("voices.language")}
        <select value={value.voice} onChange={(event) => props.onChange({ voice: event.target.value })}>
          {!languages.some((l) => l.code === value.voice) && (
            <option value={value.voice}>{value.voice}</option>
          )}
          {languages.map((l) => (
            <option key={l.code} value={l.code}>{l.name} ({l.code})</option>
          ))}
        </select>
      </label>
      <label>
        {t("voices.variant")}
        <select value={value.variant}
                onChange={(event) => props.onChange({ variant: event.target.value })}>
          <option value="">{t("voices.variantNone")}</option>
          {value.variant && !variants.some((v) => v.id === value.variant) && (
            <option value={value.variant}>{value.variant}</option>
          )}
          {variants.map((v) => (
            <option key={v.id} value={v.id}>{v.name} · {v.gender}</option>
          ))}
        </select>
      </label>
      <NumberField label={t("voices.speed")} value={value.speed} min={speedMin} max={speedMax}
                   onCommit={(speed) => props.onChange({ speed })} />
      <NumberField label={t("voices.pitch")} value={value.pitch} min={pitchMin} max={pitchMax}
                   onCommit={(pitch) => props.onChange({ pitch })} />
    </div>
  );
}

/** Commits on blur or Enter, clamped — not on every keystroke. */
function NumberField(props: {
  label: string;
  value: number;
  min: number;
  max: number;
  onCommit: (value: number) => void;
}) {
  const [draft, setDraft] = useState(String(props.value));
  useEffect(() => setDraft(String(props.value)), [props.value]);

  function commit() {
    const parsed = Math.round(Number(draft));
    if (!draft.trim() || !Number.isFinite(parsed)) {
      setDraft(String(props.value));
      return;
    }
    const clamped = Math.min(props.max, Math.max(props.min, parsed));
    setDraft(String(clamped));
    if (clamped !== props.value) props.onCommit(clamped);
  }

  return (
    <label>
      {props.label}
      <input
        type="number"
        min={props.min}
        max={props.max}
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => { if (event.key === "Enter") event.currentTarget.blur(); }}
      />
    </label>
  );
}

/** Pick any number of files at once; each gets its own transcript field. */
function ClipForm(props: {
  withName?: boolean;
  onCancel: () => void;
  onSubmit: (name: string, entries: ClipUpload[]) => Promise<void>;
  onError: (message: string | null) => void;
}) {
  const { t } = useI18n();
  const [name, setName] = useState("");
  const [entries, setEntries] = useState<ClipUpload[]>([]);
  const [busy, setBusy] = useState(false);

  const ready = entries.length > 0 && entries.every((entry) => entry.refText.trim());

  async function submit() {
    if (!ready) return;
    setBusy(true);
    props.onError(null);
    try {
      await props.onSubmit(name, entries);
      setName("");
      setEntries([]);
    } catch (exc) {
      props.onError(String((exc as Error).message));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="voice-form">
      {props.withName && (
        <label>
          {t("voices.name")}
          <input value={name} onChange={(event) => setName(event.target.value)}
                 placeholder={t("voices.namePlaceholder")} />
        </label>
      )}
      <label>
        {t("voices.file")}
        <input
          type="file"
          multiple
          accept=".wav,.mp3,.m4a,.flac,.ogg"
          onChange={(event) => setEntries(
            Array.from(event.target.files ?? []).map((file) => ({ file, refText: "" })))}
        />
      </label>

      {entries.map((entry, index) => (
        <label key={`${entry.file.name}-${index}`}>
          {t("voices.refTextFor", { name: entry.file.name })}
          <textarea
            rows={3}
            value={entry.refText}
            placeholder={t("voices.refTextPlaceholder")}
            onChange={(event) => setEntries(entries.map((old, i) =>
              i === index ? { ...old, refText: event.target.value } : old))}
          />
        </label>
      ))}

      <p className="hint">{t("voices.refTextHint")}</p>
      <div className="voice-form-actions">
        <Button onClick={props.onCancel}>{t("common.cancel")}</Button>
        <Button primary disabled={!ready || busy} onClick={submit}>
          {busy ? t("voices.adding") : t("voices.add")}
        </Button>
      </div>
    </div>
  );
}
