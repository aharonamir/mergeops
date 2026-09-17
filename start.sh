#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME_DIR="$ROOT_DIR/.mergeops-runtime"
BACKEND_PID_FILE="$RUNTIME_DIR/backend.pid"
FRONTEND_PID_FILE="$RUNTIME_DIR/frontend.pid"
BACKEND_LOG="$RUNTIME_DIR/backend.log"
FRONTEND_LOG="$RUNTIME_DIR/frontend.log"

mkdir -p "$RUNTIME_DIR"

is_running() {
  local pid="$1"
  [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null
}

process_matches() {
  local pid="$1"
  local expected="$2"
  is_running "$pid" || return 1
  ps -p "$pid" -o args= 2>/dev/null | grep -F -- "$expected" >/dev/null
}

read_pid() {
  local file="$1"
  [[ -f "$file" ]] && tr -d '[:space:]' < "$file"
}

start_backend() {
  local pid="$(read_pid "$BACKEND_PID_FILE" || true)"
  if [[ -n "$pid" ]] && process_matches "$pid" "uv run uvicorn"; then
    echo "Backend is already running (PID $pid)."
    return
  fi
  rm -f "$BACKEND_PID_FILE"
  setsid bash -c 'cd "$1/backend" && exec uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000' _ "$ROOT_DIR" >"$BACKEND_LOG" 2>&1 &
  pid=$!
  echo "$pid" > "$BACKEND_PID_FILE"
  sleep 1
  if ! process_matches "$pid" "uv run uvicorn"; then
    echo "Backend failed to start; see $BACKEND_LOG" >&2
    return 1
  fi
  echo "Backend started: http://127.0.0.1:8000"
}

start_frontend() {
  local pid="$(read_pid "$FRONTEND_PID_FILE" || true)"
  if [[ -n "$pid" ]] && process_matches "$pid" "npm run dev"; then
    echo "Frontend is already running (PID $pid)."
    return
  fi
  rm -f "$FRONTEND_PID_FILE"
  setsid bash -c 'cd "$1/frontend" && exec npm run dev -- --host 0.0.0.0 --port 5170' _ "$ROOT_DIR" >"$FRONTEND_LOG" 2>&1 &
  pid=$!
  echo "$pid" > "$FRONTEND_PID_FILE"
  sleep 1
  if ! process_matches "$pid" "npm run dev"; then
    echo "Frontend failed to start; see $FRONTEND_LOG" >&2
    return 1
  fi
  echo "Frontend started: http://0.0.0.0:5170"
}

command -v uv >/dev/null || { echo "Missing command: uv" >&2; exit 1; }
command -v npm >/dev/null || { echo "Missing command: npm" >&2; exit 1; }
start_backend
start_frontend
echo "Logs: $RUNTIME_DIR"
