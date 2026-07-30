#!/usr/bin/env bash
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# Start backend
echo "Starting API server on http://localhost:8000 ..."
/tmp/tw-venv/bin/uvicorn tw_quant_signal.api.app:app --reload --port 8000 &
PID_API=$!

# Start frontend dev server
echo "Starting frontend dev server on http://localhost:5173 ..."
cd frontend && npm run dev &
PID_FE=$!

trap "kill $PID_API $PID_FE 2>/dev/null" EXIT
echo ""
echo "  Frontend: http://localhost:5173"
echo "  API:      http://localhost:8000"
echo "  Press Ctrl+C to stop"
echo ""
wait
