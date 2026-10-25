"""Compose, download, and the sample library."""
import os
import re
import shutil

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..core import compose, paths, projects
from . import audio
from .projects_api import load_or_404

router = APIRouter(prefix="/api")

AUDIO_EXT = (".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac")


class ComposeRequest(BaseModel):
    format: str = "m4a"


@router.post("/projects/{pid}/compose")
def start_compose(pid: str, body: ComposeRequest):
    if body.format not in ("wav", "m4a"):
        raise HTTPException(400, "format must be wav or m4a")
    project = load_or_404(pid)
    return compose.start(project, body.format)


@router.get("/projects/{pid}/composes")
def list_composes(pid: str):
    load_or_404(pid)
    return compose.list_for(pid)


@router.get("/composes/{compose_id}")
def get_compose(compose_id: str):
    record = compose.get(compose_id)
    if not record:
        raise HTTPException(404, "compose not found")
    return record


@router.delete("/composes/{compose_id}")
def delete_compose(compose_id: str):
    if not compose.delete(compose_id):
        raise HTTPException(404, "compose not found")
    return {"ok": True}


@router.get("/composes/{compose_id}/download")
def download_compose(compose_id: str, request: Request):
    record = compose.get(compose_id)
    if not record:
        raise HTTPException(404, "compose not found")
    path = compose.file_path(record)
    if not path:
        raise HTTPException(409, "not finished yet")
    try:
        title = projects.load(record["project"])["title"]
    except (OSError, ValueError):
        title = record["project"]
    name = re.sub(r'[\\/:*?"<>|]+', "_", title).strip() or record["project"]
    return FileResponse(path, media_type=audio.content_type(path), filename=
                        f"{name}.{record.get('format', 'm4a')}")


@router.get("/composes/{compose_id}/audio")
def compose_audio(compose_id: str, request: Request):
    record = compose.get(compose_id)
    if not record:
        raise HTTPException(404, "compose not found")
    path = compose.file_path(record)
    if not path:
        raise HTTPException(409, "not finished yet")
    return audio.serve(path, request)


# --- samples ----------------------------------------------------------------

@router.get("/samples")
def list_samples():
    paths.ensure_dirs()
    out = []
    for name in sorted(os.listdir(paths.SAMPLES_DIR)):
        if not name.lower().endswith(AUDIO_EXT):
            continue
        full = os.path.join(paths.SAMPLES_DIR, name)
        out.append({"name": name,
                    "duration": round(compose.probe_duration(full), 3),
                    "size": os.path.getsize(full)})
    return out


@router.post("/samples")
async def upload_sample(file: UploadFile = File(...)):
    paths.ensure_dirs()
    name = os.path.basename(file.filename or "sample.wav")
    if not name.lower().endswith(AUDIO_EXT):
        raise HTTPException(400, f"expected one of {', '.join(AUDIO_EXT)}")
    dest = os.path.join(paths.SAMPLES_DIR, name)
    tmp = dest + ".tmp"
    with open(tmp, "wb") as fh:
        shutil.copyfileobj(file.file, fh)
    os.replace(tmp, dest)
    return {"name": name, "duration": round(compose.probe_duration(dest), 3)}


@router.delete("/samples/{name}")
def delete_sample(name: str):
    path = paths.sample_path(name)
    if not os.path.exists(path):
        raise HTTPException(404, "sample not found")
    os.remove(path)
    return {"ok": True}


@router.get("/samples/{name}/audio")
def sample_audio(name: str, request: Request):
    return audio.serve(paths.sample_path(name), request)


# --- favorites --------------------------------------------------------------

@router.get("/favorites")
def favorites():
    """Cross-project, grouped by project."""
    groups = []
    for pid in projects.list_ids():
        try:
            project = projects.load(pid)
        except (OSError, ValueError):
            continue
        rows = []
        for index, seg in enumerate(projects.segments(project), start=1):
            if not seg.get("favorite"):
                continue
            take = projects.active_take(seg)
            rows.append({
                "id": seg["id"],
                "index": index,
                "text": projects.effective_text(seg),
                "status": seg["status"],
                "duration": take.get("duration") if take else None,
                "has_audio": bool(take),
            })
        if rows:
            groups.append({"project": pid, "title": project["title"], "segments": rows})
    return groups
