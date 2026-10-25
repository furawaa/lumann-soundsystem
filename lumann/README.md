# Lumann Soundsystem internals

Notes for people changing the code. To install and use the app, see the
[main README](../README.md).

One Python process serves the API, the built UI and a server-sent-events stream.
A second process, the TTS worker, does the speaking. Nothing heavy is loaded
until you press Record.

```sh
python lumann/server/main.py                 # http://127.0.0.1:8420
python lumann/server/main.py --port 9000 --reload
LUMANN_FAKE_TTS=1 python lumann/server/main.py
```

With `LUMANN_FAKE_TTS=1` the worker writes silence of a plausible length
instead of speaking. The queue, cancellation, takes and compose are all real;
only the audio is not. The test suite runs this way.

## Layout

```text
server/
  main.py            uvicorn entry, serves API + built frontend
  tts_worker.py      separate process; JSON lines in, JSON lines out
  api/               routes
  core/
    espeak.py        eSpeak NG: synthesis, language and variant lists
    qwen.py          Qwen3-TTS install / download / delete, on demand only
    voices.py        the voice library, both engines
    textprep.py      adapt_text wrapper; text_hash and norm
    segmenter.py     paragraphs, chunking, char offsets
    projects.py      project.json, atomic writes, derived stats
    takes.py         append-only take writer
    reindex.py       the diff algorithm
    compose.py       ffmpeg assembly + progress parsing
    estimate.py      ETA / projected duration
  jobs/
    runner.py        owns the worker subprocess, queue, kills
    events.py        in-memory pub/sub -> SSE
web/                 Vite + React + TypeScript, plain CSS; dist/ is committed
tests/               unittest, fake worker
projects/ voices/ samples/   user data, git-ignored
engines/qwen/        packages/ + model/, only after the user pressed Download
```

`adapt_text.py` and `dicts/` at the repo root are the text formatter; the
server imports them.

## Engines

A voice says which engine speaks it (`voice.json` → `engine`):

| | eSpeak NG | Qwen3-TTS |
| --- | --- | --- |
| Voice is | settings: language, variant, speed, pitch | reference clips + transcripts |
| Needs | `espeak-ng` binary on `PATH` (or `ESPEAK_NG=/path`) | Download in the voice library |
| Worker start | instant | model loads on the first clone job (10–45 s) |
| Output | resampled to 24 kHz mono PCM_16 | 24 kHz mono PCM_16 |

The runner asks `voices.request_for(project)` for the engine fields of each job
and the worker dispatches on `engine`. A missing or broken voice falls back to
the built-in eSpeak voice that fits the book's script, so recording never fails
because a voice was deleted.

Both engines must write the same audio format: compose concatenates takes with
`-c copy`, and a book can switch voices halfway through.

Qwen is never fetched implicitly. `core/qwen.py` installs it only on request:
`pip install --target engines/qwen/packages` (the app's own environment stays
untouched) and the model files from Hugging Face into `engines/qwen/model/`,
with byte progress and resume. Each lands in a `.part` folder that is renamed
into place when complete. The worker loads the model by path, never by repo
id, so a missing model is an error message, not a download. Delete stops
recording and removes `engines/qwen/` entirely.

Environment variables: `QWEN_TTS_MODEL` (use your own model folder; Delete
leaves it alone), `QWEN_TTS_DEVICE` (`cuda:0`, `mps`, `cpu`; guessed otherwise),
`LUMANN_QWEN_DIR` (move `engines/qwen/`), `HF_ENDPOINT` (a Hugging Face mirror).

Voice names: a voice stores a `name` only when the user gives one.
`voices.display_name` fills the rest: an eSpeak voice is named after its
settings, a cloned one after its first clip.

## Interface language

EN / RU toggle at the bottom of the sidebar, stored in `localStorage`; English
by default. The accent colour (green by default, or blue) works the same way.

Every user-visible string lives in `web/src/i18n.tsx`. Dictionary values are
either a template with `{placeholders}` or a function, which is what Russian
plurals need: "1 дубль / 2 дубля / 5 дублей" cannot be done with interpolation
alone. `en` is typed as `Record<Key, Entry>`, so a key added to `ru` without an
English translation is a compile error rather than a blank label.

## Tests

```sh
cd lumann/tests && python -m unittest discover -p 'test_*.py'
cd lumann/web && npm test
```

`test_reindex` is the one that matters: re-indexing is what silently destroys
work if it is wrong. `test_recording` and `test_compose` drive the real HTTP
surface with the fake worker; `test_compose` shells out to ffmpeg for real.
`test_espeak` records and composes with the real eSpeak NG and is skipped when
it is not installed. `test_qwen` runs download, resume and delete against a
local stand-in for Hugging Face.

## Things that are load-bearing

**A line is not a paragraph.** Books are often hard-wrapped at ~78 columns. A
paragraph starts on an indented line or after a blank line; flush-left lines
continue it. Splitting on blank lines only would be wrong by orders of magnitude
on such a source.

**Audio is keyed by segment UUID, not by ordinal.** `audio/<segment_id>/<take_id>.wav`.
The visible index re-numbers freely; nothing on disk moves. Renaming hundreds
of files on every text edit is slow, non-atomic, and one interrupted rename
corrupts the mapping between text and audio. Ordinal names appear only on
export, where nothing depends on them.

**Re-recording appends.** Generation is stochastic (with Qwen, the run-to-run
spread exceeds most text edits), so a "fix" is often worse than what it
replaced. Every generation is a new take; `active_take` is the only pointer that
moves; `n` is never reused; deleting the active take is refused.

**Two markers, not one.** `moved` means the ordinal changed and the audio is
still valid (grey badge, no action). `stale` means the text changed and the
audio is wrong (amber border, goes in the queue).

**Re-indexing matches by text, too.** `difflib` reports a swapped pair of
paragraphs as insert+delete. Following that literally would move a good take to
`_trash` and re-record identical text. So after difflib's `equal` runs are
taken, anything still unpaired whose text survives verbatim is matched by text
before positional pairing inside `replace` runs. Swapping two paragraphs costs
nothing. See `_pair` in `core/reindex.py`.

**Stop means SIGKILL.** A model doing matrix math will not shut down politely.
Correctness comes from nothing being committed until a finished `.tmp` is
renamed into place; orphans are swept at startup.

**Every ffmpeg/ffprobe call passes `stdin=DEVNULL`.** A background process
group that touches the terminal gets `SIGTTIN` and freezes, which can silently
stall a long run.

**Worker output is unbuffered.** `PYTHONUNBUFFERED=1` plus explicit flushes;
otherwise progress lines can sit in a pipe buffer for hours.

**ETA measures generation directly.** Each take records its own `gen_seconds`
(without any one-off model load). A take that took over 300 s is treated as a
hung process, not a rate sample.

## Not implemented, by design

No word-level audio↔text alignment: highlighting is segment-granular, and
forced alignment is a much larger project. No multi-user, no auth, no cloud. No
fine-tuning: Qwen3-TTS voice cloning is zero-shot, there is nothing to train.
No websockets: SSE covers one-way push.
