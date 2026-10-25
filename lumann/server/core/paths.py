"""Where everything lives on disk.

One place that knows the layout, so nothing else has to guess. All paths are
absolute; the server may be started from anywhere.
"""
import os

# lumann/server/core/paths.py -> lumann/
LUMANN_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPO_DIR = os.path.dirname(LUMANN_DIR)

PROJECTS_DIR = os.environ.get("LUMANN_PROJECTS_DIR") or os.path.join(LUMANN_DIR, "projects")
SAMPLES_DIR = os.environ.get("LUMANN_SAMPLES_DIR") or os.path.join(LUMANN_DIR, "samples")
VOICES_DIR = os.environ.get("LUMANN_VOICES_DIR") or os.path.join(LUMANN_DIR, "voices")
WEB_DIST = os.path.join(LUMANN_DIR, "web", "dist")


def project_dir(pid: str) -> str:
    return os.path.join(PROJECTS_DIR, pid)


def project_json(pid: str) -> str:
    return os.path.join(project_dir(pid), "project.json")


def source_txt(pid: str) -> str:
    return os.path.join(project_dir(pid), "source.txt")


def formatted_txt(pid: str) -> str:
    return os.path.join(project_dir(pid), "formatted.txt")


def audio_dir(pid: str) -> str:
    return os.path.join(project_dir(pid), "audio")


def segment_dir(pid: str, segment_id: str) -> str:
    return os.path.join(audio_dir(pid), segment_id)


def take_path(pid: str, segment_id: str, take_id: str) -> str:
    return os.path.join(segment_dir(pid, segment_id), take_id + ".wav")


def trash_dir(pid: str) -> str:
    return os.path.join(audio_dir(pid), "_trash")


def composes_dir(pid: str) -> str:
    return os.path.join(project_dir(pid), "composes")


def events_log(pid: str) -> str:
    return os.path.join(project_dir(pid), "events.jsonl")


def sample_path(name: str) -> str:
    """Resolve a sample reference ('samples/door.wav' or 'door.wav') safely."""
    base = os.path.basename(name)
    return os.path.join(SAMPLES_DIR, base)


def voice_dir(vid: str) -> str:
    return os.path.join(VOICES_DIR, os.path.basename(vid))


def voice_json(vid: str) -> str:
    return os.path.join(voice_dir(vid), "voice.json")


def voice_audio(vid: str, name: str) -> str:
    return os.path.join(voice_dir(vid), os.path.basename(name))


def ensure_dirs() -> None:
    os.makedirs(PROJECTS_DIR, exist_ok=True)
    os.makedirs(SAMPLES_DIR, exist_ok=True)
    os.makedirs(VOICES_DIR, exist_ok=True)
