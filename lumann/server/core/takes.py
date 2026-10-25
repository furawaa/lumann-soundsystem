"""Takes are append-only. Nothing in here overwrites audio.

Generation is stochastic: re-running the same text gives an audibly different
take, and the run-to-run spread is wider than most text edits. So a "fix" is
often worse than what it replaced, and the old take has to survive. Everything
here follows from that:

  - a new recording is a new file with a new id, never a replacement;
  - `n` counts recordings for a segment and is never reused, even after delete;
  - `active_take` is the only pointer that moves; it is what the list plays and
    what compose consumes;
  - deleting the active take is refused — promote another one first.
"""
import os

from . import paths, projects


def next_n(segment) -> int:
    return max((t.get("n") or 0) for t in segment.get("takes") or []) + 1 if segment.get("takes") else 1


def append_take(project, segment, tmp_path, duration, text_hash,
                temperature=None, gen_seconds=None, make_active=True,
                voice=None, voice_name=None):
    """Move a finished .tmp into place as a new take. -> the take dict.

    The rename is the commit point: until it happens the file is a `.tmp` that
    the startup sweep will remove, and the previous active take is untouched.
    """
    take_id = projects.new_id()
    dest = paths.take_path(project["id"], segment["id"], take_id)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if os.path.exists(dest):                       # ids are uuid4; belt and braces
        raise FileExistsError(dest)
    os.replace(tmp_path, dest)

    take = {
        "id": take_id,
        "n": next_n(segment),
        "created_at": projects.now(),
        "duration": round(float(duration), 3),
        "text_hash": text_hash,
        "temperature": temperature,
        # Which voice said it. Kept as a name as well as an id: the point of a
        # take history is comparing voices, and a deleted voice must not turn
        # its takes into anonymous ones.
        "voice": voice,
        "voice_name": voice_name,
        "gen_seconds": round(float(gen_seconds), 3) if gen_seconds else None,
        "note": None,
    }
    segment.setdefault("takes", []).append(take)
    if make_active or not segment.get("active_take"):
        segment["active_take"] = take_id
    segment["error"] = None
    # Forced: the segment is `recording` right now, and this call is exactly the
    # event that ends it. Without the force it would stay `recording` forever
    # despite having valid audio on disk.
    projects.sync_status(segment, force=True)
    projects.log_event(project["id"], "take_added", segment=segment["id"],
                       take=take_id, n=take["n"], duration=take["duration"])
    return take


def promote(project, segment, take_id):
    """Point active_take at an existing take. Nothing else moves."""
    take = projects.find_take(segment, take_id)
    if take is None:
        raise KeyError(take_id)
    segment["active_take"] = take_id
    projects.sync_status(segment)
    projects.log_event(project["id"], "take_promoted", segment=segment["id"], take=take_id)
    return take


def delete(project, segment, take_id):
    """Remove a non-active take and its file. `n` is not reused afterwards."""
    take = projects.find_take(segment, take_id)
    if take is None:
        raise KeyError(take_id)
    if segment.get("active_take") == take_id:
        raise ValueError("active take")
    segment["takes"] = [t for t in segment["takes"] if t["id"] != take_id]
    path = paths.take_path(project["id"], segment["id"], take_id)
    try:
        os.remove(path)
    except OSError:
        pass
    projects.log_event(project["id"], "take_deleted", segment=segment["id"], take=take_id)
    return take


def delete_inactive(project):
    """'Delete all non-active takes' — the one-click disk reclaim."""
    removed = 0
    freed = 0
    for segment in projects.segments(project):
        keep = segment.get("active_take")
        for take in list(segment.get("takes") or []):
            if take["id"] == keep:
                continue
            path = paths.take_path(project["id"], segment["id"], take["id"])
            try:
                freed += os.path.getsize(path)
            except OSError:
                pass
            delete(project, segment, take["id"])
            removed += 1
    return {"removed": removed, "freed": freed}


def describe(segment, take):
    """Take as the UI needs it: newest first, with the outdated flag."""
    return {
        **take,
        "outdated": projects.take_is_outdated(segment, take),
        "active": segment.get("active_take") == take["id"],
    }


def listing(segment):
    takes = sorted(segment.get("takes") or [], key=lambda t: t.get("n") or 0, reverse=True)
    return [describe(segment, t) for t in takes]


def sweep_orphans(pid) -> int:
    """Remove .tmp wavs left by a killed worker. Called at startup.

    A half-written wav that survives a crash would be treated as done by the
    resume logic and would silently corrupt the book.
    """
    removed = 0
    for root, _dirs, files in os.walk(paths.audio_dir(pid)):
        for name in files:
            if name.endswith(".tmp"):
                try:
                    os.remove(os.path.join(root, name))
                    removed += 1
                except OSError:
                    pass
    return removed
