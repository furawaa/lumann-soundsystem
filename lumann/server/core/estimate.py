"""ETA and projected final length.

progress.py had to infer generation time from wav mtimes, which meant a pause in
the run looked like one very slow chunk and threw the ETA out by 4x. It fixed
that by discarding gaps over 300 s. Here each take records its own
`gen_seconds`, so the measurement is direct — but the same 300 s cutoff is kept
as an outlier guard, because a take that really did take five minutes was a hung
process, not a rate sample.
"""
from . import projects

FALLBACK_RATE = 0.15         # s per character, measured on this machine
AUDIO_PER_CHAR = 0.0655      # s of audio per character, measured
GAP_CUTOFF = 300             # a sample longer than this was not generation
WINDOW = 20                  # rolling window, in completed segments


def rate(project) -> float:
    """Seconds of generation per character, from recent takes."""
    samples = []
    for segment in projects.segments(project):
        for take in segment.get("takes") or []:
            gen = take.get("gen_seconds")
            if not gen or gen > GAP_CUTOFF:
                continue
            chars = len(projects.effective_text(segment))
            if chars:
                samples.append((take.get("created_at") or "", gen, chars))
    if not samples:
        return FALLBACK_RATE
    samples.sort(key=lambda s: s[0])
    recent = samples[-WINDOW:]
    total_seconds = sum(s[1] for s in recent)
    total_chars = sum(s[2] for s in recent)
    return (total_seconds / total_chars) if total_chars else FALLBACK_RATE


def compute(project) -> dict:
    stats = projects.stats(project)
    per_char = rate(project)
    eta = stats["chars_left"] * per_char

    items = project["timeline"]
    gaps = max(len(items) - 1, 0) * (project.get("gap_seconds") or 0.0)
    projected = (stats["recorded_seconds"]
                 + stats["chars_left"] * AUDIO_PER_CHAR
                 + stats["insert_seconds"]
                 + gaps)

    return {
        "rate": round(per_char, 4),
        "eta_seconds": round(eta, 1),
        "projected_duration": round(projected, 1),
        "chars_left": stats["chars_left"],
        "measured": per_char != FALLBACK_RATE,
    }
