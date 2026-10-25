"""project.json is the single source of truth. This module owns reading and
writing it.

Every write goes through `save()`: temp file, fsync, os.replace. A half-written
project.json would mismatch text against audio for a whole book, and the resume
logic would believe it.
"""
import json
import os
import re
import shutil
import threading
import time
import uuid

from . import paths, textprep, voices
from .segmenter import build_segments, format_options

DEFAULT_TTS_OPTIONS = {"temperature": 0.8, "retries": 2}
DEFAULT_GAP = 0.45

# One lock per project id. Read-modify-write of project.json happens from
# request handlers and from the recording runner thread at the same time.
_locks = {}
_locks_guard = threading.Lock()


def lock(pid: str) -> threading.RLock:
    with _locks_guard:
        if pid not in _locks:
            _locks[pid] = threading.RLock()
        return _locks[pid]


# --- ids --------------------------------------------------------------------

def new_id() -> str:
    return uuid.uuid4().hex[:12]


def slugify(title: str) -> str:
    base = re.sub(r"[^\w\-]+", "-", (title or "").strip(), flags=re.UNICODE).strip("-").lower()
    base = base[:48] or "project"
    pid, n = base, 2
    while os.path.exists(paths.project_dir(pid)):
        pid = f"{base}-{n}"
        n += 1
    return pid


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# --- atomic io --------------------------------------------------------------

def _write_atomic(path: str, data: str) -> None:
    tmp = path + ".tmp"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def save(project: dict) -> dict:
    _write_atomic(paths.project_json(project["id"]),
                  json.dumps(project, ensure_ascii=False, indent=1))
    return project


def load(pid: str) -> dict:
    with open(paths.project_json(pid), encoding="utf-8") as fh:
        return json.load(fh)


def exists(pid: str) -> bool:
    return os.path.isfile(paths.project_json(pid))


def log_event(pid: str, kind: str, **fields) -> None:
    """Append-only audit log. Never fails a request."""
    try:
        line = json.dumps({"at": now(), "event": kind, **fields}, ensure_ascii=False)
        with open(paths.events_log(pid), "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


# --- creation ---------------------------------------------------------------

def make_segment(seg: dict) -> dict:
    """Timeline segment from a segmenter output dict."""
    return {
        "kind": "segment",
        "id": new_id(),
        "line": seg["line"],
        "char_start": seg["char_start"],
        "char_end": seg["char_end"],
        "text": seg["text"],
        "text_override": None,
        "text_hash": textprep.text_hash(seg["text"]),
        "status": "pending",
        "moved": False,
        "active_take": None,
        "takes": [],
        "favorite": False,
        "rerecord": False,
        "error": None,
    }


def effective_text(item: dict) -> str:
    return item.get("text_override") or item.get("text") or ""


def refresh_hash(item: dict) -> None:
    item["text_hash"] = textprep.text_hash(effective_text(item))


def create(title: str, text: str, fmt=None, voice=None) -> dict:
    paths.ensure_dirs()
    pid = slugify(title)
    opts = format_options(fmt)
    formatted, segs = build_segments(text, **opts)

    project = {
        "id": pid,
        "title": (title or "").strip() or pid,
        "created_at": now(),
        "voice": voice or voices.default_for(text),
        "format_options": opts,
        "tts_options": dict(DEFAULT_TTS_OPTIONS),
        "gap_seconds": DEFAULT_GAP,
        "timeline": [make_segment(s) for s in segs],
    }
    os.makedirs(paths.audio_dir(pid), exist_ok=True)
    os.makedirs(paths.composes_dir(pid), exist_ok=True)
    _write_atomic(paths.source_txt(pid), text)
    _write_atomic(paths.formatted_txt(pid), formatted)
    save(project)
    log_event(pid, "created", title=project["title"], segments=len(segs))
    return project


def delete(pid: str) -> None:
    shutil.rmtree(paths.project_dir(pid), ignore_errors=True)


def list_ids():
    if not os.path.isdir(paths.PROJECTS_DIR):
        return []
    return sorted(d for d in os.listdir(paths.PROJECTS_DIR)
                  if os.path.isfile(os.path.join(paths.PROJECTS_DIR, d, "project.json")))


# --- lookups ----------------------------------------------------------------

def segments(project: dict):
    return [i for i in project["timeline"] if i["kind"] == "segment"]


def find_item(project: dict, item_id: str):
    for idx, item in enumerate(project["timeline"]):
        if item["id"] == item_id:
            return idx, item
    return -1, None


def find_project_of_item(item_id: str):
    """-> (project, index, item). Segment/insert ids are globally unique."""
    for pid in list_ids():
        project = load(pid)
        idx, item = find_item(project, item_id)
        if item is not None:
            return project, idx, item
    return None, -1, None


def find_take_global(take_id: str):
    """-> (project, segment, take). Take ids are globally unique."""
    for pid in list_ids():
        project = load(pid)
        for segment in segments(project):
            for take in segment.get("takes") or []:
                if take["id"] == take_id:
                    return project, segment, take
    return None, None, None


def find_take(segment: dict, take_id: str):
    for take in segment.get("takes", []):
        if take["id"] == take_id:
            return take
    return None


def active_take(segment: dict):
    return find_take(segment, segment.get("active_take")) if segment.get("active_take") else None


def take_is_outdated(segment: dict, take: dict) -> bool:
    return take.get("text_hash") != segment.get("text_hash")


def sync_status(segment: dict, force: bool = False) -> None:
    """Recompute done/stale from the active take.

    In-flight states belong to the runner, so they are left alone unless the
    caller is the runner itself putting a killed job back to rest (`force`).
    """
    if segment["status"] in ("queued", "recording") and not force:
        return
    take = active_take(segment)
    if take is None:
        segment["status"] = "failed" if segment.get("error") else "pending"
    elif take_is_outdated(segment, take):
        segment["status"] = "stale"
    else:
        segment["status"] = "done"


# --- derived ----------------------------------------------------------------

def rebuild_formatted(project: dict) -> str:
    """Rewrite formatted.txt and the char offsets from the timeline.

    formatted.txt is what actually gets spoken, so a per-segment edit has to
    land in it. Without this the text panel and the file disagree about what
    the book says, and the offsets used for highlighting drift.

    Segments of one paragraph share a `line`, which is what separates a space
    from a paragraph break here.
    """
    from .segmenter import INTER, INTRA

    parts, cursor, prev_line = [], 0, None
    for seg in segments(project):
        text = effective_text(seg)
        if parts:
            sep = INTRA if seg.get("line") == prev_line else INTER
            parts.append(sep)
            cursor += len(sep)
        seg["char_start"] = cursor
        seg["char_end"] = cursor + len(text)
        parts.append(text)
        cursor += len(text)
        prev_line = seg.get("line")

    formatted = "".join(parts)
    _write_atomic(paths.formatted_txt(project["id"]), formatted)
    return formatted


def stats(project: dict) -> dict:
    segs = segments(project)
    counts = {}
    for s in segs:
        counts[s["status"]] = counts.get(s["status"], 0) + 1

    recorded_seconds = 0.0
    takes_total = 0
    for s in segs:
        take = active_take(s)
        if take:
            recorded_seconds += take.get("duration") or 0.0
        takes_total += len(s.get("takes", []))

    inserts = [i for i in project["timeline"] if i["kind"] == "insert"]
    insert_seconds = sum(i.get("duration") or 0.0 for i in inserts)
    chars_total = sum(len(effective_text(s)) for s in segs)
    chars_left = sum(len(effective_text(s)) for s in segs
                     if s["status"] in ("pending", "queued", "stale", "recording", "failed"))

    return {
        "segments": len(segs),
        "inserts": len(inserts),
        "counts": counts,
        "done": counts.get("done", 0),
        "stale": counts.get("stale", 0),
        "failed": counts.get("failed", 0),
        "pending": counts.get("pending", 0) + counts.get("queued", 0) + counts.get("recording", 0),
        "favorites": sum(1 for s in segs if s.get("favorite")),
        "rerecord": sum(1 for s in segs if s.get("rerecord")),
        "takes": takes_total,
        "chars_total": chars_total,
        "chars_left": chars_left,
        "recorded_seconds": round(recorded_seconds, 2),
        "insert_seconds": round(insert_seconds, 2),
    }


def disk_usage(pid: str) -> dict:
    """Bytes on disk, split by active vs. archived takes — the thing that grows
    without bound once every re-record is kept."""
    try:
        project = load(pid)
    except OSError:
        return {"active": 0, "archived": 0, "composes": 0, "trash": 0}

    active_files = set()
    for s in segments(project):
        if s.get("active_take"):
            active_files.add(paths.take_path(pid, s["id"], s["active_take"]))

    active = archived = 0
    for root, dirs, files in os.walk(paths.audio_dir(pid)):
        if os.path.basename(root) == "_trash":
            dirs[:] = []
            continue
        for name in files:
            if not name.endswith(".wav"):
                continue
            full = os.path.join(root, name)
            size = _size(full)
            if full in active_files:
                active += size
            else:
                archived += size

    return {
        "active": active,
        "archived": archived,
        "composes": _dir_size(paths.composes_dir(pid)),
        "trash": _dir_size(paths.trash_dir(pid)),
    }


def _size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _dir_size(path: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            total += _size(os.path.join(root, name))
    return total


def summary(pid: str) -> dict:
    project = load(pid)
    return {
        "id": project["id"],
        "title": project["title"],
        "created_at": project["created_at"],
        "stats": stats(project),
    }
