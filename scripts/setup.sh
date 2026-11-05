#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
TAPEGRADE_PYTHON="${TAPEGRADE_PYTHON:-python3.12}"
command -v "$TAPEGRADE_PYTHON" >/dev/null || { echo 'Install Python 3.12 first: brew install python@3.12'; exit 1; }
command -v ffmpeg >/dev/null || { echo 'Install ffmpeg first: brew install ffmpeg'; exit 1; }
command -v npm >/dev/null || { echo 'Install Node.js 22 LTS or newer first.'; exit 1; }
"$TAPEGRADE_PYTHON" -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.lock.txt
npm --prefix frontend ci --no-audit --no-fund
echo 'TapeGrade is ready. No .env was created or modified. Defaults run the mock demo.'
echo 'See README.md for the three start commands.'
