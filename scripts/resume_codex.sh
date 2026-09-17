#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

resume_prompt='Continue the active LiveClip work autonomously to completion without routine questions. Re-read AGENTS.md, STATUS.md and docs/exec-plans/liveclip-sd6-resume-another-mac.md before acting. Preserve the isolated Coder and deterministic Runner constraints; never use --last; keep source media read-only; maintain append-only QA; do not claim success without actual evidence. Commit and push main when complete.'
session_id="${CODEX_SESSION_ID:-${1:-}}"

if [[ -n "$session_id" ]]; then
  exec codex exec \
    --approve-for-me \
    -C "$repo_root" \
    resume "$session_id" "$resume_prompt"
fi

# No --last: show all local sessions, including sessions created by
# `codex exec`, and let the operator select the exact session to resume.
exec codex resume \
  --approve-for-me \
  -C "$repo_root" \
  --all \
  --include-non-interactive
