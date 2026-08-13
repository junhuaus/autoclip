#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${PROJECT_DIR}/.venv/bin"
WEB_DIR="${PROJECT_DIR}/apps/web"
NODE_BIN_DIR="${NODE_LTS_BIN:-/usr/local/bin}"
E2E_API_PORT="${LIVECLIP_E2E_API_PORT:-18765}"
E2E_WEB_PORT="${LIVECLIP_E2E_WEB_PORT:-15174}"
E2E_TOKEN="liveclip-real-browser-test-token"
E2E_PASSWORD="liveclip real browser password 2026"
E2E_ROOT=""
E2E_ROOT_DEVICE=""
E2E_ROOT_INODE=""
E2E_LOG_DIR=""
API_PID=""
WORKER_PID=""
VITE_PID=""
PIDS=()
CLEANED=0

if [[ ! "${E2E_API_PORT}" =~ ^[0-9]+$ || ! "${E2E_WEB_PORT}" =~ ^[0-9]+$ ]]; then
  echo "LiveClip browser E2E ports must be integers" >&2
  exit 2
fi
if [[ ! -x "${VENV_DIR}/python" || ! -x "${VENV_DIR}/uvicorn" || ! -x "${VENV_DIR}/liveclip-worker" ]]; then
  echo "LiveClip Python environment is missing; run make setup first" >&2
  exit 1
fi
if [[ ! -x "${WEB_DIR}/node_modules/.bin/vite" || ! -x "${WEB_DIR}/node_modules/.bin/playwright" ]]; then
  echo "LiveClip Web dependencies are missing; run make setup first" >&2
  exit 1
fi
if [[ ! -x "${NODE_BIN_DIR}/node" ]]; then
  echo "Node LTS was not found at ${NODE_BIN_DIR}/node" >&2
  exit 1
fi
"${PROJECT_DIR}/scripts/check_test_browser.sh"

cleanup() {
  local status="${1:-0}"
  if [[ "${CLEANED}" -eq 1 ]]; then
    return
  fi
  CLEANED=1
  trap - EXIT INT TERM

  # SIGINT lets the Worker unwind its cancellable process runner and terminate
  # an owned FFmpeg process group before the bounded hard-stop fallback.
  if [[ -n "${WORKER_PID}" ]]; then
    kill -INT "${WORKER_PID}" 2>/dev/null || true
  fi
  for pid in "${API_PID}" "${VITE_PID}"; do
    if [[ -n "${pid}" ]]; then
      kill -TERM "${pid}" 2>/dev/null || true
    fi
  done
  for _attempt in {1..40}; do
    local live=0
    for pid in "${PIDS[@]:-}"; do
      if kill -0 "${pid}" 2>/dev/null; then
        live=1
      fi
    done
    if [[ "${live}" -eq 0 ]]; then
      break
    fi
    sleep 0.25
  done
  for pid in "${PIDS[@]:-}"; do
    if kill -0 "${pid}" 2>/dev/null; then
      kill -KILL "${pid}" 2>/dev/null || true
    fi
  done
  for pid in "${PIDS[@]:-}"; do
    wait "${pid}" 2>/dev/null || true
  done

  if [[ "${status}" -ne 0 && -n "${E2E_LOG_DIR}" && -d "${E2E_LOG_DIR}" ]]; then
    echo "LiveClip real browser E2E failed; bounded service log tails follow" >&2
    for log_path in "${E2E_LOG_DIR}"/*.log; do
      if [[ -f "${log_path}" ]]; then
        echo "--- $(basename "${log_path}") ---" >&2
        tail -n 80 "${log_path}" >&2 || true
      fi
    done
  fi
  local cleanup_failed=0
  if [[ -n "${E2E_ROOT}" && -n "${E2E_ROOT_DEVICE}" && -n "${E2E_ROOT_INODE}" ]]; then
    if ! "${VENV_DIR}/python" "${PROJECT_DIR}/scripts/e2e_fixture.py" \
      cleanup --root "${E2E_ROOT}" \
      --expected-device "${E2E_ROOT_DEVICE}" \
      --expected-inode "${E2E_ROOT_INODE}" >/dev/null; then
      echo "LiveClip real browser E2E refused unsafe temporary-root cleanup" >&2
      cleanup_failed=1
    fi
  fi
  return "${cleanup_failed}"
}

on_exit() {
  local status="$?"
  if cleanup "${status}"; then
    exit "${status}"
  fi
  if [[ "${status}" -eq 0 ]]; then
    exit 1
  fi
  exit "${status}"
}

on_interrupt() {
  cleanup 130 || true
  exit 130
}

on_terminate() {
  cleanup 143 || true
  exit 143
}

trap on_exit EXIT
trap on_interrupt INT
trap on_terminate TERM

IFS=$'\t' read -r E2E_ROOT E2E_ROOT_DEVICE E2E_ROOT_INODE < <(
  "${VENV_DIR}/python" "${PROJECT_DIR}/scripts/e2e_fixture.py" allocate
)
if [[ -z "${E2E_ROOT}" || -z "${E2E_ROOT_DEVICE}" || -z "${E2E_ROOT_INODE}" ]]; then
  echo "LiveClip real browser E2E could not allocate an identity-bound temporary root" >&2
  exit 1
fi

# The allocating process returns the directory identity before any fixture or
# configuration command can replace it unnoticed.
E2E_INPUT="$("${VENV_DIR}/python" "${PROJECT_DIR}/scripts/e2e_fixture.py" \
  create --root "${E2E_ROOT}" \
  --expected-device "${E2E_ROOT_DEVICE}" \
  --expected-inode "${E2E_ROOT_INODE}")"
E2E_DATA_DIR="${E2E_ROOT}/projects"
E2E_LOG_DIR="${E2E_ROOT}/logs"
mkdir -p "${E2E_LOG_DIR}"

export PATH="${NODE_BIN_DIR}:${PATH}"
export LIVECLIP_DATA_DIR="${E2E_DATA_DIR}"
export LIVECLIP_ALLOWED_MEDIA_ROOTS="${E2E_ROOT}/media"
export LIVECLIP_API_TOKEN="${E2E_TOKEN}"
export LIVECLIP_BOOTSTRAP_ADMIN_PASSWORD="${E2E_PASSWORD}"
export LIVECLIP_API_HOST="127.0.0.1"
export LIVECLIP_API_PORT="${E2E_API_PORT}"
export LIVECLIP_CORS_ORIGINS="http://127.0.0.1:${E2E_WEB_PORT}"
export LIVECLIP_AI_PROVIDER="mock"
export OPENAI_API_KEY=""
export ASR_CHUNK_SECONDS="10"
export ASR_CHUNK_OVERLAP_SECONDS="1"
export DEFAULT_TOP_N="1"
export MIN_CLIP_SECONDS="8"
export MAX_CLIP_SECONDS="12"
export PREVIEW_RENDER_WIDTH="270"
export PREVIEW_RENDER_HEIGHT="480"
export FINAL_RENDER_WIDTH="360"
export FINAL_RENDER_HEIGHT="640"
export LIVECLIP_VIDEO_ENCODER="libx264"
export WORKER_LEASE_SECONDS="30"
export WORKER_HEARTBEAT_SECONDS="5"
export MAX_STAGE_RETRIES="1"
export LOG_LEVEL="INFO"
export LIVECLIP_VITE_API_TARGET="http://127.0.0.1:${E2E_API_PORT}"
export LIVECLIP_E2E_BASE_URL="http://127.0.0.1:${E2E_WEB_PORT}"
export LIVECLIP_E2E_INPUT="${E2E_INPUT}"
export LIVECLIP_E2E_TOKEN="${E2E_TOKEN}"
export LIVECLIP_E2E_PASSWORD="${E2E_PASSWORD}"
export LIVECLIP_E2E_OUTPUT_DIR="${WEB_DIR}/test-results/real-backend"

"${VENV_DIR}/python" "${PROJECT_DIR}/scripts/e2e_fixture.py" \
  check-ports --api-port "${E2E_API_PORT}" --web-port "${E2E_WEB_PORT}" >/dev/null
"${VENV_DIR}/python" "${PROJECT_DIR}/scripts/e2e_fixture.py" \
  verify-config --root "${E2E_ROOT}" --api-port "${E2E_API_PORT}" \
  --expected-device "${E2E_ROOT_DEVICE}" \
  --expected-inode "${E2E_ROOT_INODE}" >/dev/null

cd "${PROJECT_DIR}"
"${VENV_DIR}/python" "${PROJECT_DIR}/scripts/prepare_runtime.py" >"${E2E_LOG_DIR}/prepare.log" 2>&1

"${VENV_DIR}/uvicorn" apps.api.main:app \
  --host 127.0.0.1 \
  --port "${E2E_API_PORT}" \
  --no-access-log >"${E2E_LOG_DIR}/api.log" 2>&1 &
API_PID="$!"
PIDS+=("${API_PID}")

"${VENV_DIR}/liveclip-worker" >"${E2E_LOG_DIR}/worker.log" 2>&1 &
WORKER_PID="$!"
PIDS+=("${WORKER_PID}")

"${WEB_DIR}/node_modules/.bin/vite" "${WEB_DIR}" \
  --host 127.0.0.1 \
  --port "${E2E_WEB_PORT}" \
  --strictPort \
  --config "${WEB_DIR}/vite.config.ts" >"${E2E_LOG_DIR}/vite.log" 2>&1 &
VITE_PID="$!"
PIDS+=("${VITE_PID}")

assert_owned_processes_alive() {
  for pid in "${PIDS[@]}"; do
    if ! kill -0 "${pid}" 2>/dev/null; then
      echo "An isolated LiveClip E2E service exited before readiness" >&2
      return 1
    fi
  done
}

wait_for_url() {
  local url="$1"
  local label="$2"
  for _attempt in {1..240}; do
    assert_owned_processes_alive
    if curl --fail --silent --show-error "${url}" >/dev/null 2>&1; then
      assert_owned_processes_alive
      return 0
    fi
    sleep 0.25
  done
  echo "Timed out waiting for ${label}" >&2
  return 1
}

wait_for_url "http://127.0.0.1:${E2E_API_PORT}/api/v1/health" "LiveClip API"
wait_for_url "http://127.0.0.1:${E2E_WEB_PORT}/" "LiveClip Web"

curl --fail --silent --show-error \
  -H "Authorization: Bearer ${E2E_TOKEN}" \
  "http://127.0.0.1:${E2E_API_PORT}/api/v1/projects" \
  | "${VENV_DIR}/python" -c 'import json, sys; assert json.load(sys.stdin) == []'

"${WEB_DIR}/node_modules/.bin/playwright" test \
  --config "${WEB_DIR}/playwright.real.config.ts"

assert_owned_processes_alive
"${VENV_DIR}/python" "${PROJECT_DIR}/scripts/e2e_fixture.py" \
  verify --root "${E2E_ROOT}" \
  --expected-device "${E2E_ROOT_DEVICE}" \
  --expected-inode "${E2E_ROOT_INODE}"
