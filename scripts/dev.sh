#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${PROJECT_DIR}/.venv/bin"
WEB_DIR="${PROJECT_DIR}/apps/web"
NODE_BIN_DIR="${NODE_LTS_BIN:-/usr/local/bin}"
API_HOST="${LIVECLIP_API_HOST:-127.0.0.1}"
API_PORT="${LIVECLIP_API_PORT:-8765}"
WEB_PORT="5173"

if [[ ! -x "${VENV_DIR}/uvicorn" || ! -x "${VENV_DIR}/liveclip-worker" ]]; then
  echo "LiveClip Python environment is missing; run make setup first" >&2
  exit 1
fi
if [[ ! -x "${WEB_DIR}/node_modules/.bin/vite" ]]; then
  echo "LiveClip Web dependencies are missing; run make setup first" >&2
  exit 1
fi
if [[ ! -x "${NODE_BIN_DIR}/node" ]]; then
  echo "Node LTS was not found at ${NODE_BIN_DIR}/node" >&2
  exit 1
fi

cd "${PROJECT_DIR}"
export PATH="${NODE_BIN_DIR}:${PATH}"

PIDS=()
CLEANED=0

cleanup() {
  if [[ "${CLEANED}" -eq 1 ]]; then
    return
  fi
  CLEANED=1
  trap - EXIT INT TERM
  for pid in "${PIDS[@]:-}"; do
    kill "${pid}" 2>/dev/null || true
  done
  for pid in "${PIDS[@]:-}"; do
    wait "${pid}" 2>/dev/null || true
  done
}

shutdown() {
  cleanup
  exit 0
}

trap cleanup EXIT
trap shutdown INT TERM

# Serialize schema upgrades before API and Worker open the same SQLite database.
# Their runtime startup still verifies the head revision, but no process races a
# fresh DDL migration with another long-lived process.
"${VENV_DIR}/python" "${PROJECT_DIR}/scripts/prepare_runtime.py"

"${VENV_DIR}/uvicorn" apps.api.main:app \
  --host "${API_HOST}" \
  --port "${API_PORT}" \
  --no-access-log &
PIDS+=("$!")

"${VENV_DIR}/liveclip-worker" &
PIDS+=("$!")

"${WEB_DIR}/node_modules/.bin/vite" "${WEB_DIR}" \
  --host 127.0.0.1 \
  --port "${WEB_PORT}" \
  --strictPort \
  --config "${WEB_DIR}/vite.config.ts" &
PIDS+=("$!")

echo "LiveClip API: http://${API_HOST}:${API_PORT}/api/v1/health"
echo "LiveClip Web: http://127.0.0.1:${WEB_PORT}"
echo "LiveClip Worker: started with SQLite task leases"
echo "Press Ctrl+C to stop all services"

while true; do
  for pid in "${PIDS[@]}"; do
    if ! kill -0 "${pid}" 2>/dev/null; then
      wait "${pid}" || status=$?
      status="${status:-0}"
      echo "A LiveClip development process exited with status ${status}" >&2
      exit "${status}"
    fi
  done
  sleep 1
done
