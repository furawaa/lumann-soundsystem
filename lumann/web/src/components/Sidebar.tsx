import { api, type ProjectSummary, type WorkerState } from "../api";
import { AccentToggle } from "../accent";
import { LanguageToggle, useI18n } from "../i18n";
import type { SideView } from "../App";

export function Sidebar(props: {
  projects: ProjectSummary[];
  activeProject: string | null;
  view: SideView;
  worker: WorkerState | null;
  workerLabel: string | null;
  onPick: (id: string) => void;
  onView: (view: SideView) => void;
  onNew: () => void;
  onChanged: () => void;
}) {
  const { t } = useI18n();
  const queued = props.worker?.queued ?? 0;
  const busy = !!props.worker?.running || queued > 0;
  return (
    <nav className="sidebar">
      <div className="side-head">
        <span className="brand">{t("app.brand")}</span>
        <button className="link" onClick={props.onNew}>{t("app.new")}</button>
      </div>

      <div className="side-group">{t("app.projects")}</div>
      {props.projects.length === 0 && <div className="side-empty">{t("app.noProjects")}</div>}
      {props.projects.map((project) => {
        const total = project.stats.segments || 1;
        const done = project.stats.done;
        return (
          <div
            key={project.id}
            className={`side-row ${props.activeProject === project.id && props.view === "project" ? "on" : ""}`}
            onClick={() => props.onPick(project.id)}
          >
            <div className="side-row-main">
              <span className="side-title">
                {project.title}
                {/* Same blinking disc as the record button: this book is in
                    the model right now, whichever book is on screen. */}
                {props.worker?.current?.project === project.id && (
                  <span className="rec-dot live" title={t("record.recording")} />
                )}
              </span>
              <span className="side-sub">
                {done}/{project.stats.segments}
                {project.stats.stale > 0 && (
                  <span className="stale-dot"> · {t("app.stale", { n: project.stats.stale })}</span>
                )}
              </span>
            </div>
            <div className="side-bar"><div style={{ width: `${(done / total) * 100}%` }} /></div>
            <button
              className="icon side-del"
              title={t("app.deleteProject")}
              onClick={async (event) => {
                event.stopPropagation();
                if (window.confirm(
                  t("app.deleteProjectConfirm", { title: project.title }))) {
                  await api.deleteProject(project.id);
                  props.onChanged();
                }
              }}
            >
              ✕
            </button>
          </div>
        );
      })}

      <div className="side-group">{t("app.sections")}</div>
      {(["queue", "favorites", "samples"] as SideView[]).map((view) => (
        <div
          key={view}
          className={`side-row ${props.view === view ? "on" : ""}`}
          onClick={() => props.onView(view)}
        >
          <span className="side-title">
            {t(`nav.${view}` as "nav.favorites")}
            {view === "queue" && queued > 0 && <span className="side-count">{queued}</span>}
          </span>
        </div>
      ))}

      <div className="spacer" />
      <div className="prefs">
        <LanguageToggle />
        <AccentToggle />
      </div>
      {props.workerLabel && (
        <div className="worker-state">
          <span>{props.workerLabel}</span>
          {busy && (
            <button
              className="btn danger stop-all"
              onClick={() => api.stopAll().then(props.onChanged)}
              title={t("queue.stopAllTitle")}
            >
              {t("queue.stopAll")}
            </button>
          )}
        </div>
      )}
    </nav>
  );
}
