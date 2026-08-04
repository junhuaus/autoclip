#!/usr/bin/env bash
set -Eeuo pipefail

DEFAULT_CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
CHROME_EXECUTABLE="${LIVECLIP_CHROME_EXECUTABLE:-${DEFAULT_CHROME}}"

if [[ ! "${CHROME_EXECUTABLE}" = /* || ! -x "${CHROME_EXECUTABLE}" ]]; then
  echo "LiveClip browser tests require Google Chrome at ${DEFAULT_CHROME}" >&2
  echo "Install Chrome or set LIVECLIP_CHROME_EXECUTABLE to an executable absolute path" >&2
  exit 1
fi

echo "LiveClip test browser: ${CHROME_EXECUTABLE}"
