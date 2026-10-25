"""eSpeak NG: the voice that works out of the box.

https://github.com/espeak-ng/espeak-ng — a small formant synthesizer, installed
as a system program (`brew install espeak-ng`, `apt install espeak-ng`). It
sounds robotic, but it needs no GPU, no model download and no reference clip,
and it speaks about a hundred languages. The app calls the `espeak-ng` binary;
nothing of eSpeak is bundled.

Standard library only: the TTS worker imports this module in its own process,
before anything heavy is loaded.

The output is resampled to the same format the Qwen backend writes (24 kHz
mono PCM_16), because compose concatenates takes with `-c copy` and a book can
switch voices halfway through.
"""
import functools
import os
import shutil
import subprocess
import tempfile
import wave

SAMPLE_RATE = 24000

DEFAULTS = {"voice": "en-us", "variant": "", "speed": 160, "pitch": 50}
SPEED_RANGE = (80, 450)          # words per minute, what espeak-ng accepts
PITCH_RANGE = (0, 99)

# A line to preview a voice with, in its own language where we have one.
PREVIEW = {
    "en": "This is how your book will sound with this voice.",
    "ru": "Так будет звучать ваша книга этим голосом.",
    "uk": "Так звучатиме ваша книжка цим голосом.",
    "de": "So wird Ihr Buch mit dieser Stimme klingen.",
    "fr": "Voici comment votre livre sonnera avec cette voix.",
    "es": "Así sonará tu libro con esta voz.",
    "it": "Ecco come suonerà il tuo libro con questa voce.",
    "pt": "É assim que o seu livro vai soar com esta voz.",
    "pl": "Tak zabrzmi twoja książka tym głosem.",
}


def binary() -> str | None:
    """-> path to espeak-ng, or None. ESPEAK_NG overrides the PATH lookup."""
    override = os.environ.get("ESPEAK_NG")
    if override:
        return override if os.path.exists(override) else None
    return shutil.which("espeak-ng") or shutil.which("espeak")


def available() -> bool:
    return binary() is not None


def settings(raw: dict | None) -> dict:
    """Fill gaps with defaults and clamp numbers to what espeak-ng accepts."""
    out = dict(DEFAULTS)
    out.update({k: v for k, v in (raw or {}).items() if k in DEFAULTS and v is not None})
    out["voice"] = str(out["voice"]).strip() or DEFAULTS["voice"]
    out["variant"] = str(out["variant"] or "").strip()
    out["speed"] = min(max(int(out["speed"]), SPEED_RANGE[0]), SPEED_RANGE[1])
    out["pitch"] = min(max(int(out["pitch"]), PITCH_RANGE[0]), PITCH_RANGE[1])
    return out


def preview_text(voice: str) -> str:
    return PREVIEW.get(voice.split("-")[0].lower(), PREVIEW["en"])


def synth(text: str, out: str, options: dict) -> float:
    """Speak `text` into `out` (WAV, 24 kHz mono PCM_16). -> seconds of audio.

    `out` may end in `.tmp`; the format is stated, not inferred.
    """
    exe = binary()
    if exe is None:
        raise RuntimeError("espeak-ng is not installed — see the README")
    opts = settings(options)
    voice = opts["voice"] + (f"+{opts['variant']}" if opts["variant"] else "")

    fd, raw = tempfile.mkstemp(suffix=".wav", dir=os.path.dirname(out) or None)
    os.close(fd)
    try:
        # Text goes in on stdin: no argument-length limit, and a paragraph that
        # starts with "-" is not mistaken for a flag.
        spoken = subprocess.run(
            [exe, "-v", voice, "-s", str(opts["speed"]), "-p", str(opts["pitch"]),
             "-w", raw, "--stdin"],
            input=text, text=True, encoding="utf-8",
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        if spoken.returncode != 0 or not os.path.getsize(raw):
            raise RuntimeError(f"espeak-ng failed: {spoken.stderr.strip() or spoken.returncode}")

        # stdin=DEVNULL: an ffmpeg that touches the terminal from a background
        # process group gets SIGTTIN and freezes.
        converted = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", raw,
             "-ac", "1", "-ar", str(SAMPLE_RATE), "-c:a", "pcm_s16le", "-f", "wav", out],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            text=True)
        if converted.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {converted.stderr.strip()}")
    finally:
        if os.path.exists(raw):
            os.remove(raw)

    with wave.open(out, "rb") as fh:
        return fh.getnframes() / fh.getframerate()


def _table(arg: str) -> list[list[str]]:
    exe = binary()
    if exe is None:
        return []
    try:
        result = subprocess.run([exe, arg], capture_output=True, text=True,
                                stdin=subprocess.DEVNULL, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return []
    # Pty  Language  Age/Gender  VoiceName  File  Other Languages
    return [line.split() for line in result.stdout.splitlines()[1:] if len(line.split()) >= 5]


@functools.lru_cache(maxsize=1)
def languages() -> list[dict]:
    """-> [{code, name}] — every language voice the installed espeak-ng has."""
    seen, out = set(), []
    for row in _table("--voices"):
        code, name = row[1], row[3].replace("_", " ")
        if code not in seen:
            seen.add(code)
            out.append({"code": code, "name": name})
    return sorted(out, key=lambda v: v["name"].lower())


@functools.lru_cache(maxsize=1)
def variants() -> list[dict]:
    """-> [{id, name, gender}] — the `+variant` voice colours (m1, f3, klatt, ...)."""
    out = []
    for row in _table("--voices=variant"):
        if row[4].startswith("!v/"):
            gender = row[2].split("/")[-1]
            out.append({"id": row[4][3:], "name": row[3].replace("_", " "), "gender": gender})
    return sorted(out, key=lambda v: v["name"].lower())
