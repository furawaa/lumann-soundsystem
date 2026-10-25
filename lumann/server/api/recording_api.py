"""Start, stop and inspect the narration queue."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..core import estimate, projects
from ..jobs.runner import runner
from .projects_api import load_or_404

router = APIRouter(prefix="/api")

SCOPES = ("all", "stale", "rerecord", "failed", "remaining")


class RecordStart(BaseModel):
    scope: str | list[str] = "remaining"


def select(project, scope):
    """-> segment ids to record, in timeline order."""
    segs = projects.segments(project)
    if isinstance(scope, list):
        wanted = set(scope)
        return [s["id"] for s in segs if s["id"] in wanted]
    if scope == "all":
        return [s["id"] for s in segs]
    if scope == "stale":
        return [s["id"] for s in segs if s["status"] == "stale"]
    if scope == "rerecord":
        return [s["id"] for s in segs if s.get("rerecord")]
    if scope == "failed":
        return [s["id"] for s in segs if s["status"] == "failed"]
    # "remaining": everything that has no valid audio yet, plus explicit marks
    return [s["id"] for s in segs
            if s["status"] in ("pending", "stale", "failed", "queued") or s.get("rerecord")]


@router.post("/projects/{pid}/record/start")
def record_start(pid: str, body: RecordStart):
    if isinstance(body.scope, str) and body.scope not in SCOPES:
        raise HTTPException(400, f"scope must be one of {SCOPES} or a list of ids")
    # Before choosing what to record: free anything left claiming to be
    # recording or queued with nothing behind it. Otherwise such a segment is
    # invisible to every scope and can never be recorded again.
    runner.reconcile(pid)
    with projects.lock(pid):
        project = load_or_404(pid)
        ids = select(project, body.scope)
        added = runner.enqueue(project, ids)
    runner.start(pid)
    return {"queued": len(runner.queued_ids(pid)), "added": len(added),
            "state": runner.state()}


@router.post("/projects/{pid}/record/stop")
def record_stop(pid: str):
    load_or_404(pid)
    runner.stop(pid)
    return {"ok": True, "state": runner.state()}


@router.post("/projects/{pid}/record/clear")
def record_clear(pid: str):
    load_or_404(pid)
    dropped = runner.clear(pid)
    return {"ok": True, "dropped": dropped, "state": runner.state()}


@router.get("/projects/{pid}/queue")
def get_queue(pid: str):
    project = load_or_404(pid)
    jobs = runner.queued_jobs(pid)
    position = {sid: i for i, (sid, _p) in enumerate(jobs)}
    priority = {sid: p for sid, p in jobs}
    index = {seg["id"]: i + 1 for i, seg in enumerate(projects.segments(project))}
    rows = []
    for seg in projects.segments(project):
        if seg["id"] in position or seg["status"] in ("queued", "recording"):
            rows.append({
                "id": seg["id"],
                "index": index[seg["id"]],
                "status": seg["status"],
                "text": projects.effective_text(seg),
                "chars": len(projects.effective_text(seg)),
                "position": position.get(seg["id"]),
                # A re-record is work on something already voiced; the UI shows
                # the two groups separately because they mean different things.
                "rerecord": priority.get(seg["id"]) == 0 or bool(seg.get("rerecord")),
                "favorite": seg.get("favorite"),
            })
    rows.sort(key=lambda r: (r["status"] != "recording",
                             r["position"] if r["position"] is not None else 1e9))
    return {"queue": rows, "state": runner.state(), "estimate": estimate.compute(project)}


@router.get("/queue")
def global_queue():
    """The queue across every project, in the order it will actually be recorded.

    A per-project queue cannot express this: two books share one worker, and a
    re-record in one of them overtakes first-pass work in the other, so the
    real order only exists as a single list.
    """
    cache = {}

    def project_of(pid):
        if pid not in cache:
            try:
                project = projects.load(pid)
            except OSError:
                return None
            cache[pid] = (project, {seg["id"]: (i + 1, seg)
                                    for i, seg in enumerate(projects.segments(project))})
        return cache[pid]

    rows = []
    for job in runner.all_jobs():
        found = project_of(job["project"])
        if found is None:
            continue
        project, index = found
        place = index.get(job["segment"])
        if place is None:
            continue
        position, segment = place
        text = projects.effective_text(segment)
        rows.append({
            "id": segment["id"],
            "project": project["id"],
            "project_title": project.get("title") or project["id"],
            "index": position,
            "status": segment["status"],
            "text": text,
            "chars": len(text),
            "rerecord": job["rerecord"],
            "paused": job["paused"],
            "favorite": bool(segment.get("favorite")),
        })
    return {"queue": rows, "state": runner.state()}


@router.get("/queue/projects")
def queue_projects():
    """One row per book with work waiting, in the order the scheduler takes them."""
    state = runner.state()
    current = (state["current"] or {}).get("project")
    counts, rerecords = {}, {}
    for job in runner.all_jobs():
        pid = job["project"]
        counts[pid] = counts.get(pid, 0) + 1
        if job["rerecord"]:
            rerecords[pid] = rerecords.get(pid, 0) + 1

    rows = []
    for pid in runner.project_order():
        try:
            project = projects.load(pid)
        except OSError:
            continue
        stats = projects.stats(project)
        rows.append({
            "project": pid,
            "title": project.get("title") or pid,
            "queued": counts.get(pid, 0),
            "rerecord_queued": rerecords.get(pid, 0),
            "recording": pid == current,
            "paused": pid in state["paused"],
            "done": stats["done"],
            "segments": stats["segments"],
            "eta_seconds": estimate.compute(project)["eta_seconds"],
        })
    return {"projects": rows, "state": state}


class ProjectOrder(BaseModel):
    ids: list[str]


@router.post("/queue/projects/order")
def set_queue_order(body: ProjectOrder):
    return {"order": runner.set_project_order(body.ids), "state": runner.state()}


@router.post("/record/stop-all")
def stop_everything():
    """One button for every book at once — the worker dies and 4 GB come back."""
    runner.stop()
    return {"ok": True, "state": runner.state()}


@router.get("/worker")
def worker_state():
    return runner.state()
