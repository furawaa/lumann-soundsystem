// REST client and the shapes the server sends back.

export type Status =
  | "pending" | "queued" | "recording" | "done" | "stale" | "failed";

export interface Take {
  id: string;
  n: number;
  created_at: string;
  duration: number | null;
  text_hash: string;
  temperature: number | null;
  gen_seconds: number | null;
  note: string | null;
  voice?: string | null;
  voice_name?: string | null;
  outdated?: boolean;
  active?: boolean;
}

export interface Segment {
  kind: "segment";
  id: string;
  index: number;
  line: number;
  char_start: number;
  char_end: number;
  text: string;
  text_override: string | null;
  effective_text: string;
  text_hash: string;
  status: Status;
  moved: boolean;
  active_take: string | null;
  takes: Take[];
  take_count: number;
  outdated_takes: number;
  in_queue: boolean;
  favorite: boolean;
  rerecord: boolean;
  error: string | null;
}

export interface Insert {
  kind: "insert";
  /** Set on inserts made by one scatter, so that run can be reviewed or undone. */
  batch?: string | null;
  created_at?: string;
  id: string;
  insert_type: "silence" | "sample";
  seconds: number | null;
  sample: string | null;
  duration: number;
}

export type Item = Segment | Insert;

export interface Stats {
  segments: number; inserts: number; done: number; stale: number;
  failed: number; pending: number; favorites: number; rerecord: number;
  takes: number; chars_total: number; chars_left: number;
  recorded_seconds: number; insert_seconds: number;
  counts: Record<string, number>;
}

export interface Estimate {
  rate: number; eta_seconds: number; projected_duration: number;
  chars_left: number; measured: boolean;
}

export interface Project {
  id: string;
  title: string;
  created_at: string;
  voice: string | null;
  gap_seconds: number;
  format_options: { max_words: number; target: number; hard_max: number; skip_short: number; yo: number };
  tts_options: { temperature: number; retries: number };
  timeline: Item[];
  stats: Stats;
  estimate: Estimate;
}

export interface ProjectSummary {
  id: string; title: string; created_at: string; stats: Stats;
}

export interface PreviewRow {
  kind: "unchanged" | "moved" | "changed" | "new" | "deleted";
  id: string;
  old_index: number | null;
  new_index: number | null;
  text: string;
  takes: number;
  has_audio: boolean;
  favorite: boolean;
  override_conflict?: boolean;
}

export interface InsertNote {
  id: string; insert_type: string; anchor: string | null;
  review: boolean; reattached_to?: string | null;
}

export interface Preview {
  counts: Record<string, number>;
  segments: PreviewRow[];
  inserts: InsertNote[];
  formatted_length: number;
}

export interface QueueRow {
  id: string; index: number; status: Status; text: string; chars: number;
  position: number | null; rerecord: boolean; favorite: boolean;
}

/** A row of the queue across every project, in real recording order. */
export interface GlobalQueueRow {
  id: string; project: string; project_title: string;
  index: number; status: Status; text: string; chars: number;
  rerecord: boolean; paused: boolean; favorite: boolean;
}

/** A book with work waiting, as the scheduler sees it. */
export interface QueueProject {
  project: string; title: string;
  queued: number; rerecord_queued: number;
  recording: boolean; paused: boolean;
  done: number; segments: number; eta_seconds: number;
}

export interface WorkerState {
  worker: "stopped" | "loading" | "ready" | "error";
  running: boolean;
  queued: number;
  by_project: Record<string, number>;
  /** Projects the user has stopped; their queued work is skipped, not lost. */
  paused: string[];
  current: { project: string; segment: string } | null;
}

export interface ComposeRecord {
  id: string; project: string; format: string;
  status: "running" | "done" | "failed";
  progress: number; created_at: string; steps: number; skipped: number;
  total_duration: number; determinate: boolean;
  error: string | null; duration?: number; size?: number;
}

export interface Sample { name: string; duration: number; size: number }

export interface Clip {
  index: number;
  audio: string;
  ref_text: string;
  duration: number;
  missing: boolean;
}

export interface EspeakSettings {
  /** espeak-ng language voice, e.g. "en-us", "ru". */
  voice: string;
  /** Voice colour appended as "+variant", e.g. "m3", "f2"; "" for none. */
  variant: string;
  /** Words per minute. */
  speed: number;
  /** 0–99. */
  pitch: number;
}

export interface Engines {
  espeak: {
    available: boolean;
    languages: { code: string; name: string }[];
    variants: { id: string; name: string; gender: string }[];
    speed_range: [number, number];
    pitch_range: [number, number];
  };
  qwen: QwenStatus;
}

/** The optional cloning engine, which the user installs and deletes by hand. */
export interface QwenStatus {
  /** Packages and model both present: cloned voices can record. */
  available: boolean;
  packages: boolean;
  /** Installed by the app (so Delete removes it), not by the user's own pip. */
  packages_managed: boolean;
  model: boolean;
  /** QWEN_TTS_MODEL points elsewhere; not ours to delete. */
  model_external: boolean;
  disk_bytes: number;
  /** null when idle. */
  step: null | "starting" | "packages" | "model";
  downloaded: number;
  total: number;
  error: string | null;
}

export interface Voice {
  id: string;
  /** What to show: the user's name, or one made from the voice's settings. */
  name: string;
  /** The user named it; otherwise the name follows the settings. */
  custom_name: boolean;
  /** eSpeak voices are settings; Qwen voices are reference clips. */
  engine: "espeak" | "qwen";
  espeak?: EspeakSettings;
  clips: Clip[];
  /** Index of the clip handed to the model, or "all" for the joined reference. */
  active: number | "all";
  created_at: string;
  builtin?: boolean;
  missing: boolean;
}

/** One reference clip on its way up: the file and what it says. */
export interface ClipUpload { file: File; refText: string }

function clipForm(entries: ClipUpload[], name?: string) {
  const form = new FormData();
  if (name !== undefined) form.append("name", name);
  for (const entry of entries) {
    form.append("files", entry.file);
    form.append("ref_texts", entry.refText);
  }
  return form;
}

async function upload(path: string, form: FormData) {
  const res = await fetch(path, { method: "POST", body: form });
  if (!res.ok) throw new ApiError((await res.json()).detail ?? res.statusText, res.status);
  return res.json() as Promise<Voice>;
}

export interface FavoriteGroup {
  project: string; title: string;
  segments: { id: string; index: number; text: string; status: Status;
              duration: number | null; has_audio: boolean }[];
}

export interface Usage { active: number; archived: number; composes: number; trash: number }

export interface Flags {
  changes: string[];
  flags: string[];
  segments: { id: string; issues: string[] }[];
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: init?.body ? { "Content-Type": "application/json", ...init?.headers } : init?.headers,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch { /* non-JSON error body */ }
    throw new ApiError(detail, res.status);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

const post = <T,>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
const patch = <T,>(path: string, body: unknown) =>
  request<T>(path, { method: "PATCH", body: JSON.stringify(body) });
const put = <T,>(path: string, body: unknown) =>
  request<T>(path, { method: "PUT", body: JSON.stringify(body) });
const del = <T,>(path: string) => request<T>(path, { method: "DELETE" });

export const api = {
  projects: () => request<ProjectSummary[]>("/api/projects"),
  project: (id: string) => request<Project>(`/api/projects/${id}`),
  createProject: (title: string, text: string) =>
    post<Project>("/api/projects", { title, text }),
  deleteProject: (id: string) => del<{ ok: boolean }>(`/api/projects/${id}`),
  updateProject: (id: string, body: Record<string, unknown>) =>
    patch<Project>(`/api/projects/${id}`, body),

  source: (id: string) => request<{ text: string }>(`/api/projects/${id}/source`),
  saveSource: (id: string, text: string) =>
    put<{ ok: boolean }>(`/api/projects/${id}/source`, { text }),
  formatted: (id: string) =>
    request<{ text: string; spans: { id: string; start: number; end: number }[] }>(
      `/api/projects/${id}/formatted`),
  flags: (id: string) => request<Flags>(`/api/projects/${id}/flags`),
  formatText: (id: string, text: string) =>
    post<{ text: string }>(`/api/projects/${id}/format`, { text }),
  preview: (id: string, text: string | null, preformatted: boolean) =>
    post<Preview>(`/api/projects/${id}/reformat/preview`,
                  { text: text ?? undefined, preformatted }),
  applyReformat: (id: string) => post<Project>(`/api/projects/${id}/reformat/apply`),
  usage: (id: string) => request<Usage>(`/api/projects/${id}/usage`),
  pruneTakes: (id: string) =>
    post<{ removed: number; freed: number }>(`/api/projects/${id}/takes/prune`),

  patchSegment: (id: string, body: Record<string, unknown>) =>
    patch<{ segment: Segment; stats: Stats }>(`/api/segments/${id}`, body),
  requeue: (id: string) => post<{ ok: boolean }>(`/api/segments/${id}/requeue`),
  dequeue: (id: string) =>
    post<{ ok: boolean; removed: number }>(`/api/segments/${id}/dequeue`),
  takes: (id: string) => request<Take[]>(`/api/segments/${id}/takes`),
  promoteTake: (segment: string, take: string) =>
    post<{ segment: Segment; takes: Take[] }>(`/api/segments/${segment}/takes/${take}/promote`),
  noteTake: (segment: string, take: string, note: string) =>
    patch<Take>(`/api/segments/${segment}/takes/${take}`, { note }),
  deleteTake: (segment: string, take: string) =>
    del<{ ok: boolean; takes: Take[] }>(`/api/segments/${segment}/takes/${take}`),

  addInsert: (project: string, body: Record<string, unknown>) =>
    post<{ insert: Insert; project: Project }>(`/api/projects/${project}/inserts`, body),
  patchInsert: (id: string, body: Record<string, unknown>) =>
    patch<{ insert: Insert; project: Project }>(`/api/inserts/${id}`, body),
  deleteInsert: (id: string) => del<{ project: Project }>(`/api/inserts/${id}`),
  scatterInserts: (project: string, body: {
    count: number; samples: string[]; min_gap_seconds: number | null;
  }) =>
    post<{ placed: number; asked: number; batch: string | null; project: Project }>(
      `/api/projects/${project}/inserts/scatter`, body),
  deleteInsertBatch: (project: string, batch: string) =>
    del<{ ok: boolean; removed: number; project: Project }>(
      `/api/projects/${project}/inserts/batch/${batch}`),

  recordStart: (id: string, scope: string | string[]) =>
    post<{ queued: number; added: number; state: WorkerState }>(
      `/api/projects/${id}/record/start`, { scope }),
  recordStop: (id: string) => post<{ state: WorkerState }>(`/api/projects/${id}/record/stop`),
  recordClear: (id: string) => post<{ dropped: number }>(`/api/projects/${id}/record/clear`),
  queue: (id: string) =>
    request<{ queue: QueueRow[]; state: WorkerState; estimate: Estimate }>(
      `/api/projects/${id}/queue`),
  worker: () => request<WorkerState>("/api/worker"),
  globalQueue: () =>
    request<{ queue: GlobalQueueRow[]; state: WorkerState }>("/api/queue"),
  queueProjects: () =>
    request<{ projects: QueueProject[]; state: WorkerState }>("/api/queue/projects"),
  setQueueOrder: (ids: string[]) =>
    post<{ order: string[]; state: WorkerState }>("/api/queue/projects/order", { ids }),
  stopAll: () => post<{ ok: boolean; state: WorkerState }>("/api/record/stop-all", {}),

  compose: (id: string, format: "wav" | "m4a") =>
    post<ComposeRecord>(`/api/projects/${id}/compose`, { format }),
  composes: (id: string) => request<ComposeRecord[]>(`/api/projects/${id}/composes`),
  deleteCompose: (id: string) => del<{ ok: boolean }>(`/api/composes/${id}`),

  engines: () => request<Engines>("/api/engines"),
  installQwen: () => post<QwenStatus>("/api/engines/qwen/install"),
  cancelQwen: () => post<QwenStatus>("/api/engines/qwen/cancel"),
  deleteQwen: () => del<QwenStatus>("/api/engines/qwen"),
  voices: () => request<Voice[]>("/api/voices"),
  addEspeakVoice: (body: { name: string } & Partial<EspeakSettings>) =>
    post<Voice>("/api/voices/espeak", body),
  addVoice: (name: string, entries: ClipUpload[]) =>
    upload("/api/voices", clipForm(entries, name)),
  addClips: (id: string, entries: ClipUpload[]) =>
    upload(`/api/voices/${id}/clips`, clipForm(entries)),
  deleteClip: (id: string, index: number) =>
    del<Voice>(`/api/voices/${id}/clips/${index}`),
  patchVoice: (id: string,
               body: { name?: string; active?: number | "all"; clip?: number; ref_text?: string;
                       espeak?: Partial<EspeakSettings> }) =>
    patch<Voice>(`/api/voices/${id}`, body),
  deleteVoice: (id: string) => del<{ ok: boolean }>(`/api/voices/${id}`),

  samples: () => request<Sample[]>("/api/samples"),
  deleteSample: (name: string) => del<{ ok: boolean }>(`/api/samples/${encodeURIComponent(name)}`),
  uploadSample: async (file: File) => {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch("/api/samples", { method: "POST", body: form });
    if (!res.ok) throw new ApiError("upload failed", res.status);
    return res.json() as Promise<Sample>;
  },

  favorites: () => request<FavoriteGroup[]>("/api/favorites"),
};

export const segmentAudioUrl = (id: string, take: string | null) =>
  `/api/segments/${id}/audio?t=${take ?? ""}`;
export const segmentDownloadUrl = (id: string) => `/api/segments/${id}/audio?download=1`;
export const takeAudioUrl = (take: string) => `/api/takes/${take}/audio`;
export const takeDownloadUrl = (take: string) => `/api/takes/${take}/audio?download=1`;
export const sampleAudioUrl = (name: string) =>
  `/api/samples/${encodeURIComponent(name)}/audio`;
/** `clip` -1 is the joined reference. */
export const voiceAudioUrl = (id: string, clip = 0) =>
  `/api/voices/${id}/audio?clip=${clip}`;
export const composeAudioUrl = (id: string) => `/api/composes/${id}/audio`;
export const composeDownloadUrl = (id: string) => `/api/composes/${id}/download`;

export const isSegment = (item: Item): item is Segment => item.kind === "segment";

/** Is there anything to hear? A segment needs a take; an insert needs a
 *  non-zero duration, which the server reports as 0 for a pause of 0 seconds
 *  and for a sample whose file has gone missing. */
export const playable = (item: Item): boolean =>
  isSegment(item) ? Boolean(item.active_take) : item.duration > 0;
