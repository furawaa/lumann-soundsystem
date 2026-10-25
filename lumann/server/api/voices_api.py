"""The voice library: list, add, extend, retype, retune, remove, preview.

eSpeak voices are plain settings and arrive as JSON. Clone voices' clips arrive as two parallel lists — the files and their transcripts, aligned
by position. A clip without its own transcript is refused rather than filled in
with a neighbour's: the wrong transcript is precisely the failure that produces
bad audio without producing an error.
"""
import shutil

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel

from ..core import espeak, qwen, voices
from ..jobs.runner import runner
from . import audio

router = APIRouter(prefix="/api")


class EspeakSettings(BaseModel):
    voice: str | None = None
    variant: str | None = None
    speed: int | None = None
    pitch: int | None = None


class EspeakVoice(EspeakSettings):
    name: str = ""


class VoicePatch(BaseModel):
    name: str | None = None
    espeak: EspeakSettings | None = None
    # An index picks one clip; "all" concatenates them into one reference.
    active: int | str | None = None
    clip: int | None = None
    ref_text: str | None = None


def _writer(upload: UploadFile):
    """Closing matters: the duration is probed the moment the clip lands."""
    def write(destination):
        with open(destination, "wb") as fh:
            shutil.copyfileobj(upload.file, fh)
    return write


def _pairs(files: list[UploadFile], ref_texts: list[str]):
    if not files:
        raise HTTPException(400, "no audio uploaded")
    if len(ref_texts) != len(files):
        raise HTTPException(400, "each clip needs its own transcript")
    return [(file.filename or "voice.wav", text, _writer(file))
            for file, text in zip(files, ref_texts)]


@router.get("/engines")
def engines():
    """What can speak on this machine, and the choices an eSpeak voice has."""
    return {
        "espeak": {
            "available": espeak.available(),
            "languages": espeak.languages(),
            "variants": espeak.variants(),
            "speed_range": espeak.SPEED_RANGE,
            "pitch_range": espeak.PITCH_RANGE,
        },
        "qwen": qwen.status(),
    }


@router.post("/engines/qwen/install")
def install_qwen():
    """Download what Qwen3-TTS needs. Only ever started by the user."""
    if not qwen.install():
        raise HTTPException(409, "already installing")
    return qwen.status()


@router.post("/engines/qwen/cancel")
def cancel_qwen():
    qwen.cancel()
    return qwen.status()


@router.delete("/engines/qwen")
def delete_qwen():
    """Remove the model and the app-installed packages, all of it.

    Recording is stopped first: the worker may have the model loaded, and a
    clone job in flight would only fail once its files are gone.
    """
    runner.stop()
    qwen.delete()
    return qwen.status()


@router.get("/voices")
def list_voices():
    return voices.list_all()


@router.post("/voices/espeak")
def add_espeak_voice(body: EspeakVoice):
    return voices.create_espeak(body.name, body.model_dump(exclude={"name"}))


@router.post("/voices")
async def add_voice(
    name: str = Form(""),
    ref_texts: list[str] = Form(...),
    files: list[UploadFile] = File(...),
):
    try:
        return voices.create(name, _pairs(files, ref_texts))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.post("/voices/{vid}/clips")
async def add_clips(
    vid: str,
    ref_texts: list[str] = Form(...),
    files: list[UploadFile] = File(...),
):
    try:
        voice = voices.add_clips(vid, _pairs(files, ref_texts))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if voice is None:
        raise HTTPException(404, "voice not found")
    return voice


@router.delete("/voices/{vid}/clips/{index}")
def remove_clip(vid: str, index: int):
    try:
        voice = voices.remove_clip(vid, index)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if voice is None:
        raise HTTPException(404, "clip not found")
    return voice


@router.patch("/voices/{vid}")
def patch_voice(vid: str, body: VoicePatch):
    try:
        voice = voices.update(
            vid, name=body.name, active=body.active, clip=body.clip, ref_text=body.ref_text,
            espeak_options=body.espeak.model_dump(exclude_none=True) if body.espeak else None)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if voice is None:
        raise HTTPException(404, "voice not found")
    return voice


@router.delete("/voices/{vid}")
def delete_voice(vid: str):
    voice = voices.load(vid)
    if voice is None:
        raise HTTPException(404, "voice not found")
    if voice.get("builtin"):
        raise HTTPException(400, "a built-in voice cannot be deleted")
    voices.delete(vid)
    return {"ok": True}


@router.get("/voices/{vid}/audio")
def voice_audio(vid: str, request: Request, clip: int = 0):
    """One clip of a voice, for preview. `clip=-1` is the joined reference.

    An eSpeak voice has no clips; it speaks a sample line instead.
    """
    voice = voices.load(vid)
    if voice is None:
        raise HTTPException(404, "voice not found")

    if voice["engine"] == "espeak":
        path = voices.preview(vid)
        if not path:
            raise HTTPException(503, "espeak-ng is not installed")
        return audio.serve(path, request)

    if clip < 0:
        path = voices.build_joined(vid, voice["clips"])
        if not path:
            raise HTTPException(404, "nothing to join")
        return audio.serve(path, request)

    clips = voice.get("clips") or []
    if not (0 <= clip < len(clips)):
        raise HTTPException(404, "clip not found")
    return audio.serve(voices.clip_path(vid, clips[clip]), request)
