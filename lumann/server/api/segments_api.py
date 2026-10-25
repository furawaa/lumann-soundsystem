"""Segments, tags, takes and inserts."""
import os
import random

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..core import estimate, paths, projects, takes
from ..jobs import events
from ..jobs.runner import RERECORD, runner
from . import audio
from .projects_api import decorate, load_or_404

router = APIRouter(prefix="/api")


class SegmentPatch(BaseModel):
    favorite: bool | None = None
    rerecord: bool | None = None
    text_override: str | None = None
    clear_override: bool = False


class TakePatch(BaseModel):
    note: str | None = None


class InsertCreate(BaseModel):
    after_id: str | None = None
    insert_type: str = "silence"
    seconds: float | None = 1.0
    sample: str | None = None


class InsertPatch(BaseModel):
    seconds: float | None = None
    sample: str | None = None
    after_id: str | None = None


def _find(item_id, kind="segment"):
    project, idx, item = projects.find_project_of_item(item_id)
    if item is None or item["kind"] != kind:
        raise HTTPException(404, f"{kind} not found")
    return project, idx, item


# --- segments ---------------------------------------------------------------

@router.patch("/segments/{segment_id}")
def patch_segment(segment_id: str, body: SegmentPatch):
    project, _idx, segment = _find(segment_id)
    with projects.lock(project["id"]):
        project = projects.load(project["id"])
        _idx, segment = projects.find_item(project, segment_id)
        if body.favorite is not None:
            segment["favorite"] = body.favorite
        if body.rerecord is not None:
            segment["rerecord"] = body.rerecord
        text_changed = body.clear_override or body.text_override is not None
        if body.clear_override:
            segment["text_override"] = None
            projects.refresh_hash(segment)
            projects.sync_status(segment)
        elif body.text_override is not None:
            segment["text_override"] = body.text_override or None
            projects.refresh_hash(segment)
            projects.sync_status(segment)
        if text_changed:
            # Keep formatted.txt in step: it is what gets spoken, so an edit
            # here has to be visible there and the offsets have to follow.
            projects.rebuild_formatted(project)
        projects.save(project)
        went_stale = text_changed and segment["status"] == "stale"

    # Marking for re-recording is not a sticky note: it puts the segment in the
    # queue, ahead of first-pass work. Un-marking takes it back out.
    if body.rerecord is True:
        runner.enqueue(project, [segment_id], priority=RERECORD)
    elif body.rerecord is False:
        runner.dequeue(project, [segment_id])

    # An edit that invalidated the audio is itself a job. Queue it, at the same
    # priority as an explicit mark: both mean "this needs re-recording".
    if went_stale:
        runner.enqueue(project, [segment_id], priority=RERECORD)

    project = projects.load(project["id"])
    _idx, segment = projects.find_item(project, segment_id)
    events.segment_event(project["id"], segment)
    return {"segment": segment, "stats": projects.stats(project)}


@router.post("/segments/{segment_id}/requeue")
def requeue(segment_id: str):
    """Force a re-record. Appends a take; never overwrites the current one."""
    project, _idx, segment = _find(segment_id)
    with projects.lock(project["id"]):
        project = projects.load(project["id"])
        runner.enqueue(project, [segment_id], priority=RERECORD)
    runner.start(project["id"])
    return {"ok": True, "queued": runner.queued_ids(project["id"])}


@router.post("/segments/{segment_id}/dequeue")
def dequeue(segment_id: str):
    """Drop one segment from the queue. Recorded counts are unaffected."""
    project, _idx, _segment = _find(segment_id)
    removed = runner.dequeue(project, [segment_id])
    project = projects.load(project["id"])
    _idx, segment = projects.find_item(project, segment_id)
    return {"ok": True, "removed": len(removed), "segment": segment}


def _export_name(project, segment, suffix=""):
    """0042_L0187.wav — segment number and source line; a snapshot, not an identity."""
    index = next((i for i, s in enumerate(projects.segments(project), start=1)
                  if s["id"] == segment["id"]), 0)
    return f"{index:04d}_L{segment.get('line', 0):04d}{suffix}.wav"


@router.get("/segments/{segment_id}/audio")
def segment_audio(segment_id: str, request: Request, download: bool = False):
    project, _idx, segment = _find(segment_id)
    take_id = segment.get("active_take")
    if not take_id:
        raise HTTPException(404, "no active take")
    return audio.serve(paths.take_path(project["id"], segment_id, take_id), request,
                       filename=_export_name(project, segment) if download else None,
                       download=download)


# --- takes ------------------------------------------------------------------

@router.get("/segments/{segment_id}/takes")
def list_takes(segment_id: str):
    _project, _idx, segment = _find(segment_id)
    return takes.listing(segment)


@router.post("/segments/{segment_id}/takes/{take_id}/promote")
def promote_take(segment_id: str, take_id: str):
    project, _idx, _segment = _find(segment_id)
    with projects.lock(project["id"]):
        project = projects.load(project["id"])
        _idx, segment = projects.find_item(project, segment_id)
        try:
            takes.promote(project, segment, take_id)
        except KeyError:
            raise HTTPException(404, "take not found")
        projects.save(project)
    events.segment_event(project["id"], segment)
    return {"segment": segment, "takes": takes.listing(segment)}


@router.patch("/segments/{segment_id}/takes/{take_id}")
def patch_take(segment_id: str, take_id: str, body: TakePatch):
    project, _idx, _segment = _find(segment_id)
    with projects.lock(project["id"]):
        project = projects.load(project["id"])
        _idx, segment = projects.find_item(project, segment_id)
        take = projects.find_take(segment, take_id)
        if take is None:
            raise HTTPException(404, "take not found")
        if body.note is not None:
            take["note"] = body.note or None
        projects.save(project)
    return takes.describe(segment, take)


@router.delete("/segments/{segment_id}/takes/{take_id}")
def delete_take(segment_id: str, take_id: str):
    project, _idx, _segment = _find(segment_id)
    with projects.lock(project["id"]):
        project = projects.load(project["id"])
        _idx, segment = projects.find_item(project, segment_id)
        try:
            takes.delete(project, segment, take_id)
        except KeyError:
            raise HTTPException(404, "take not found")
        except ValueError:
            raise HTTPException(409, "that is the active take — promote another one first")
        projects.save(project)
    events.segment_event(project["id"], segment)
    return {"ok": True, "takes": takes.listing(segment)}


@router.get("/takes/{take_id}/audio")
def take_audio(take_id: str, request: Request, download: bool = False):
    project, segment, take = projects.find_take_global(take_id)
    if take is None:
        raise HTTPException(404, "take not found")
    name = _export_name(project, segment, f"_take{take.get('n', 1)}") if download else None
    return audio.serve(paths.take_path(project["id"], segment["id"], take_id), request,
                       filename=name, download=download)


# --- inserts ----------------------------------------------------------------

def _insert_duration(insert):
    if insert["insert_type"] == "silence":
        return float(insert.get("seconds") or 0.0)
    path = paths.sample_path(insert.get("sample") or "")
    if not os.path.exists(path):
        return 0.0
    from ..core import compose
    return round(compose.probe_duration(path), 3)


@router.post("/projects/{pid}/inserts")
def create_insert(pid: str, body: InsertCreate):
    if body.insert_type not in ("silence", "sample"):
        raise HTTPException(400, "insert_type must be silence or sample")
    with projects.lock(pid):
        project = load_or_404(pid)
        insert = {
            "kind": "insert",
            "id": projects.new_id(),
            "insert_type": body.insert_type,
            "seconds": float(body.seconds) if body.insert_type == "silence" else None,
            "sample": body.sample if body.insert_type == "sample" else None,
        }
        if body.insert_type == "sample" and not body.sample:
            raise HTTPException(400, "sample required")
        insert["duration"] = _insert_duration(insert)

        if body.after_id:
            idx, anchor = projects.find_item(project, body.after_id)
            if anchor is None:
                raise HTTPException(404, "anchor not found")
            project["timeline"].insert(idx + 1, insert)
        else:
            project["timeline"].insert(0, insert)
        projects.save(project)
    events.project_event(pid, "insert_added")
    return {"insert": insert, "project": decorate(project)}


class InsertScatter(BaseModel):
    count: int
    samples: list[str]
    min_gap_seconds: float | None = None


@router.post("/projects/{pid}/inserts/scatter")
def scatter_inserts(pid: str, body: InsertScatter):
    """Drop `count` random samples across the book, no two closer than a gap.

    The gap is measured in seconds of the finished audio, not in segments: two
    samples separated by four one-second lines are close together no matter how
    many segments sit between them. Unrecorded segments are counted at the
    project's own measured rate, so scattering works before anything is voiced.

    Placing fewer than asked is a normal outcome — a short book with a long gap
    simply has fewer places to put them — so the count actually placed comes
    back rather than an error.
    """
    if body.count < 1:
        raise HTTPException(400, "count must be at least 1")
    if not body.samples:
        raise HTTPException(400, "pick at least one sample")
    for name in body.samples:
        if not os.path.exists(paths.sample_path(name)):
            raise HTTPException(404, f"sample not found: {name}")

    gap = max(0.0, float(body.min_gap_seconds or 0.0))
    with projects.lock(pid):
        project = load_or_404(pid)
        anchors, taken = _timeline_positions(project)
        if not anchors:
            raise HTTPException(400, "nothing to scatter between")

        chosen = []
        for seg_id, at in random.sample(anchors, len(anchors)):
            if len(chosen) >= body.count:
                break
            if gap and any(abs(at - other) < gap for other in taken):
                continue
            chosen.append((seg_id, at))
            taken.append(at)

        # One scatter is one batch, so it can be reviewed and undone as a unit.
        # Placing forty samples blind and having no way back would make the
        # feature unusable, whatever it does to the audio.
        batch = projects.new_id()
        made = []
        for seg_id, _at in chosen:
            insert = {
                "kind": "insert",
                "id": projects.new_id(),
                "insert_type": "sample",
                "seconds": None,
                "sample": random.choice(body.samples),
                "batch": batch,
                "created_at": projects.now(),
            }
            insert["duration"] = _insert_duration(insert)
            idx, _anchor = projects.find_item(project, seg_id)
            project["timeline"].insert(idx + 1, insert)
            made.append(insert)
        if made:
            projects.save(project)

    if made:
        events.project_event(pid, "insert_added")
    return {"placed": len(made), "asked": body.count, "batch": batch if made else None,
            "project": decorate(project)}


@router.delete("/projects/{pid}/inserts/batch/{batch}")
def delete_insert_batch(pid: str, batch: str):
    """Undo one scatter: take back exactly what that run put in.

    Anything the user has since deleted by hand is simply not there any more;
    anything they moved is still theirs to keep or drop, and moving does not
    change which batch it came from.
    """
    with projects.lock(pid):
        project = load_or_404(pid)
        before = len(project["timeline"])
        project["timeline"] = [item for item in project["timeline"]
                               if not (item["kind"] == "insert" and item.get("batch") == batch)]
        removed = before - len(project["timeline"])
        if removed:
            projects.save(project)
    if removed:
        events.project_event(pid, "insert_deleted")
    return {"ok": True, "removed": removed, "project": decorate(project)}


def _timeline_positions(project):
    """-> ([(segment id, when it ends)], [where inserts already sit]), in seconds.

    Unrecorded segments have no duration yet, so they are estimated from their
    length at the same rate the ETA uses.
    """
    gap = project.get("gap_seconds") or 0.0
    anchors, taken, at = [], [], 0.0
    for item in project["timeline"]:
        if item["kind"] == "insert":
            taken.append(at)
            at += (item.get("duration") or 0.0) + gap
            continue
        take = projects.active_take(item)
        if take and take.get("duration"):
            at += float(take["duration"])
        else:
            at += len(projects.effective_text(item)) * estimate.AUDIO_PER_CHAR
        at += gap
        anchors.append((item["id"], at))
    return anchors, taken


@router.patch("/inserts/{insert_id}")
def patch_insert(insert_id: str, body: InsertPatch):
    project, _idx, _item = _find(insert_id, kind="insert")
    pid = project["id"]
    with projects.lock(pid):
        project = projects.load(pid)
        idx, insert = projects.find_item(project, insert_id)
        if body.seconds is not None and insert["insert_type"] == "silence":
            insert["seconds"] = max(0.0, float(body.seconds))
        if body.sample is not None and insert["insert_type"] == "sample":
            insert["sample"] = body.sample
        insert["duration"] = _insert_duration(insert)

        if body.after_id is not None:
            project["timeline"].pop(idx)
            if body.after_id == "":
                project["timeline"].insert(0, insert)
            else:
                anchor_idx, anchor = projects.find_item(project, body.after_id)
                if anchor is None:
                    raise HTTPException(404, "anchor not found")
                project["timeline"].insert(anchor_idx + 1, insert)
        projects.save(project)
    events.project_event(pid, "insert_updated")
    return {"insert": insert, "project": decorate(project)}


@router.delete("/inserts/{insert_id}")
def delete_insert(insert_id: str):
    project, _idx, _item = _find(insert_id, kind="insert")
    pid = project["id"]
    with projects.lock(pid):
        project = projects.load(pid)
        idx, _insert = projects.find_item(project, insert_id)
        project["timeline"].pop(idx)
        projects.save(project)
    events.project_event(pid, "insert_deleted")
    return {"ok": True, "project": decorate(project)}
