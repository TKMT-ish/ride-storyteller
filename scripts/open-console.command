#!/bin/bash
# Double-click this file in Finder: it starts the Ride Storyteller console on
# this Mac if it is not already running, then opens it in your browser.
#
# Everything stays on this machine. The console reads private-media/ under
# this project and talks to no one unless you approve a judgement in it.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${RIDE_CONSOLE_PORT:-8765}"
URL="http://127.0.0.1:${PORT}/private-journey"
LOG="${ROOT}/.autonomy/console.log"

cd "$ROOT"
mkdir -p "${ROOT}/.autonomy"

if [ ! -x "${ROOT}/.venv/bin/python" ]; then
  echo "The project's Python environment (.venv) is missing. Run: python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'"
  read -r -p "Press Return to close." _
  exit 1
fi

listening() {
  curl -s -o /dev/null --max-time 1 "http://127.0.0.1:${PORT}/" >/dev/null 2>&1
}

if listening; then
  echo "The console is already running on port ${PORT}."
else
  echo "Starting the console on port ${PORT} (log: ${LOG}) ..."
  nohup "${ROOT}/.venv/bin/python" -m app.web.server >>"$LOG" 2>&1 &
  for _ in $(seq 1 40); do
    if listening; then break; fi
    sleep 0.25
  done
  if ! listening; then
    echo "The console did not start. The last lines of its log:"
    tail -n 20 "$LOG" || true
    read -r -p "Press Return to close." _
    exit 1
  fi
fi

echo "Opening ${URL}"
open "$URL"
