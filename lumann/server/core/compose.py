"""Assemble the timeline into one file with ffmpeg's concat demuxer.

Compose runs while narration continues. It snapshots the timeline when asked,
so segments that finish mid-compose are simply not in that snapshot — which is
also why the manifest records the exact take id used for every segment: a
finished file can always be traced back to what produced it.

Only the active take of each segment is ever read. Other takes are archive.

Every subprocess call passes stdin=DEVNULL. A background process group that
touches the terminal gets SIGTTIN and freezes; an 8-hour overnight run was lost
to exactly that.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time

from . import paths, projects
from ..jobs import events

DEVNULL = subprocess.DEVNULL
_registry = {}
_registry_lock = threading.Lock()

_OUT_TIME = re.compile(r"out_time=(\d+):(\d+):(\d+\.\d+)")


def _run(cmd, **kwargs):
    return subprocess.run(cmd, stdin=DEVNULL, capture_output=True, text=True, **kwargs)


def probe_rate(path, default="24000"):
    out = _run(["ffprobe", "-v", "error", "-show_entries", "stream=sample_rate",
                "-of", "csv=p=0", path]).stdout.strip()
    return out.splitlines()[0].strip() if out else default


def probe_duration(path):
    out = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "csv=p=0", path]).stdout.strip()
    try:
        return float(out)
    except (TypeError, ValueError):
        return 0.0


def snapshot(project):
    """-> ([step], total_seconds). A step is one file in the concat list."""
    steps = []
    for item in project["timeline"]:
        if item["kind"] == "segment":
            take = projects.active_take(item)
            if not take:
                continue
            path = paths.take_path(project["id"], item["id"], take["id"])
            if not os.path.exists(path):
                continue
            steps.append({"kind": "segment", "id": item["id"], "take": take["id"],
                          "path": path, "duration": take.get("duration") or 0.0})
        else:
            if item.get("insert_type") == "silence":
                steps.append({"kind": "silence", "id": item["id"],
                              "duration": float(item.get("seconds") or 0.0)})
            else:
                path = paths.sample_path(item.get("sample") or "")
                if not os.path.exists(path):
                    continue
                steps.append({"kind": "sample", "id": item["id"], "path": path,
                              "duration": item.get("duration") or probe_duration(path)})
    return steps


def start(project, fmt="m4a"):
    """Kick off a compose in a background thread. -> the compose record."""
    pid = project["id"]
    compose_id = projects.new_id()
    steps = snapshot(project)
    segments_total = len([i for i in project["timeline"] if i["kind"] == "segment"])
    skipped = segments_total - len([s for s in steps if s["kind"] == "segment"])
    gap = float(project.get("gap_seconds") or 0.0)
    total = sum(s["duration"] for s in steps) + gap * max(len(steps) - 1, 0)

    record = {
        "id": compose_id,
        "project": pid,
        "format": fmt,
        "status": "running",
        "progress": 0.0,
        "created_at": projects.now(),
        "steps": len(steps),
        "skipped": skipped,
        "total_duration": round(total, 2),
        "determinate": fmt != "wav",     # -c copy finishes in about a second
        "error": None,
        "file": None,
    }
    with _registry_lock:
        _registry[compose_id] = record

    if not steps:
        record["status"] = "failed"
        record["error"] = "nothing recorded yet"
        events.compose_event(compose_id, pid, "failed", 0.0, error=record["error"])
        return record

    thread = threading.Thread(target=_compose, args=(project, record, steps, gap),
                              daemon=True, name="compose-" + compose_id)
    thread.start()
    events.compose_event(compose_id, pid, "running", 0.0,
                         total_duration=record["total_duration"])
    return record


def _compose(project, record, steps, gap):
    pid = project["id"]
    workdir = tempfile.mkdtemp(prefix="lumann-compose-")
    try:
        rate = probe_rate(next(s["path"] for s in steps if s.get("path")))
        listing = _build_listing(workdir, steps, gap, rate)

        os.makedirs(paths.composes_dir(pid), exist_ok=True)
        ext = record["format"]
        final = os.path.join(paths.composes_dir(pid), f"{record['id']}.{ext}")
        tmp = final + ".tmp." + ext

        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
               "-f", "concat", "-safe", "0", "-i", listing]
        if ext == "wav":
            cmd += ["-c", "copy"]
        else:
            cmd += ["-c:a", "aac", "-b:a", "96k"]
        cmd += ["-progress", "pipe:1", "-nostats", tmp]

        code = _run_with_progress(cmd, record, pid)
        if code != 0:
            raise RuntimeError(record.get("error") or f"ffmpeg exited {code}")

        os.replace(tmp, final)
        record["file"] = final
        record["progress"] = 1.0
        record["duration"] = probe_duration(final)
        record["size"] = os.path.getsize(final)
        # Manifest first: `status: done` is what everything else waits on, so
        # flipping it before the manifest exists hands out a compose that
        # cannot be traced back to the takes that made it.
        _write_manifest(pid, record, steps)
        record["status"] = "done"
        projects.log_event(pid, "compose", compose=record["id"], format=ext,
                           steps=len(steps), skipped=record["skipped"])
        events.compose_event(record["id"], pid, "done", 1.0,
                             duration=record["duration"], size=record["size"],
                             skipped=record["skipped"])
    except Exception as exc:                       # noqa: BLE001 - surface, don't crash
        record["status"] = "failed"
        record["error"] = str(exc)
        events.compose_event(record["id"], pid, "failed", record.get("progress") or 0.0,
                             error=str(exc))
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _build_listing(workdir, steps, gap, rate):
    """Write the concat list, generating gaps and normalising samples.

    Everything must be pcm_s16le mono at the same rate or `-c copy` refuses.
    """
    gap_file = None
    if gap > 0:
        gap_file = os.path.join(workdir, "_gap.wav")
        _silence(gap_file, gap, rate)

    normalised = {}
    lines = []
    for i, step in enumerate(steps):
        if step["kind"] == "silence":
            path = os.path.join(workdir, f"_silence_{i}.wav")
            _silence(path, step["duration"], rate)
        elif step["kind"] == "sample":
            path = normalised.get(step["path"])
            if path is None:
                path = os.path.join(workdir, f"_sample_{len(normalised)}.wav")
                _normalise(step["path"], path, rate)
                normalised[step["path"]] = path
        else:
            path = step["path"]
        lines.append(f"file '{_escape(path)}'")
        if gap_file and i != len(steps) - 1:
            lines.append(f"file '{_escape(gap_file)}'")

    listing = os.path.join(workdir, "concat.txt")
    with open(listing, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return listing


def _escape(path):
    return path.replace("\\", "\\\\").replace("'", r"'\''")


def _silence(path, seconds, rate):
    _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
          "-i", f"anullsrc=r={rate}:cl=mono", "-t", f"{max(seconds, 0.01):.3f}",
          "-c:a", "pcm_s16le", path], check=True)


def _normalise(src, dst, rate):
    _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", src,
          "-ac", "1", "-ar", str(rate), "-c:a", "pcm_s16le", dst], check=True)


def _run_with_progress(cmd, record, pid):
    """Run ffmpeg, translating -progress output into compose events."""
    proc = subprocess.Popen(cmd, stdin=DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, bufsize=1)
    total = record["total_duration"] or 0.0
    last_sent = 0.0
    for line in proc.stdout:
        match = _OUT_TIME.search(line)
        if not match or not total:
            continue
        h, m, s = match.groups()
        seconds = int(h) * 3600 + int(m) * 60 + float(s)
        progress = max(0.0, min(seconds / total, 0.999))
        record["progress"] = round(progress, 4)
        now = time.time()
        if now - last_sent > 0.2:                  # don't flood the SSE stream
            last_sent = now
            events.compose_event(record["id"], pid, "running", record["progress"])
    proc.wait()
    if proc.returncode != 0:
        record["error"] = (proc.stderr.read() or "").strip()[-400:]
    return proc.returncode


def _write_manifest(pid, record, steps):
    # Only ever called on success, and deliberately called before the record's
    # own status flips — so the status is stated here rather than copied.
    manifest = {
        **{k: v for k, v in record.items() if k not in ("file", "status")},
        "status": "done",
        "file": os.path.basename(record["file"]) if record.get("file") else None,
        "timeline": [{"kind": s["kind"], "id": s["id"], "take": s.get("take"),
                      "duration": s["duration"]} for s in steps],
    }
    path = os.path.join(paths.composes_dir(pid), record["id"] + ".json")
    with open(path + ".tmp", "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=1)
    os.replace(path + ".tmp", path)


def get(compose_id):
    with _registry_lock:
        record = _registry.get(compose_id)
    if record:
        return record
    for pid in projects.list_ids():
        path = os.path.join(paths.composes_dir(pid), compose_id + ".json")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
    return None


def list_for(pid):
    """In-flight composes plus finished ones on disk, newest first."""
    out = {}
    directory = paths.composes_dir(pid)
    if os.path.isdir(directory):
        for name in os.listdir(directory):
            if not name.endswith(".json"):
                continue
            try:
                with open(os.path.join(directory, name), encoding="utf-8") as fh:
                    record = json.load(fh)
            except (OSError, ValueError):
                continue
            record.pop("timeline", None)
            out[record["id"]] = record
    with _registry_lock:
        for record in _registry.values():
            if record["project"] == pid:
                out[record["id"]] = {k: v for k, v in record.items() if k != "steps_detail"}
    return sorted(out.values(), key=lambda r: r.get("created_at") or "", reverse=True)


def file_path(record):
    if record.get("file"):
        candidate = record["file"]
        if os.path.isabs(candidate) and os.path.exists(candidate):
            return candidate
        candidate = os.path.join(paths.composes_dir(record["project"]),
                                 os.path.basename(candidate))
        if os.path.exists(candidate):
            return candidate
    guess = os.path.join(paths.composes_dir(record["project"]),
                         f"{record['id']}.{record.get('format', 'm4a')}")
    return guess if os.path.exists(guess) else None


def delete(compose_id):
    record = get(compose_id)
    if not record:
        return False
    path = file_path(record)
    if path:
        try:
            os.remove(path)
        except OSError:
            pass
    manifest = os.path.join(paths.composes_dir(record["project"]), compose_id + ".json")
    try:
        os.remove(manifest)
    except OSError:
        pass
    with _registry_lock:
        _registry.pop(compose_id, None)
    return True
