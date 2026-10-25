"""Projects, source text, reformatting."""
import os

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel

from ..core import estimate, paths, projects, reindex, takes, textprep, voices
from ..jobs import events
from ..jobs.runner import runner

router = APIRouter(prefix="/api")

# Staged reformats, keyed by project. Held in memory between preview and apply
# so the user confirms exactly what they were shown.
_staged = {}


class CreateProject(BaseModel):
    title: str = ""
    text: str = ""
    max_words: int | None = None
    target: int | None = None
    hard_max: int | None = None
    yo: bool | None = None


class SourceUpdate(BaseModel):
    text: str


class FormatRequest(BaseModel):
    text: str = ""


class ReformatRequest(BaseModel):
    text: str | None = None
    preformatted: bool = False
    max_words: int | None = None
    target: int | None = None
    hard_max: int | None = None
    yo: bool | None = None


class Settings(BaseModel):
    title: str | None = None
    gap_seconds: float | None = None
    temperature: float | None = None
    retries: int | None = None
    voice: str | None = None


def load_or_404(pid: str) -> dict:
    if not projects.exists(pid):
        raise HTTPException(404, "project not found")
    return projects.load(pid)


def decorate(project: dict) -> dict:
    """project.json plus everything the UI derives from it."""
    queued = set(runner.queued_ids(project["id"]))
    timeline = []
    index = 0
    for item in project["timeline"]:
        row = dict(item)
        if item["kind"] == "segment":
            index += 1
            row["index"] = index
            row["effective_text"] = projects.effective_text(item)
            row["take_count"] = len(item.get("takes") or [])
            row["outdated_takes"] = sum(
                1 for t in item.get("takes") or [] if projects.take_is_outdated(item, t))
            row["in_queue"] = item["id"] in queued
        timeline.append(row)
    return {
        **{k: v for k, v in project.items() if k != "timeline"},
        "timeline": timeline,
        "stats": projects.stats(project),
        "estimate": estimate.compute(project),
    }


@router.get("/projects")
def list_projects():
    out = []
    for pid in projects.list_ids():
        try:
            out.append(projects.summary(pid))
        except (OSError, ValueError):
            continue
    return out


@router.post("/projects")
def create_project(body: CreateProject):
    if not body.text.strip():
        raise HTTPException(400, "no text")
    fmt = {"max_words": body.max_words, "target": body.target, "hard_max": body.hard_max,
           "yo": body.yo}
    project = projects.create(body.title, body.text, fmt=fmt)
    events.project_event(project["id"], "created")
    return decorate(project)


@router.get("/projects/{pid}")
def get_project(pid: str):
    return decorate(load_or_404(pid))


@router.delete("/projects/{pid}")
def delete_project(pid: str):
    load_or_404(pid)
    runner.clear(pid)
    projects.delete(pid)
    _staged.pop(pid, None)
    events.project_event(pid, "deleted")
    return {"ok": True}


@router.patch("/projects/{pid}")
def update_settings(pid: str, body: Settings):
    with projects.lock(pid):
        project = load_or_404(pid)
        if body.title is not None:
            project["title"] = body.title.strip() or project["title"]
        if body.gap_seconds is not None:
            project["gap_seconds"] = max(0.0, float(body.gap_seconds))
        tts = project.setdefault("tts_options", {})
        if body.temperature is not None:
            tts["temperature"] = float(body.temperature)
        if body.retries is not None:
            tts["retries"] = max(0, int(body.retries))
        if body.voice is not None:
            if voices.load(body.voice) is None:
                raise HTTPException(404, "voice not found")
            project["voice"] = body.voice
        projects.save(project)
    events.project_event(pid, "updated")
    return decorate(project)


@router.get("/projects/{pid}/source")
def get_source(pid: str):
    load_or_404(pid)
    with open(paths.source_txt(pid), encoding="utf-8") as fh:
        return {"text": fh.read()}


@router.put("/projects/{pid}/source")
def put_source(pid: str, body: SourceUpdate):
    """Saves source.txt only. Nothing is re-segmented until reformat/apply."""
    load_or_404(pid)
    projects._write_atomic(paths.source_txt(pid), body.text)
    return {"ok": True, "length": len(body.text)}


@router.get("/projects/{pid}/formatted")
def get_formatted(pid: str):
    project = load_or_404(pid)
    try:
        with open(paths.formatted_txt(pid), encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        text = ""
    spans = [{"id": s["id"], "start": s["char_start"], "end": s["char_end"]}
             for s in projects.segments(project)]
    return {"text": text, "spans": spans}


@router.get("/projects/{pid}/flags")
def get_flags(pid: str):
    project = load_or_404(pid)
    with open(paths.source_txt(pid), encoding="utf-8") as fh:
        source = fh.read()
    opts = project.get("format_options") or {}
    review = textprep.review(source, opts.get("max_words", 20), yo=bool(opts.get("yo", 1)))
    per_segment = []
    for seg in projects.segments(project):
        issues = textprep.issues(projects.effective_text(seg))
        if issues:
            per_segment.append({"id": seg["id"], "issues": issues})
    return {**review, "segments": per_segment}


@router.post("/projects/{pid}/format")
def format_text(pid: str, body: FormatRequest):
    """Run the formatting rules over arbitrary text. Nothing is written.

    What the editor needs before committing: the same text the reformat preview
    would segment, so the user can diff their edit against it and pick a side.
    The rules are the project's own, so the answer matches what applying would
    actually produce.
    """
    project = load_or_404(pid)
    from ..core.segmenter import build_segments, format_options
    opts = format_options(project.get("format_options"))
    formatted, _segments = build_segments(body.text, **opts)
    return {"text": formatted}


@router.post("/projects/{pid}/reformat/preview")
def reformat_preview(pid: str, body: ReformatRequest):
    project = load_or_404(pid)
    if body.text is not None:
        source = body.text
    elif body.preformatted:
        with open(paths.formatted_txt(pid), encoding="utf-8") as fh:
            source = fh.read()
    else:
        with open(paths.source_txt(pid), encoding="utf-8") as fh:
            source = fh.read()
    fmt = {"max_words": body.max_words, "target": body.target, "hard_max": body.hard_max,
           "yo": body.yo}
    preview, staged = reindex.plan_reindex(project, source, fmt=fmt,
                                           preformatted=body.preformatted)
    _staged[pid] = staged
    return preview


@router.post("/projects/{pid}/reformat/apply")
def reformat_apply(pid: str):
    with projects.lock(pid):
        project = load_or_404(pid)
        staged = _staged.pop(pid, None)
        if staged is None:
            raise HTTPException(409, "no preview to apply — run reformat/preview first")
        queued = set(runner.queued_ids(pid))
        if queued & set(staged["deleted"]):
            runner.clear(pid)
        project = reindex.apply_reindex(project, staged)
        stale = [s["id"] for s in projects.segments(project) if s["status"] == "stale"]
    # Stale means the text moved out from under the audio. Those are the jobs.
    if stale:
        runner.enqueue(project, stale, priority=1 if len(stale) > 50 else 0)
    events.project_event(pid, "reindexed")
    return decorate(projects.load(pid))


@router.get("/projects/{pid}/usage")
def usage(pid: str):
    load_or_404(pid)
    return projects.disk_usage(pid)


@router.post("/projects/{pid}/takes/prune")
def prune_takes(pid: str):
    """Delete every non-active take. The one-click disk reclaim."""
    with projects.lock(pid):
        project = load_or_404(pid)
        result = takes.delete_inactive(project)
        projects.save(project)
    events.project_event(pid, "pruned")
    return result
