// The sidebar's secondary views: Composes, Samples, Favorites.
import { useEffect, useRef, useState } from "react";
import {
  api, composeAudioUrl, composeDownloadUrl, sampleAudioUrl,
  type ComposeRecord, type FavoriteGroup, type Project, type Sample, type Usage,
} from "../api";
import { bytes, clock, humanDuration } from "../format";
import { useI18n } from "../i18n";
import type { Player } from "../player";
import { PlayerBar } from "./PlayerBar";
import { Button, Empty, Progress } from "./ui";

/** Lives as a tab next to Tracks and Queue: composes are finished work for
 *  this project, not a separate place. */
export function ComposesPanel(props: {
  project: Project | null;
  composes: ComposeRecord[];
  player: Player;
  onCompose: (format: "wav" | "m4a") => void;
  onChanged: () => void;
}) {
  const { t } = useI18n();
  const [usage, setUsage] = useState<Usage | null>(null);

  useEffect(() => {
    if (props.project) api.usage(props.project.id).then(setUsage).catch(() => setUsage(null));
  }, [props.project?.id, props.composes.length]);

  if (!props.project) return <Empty title={t("compose.pickProject")} />;

  return (
    <div className="composes-tab">
      <div className="queue-head">
        <span>{t("compose.title")}</span>
        <div className="spacer" />
        <Button onClick={() => props.onCompose("m4a")} primary>{t("compose.makeM4a")}</Button>
        <Button onClick={() => props.onCompose("wav")} title={t("compose.wavTitle")}>
          {t("compose.makeWav")}
        </Button>
      </div>

      <div className="scroll">
        {props.composes.length === 0 && (
          <Empty title={t("compose.empty")} hint={t("compose.emptyHint")} />
        )}

        {props.composes.map((compose) => {
          const target = { kind: "compose", id: compose.id } as const;
          const playing = props.player.isPlaying(target);
          return (
          <div key={compose.id} className="row compose">
            <div className="compose-main">
              <div className="compose-line">
                {compose.status === "done" && (
                  <button
                    className={`play ${playing ? "on" : ""}`}
                    onClick={() => props.player.play(target, composeAudioUrl(compose.id))}
                    aria-label={t("track.play")}
                  >
                    {playing && !props.player.paused ? "❙❙" : "▶"}
                  </button>
                )}
                {playing
                  ? <PlayerBar player={props.player} />
                  : (
                    <>
                      <span className="mono">{compose.format.toUpperCase()}</span>
                      <span className="hint">
                        {t("compose.parts", { n: compose.steps })}
                        {compose.skipped > 0
                          && ` · ${t("compose.skipped", { n: compose.skipped })}`}
                        {compose.duration ? ` · ${humanDuration(compose.duration, t)}` : ""}
                        {compose.size ? ` · ${bytes(compose.size, t)}` : ""}
                      </span>
                      <div className="spacer" />
                    </>
                  )}
                {compose.status === "done" && (
                  <>
                    <a className="link" href={composeDownloadUrl(compose.id)}>
                      {t("compose.download")}
                    </a>
                    <button
                      className="icon"
                      title={t("compose.delete")}
                      onClick={() => {
                        if (playing) props.player.stop();
                        api.deleteCompose(compose.id).then(props.onChanged);
                      }}
                    >
                      ✕
                    </button>
                  </>
                )}
                {compose.status === "failed" && <span className="tag failed">{compose.error}</span>}
              </div>

              {compose.status === "running" && (
                <>
                  <Progress value={compose.determinate ? compose.progress : null} />
                  <span className="hint">
                    {compose.determinate
                      ? t("compose.progress", {
                          percent: Math.round((compose.progress ?? 0) * 100),
                          total: humanDuration(compose.total_duration, t),
                        })
                      : t("compose.copying")}
                  </span>
                </>
              )}
            </div>
          </div>
          );
        })}
      </div>

      {usage && (
        <footer className="panel-foot">
          <span className="hint">
            {t("compose.usage", {
              active: bytes(usage.active, t),
              archived: bytes(usage.archived, t),
            })}
            {usage.composes > 0 && t("compose.usageComposes", { size: bytes(usage.composes, t) })}
            {usage.trash > 0 && t("compose.usageTrash", { size: bytes(usage.trash, t) })}
          </span>
          <div className="spacer" />
          {usage.archived > 0 && (
            <Button
              danger
              onClick={async () => {
                if (!window.confirm(t("compose.pruneConfirm"))) return;
                const result = await api.pruneTakes(props.project!.id);
                window.alert(t("compose.pruneDone", {
                  removed: result.removed, freed: bytes(result.freed, t),
                }));
                props.onChanged();
              }}
            >
              {t("compose.prune")}
            </Button>
          )}
        </footer>
      )}
    </div>
  );
}

export function SamplesPanel(props: { samples: Sample[]; onChanged: () => void }) {
  const { t } = useI18n();
  const input = useRef<HTMLInputElement>(null);

  return (
    <section className="panel">
      <header className="panel-head">
        <span className="panel-title">{t("samples.title")}</span>
        <div className="spacer" />
        <Button primary onClick={() => input.current?.click()}>{t("samples.upload")}</Button>
        <input
          ref={input}
          type="file"
          accept="audio/*"
          hidden
          onChange={async (event) => {
            const file = event.target.files?.[0];
            if (file) {
              await api.uploadSample(file);
              props.onChanged();
            }
            event.target.value = "";
          }}
        />
      </header>

      <div className="scroll">
        {props.samples.length === 0 && (
          <Empty title={t("samples.empty")} hint={t("samples.emptyHint")} />
        )}
        {props.samples.map((sample) => (
          <div key={sample.name} className="row">
            <button className="play" onClick={() => new Audio(sampleAudioUrl(sample.name)).play()}>
              ▶
            </button>
            <span className="track-text">{sample.name}</span>
            <span className="track-meta">{clock(sample.duration)} · {bytes(sample.size, t)}</span>
            <button
              className="icon"
              onClick={async () => {
                if (window.confirm(t("samples.deleteConfirm", { name: sample.name }))) {
                  await api.deleteSample(sample.name);
                  props.onChanged();
                }
              }}
            >
              ✕
            </button>
          </div>
        ))}
      </div>
    </section>
  );
}

export function FavoritesPanel(props: {
  groups: FavoriteGroup[];
  onOpen: (project: string, segment: string) => void;
}) {
  const { t } = useI18n();
  if (props.groups.length === 0) {
    return <Empty title={t("favorites.empty")} hint={t("favorites.emptyHint")} />;
  }
  return (
    <section className="panel">
      <header className="panel-head">
        <span className="panel-title">{t("favorites.title")}</span>
      </header>
      <div className="scroll">
        {props.groups.map((group) => (
          <div key={group.project}>
            <div className="group-head">{group.title}</div>
            {group.segments.map((segment) => (
              <div
                key={segment.id}
                className="row"
                onClick={() => props.onOpen(group.project, segment.id)}
              >
                <span className="idx">{String(segment.index).padStart(4, "0")}</span>
                <span className="icon fav on">♥</span>
                <span className="track-text">{segment.text}</span>
                <span className="track-meta">
                  {segment.has_audio ? clock(segment.duration) : t("favorites.noAudio")}
                </span>
              </div>
            ))}
          </div>
        ))}
      </div>
    </section>
  );
}
