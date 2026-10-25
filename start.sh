#!/usr/bin/env bash
# Start Lumann Soundsystem.
#
#   bash start.sh              # http://127.0.0.1:8420, opens your browser
#   PORT=9000 bash start.sh    # another port
#   NO_BROWSER=1 bash start.sh
#
# The first run creates a Python environment in .venv/ and installs the few
# packages the app needs. Later runs start right away.
set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-8420}"
URL="http://127.0.0.1:$PORT"
VENV=".venv"

# --- Python 3.10+ -------------------------------------------------------------
PY=""
for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$candidate" >/dev/null 2>&1 \
      && "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
    PY="$candidate"
    break
  fi
done
if [ -z "$PY" ]; then
  echo "Lumann Soundsystem needs Python 3.10 or newer: https://www.python.org/downloads/"
  exit 1
fi

# --- system programs ----------------------------------------------------------
if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "ffmpeg is missing. It is needed to stitch the audio together."
  echo "  macOS:          brew install ffmpeg"
  echo "  Debian/Ubuntu:  sudo apt install ffmpeg"
  echo "Install it, then run this script again."
  exit 1
fi
if ! command -v espeak-ng >/dev/null 2>&1 && ! command -v espeak >/dev/null 2>&1; then
  echo "Warning: eSpeak NG is missing, so the built-in voices will not speak."
  echo "  macOS:          brew install espeak-ng"
  echo "  Debian/Ubuntu:  sudo apt install espeak-ng"
  echo "  More:           https://github.com/espeak-ng/espeak-ng"
  echo "Starting anyway."
fi

# --- Python packages, once ----------------------------------------------------
if [ ! -x "$VENV/bin/python" ]; then
  echo "First run: setting up Python packages in $VENV/ (takes a minute)..."
  "$PY" -m venv "$VENV"
fi
if ! cmp -s requirements.txt "$VENV/.installed"; then
  "$VENV/bin/python" -m pip install --quiet --disable-pip-version-check -r requirements.txt
  cp requirements.txt "$VENV/.installed"
fi

# --- go -------------------------------------------------------------------------
if [ -z "${NO_BROWSER:-}" ]; then
  (
    for _ in $(seq 1 60); do
      "$VENV/bin/python" -c "import urllib.request; urllib.request.urlopen('$URL/api/health')" \
        >/dev/null 2>&1 && break
      sleep 0.25
    done
    if command -v open >/dev/null 2>&1; then open "$URL"
    elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL" >/dev/null 2>&1
    fi
  ) &
fi

exec "$VENV/bin/python" lumann/server/main.py --port "$PORT" "$@"
