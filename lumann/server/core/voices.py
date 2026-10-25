"""The voice library. A voice is one of two kinds, and `engine` says which.

  espeak — a set of eSpeak NG settings: language, variant, speed, pitch.
           Works out of the box; the built-in voices are of this kind.
  qwen   — one or more reference clips for Qwen3-TTS voice cloning, each with
           its transcript. Needs the optional Qwen install (see README).

Both go through the same queue, takes and compose; only the worker cares
which one it was handed.

Cloning needs both halves, and they only make sense together — a reference
paired with the wrong transcript is the one mistake here that produces
plausible-sounding garbage rather than an error. So a clip is the pair, and a
voice is a list of them.

The model takes exactly one reference per generation (`generate_voice_clone`
has a single `ref_audio`), so a voice with several clips still has to name one
thing to hand it. That is what `active` decides: an index picks one clip, and
the literal "all" concatenates them into a single longer reference, built once
with ffmpeg and cached next to the clips.

Voices are global rather than per-project on purpose: trying the same book in
two voices is the whole point of having them.
"""
import json
import os
import re
import shutil
import subprocess
import time
import uuid

from . import espeak, paths

AUDIO_EXT = (".wav", ".mp3", ".m4a", ".flac", ".ogg")

# The voices the app ships with, materialised into the library on first use so
# they can be listed, previewed and tuned like any other.
BUILTINS = {
    "espeak-en": {"voice": "en-us", "variant": "m3"},
    "espeak-ru": {"voice": "ru", "variant": "m3"},
}
BUILTIN_ID = "espeak-en"            # the last-resort fallback
CYRILLIC_ID = "espeak-ru"

OLD_BUILTIN_NAMES = ("eSpeak · English", "eSpeak · Русский")
OLD_AUTO_NAME = re.compile(r"^eSpeak · [a-z]{2,3}(-[a-z0-9]+)*$")

PREVIEW_AUDIO = "_preview.wav"
PREVIEW_STAMP = "_preview.json"

# Name of the concatenated reference and of the stamp that says what went into
# it. Underscored so they can never collide with an uploaded clip.
JOINED_AUDIO = "_joined.wav"
JOINED_STAMP = "_joined.json"
JOINED_RATE = 24000


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def engine(voice: dict) -> str:
    return voice.get("engine") or ("espeak" if "espeak" in voice else "qwen")


def _migrate(voice: dict) -> dict:
    """Single-clip voices, as the library first stored them, become one-clip lists."""
    voice["engine"] = engine(voice)
    if voice["engine"] == "espeak":
        voice["espeak"] = espeak.settings(voice.get("espeak"))
        # Names the app itself once wrote, before names followed the settings:
        # the built-ins' fixed names and "eSpeak · <language code>". They were
        # never the user's choice, and often no longer match the settings.
        if voice.get("name") in OLD_BUILTIN_NAMES or OLD_AUTO_NAME.match(voice.get("name") or ""):
            voice["name"] = None
        voice.setdefault("clips", [])
        voice.setdefault("active", 0)
        return voice
    if "clips" not in voice:
        voice["clips"] = [{
            "audio": voice.get("audio"),
            "ref_text": voice.get("ref_text") or "",
        }] if voice.get("audio") else []
    voice.pop("audio", None)
    voice.pop("ref_text", None)
    if "active" not in voice:
        voice["active"] = 0
    return voice


def _read(vid: str) -> dict | None:
    try:
        with open(paths.voice_json(vid), encoding="utf-8") as fh:
            return _migrate(json.load(fh))
    except (OSError, ValueError):
        return None


def _write(voice: dict) -> dict:
    os.makedirs(paths.voice_dir(voice["id"]), exist_ok=True)
    target = paths.voice_json(voice["id"])
    tmp = target + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(voice, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, target)
    return voice


def ensure_builtin() -> None:
    """Seed the library with the eSpeak voices the app ships with."""
    paths.ensure_dirs()
    for vid, spec in BUILTINS.items():
        if _read(vid) is not None:
            continue
        _write({
            "id": vid,
            "engine": "espeak",
            "espeak": espeak.settings({"voice": spec["voice"], "variant": spec["variant"]}),
            "clips": [],
            "active": 0,
            "created_at": _now(),
            "builtin": True,
        })


def _custom_name(name) -> str | None:
    return (name or "").strip() or None


def display_name(voice: dict) -> str:
    """The user's name for a voice if they gave one, else one made from it.

    An eSpeak voice is named after its settings, so the name follows them
    when they change: "English (America) · male3 · 140 wpm". A cloned voice
    falls back to the file name of its first clip.
    """
    if voice.get("name"):
        return voice["name"]
    if engine(voice) == "espeak":
        opts = voice["espeak"]
        language = next((l["name"] for l in espeak.languages() if l["code"] == opts["voice"]),
                        opts["voice"])
        parts = [language]
        if opts["variant"]:
            parts.append(next((v["name"] for v in espeak.variants() if v["id"] == opts["variant"]),
                              opts["variant"]))
        if opts["speed"] != espeak.DEFAULTS["speed"]:
            parts.append(f"{opts['speed']} wpm")
        if opts["pitch"] != espeak.DEFAULTS["pitch"]:
            parts.append(f"pitch {opts['pitch']}")
        return " · ".join(parts)
    clips = voice.get("clips") or []
    return clips[0]["audio"] if clips else voice["id"]


def default_for(text: str) -> str:
    """The built-in voice that fits a text: Russian for mostly-Cyrillic, else English."""
    letters = [c for c in text[:5000] if c.isalpha()]
    cyrillic = sum(1 for c in letters if "\u0400" <= c <= "\u04ff")
    return CYRILLIC_ID if letters and cyrillic * 2 > len(letters) else BUILTIN_ID


def _get(vid: str) -> dict | None:
    """Read a voice, seeding the built-in one if that is what is being asked for.

    Every entry point goes through here: without it, whichever call happens to
    come before the first listing sees no built-in voice at all.
    """
    if vid in BUILTINS:
        ensure_builtin()
    return _read(vid)


# --- reading ----------------------------------------------------------------

def clip_path(vid: str, clip: dict) -> str | None:
    return paths.voice_audio(vid, clip["audio"]) if clip.get("audio") else None


def decorate(voice: dict) -> dict:
    """Add what the UI needs and never stores: per-clip presence and duration."""
    from . import compose                       # ffprobe lives there
    named = {"name": display_name(voice), "custom_name": bool(voice.get("name"))}
    if engine(voice) == "espeak":
        # Nothing on disk to lose; it can only go missing with the binary.
        return {**voice, **named, "clips": [], "missing": not espeak.available()}
    clips = []
    for index, clip in enumerate(voice.get("clips") or []):
        path = clip_path(voice["id"], clip)
        exists = bool(path and os.path.exists(path))
        clips.append({
            **clip,
            "index": index,
            "missing": not exists,
            "duration": round(compose.probe_duration(path), 2) if exists else 0.0,
        })
    return {
        **voice,
        **named,
        "clips": clips,
        # A voice with nothing playable cannot record, and the picker greys out.
        "missing": not any(not c["missing"] for c in clips),
    }


def list_all() -> list[dict]:
    ensure_builtin()
    out = []
    for vid in sorted(os.listdir(paths.VOICES_DIR)):
        if not os.path.isdir(paths.voice_dir(vid)):
            continue
        voice = _read(vid)
        if voice:
            out.append(decorate(voice))
    out.sort(key=lambda v: (not v.get("builtin"), v.get("created_at") or ""))
    return out


def load(vid: str) -> dict | None:
    voice = _get(vid)
    return decorate(voice) if voice else None


# --- writing ----------------------------------------------------------------

def _store_clip(vid: str, audio_name: str, ref_text: str, write_audio) -> dict:
    if not audio_name.lower().endswith(AUDIO_EXT):
        raise ValueError(f"expected one of {', '.join(AUDIO_EXT)}")
    if not (ref_text or "").strip():
        raise ValueError("every clip needs its transcript — it is what the clip says")

    base = os.path.basename(audio_name)
    stem, ext = os.path.splitext(base)
    n = 1
    while os.path.exists(paths.voice_audio(vid, base)):    # same filename twice
        n += 1
        base = f"{stem}-{n}{ext}"
    write_audio(paths.voice_audio(vid, base))
    return {"audio": base, "ref_text": ref_text.strip()}


def create(name: str, clips: list[tuple[str, str, object]]) -> dict:
    """`clips` is [(filename, transcript, write_audio)] — at least one."""
    if not clips:
        raise ValueError("a voice needs at least one clip")

    vid = uuid.uuid4().hex[:12]
    os.makedirs(paths.voice_dir(vid), exist_ok=True)
    try:
        stored = [_store_clip(vid, audio, text, write) for audio, text, write in clips]
    except ValueError:
        shutil.rmtree(paths.voice_dir(vid), ignore_errors=True)
        raise
    return decorate(_write({
        "id": vid,
        "name": _custom_name(name),
        "engine": "qwen",
        "clips": stored,
        "active": 0,
        "created_at": _now(),
    }))


def create_espeak(name: str, options: dict) -> dict:
    opts = espeak.settings(options)
    vid = uuid.uuid4().hex[:12]
    return decorate(_write({
        "id": vid,
        "name": _custom_name(name),
        "engine": "espeak",
        "espeak": opts,
        "clips": [],
        "active": 0,
        "created_at": _now(),
    }))


def add_clips(vid: str, clips: list[tuple[str, str, object]]) -> dict | None:
    voice = _get(vid)
    if voice is None:
        return None
    if engine(voice) != "qwen":
        raise ValueError("an eSpeak voice has no clips")
    voice["clips"].extend(
        _store_clip(vid, audio, text, write) for audio, text, write in clips)
    _invalidate_joined(vid)
    return decorate(_write(voice))


def remove_clip(vid: str, index: int) -> dict | None:
    voice = _get(vid)
    if voice is None or not (0 <= index < len(voice["clips"])):
        return None
    if len(voice["clips"]) == 1:
        raise ValueError("a voice needs at least one clip")
    clip = voice["clips"].pop(index)
    path = clip_path(vid, clip)
    if path and os.path.exists(path):
        os.remove(path)
    active = voice.get("active")
    if isinstance(active, int) and active >= len(voice["clips"]):
        voice["active"] = len(voice["clips"]) - 1
    _invalidate_joined(vid)
    return decorate(_write(voice))


def update(vid: str, name=None, active=None, clip=None, ref_text=None,
           espeak_options=None) -> dict | None:
    """Rename, retune an eSpeak voice, choose the active clip, or fix a transcript.

    An empty name is not an error: it hands naming back to the voice itself.
    """
    voice = _get(vid)
    if voice is None:
        return None
    if name is not None:
        voice["name"] = _custom_name(name)
    if espeak_options is not None:
        if engine(voice) != "espeak":
            raise ValueError("not an eSpeak voice")
        voice["espeak"] = espeak.settings({**voice["espeak"], **espeak_options})
    if active is not None:
        if active == "all":
            voice["active"] = "all"
        else:
            index = int(active)
            if not (0 <= index < len(voice["clips"])):
                raise ValueError("no such clip")
            voice["active"] = index
    if clip is not None and ref_text is not None:
        if not (0 <= clip < len(voice["clips"])):
            raise ValueError("no such clip")
        if not ref_text.strip():
            raise ValueError("a transcript cannot be empty")
        voice["clips"][clip]["ref_text"] = ref_text.strip()
        _invalidate_joined(vid)
    return decorate(_write(voice))


def delete(vid: str) -> bool:
    if _get(vid) is None:
        return False
    shutil.rmtree(paths.voice_dir(vid), ignore_errors=True)
    return True


# --- the joined reference ---------------------------------------------------

def _stamp_of(vid: str, clips: list[dict]) -> list:
    """What the cached join was built from: names, transcripts and mtimes."""
    out = []
    for clip in clips:
        path = clip_path(vid, clip)
        out.append([clip.get("audio"), clip.get("ref_text"),
                    round(os.path.getmtime(path), 3) if path and os.path.exists(path) else 0])
    return out


def _invalidate_joined(vid: str) -> None:
    for name in (JOINED_AUDIO, JOINED_STAMP):
        path = paths.voice_audio(vid, name)
        if os.path.exists(path):
            os.remove(path)


def build_joined(vid: str, clips: list[dict]) -> str | None:
    """Concatenate the clips into one reference. -> path, or None if ffmpeg fails.

    Cached: rebuilt only when a clip is added, removed, retyped or replaced.
    Every input is normalised first, because a set of clips is exactly where
    mixed sample rates and stereo/mono come from.
    """
    from . import compose

    usable = [c for c in clips if (clip_path(vid, c) and os.path.exists(clip_path(vid, c)))]
    if not usable:
        return None

    target = paths.voice_audio(vid, JOINED_AUDIO)
    stamp_path = paths.voice_audio(vid, JOINED_STAMP)
    stamp = _stamp_of(vid, usable)
    if os.path.exists(target) and os.path.exists(stamp_path):
        try:
            with open(stamp_path, encoding="utf-8") as fh:
                if json.load(fh) == stamp:
                    return target
        except (OSError, ValueError):
            pass

    workdir = paths.voice_dir(vid)
    parts = []
    try:
        for index, clip in enumerate(usable):
            part = os.path.join(workdir, f"_part{index}.wav")
            compose._normalise(clip_path(vid, clip), part, JOINED_RATE)
            parts.append(part)

        listing = os.path.join(workdir, "_join.txt")
        with open(listing, "w", encoding="utf-8") as fh:
            for part in parts:
                fh.write(f"file '{part}'\n")
        # .wav, not .tmp: ffmpeg picks the output format from the extension and
        # has no idea what a .tmp is.
        tmp = os.path.join(workdir, "_joined.part.wav")
        result = compose._run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "concat", "-safe", "0", "-i", listing, "-c", "copy", tmp])
        if result.returncode != 0 or not os.path.exists(tmp):
            return None
        os.replace(tmp, target)
        with open(stamp_path, "w", encoding="utf-8") as fh:
            json.dump(stamp, fh)
        return target
    except (OSError, subprocess.SubprocessError):
        return None
    finally:
        for part in parts:
            if os.path.exists(part):
                os.remove(part)
        listing = os.path.join(workdir, "_join.txt")
        if os.path.exists(listing):
            os.remove(listing)


def reference_of(voice: dict) -> tuple[str, str] | None:
    """-> (audio path, transcript) for a voice, honouring its `active` choice."""
    clips = voice.get("clips") or []
    usable = [c for c in clips if (clip_path(voice["id"], c)
                                   and os.path.exists(clip_path(voice["id"], c)))]
    if not usable:
        return None

    if voice.get("active") == "all" and len(usable) > 1:
        joined = build_joined(voice["id"], usable)
        if joined:
            return joined, " ".join(c["ref_text"] for c in usable if c.get("ref_text"))
        # ffmpeg missing or unhappy: one real clip beats no recording at all.

    index = voice.get("active")
    clip = clips[index] if isinstance(index, int) and 0 <= index < len(clips) else None
    if clip is None or clip not in usable:
        clip = usable[0]
    return clip_path(voice["id"], clip), clip.get("ref_text") or ""


def preview(vid: str) -> str | None:
    """A short sample of an eSpeak voice, cached until its settings change."""
    voice = _get(vid)
    if voice is None or engine(voice) != "espeak" or not espeak.available():
        return None
    target = paths.voice_audio(vid, PREVIEW_AUDIO)
    stamp_path = paths.voice_audio(vid, PREVIEW_STAMP)
    stamp = voice["espeak"]
    if os.path.exists(target) and os.path.exists(stamp_path):
        try:
            with open(stamp_path, encoding="utf-8") as fh:
                if json.load(fh) == stamp:
                    return target
        except (OSError, ValueError):
            pass
    tmp = target + ".tmp"
    try:
        espeak.synth(espeak.preview_text(stamp["voice"]), tmp, stamp)
    except (OSError, RuntimeError):
        return None
    os.replace(tmp, target)
    with open(stamp_path, "w", encoding="utf-8") as fh:
        json.dump(stamp, fh)
    return target


def _request_of(voice: dict) -> dict | None:
    if engine(voice) == "espeak":
        return {"engine": "espeak", "espeak": voice["espeak"]}
    found = reference_of(voice)
    if not found:
        return None
    return {"engine": "qwen", "ref_audio": found[0], "ref_text": found[1],
            "language": voice.get("language") or "Auto"}


def request_for(project: dict) -> dict:
    """-> the engine fields of a worker request for this project.

    The one place that decides what the worker is handed. A project must never
    fail to record because its voice was deleted or lost its clips, so anything
    unusable falls back to the built-in voice that fits the book.
    """
    vid = project.get("voice")
    voice = _get(vid) if vid else None
    found = _request_of(voice) if voice else None
    if found:
        return found
    sample = " ".join(item.get("text") or "" for item in project.get("timeline", [])[:50])
    return _request_of(_get(default_for(sample)))


def label(project: dict) -> tuple[str | None, str | None]:
    """-> (voice id, display name) recorded onto a take, for its history."""
    vid = project.get("voice")
    voice = _get(vid) if vid else None
    if voice:
        return voice["id"], display_name(voice)
    return None, None
