#!/usr/bin/env python3
"""Standalone TTS worker. Speaks JSON lines on stdin/stdout.

It lives in its own OS process for one reason: cancellation. Interrupting
`model.generate()` from inside the server is not reliably possible, killing a
process is.

    {"cmd": "generate", "job": "...", "text": "...", "out": "/abs/x.wav.tmp",
     "engine": "espeak", "espeak": {"voice": "en-us", ...}}
    {"cmd": "generate", ..., "engine": "qwen", "ref_audio": "...", "ref_text": "..."}
    {"cmd": "ping"}

Two engines, picked per request by the voice:

  espeak — calls the espeak-ng binary. Nothing to load, so the worker is
           ready the moment it starts.
  qwen   — Qwen3-TTS voice cloning. Optional and heavy, installed by the user
           from the voice library (see core/qwen.py); never downloaded here.
           Loaded on the first clone request only, announced with a "loading"
           event so the UI can say why nothing is happening; a stop kills the
           process and the next clone request pays the load again.

Every response is a single line on stdout, flushed immediately — progress
output once vanished into a pipe buffer for hours.

Set LUMANN_FAKE_TTS=1 to run the whole pipeline without any engine: it
writes silence of a plausible length. The server, the queue, cancellation and
compose are all exercised; only the audio is not real.
"""
import json
import os
import sys
import time

# Own process, spawned by jobs/runner.py — neither the repo root nor lumann/
# is on sys.path.
_LUMANN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPO = os.path.dirname(_LUMANN)
for _path in (_REPO, _LUMANN):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from server.core import espeak, qwen              # noqa: E402 - stdlib only

FAKE = os.environ.get("LUMANN_FAKE_TTS") == "1"
SAMPLE_RATE = 24000
SECONDS_PER_CHAR = 0.0655        # measured over a 494-chunk Qwen run


class Unavailable(RuntimeError):
    """An engine that is not installed. Retrying will not install it."""


def emit(**payload):
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _device(torch):
    """-> (device_map, dtype). QWEN_TTS_DEVICE overrides the guess."""
    device = os.environ.get("QWEN_TTS_DEVICE")
    if not device:
        if torch.cuda.is_available():
            device = "cuda:0"
        elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            device = "mps"
        else:
            device = "cpu"
    # Half precision on a GPU; on a CPU it is slower than float32, not faster.
    return device, (torch.float32 if device == "cpu" else torch.float16)


class Qwen:
    """Loads once, on first use, generates many times."""

    def __init__(self):
        self.model = None
        self.torch = None
        self.count = 0
        self.load_seconds = 0.0        # of the load inside the last call, if any

    def load(self):
        model = qwen.model_path()
        if model is None:
            raise Unavailable("the Qwen3-TTS model is not downloaded. "
                              "Download it in Voices → Qwen3-TTS.")
        qwen.add_to_path()
        try:
            import torch
            from qwen_tts import Qwen3TTSModel
        except ImportError as exc:
            raise Unavailable(f"Qwen3-TTS is not installed ({exc.name}). "
                              "Install it in Voices → Qwen3-TTS.") from exc

        device, dtype = _device(torch)
        self.torch = torch
        self.model = Qwen3TTSModel.from_pretrained(
            model, device_map=device, dtype=dtype, attn_implementation="eager")

    def generate(self, req):
        self.load_seconds = 0.0
        if self.model is None:
            emit(event="loading", job=req.get("job"))
            began = time.time()
            self.load()
            self.load_seconds = time.time() - began
            emit(event="loaded", job=req.get("job"))

        wavs, sr = self.model.generate_voice_clone(
            text=req["text"], language=req.get("language") or "Auto",
            ref_audio=req["ref_audio"], ref_text=req["ref_text"],
            temperature=req.get("temperature", 0.8))
        _write(req["out"], wavs[0], sr)

        self.count += 1
        if self.count % 25 == 0 and getattr(self.torch, "mps", None) \
                and self.torch.backends.mps.is_available():
            self.torch.mps.empty_cache()
        return len(wavs[0]) / sr


def _write(out, wav, sr):
    """Always WAV/PCM_16, stated explicitly for two reasons.

    The destination is a `.tmp`, so soundfile cannot infer the format from the
    extension. And compose's `-c copy` concat needs every take in one format —
    a stray float wav in the middle of a book would make the whole concat fail.
    """
    import soundfile as sf
    sf.write(out, wav, sr, format="WAV", subtype="PCM_16")


def _fake(req):
    import numpy as np
    seconds = max(0.4, len(req["text"]) * SECONDS_PER_CHAR)
    time.sleep(min(1.5, seconds * 0.05))
    _write(req["out"], np.zeros(int(seconds * SAMPLE_RATE), dtype="float32"), SAMPLE_RATE)
    return seconds


def main():
    qwen = Qwen()
    emit(event="ready", fake=FAKE, espeak=espeak.available())

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            continue

        cmd = req.get("cmd")
        if cmd == "ping":
            emit(event="pong")
            continue
        if cmd == "shutdown":
            return 0
        if cmd != "generate":
            continue

        job = req.get("job")
        emit(event="started", job=job)
        os.makedirs(os.path.dirname(req["out"]), exist_ok=True)
        engine = req.get("engine") or "espeak"
        retries = int(req.get("retries", 2))
        started = time.time()
        for attempt in range(retries + 1):
            try:
                if FAKE:
                    seconds = _fake(req)
                elif engine == "qwen":
                    seconds = qwen.generate(req)
                    # The ETA is a rate sample; the one-off load is not.
                    started += qwen.load_seconds
                else:
                    if not espeak.available():
                        raise Unavailable("espeak-ng is not installed — see the README")
                    seconds = espeak.synth(req["text"], req["out"], req.get("espeak"))
                emit(event="done", job=job, seconds=round(seconds, 3),
                     gen_seconds=round(time.time() - started, 3))
                break
            except Exception as exc:              # noqa: BLE001 - keep going overnight
                # A missing install will not fix itself on retry.
                if attempt == retries or isinstance(exc, Unavailable):
                    emit(event="error", job=job, message=str(exc))
                    break
                time.sleep(2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
