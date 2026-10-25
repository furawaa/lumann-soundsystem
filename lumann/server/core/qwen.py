"""Qwen3-TTS, the optional voice-cloning engine: installed and removed on demand.

Nothing here runs until the user presses Download in the voice library. Then
everything lands in one folder, so that Delete takes all of it away again:

  engines/qwen/packages/   qwen-tts, PyTorch and friends (pip --target)
  engines/qwen/model/      the model, ~4.5 GB from Hugging Face

The app's own Python environment is never touched: the worker adds packages/
to its import path. And nothing is fetched behind the user's back: with no
model/ folder a cloned voice fails with a message, it does not start a
download.

The model is loaded by path, never by repo id. A repo id makes transformers
call huggingface.co on every load (inside `_patch_mistral_regex`, which
qwen_tts triggers), which would break offline use and send your IP to
huggingface.co after every stop.

Standard library only: the worker imports this module before anything heavy.

    QWEN_TTS_MODEL=/path/to/model   # use a model folder of your own instead
    LUMANN_QWEN_DIR=/path           # keep engines/qwen/ somewhere else
    HF_ENDPOINT=https://mirror      # a Hugging Face mirror, as huggingface_hub reads it
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request

from . import paths

REPO = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
HUB = (os.environ.get("HF_ENDPOINT") or "https://huggingface.co").rstrip("/")
ROOT = os.environ.get("LUMANN_QWEN_DIR") or os.path.join(paths.LUMANN_DIR, "engines", "qwen")
PACKAGES_DIR = os.path.join(ROOT, "packages")
MODEL_DIR = os.path.join(ROOT, "model")
REQUIREMENTS = os.path.join(paths.REPO_DIR, "requirements-qwen.txt")

# Written last, so a folder without it is a download that did not finish.
COMPLETE = ".complete"
CHUNK = 1 << 20


class Cancelled(Exception):
    pass


# --- what is there ------------------------------------------------------------

def packages_managed() -> bool:
    """Installed by the app, into engines/qwen/packages/."""
    return os.path.exists(os.path.join(PACKAGES_DIR, COMPLETE))


def packages_ready() -> bool:
    """Importable at all: ours, or a qwen-tts the user installed themselves."""
    if packages_managed():
        return True
    # Only whether it is there: importing it would cost seconds and gigabytes.
    return importlib.util.find_spec("qwen_tts") is not None


def model_path() -> str | None:
    """-> the model folder to load, or None if there is none. Never a repo id."""
    override = os.environ.get("QWEN_TTS_MODEL")
    if override:
        return override if os.path.isdir(override) else None
    if os.path.exists(os.path.join(MODEL_DIR, COMPLETE)):
        return MODEL_DIR
    return None


def add_to_path() -> None:
    """For the worker: make the app-installed packages importable."""
    if packages_managed() and PACKAGES_DIR not in sys.path:
        sys.path.append(PACKAGES_DIR)


def _size(path: str) -> int:
    total = 0
    for base, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(base, name))
            except OSError:
                pass
    return total


# --- install / delete -----------------------------------------------------------

_lock = threading.Lock()
_job = {"step": None, "downloaded": 0, "total": 0, "error": None}
_proc = None
_cancel = threading.Event()
_thread = None
_disk = None                      # cached size of ROOT; walking 20k files is slow


def status() -> dict:
    global _disk
    with _lock:
        job = dict(_job)
    if job["step"] is None and _disk is None:
        _disk = _size(ROOT) if os.path.isdir(ROOT) else 0
    packages, model = packages_ready(), model_path() is not None
    return {
        "available": packages and model,
        "packages": packages,
        "packages_managed": packages_managed(),
        "model": model,
        "model_external": bool(os.environ.get("QWEN_TTS_MODEL")),
        "disk_bytes": _disk or 0,
        # null when idle; "packages" or "model" while installing.
        "step": job["step"],
        "downloaded": job["downloaded"],
        "total": job["total"],
        "error": job["error"],
    }


def install() -> bool:
    """Start installing whatever is missing, in the background. -> False if busy."""
    global _thread
    with _lock:
        if _job["step"] is not None:
            return False
        _job.update(step="starting", downloaded=0, total=0, error=None)
    _cancel.clear()
    _thread = threading.Thread(target=_install, name="qwen-install", daemon=True)
    _thread.start()
    return True


def cancel() -> None:
    _cancel.set()
    with _lock:
        proc = _proc
    if proc is not None and proc.poll() is None:
        proc.kill()
    if _thread is not None:
        _thread.join(timeout=30)


def delete() -> None:
    """Remove engines/qwen/ completely. The caller unloads the worker first."""
    global _disk
    cancel()
    shutil.rmtree(ROOT, ignore_errors=True)
    with _lock:
        _job.update(step=None, downloaded=0, total=0, error=None)
    _disk = None


def _set(**fields):
    with _lock:
        _job.update(fields)


def _install():
    global _disk
    try:
        if not packages_ready():
            _set(step="packages")
            _install_packages()
        if model_path() is None:
            _set(step="model")
            _download_model()
        _set(step=None, error=None)
    except Cancelled:
        _set(step=None, error=None)
    except Exception as exc:                    # noqa: BLE001 - shown to the user
        _set(step=None, error=str(exc))
    _disk = None


def _install_packages():
    """pip --target into a scratch folder, renamed into place only when complete."""
    global _proc
    part = PACKAGES_DIR + ".part"
    shutil.rmtree(part, ignore_errors=True)
    os.makedirs(part)
    with _lock:
        _proc = subprocess.Popen(
            [sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
             "--no-input", "--target", part, "-r", REQUIREMENTS],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            text=True)
    _, err = _proc.communicate()
    code = _proc.returncode
    with _lock:
        _proc = None
    if _cancel.is_set():
        shutil.rmtree(part, ignore_errors=True)
        raise Cancelled
    if code != 0:
        shutil.rmtree(part, ignore_errors=True)
        tail = " ".join((err or "").strip().splitlines()[-2:])
        raise RuntimeError(f"installing the Qwen packages failed: {tail or code}")
    open(os.path.join(part, COMPLETE), "w").close()
    shutil.rmtree(PACKAGES_DIR, ignore_errors=True)
    os.replace(part, PACKAGES_DIR)


def _files():
    """-> (revision, [(path, size)]) from the Hugging Face API."""
    url = f"{HUB}/api/models/{REPO}?blobs=true"
    with urllib.request.urlopen(url, timeout=30) as response:
        info = json.load(response)
    files = [(s["rfilename"], int(s.get("size") or 0)) for s in info.get("siblings", [])
             if s["rfilename"] not in (".gitattributes",)]
    if not files:
        raise RuntimeError("Hugging Face listed no files for the model")
    return info.get("sha") or "main", files


def _download_model():
    """File by file into model.part/, resuming whatever an earlier try left."""
    part = MODEL_DIR + ".part"
    revision, files = _files()
    total = sum(size for _name, size in files)
    have = sum(min(os.path.getsize(os.path.join(part, name)), size)
               for name, size in files if os.path.exists(os.path.join(part, name)))
    _set(total=total, downloaded=have)

    for name, size in files:
        target = os.path.join(part, name)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        done = os.path.getsize(target) if os.path.exists(target) else 0
        if size and done >= size:
            continue
        url = f"{HUB}/{REPO}/resolve/{revision}/{name}"
        request = urllib.request.Request(url, headers={"Range": f"bytes={done}-"} if done else {})
        for attempt in range(4):
            try:
                with urllib.request.urlopen(request, timeout=60) as response, \
                        open(target, "ab" if response.status == 206 else "wb") as fh:
                    if response.status != 206:
                        have -= done
                        done = 0
                    while True:
                        if _cancel.is_set():
                            raise Cancelled
                        chunk = response.read(CHUNK)
                        if not chunk:
                            break
                        fh.write(chunk)
                        done += len(chunk)
                        have += len(chunk)
                        _set(downloaded=have)
                break
            except (OSError, TimeoutError) as exc:   # urllib errors are OSErrors
                if attempt == 3:
                    raise RuntimeError(f"downloading {name} failed: {exc}") from exc
                time.sleep(2 * (attempt + 1))
                done = os.path.getsize(target) if os.path.exists(target) else 0
                request = urllib.request.Request(
                    url, headers={"Range": f"bytes={done}-"} if done else {})

    open(os.path.join(part, COMPLETE), "w").close()
    shutil.rmtree(MODEL_DIR, ignore_errors=True)
    os.replace(part, MODEL_DIR)
