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
API_PORT="${MCMAP_API_PORT:-8765}"
UI_PORT="${MCMAP_UI_PORT:-5173}"
API_PID=""
UI_PID=""

kill_tree() {
  local pid="$1"
  local child
  [[ -n "$pid" ]] || return 0
  while read -r child; do
    [[ -n "$child" ]] || continue
    kill_tree "$child"
  done < <(pgrep -P "$pid" 2>/dev/null || true)
  kill "$pid" 2>/dev/null || true
}

cleanup() {
  local api="${API_PID}" ui="${UI_PID}"
  API_PID=""
  UI_PID=""
  kill_tree "$ui"
  kill_tree "$api"
}
trap cleanup EXIT
trap 'cleanup; exit 130' INT
trap 'cleanup; exit 143' TERM

.venv/bin/python -m mcmap --host 127.0.0.1 --port "$API_PORT" &
API_PID=$!
cd ui
npm run dev -- --host 127.0.0.1 --port "$UI_PORT" &
UI_PID=$!
set +e
wait "$UI_PID"
status=$?
set -e
exit "$status"
