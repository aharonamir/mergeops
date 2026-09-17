#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME_DIR="$ROOT_DIR/.mergeops-runtime"

stop_group() {
  local name="$1"
  local pid_file="$2"
  local pid
  pid="$(if [[ -f "$pid_file" ]]; then tr -d '[:space:]' < "$pid_file"; fi)"
  if [[ ! "$pid" =~ ^[0-9]+$ ]] || ! kill -0 "$pid" 2>/dev/null; then
    rm -f "$pid_file"
    echo "$name is not running."
    return
  fi

  echo "Stopping $name (PID $pid)..."
  kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
  for _ in {1..20}; do
    kill -0 "$pid" 2>/dev/null || break
    sleep 0.25
  done
  if kill -0 "$pid" 2>/dev/null; then
    echo "$name did not stop gracefully; terminating it."
    kill -KILL -- "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true
  fi
  rm -f "$pid_file"
}

mkdir -p "$RUNTIME_DIR"
stop_group "Frontend" "$RUNTIME_DIR/frontend.pid"
stop_group "Backend" "$RUNTIME_DIR/backend.pid"
echo "MergeOps stopped."
