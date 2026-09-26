#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
fi
if [[ ! -d ui/node_modules ]]; then
  npm install --prefix ui
fi
export PYTHONPATH="$ROOT/server${PYTHONPATH:+:$PYTHONPATH}"
.venv/bin/python -m mcmap --host 127.0.0.1 --port 8765 &
API_PID=$!
cleanup() {
  kill "$API_PID" 2>/dev/null || true
}
trap cleanup EXIT
cd ui
exec npm run dev -- --host 127.0.0.1 --port 5173
