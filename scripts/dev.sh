#!/usr/bin/env bash
# Start the Wese Trade backend (FastAPI) and frontend (Vite) together for local development.
# Prerequisites: README setup steps 2-8 completed. Ctrl+C stops both.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/backend/.venv/bin/python"
[[ -x "$PY" ]] || PY="$ROOT/backend/.venv/Scripts/python.exe"   # Git Bash on Windows

if [[ ! -x "$PY" ]]; then
  echo "error: backend virtualenv not found. Follow README setup first." >&2
  exit 1
fi
if [[ ! -d "$ROOT/frontend/node_modules" ]]; then
  echo "error: frontend dependencies missing. Run: (cd frontend && npm install)" >&2
  exit 1
fi

cleanup() {
  trap - INT TERM EXIT
  kill 0 2>/dev/null || true
}
trap cleanup INT TERM EXIT

(cd "$ROOT/backend" && "$PY" -m app.main) &
(cd "$ROOT/frontend" && npm run dev) &
wait
