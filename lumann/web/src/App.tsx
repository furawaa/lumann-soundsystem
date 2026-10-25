import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  api, isSegment, playable, sampleAudioUrl, segmentAudioUrl, takeAudioUrl,
  type ComposeRecord, type FavoriteGroup, type Insert, type Item, type Project,
  type ProjectSummary, type QueueRow, type Sample, type Segment, type Take,
  type Voice, type WorkerState,
} from "./api";
import { useEventStream, type AppEvent } from "./events";
import { humanDuration } from "./format";
import { useI18n, type Key } from "./i18n";
import { silenceUrl, usePlayer, type Playing } from "./player";
import { Divider, usePanes } from "./panes";
import {
  EditTextModal, InsertModal, NewProjectModal, ScatterModal,
} from "./components/Dialogs";
import { ComposesPanel, FavoritesPanel, SamplesPanel } from "./components/Panels";
import { QueueOverview } from "./components/QueueOverview";
import { lastBatch, ScatterBar, withContext } from "./components/ScatterBar";
import { QueuePanel } from "./components/QueuePanel";
import { ReformatModal } from "./components/ReformatModal";
import { Sidebar } from "./components/Sidebar";
import { TextPanel } from "./components/TextPanel";
import { TrackList } from "./components/TrackList";
import { VoicesModal } from "./components/VoicesModal";
import { Button, Empty, Segmented } from "./components/ui";

export type SideView = "project" | "queue" | "favorites" | "samples";
type MiddleTab = "tracks" | "queue" | "composes";
type Scope = "remaining" | "all" | "stale" | "rerecord";

const SCOPE_KEY: Record<Scope, Key> = {
  remaining: "scope.remaining",
  all: "scope.all",
  stale: "scope.stale",
  rerecord: "scope.rerecord",
};

export default function App() {
  const { t } = useI18n();
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [projectId, setProjectId] = useState<string | null>(null);
  const [project, setProject] = useState<Project | null>(null);
  const [view, setView] = useState<SideView>("project");
  const [tab, setTab] = useState<MiddleTab>("tracks");
  const [scope, setScope] = useState<Scope>("remaining");
  const [selected, setSelected] = useState<string | null>(null);
  const player = usePlayer();
  const panes = usePanes();
  const [playAll, setPlayAll] = useState(false);
  const [voices, setVoices] = useState<Voice[]>([]);
  const [showVoices, setShowVoices] = useState(false);
  const [worker, setWorker] = useState<WorkerState | null>(null);
  const [queue, setQueue] = useState<QueueRow[]>([]);
  const [composes, setComposes] = useState<ComposeRecord[]>([]);
  const [samples, setSamples] = useState<Sample[]>([]);
  const [favorites, setFavorites] = useState<FavoriteGroup[]>([]);
  // null text means "re-derive from the original"; the modal is open whenever
  // this is not null itself.
  const [reformat, setReformat] =
    useState<{ text: string | null; formatted: boolean } | null>(null);
  const [editing, setEditing] = useState<Segment | null>(null);
  const [insertAfter, setInsertAfter] = useState<string | null>(null);
  const [showNew, setShowNew] = useState(false);
  const [showScatter, setShowScatter] = useState(false);
  const [scatterOnly, setScatterOnly] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // --- loading ------------------------------------------------------------

  const loadProjects = useCallback(async () => {
    const list = await api.projects();
    setProjects(list);
    setProjectId((current) => current ?? list[0]?.id ?? null);
  }, []);

  const loadProject = useCallback(async (id: string) => {
    try {
      setProject(await api.project(id));
    } catch (exc) {
      setError(String((exc as Error).message));
    }
  }, []);

  const loadQueue = useCallback(async (id: string) => {
    const result = await api.queue(id);
    setQueue(result.queue);
    setWorker(result.state);
  }, []);

  const loadComposes = useCallback(async (id: string) => {
    setComposes(await api.composes(id));
  }, []);

  useEffect(() => { loadProjects(); }, [loadProjects]);
  useEffect(() => { api.samples().then(setSamples).catch(() => {}); }, []);

  const loadVoices = useCallback(
    () => api.voices().then(setVoices).catch(() => {}), []);
  useEffect(() => { loadVoices(); }, [loadVoices]);
  useEffect(() => { api.worker().then(setWorker).catch(() => {}); }, []);

  useEffect(() => {
    if (!projectId) { setProject(null); return; }
    loadProject(projectId);
    loadQueue(projectId);
    loadComposes(projectId);
    setSelected(null);
  }, [projectId, loadProject, loadQueue, loadComposes]);

  useEffect(() => {
    if (view === "favorites") api.favorites().then(setFavorites).catch(() => {});
  }, [view]);

  // --- live events --------------------------------------------------------

  const refreshSoon = useDebounced(() => {
    if (projectId) { loadProject(projectId); loadProjects(); }
  }, 400);
  const refreshQueueSoon = useDebounced(() => {
    if (projectId) loadQueue(projectId);
  }, 400);

  useEventStream((event: AppEvent) => {
    switch (event.type) {
      case "segment":
        if (event.project !== projectId) { loadProjects(); return; }
        // Patch in place so a 500-row list does not re-render from scratch on
        // every finished chunk; the periodic refresh reconciles the rest.
        setProject((current) => {
          if (!current) return current;
          const timeline = current.timeline.map((item) =>
            item.kind === "segment" && item.id === event.id
              ? { ...item, status: event.status as Segment["status"],
                  active_take: event.active_take, take_count: event.takes,
                  error: event.error }
              : item);
          return { ...current, timeline };
        });
        refreshSoon();
        refreshQueueSoon();
        break;
      case "queue":
        if (event.project === projectId) refreshQueueSoon();
        break;
      case "worker":
        api.worker().then(setWorker).catch(() => {});
        if (event.state === "error") setError(event.message ?? t("worker.error"));
        break;
      case "estimate":
        if (event.project === projectId) {
          setProject((current) => current
            ? { ...current, estimate: { ...current.estimate,
                eta_seconds: event.eta_seconds,
                projected_duration: event.projected_duration,
                rate: event.rate, measured: true } }
            : current);
        }
        break;
      case "compose":
        if (event.project === projectId) {
          setComposes((current) => {
            const next = current.map((item) =>
              item.id === event.id
                ? { ...item, status: event.status as ComposeRecord["status"],
                    progress: event.progress ?? item.progress,
                    duration: event.duration ?? item.duration,
                    size: event.size ?? item.size,
                    error: event.error ?? item.error }
                : item);
            return next.some((item) => item.id === event.id) ? next : current;
          });
          if (event.status === "done" || event.status === "failed") loadComposes(projectId!);
        }
        break;
      case "project":
        loadProjects();
        if (event.project === projectId) refreshSoon();
        break;
    }
  });

  // --- playback -----------------------------------------------------------

  const playSegment = useCallback((segment: Segment) => {
    if (!segment.active_take) return;
    const target: Playing = { kind: "segment", id: segment.id, take: null };
    player.play(target, segmentAudioUrl(segment.id, segment.active_take));
    setSelected(segment.id);
  }, [player]);

  const playTake = useCallback((segment: Segment, take: Take) => {
    const target: Playing = { kind: "segment", id: segment.id, take: take.id };
    player.play(target, takeAudioUrl(take.id));
    // The text belongs to the segment, not to the take, so the highlight is
    // the same either way.
    setSelected(segment.id);
  }, [player]);

  // Keyboard navigation still steps segment to segment: an insert has no text
  // to show in the panel and nothing to record.
  const segmentsOnly = useMemo(
    () => (project?.timeline ?? []).filter(isSegment), [project?.timeline]);

  const playInsert = useCallback((insert: Insert) => {
    if (!playable(insert)) return;
    const target: Playing = { kind: "insert", id: insert.id };
    player.play(target, insert.insert_type === "silence"
      ? silenceUrl(insert.duration)
      : sampleAudioUrl(insert.sample ?? ""));
    setSelected(insert.id);
  }, [player]);

  const playItem = useCallback((item: Item) => {
    if (isSegment(item)) playSegment(item);
    else playInsert(item);
  }, [playSegment, playInsert]);

  const timeline = useMemo(() => project?.timeline ?? [], [project?.timeline]);

  // Sequential playback: on each track ending, look for the next one that has
  // something to play — inserts included, since a pause between two sentences
  // is part of the reading. Registered as a callback because the <audio>
  // element outlives any single render's copy of the track list.
  useEffect(() => {
    if (!playAll) {
      player.setAdvance(null);
      return;
    }
    player.setAdvance((finished) => {
      const from = timeline.findIndex((item) => item.id === finished.id);
      const next = timeline.slice(from + 1).find(playable);
      if (!next) {
        setPlayAll(false);
        return false;
      }
      playItem(next);
      return true;
    });
    return () => player.setAdvance(null);
  }, [playAll, timeline, playItem, player]);

  function startPlayAll() {
    const fromSelected = selected
      ? timeline.slice(timeline.findIndex((item) => item.id === selected))
      : timeline;
    const first = fromSelected.find(playable) ?? timeline.find(playable);
    if (!first) return;
    setPlayAll(true);
    playItem(first);
  }

  async function pickVoice(id: string) {
    if (!projectId || !id) return;
    await api.updateProject(projectId, { voice: id });
    loadProject(projectId);
  }

  function stopPlayAll() {
    setPlayAll(false);
    player.stop();
  }

  // --- keyboard -----------------------------------------------------------

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const target = event.target as HTMLElement;
      if (target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;

      const index = segmentsOnly.findIndex((item) => item.id === selected);
      const current = index >= 0 ? segmentsOnly[index] : null;

      switch (event.key) {
        case " ": {
          // Whatever row is selected, not only a segment: an insert is a track
          // like any other now.
          const item = timeline.find((row) => row.id === selected);
          if (item) { event.preventDefault(); playItem(item); }
          break;
        }
        case "j":
          event.preventDefault();
          setSelected(segmentsOnly[Math.min(index + 1, segmentsOnly.length - 1)]?.id ?? null);
          break;
        case "k":
          event.preventDefault();
          setSelected(segmentsOnly[Math.max(index - 1, 0)]?.id ?? null);
          break;
        case "f":
          if (current) {
            api.patchSegment(current.id, { favorite: !current.favorite })
              .then(() => { if (projectId) loadProject(projectId); });
          }
          break;
        case "r":
          if (current) {
            api.patchSegment(current.id, { rerecord: !current.rerecord })
              .then(() => { if (projectId) loadProject(projectId); });
          }
          break;
        case "i":
          if (current) setInsertAfter(current.id);
          break;
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [segmentsOnly, timeline, selected, playItem, projectId, loadProject]);

  // --- recording ----------------------------------------------------------

  // "Recording" means this project specifically: the worker is consuming and
  // either its in-flight job or something still queued belongs to us.
  // Paused counts as not recording even while another book keeps the worker
  // busy: the button has to offer a resume, not a stop that does nothing here.
  // Reviewing a scatter: only the samples it placed, each under the segment it
  // follows. Falls back to the whole timeline the moment the batch is gone.
  const reviewBatch = scatterOnly && project ? lastBatch(project.timeline) : null;
  const scatterView = reviewBatch && project
    ? withContext(project.timeline, reviewBatch)
    : project?.timeline ?? [];

  const recording = !!worker?.running && !!projectId
    && !(worker.paused ?? []).includes(projectId)
    && (worker.current?.project === projectId || (worker.by_project[projectId] ?? 0) > 0);

  async function startRecording() {
    if (!projectId) return;
    try {
      await api.recordStart(projectId, scope);
      await loadQueue(projectId);
      await loadProject(projectId);
    } catch (exc) {
      setError(String((exc as Error).message));
    }
  }

  async function stopRecording() {
    if (!projectId) return;
    await api.recordStop(projectId);
    await loadQueue(projectId);
    await loadProject(projectId);
  }

  async function startCompose(format: "wav" | "m4a") {
    if (!projectId) return;
    const record = await api.compose(projectId, format);
    setComposes((current) => [record, ...current]);
    setTab("composes");
  }

  const workerLabel = worker
    ? worker.worker === "loading" ? t("worker.loading")
      : worker.worker === "ready"
        ? t(worker.running ? "worker.running" : "worker.ready")
      : worker.worker === "error" ? t("worker.error")
      : worker.queued > 0 ? t("worker.paused", { n: worker.queued }) : t("worker.stopped")
    : null;

  // --- render -------------------------------------------------------------

  return (
    <div
      className="app"
      style={{ gridTemplateColumns: `${panes.sidebar}px 5px minmax(0, 1fr)` }}
    >
      <Sidebar
        projects={projects}
        activeProject={projectId}
        view={view}
        worker={worker}
        workerLabel={workerLabel}
        onPick={(id) => { setProjectId(id); setView("project"); }}
        onView={setView}
        onNew={() => setShowNew(true)}
        onChanged={() => { loadProjects(); setProjectId(null); }}
      />

      <Divider width={panes.sidebar} onChange={panes.setSidebar} onReset={panes.reset} />

      {error && (
        <div className="banner error" onClick={() => setError(null)}>
          {error} <span className="hint">{t("app.dismiss")}</span>
        </div>
      )}

      <div
        className="main"
        style={{
          gridTemplateColumns: view === "project" && project
            ? `${panes.middle}px 5px minmax(0, 1fr)`
            : "minmax(0, 1fr)",
        }}
      >
      {view === "queue" && (
        <QueueOverview
          activeProject={projectId}
          onOpen={(pid, segment) => {
            setProjectId(pid);
            setView("project");
            if (segment) setSelected(segment);
          }}
          onChanged={() => { loadProjects(); api.worker().then(setWorker).catch(() => {}); }}
        />
      )}
      {view === "favorites" && (
        <FavoritesPanel
          groups={favorites}
          onOpen={(pid, segment) => {
            setProjectId(pid);
            setView("project");
            setSelected(segment);
          }}
        />
      )}
      {view === "samples" && (
        <SamplesPanel samples={samples} onChanged={() => api.samples().then(setSamples)} />
      )}
      {view === "project" && (
        !project
          ? (
            <Empty
              title={t("app.emptyTitle")}
              hint={(
                <Button primary onClick={() => setShowNew(true)}>
                  {t("app.createProject")}
                </Button>
              )}
            />
          )
          : (
            <>
              <section className="panel middle">
                <header className="panel-head">
                  <Segmented
                    value={tab}
                    onChange={setTab}
                    options={[
                      { value: "tracks", label: t("tab.tracks") },
                      { value: "queue",
                        label: `${t("tab.queue")}${queue.length ? ` (${queue.length})` : ""}` },
                      { value: "composes",
                        label: `${t("tab.composes")}${composes.length ? ` (${composes.length})` : ""}` },
                    ]}
                  />
                  {tab === "tracks" && (
                    <button
                      className="icon scatter"
                      onClick={() => setShowScatter(true)}
                      title={t("scatter.buttonTitle")}
                    >
                      ◆◆◆
                    </button>
                  )}
                  {/* Play and record as one group: on a narrow panel it moves to
                      a second row as a unit, right-aligned, instead of crushing. */}
                  <div className="head-actions">
                  {playAll
                    ? (
                      <div className="playall on">
                        <button
                          className="play"
                          onClick={() => player.toggle()}
                          title={t(player.paused ? "playAll.resume" : "playAll.pause")}
                        >
                          {player.paused ? "▶" : "❙❙"}
                        </button>
                        <button className="play" onClick={stopPlayAll}
                                title={t("playAll.stop")}>
                          ■
                        </button>
                      </div>
                    )
                    : (
                      <button
                        className="play playall-start"
                        onClick={startPlayAll}
                        disabled={!timeline.some(playable)}
                        title={t(selected ? "playAll.fromSelected" : "playAll.start")}
                      >
                        ▶
                      </button>
                    )}

                  <span className="head-sep" />

                  {project.stats.rerecord > 0 && (
                    <button
                      className="marked-badge"
                      onClick={() => setScope("rerecord")}
                      title={t("record.markedTitle")}
                    >
                      ⟳ {project.stats.rerecord}
                    </button>
                  )}

                  {!recording && (
                    <select
                      className="scope"
                      value={scope}
                      onChange={(event) => setScope(event.target.value as Scope)}
                    >
                      {(Object.keys(SCOPE_KEY) as Scope[]).map((key) => (
                        <option key={key} value={key}>{t(SCOPE_KEY[key])}</option>
                      ))}
                    </select>
                  )}
                  {!recording && (
                    <select
                      className="scope voice-pick-inline"
                      title={t("voices.pickTitle")}
                      value={project.voice ?? ""}
                      onChange={(event) => {
                        if (event.target.value === "__manage__") setShowVoices(true);
                        else pickVoice(event.target.value);
                      }}
                    >
                      {!project.voice && <option value="">{t("voices.none")}</option>}
                      {voices.map((voice) => (
                        <option key={voice.id} value={voice.id}>♪ {voice.name}</option>
                      ))}
                      <option value="__manage__">{t("voices.manage")}</option>
                    </select>
                  )}
                  {recording
                    ? (
                      <div className="stop-wrap">
                        <div className="recording-now">
                          <span className="rec-dot live" />
                          <span>{t("record.recording")}</span>
                          <Button danger onClick={stopRecording}>{t("record.stop")}</Button>
                        </div>
                        <span className="stop-sub">{t("record.stopSub")}</span>
                      </div>
                    )
                    : (
                      <Button
                        primary
                        onClick={startRecording}
                        className={queue.length > 0 ? "inviting" : ""}
                        title={t(queue.length > 0 ? "record.pending" : "record.startTitle")}
                      >
                        <span className="rec-dot" />
                        {t("record.start")}
                        {queue.length > 0 && ` (${queue.length})`}
                      </Button>
                    )}
                  </div>
                </header>

                <div className="stats-line">
                  <span>
                    {t("stats.done", {
                      done: project.stats.done, total: project.stats.segments,
                    })}
                  </span>
                  {project.stats.stale > 0 && (
                    <span className="stale-text">
                      {t("stats.stale", { n: project.stats.stale })}
                    </span>
                  )}
                  {project.stats.failed > 0 && (
                    <span className="failed-text">
                      {t("stats.failed", { n: project.stats.failed })}
                    </span>
                  )}
                  <div className="spacer" />
                  {project.estimate.eta_seconds > 0 && (
                    <span>
                      {t("stats.left", {
                        time: humanDuration(project.estimate.eta_seconds, t),
                      })}
                    </span>
                  )}
                  <span title={t("stats.totalTitle")}>
                    {t("stats.total", {
                      time: humanDuration(project.estimate.projected_duration, t),
                    })}
                  </span>
                </div>

                {tab === "tracks" && (
                  <>
                    <ScatterBar
                      projectId={project.id}
                      items={project.timeline}
                      filtered={scatterOnly}
                      onFilter={setScatterOnly}
                      onChanged={() => { loadProject(project.id); loadProjects(); }}
                    />
                    <TrackList
                      items={scatterView}
                      selected={selected}
                      player={player}
                      samples={samples}
                      onSelect={setSelected}
                      currentVoice={project.voice ?? null}
                      onPlaySegment={playSegment}
                      onPlayInsert={playInsert}
                      onPlayTake={playTake}
                      onChanged={() => { loadProject(project.id); loadProjects(); }}
                      onEditText={setEditing}
                      onInsertAfter={(segment) => setInsertAfter(segment.id)}
                    />
                  </>
                )}
                {tab === "queue" && (
                  <QueuePanel
                    rows={queue}
                    estimate={project.estimate}
                    projectId={project.id}
                    onSelect={(id) => { setSelected(id); setTab("tracks"); }}
                    onOpenProject={(pid, segmentId) => {
                      if (pid !== project.id) setProjectId(pid);
                      setSelected(segmentId);
                      setTab("tracks");
                    }}
                    onChanged={() => { loadQueue(project.id); loadProject(project.id); }}
                  />
                )}
                {tab === "composes" && (
                  <ComposesPanel
                    project={project}
                    composes={composes}
                    player={player}
                    onCompose={startCompose}
                    onChanged={() => loadComposes(project.id)}
                  />
                )}
              </section>

              <Divider width={panes.middle} onChange={panes.setMiddle} onReset={panes.reset} />

              <TextPanel
                project={project}
                selected={selected}
                onSelect={setSelected}
                onPlay={(id) => {
                  const segment = segmentsOnly.find((item) => item.id === id);
                  if (segment) playSegment(segment);
                }}
                onReformat={(text, origin) =>
                  setReformat({ text, formatted: origin === "formatted" })}
              />
            </>
          )
      )}
      </div>

      <audio {...player.bind} />

      {showVoices && projectId && (
        <VoicesModal
          voices={voices}
          current={project?.voice ?? null}
          onPick={(id) => pickVoice(id)}
          onChanged={loadVoices}
          onClose={() => setShowVoices(false)}
        />
      )}
      {showNew && (
        <NewProjectModal
          onClose={() => setShowNew(false)}
          onCreated={(id) => { loadProjects(); setProjectId(id); setView("project"); }}
        />
      )}
      {reformat && projectId && (
        <ReformatModal
          projectId={projectId}
          text={reformat.text}
          fromFormatted={reformat.formatted}
          onClose={() => setReformat(null)}
          onApplied={() => { loadProject(projectId); loadProjects(); }}
        />
      )}
      {editing && (
        <EditTextModal
          segment={editing}
          onClose={() => setEditing(null)}
          onSaved={() => projectId && loadProject(projectId)}
        />
      )}
      {showScatter && projectId && (
        <ScatterModal
          projectId={projectId}
          samples={samples}
          onClose={() => setShowScatter(false)}
          onAdded={() => loadProject(projectId)}
        />
      )}
      {insertAfter && projectId && (
        <InsertModal
          projectId={projectId}
          afterId={insertAfter}
          samples={samples}
          onClose={() => setInsertAfter(null)}
          onAdded={() => loadProject(projectId)}
        />
      )}
    </div>
  );
}

/** Coalesces bursts of SSE events into one refetch. */
function useDebounced(fn: () => void, delay: number) {
  const timer = useRef<number | undefined>(undefined);
  const latest = useRef(fn);
  latest.current = fn;
  return useCallback(() => {
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => latest.current(), delay);
  }, [delay]);
}
