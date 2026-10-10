#!/usr/bin/env bash
# Start the NBA app at http://127.0.0.1:8001 (local only).
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install --quiet -r requirements.txt
fi

exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
