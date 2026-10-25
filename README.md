# Lumann Soundsystem

[![Download ZIP](https://img.shields.io/badge/Download-ZIP-4D9537?style=for-the-badge)](https://github.com/furawaa/lumann-soundsystem/archive/refs/heads/main.zip)

Lumann Soundsystem is software for voicing text. Give it a text, pick a voice,
and it reads the text aloud, on your own computer. The main use is audiobooks,
i.e. a local audiobook generator: you paste a chapter or a whole book, press
Record, and listen as it goes. Bad lines can be re-recorded without
touching the rest. At the end you export one audio file.

Runs locally in your browser.

The idea was inspired by the film *Drive My Car* (2021).

Two kinds of voices:

- **Cloned voices (Qwen3-TTS).** Optional, but a lot more fun. Give it a short
  recording of a voice plus the exact words spoken in it, and it reads your text
  in that voice. Sounds far more natural, but needs a big extra install (see below).
- **eSpeak NG voices.** These work out of the box. They sound robotic, but they
  are fast, need no graphics card, and cover about 100 languages. You can make as
  many as you like by picking a language, a voice variant, speed and pitch.

Both use the same queue, the same takes and the same export.

## See it in action

Three short clips with sound. The voice you hear is a clone of a real voice,
made with Qwen3-TTS (see "Cloned voices" below). Where the picture is marked
"sped up", the wait for the model is skipped.

**1. A voice of your own** (49 s). Add a short recording of a voice and what it
says, hear the recording, and record the first line in that voice.

https://github.com/user-attachments/assets/d472b9cc-6e1e-4ebc-a5c5-75e5ac80bc14

**2. From text to audiobook** (77 s). Paste a text, pick the voice, press Record.
While it records, mark finished lines to redo and watch them jump ahead of the
unrecorded ones in the queue. Then listen and export one file.

https://github.com/user-attachments/assets/e47ab807-7b87-4c0b-a9ee-eb23ae73810e

**3. Fixing single lines** (81 s). Replace one line with another voice (a robotic
announcer from eSpeak) and compare the takes: the first one is kept. Change the
wording of a line, and add a sound between two lines.

https://github.com/user-attachments/assets/d5ae98f4-b911-494a-a300-1407b91eaef5

## What you need

- macOS or Linux. Windows is not tested; WSL should work.
- Python 3.10 or newer
- [ffmpeg](https://ffmpeg.org), which stitches the audio together
- [eSpeak NG](https://github.com/espeak-ng/espeak-ng), which speaks the built-in voices

Install ffmpeg and eSpeak NG:

```sh
# macOS (with Homebrew)
brew install ffmpeg espeak-ng

# Debian / Ubuntu
sudo apt install ffmpeg espeak-ng
```

For other systems, see the [eSpeak NG install guide](https://github.com/espeak-ng/espeak-ng/blob/master/docs/guide.md).

## Install and start

1. Download the ZIP (button above) and unzip it, or clone the repo:
   `git clone https://github.com/furawaa/lumann-soundsystem.git`
2. Open a terminal in that folder and run:

   ```sh
   bash start.sh
   ```

3. Your browser opens at <http://127.0.0.1:8420>.

The first start takes a minute: it creates a private Python environment in
`.venv/` and installs a few small packages into it. After that it starts at once.
If ffmpeg or eSpeak NG is missing, the script tells you the exact command to
install it.

To stop Lumann Soundsystem, press `Ctrl+C` in the terminal.

Options: `PORT=9000 bash start.sh` uses another port, `NO_BROWSER=1 bash start.sh`
skips opening the browser.

## How to use it

1. **New project.** Click **+ New**, give it a title, paste your text (or drop a
   `.txt` file). A new paragraph starts on an indented line or after a blank line.
   Got an `.epub`? Convert it first: `python3 epub2txt.py book.epub`.
2. **Check the text.** The right panel shows the original and the formatted
   version that will be read aloud. Click the pencil to edit, `⌘F` / `Ctrl+F` to
   find and replace.
3. **Pick a voice** in the drop-down next to **Record**. "Voices…" opens the voice
   library, where you can preview, tune and add voices.
4. **Record.** Choose what to record (everything unrecorded, all, only changed
   text, or lines you marked ⟳) and press **Record**. You can listen while it
   works. **Stop** pauses; pressing Record again carries on.
5. **Fix what sounds wrong.** Every line can be played, re-recorded (⟳) or edited.
   A re-record adds a new take and keeps the old ones, so you can compare and pick
   the best. Changing a line's text marks its audio as out of date.
6. **Add pauses or sounds** between lines if you want: silence, or any audio file
   you uploaded under **Samples**.
7. **Export.** Under **Composes**, build the whole project into one `.m4a` or
   `.wav` file and download it.

You can run several projects at once; they share one queue.

## Voices

### eSpeak NG (built in)

Two are ready to use: English and Russian. A new project picks the Russian one
if the text is mostly Cyrillic, otherwise the English one.

To make your own, open **Voices…** and click **+ eSpeak voice**:

- **Language**: any language your eSpeak NG install has.
- **Variant**: changes the character of the voice (male, female, older, whispery…).
- **Speed**: words per minute, 80–450. Around 140–170 is comfortable for books.
- **Pitch**: 0–99, default 50.

Every voice has a play button so you can hear the change right away. An eSpeak
voice is named after its settings ("English (America) · male3 · 140 wpm") until
you rename it with ✎; clear the name to go back to the automatic one. The
built-in voices can be tuned and renamed, but not deleted.

### Cloned voices (Qwen3-TTS, optional)

This uses [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS) to copy a real voice
from a short recording.

What it takes:

- A computer with a decent graphics chip: an NVIDIA GPU, or an Apple Silicon Mac.
  It runs on a plain CPU too, but very slowly.
- About 6 GB of disk: 1.5 GB of Python packages (PyTorch and friends) and the
  4.2 GB model.

Nothing of it is downloaded until you ask for it. To install it, open **Voices…**
and press **Download** in the Qwen3-TTS box at the bottom. It shows its progress,
can be cancelled, and picks up where it stopped if you press **Resume** later.
Everything goes into one folder, `lumann/engines/qwen/`, and **Delete** in the
same box removes all of it again. Your own Python environment is not touched.

Then click **+ Cloned voice (Qwen3-TTS)**. Upload a clip of 10–30 seconds of clear speech and type out exactly what is said
in it, word for word. A wrong transcript gives no error; it just makes every line
sound worse.

Good to know:

- The first line you record with a cloned voice waits 10–45 seconds while the
  model loads. After 15 idle minutes the model is unloaded to free memory.
- Stop is instant, but it unloads the model, so the next start waits again.
- On an Apple M-series Mac, generation runs about 2–3 times slower than the
  audio it produces. A one-hour book takes a few hours, so it is best left running.
- The clip sets the pace and mood. A fast, chatty clip gives a fast, chatty book.
- Results vary from take to take. If a line sounds off, re-record it two or three
  times and keep the best take. That usually works better than rewording.
- Only clone voices you have the right to use.

## UX decisions

Making audio takes time, so most of the choices below come from one rule: the app
never throws your audio away behind your back, and it shows you what a change will
do before it does it.

- **Re-recording never overwrites.** It adds a take and keeps the old ones. Play
  any of them, make another one active, mark good ones with ♥ (they gather under
  **Favorites**, from all projects), or delete them by hand. The active take is the
  one that goes into the export.
- **Edited text makes audio out of date, not gone.** A changed line is tagged
  *text changed*, and its old takes are tagged *older text*. They stay playable, so
  you can hear what the line used to say. Making such a take active asks first.
- **You see the effect before you apply it.** Formatting your edits, or formatting
  the whole text again, first shows a diff: which lines are unchanged, moved or
  changed, and how many lines that already have audio would need re-recording.
  Nothing happens until you press Apply. Audio of a line that disappears is moved
  to `audio/_trash/` inside the project, not erased.
- **Audio follows the line, not its number.** Add or delete a paragraph and the
  lines below get new numbers, but keep their takes. A line whose text did not
  change keeps its audio even if it moved.
- **The original text is read-only.** The **Original** tab is the record of what you
  pasted. You edit the **Formatted** text, because that is what gets spoken, and
  **Compare** shows the original beside it. A single-line edit is stored apart from
  the source, so it survives re-formatting. Going back to the original ("Re-derive
  from original") warns that your edits will be lost.
- **Narration starts only when you press Record.** Marking a line, editing it or
  changing the scope only fills the queue; the button shows how much is waiting,
  like **Record (3)**. Lines marked ⟳ go first, in any project.
- **You can listen while it records.** A finished line plays right away. Autoplay
  starts from the first or the selected line, and the text panel highlights the
  line being read.
- **One queue for all projects, and you can see it.** **Queue** lists every project
  that has something waiting, in the order they will be recorded. Drag to reorder,
  pause one project while the others go, or Stop all.
- **Slow things show progress.** Recording shows "~3 min left" and the projected
  length of the book; m4a export shows a real percentage; the Qwen3-TTS download
  shows its progress and can be cancelled and resumed. Nothing heavy is downloaded
  or loaded before you ask for it.
- **Pauses and sounds are items on the timeline,** not baked into the audio. Each
  sits after a line, can be dragged elsewhere, changed or deleted. **Scatter**
  drops random samples across the book with a minimum spacing, and can undo the
  last batch in one click; inserts you placed by hand stay. If the line an insert
  followed is removed by a re-format, the insert moves to the previous line and
  the dialog asks you to check it.
- **A missing voice never stops a recording.** Delete a voice and the takes it
  made stay. A project whose voice is gone falls back to the built-in voice that
  fits the text.
- **Disk use is visible.** The bottom of **Composes** shows how much space active
  takes, archived takes, composes and the trash use. **Delete non-active takes**
  frees it, after asking.
- **Small things.** `⌘F` / `Ctrl+F` find and replace (regular expressions, whole
  words, and е = ё for Russian), `⌘Z` undo while editing text, draggable panes
  (double-click the divider to reset), English / Russian interface and two accent
  colours at the bottom left.

## Limits

- **Local, single user, no passwords.** Do not expose it to the internet. It only
  listens on your own machine unless you start it with `--host 0.0.0.0`.
- **The text clean-up is made for Russian.** For Russian text, Format writes numbers
  as words, restores ё, splits very long sentences and flags things to check by
  hand. For other languages it only does the general clean-up (quotes, dashes,
  invisible characters, links, markdown). The voices themselves work in any
  language they support.
- **The interface is in English and Russian** (switch at the bottom left).
- **eSpeak NG sounds synthetic.** That is the trade-off for working everywhere
  with no setup.
- **Highlighting follows whole lines,** not single words.
- **Narrate only texts you are allowed to.** Audio made from a copyrighted book is
  still that book.

## Tips for better audio

- Break long sentences that are glued together with commas into several short ones.
  This helps pacing more than anything else.
- Spell out abbreviations and symbols (`%`, `№`, `e.g.`) the way they should be read.
- If a word gets the wrong stress, rephrase the sentence. Qwen ignores stress marks.
- For eSpeak, try a few variants and a slightly lower speed before anything else.

## Where your data lives

Everything stays inside the app's folder and is never uploaded:

| Folder | What |
| --- | --- |
| `lumann/projects/` | your projects: text, every take, exports |
| `lumann/voices/` | your voices and their clips |
| `lumann/samples/` | sounds you uploaded for inserts |
| `lumann/engines/qwen/` | Qwen3-TTS, only if you downloaded it |

These folders are in `.gitignore`. To keep data somewhere else, set
`LUMANN_PROJECTS_DIR`, `LUMANN_VOICES_DIR` or `LUMANN_SAMPLES_DIR`.

## For developers

```sh
# tests (they use a fake TTS engine, so no model is needed)
.venv/bin/pip install -r requirements-dev.txt
cd lumann/tests && ../../.venv/bin/python -m unittest discover -p 'test_*.py'

# change the interface: needs Node.js
cd lumann/web && npm install && npm run dev     # live reload at :5173
npm run build                                     # updates lumann/web/dist/
```

The built interface in `lumann/web/dist/` is committed so that people can run
the app without Node. Rebuild it after changing anything in `lumann/web/src/`.

How the pieces fit together is described in [lumann/README.md](lumann/README.md).

## Credits

- [eSpeak NG](https://github.com/espeak-ng/espeak-ng) (GPL-3.0). The app runs it
  as a separate program; it is not included here.
- [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS) by the Qwen team, for voice
  cloning. Check the model's own license before using its output commercially.
- [FFmpeg](https://ffmpeg.org) for all audio stitching and conversion.
- The ё dictionaries come from [eyo-kernel](https://github.com/hcodes/eyo-kernel)
  (MIT). See [dicts/README.md](dicts/README.md).

## License

Copyright 2026 Matvei Bondarenko.

[Apache License 2.0](LICENSE). Use it, change it, sell it, build on it, as you
like. Keep the licence text and the credits when you pass it on.

The software is provided as it is, without any warranty, and the author is not
liable for what you do with it or for any damage it causes, as far as the law
allows (sections 7 and 8 of the licence). You alone are responsible for the texts
you narrate and the voices you clone.
