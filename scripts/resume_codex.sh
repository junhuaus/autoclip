#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

resume_prompt='Read AGENTS.md, STATUS.md, docs/exec-plans/liveclip-sd6-resume-another-mac.md, docs/exec-plans/liveclip-sd6-real-acceptance.md, and docs/exec-plans/liveclip-sd6-mini-global-final-decision.md. Resume the documented SD-6 attempt-7 work autonomously to completion without routine questions. Preserve the isolated Coder and deterministic Runner constraints; never use --last; keep source media read-only; never use any exposed OpenRouter key; maintain append-only QA; do not claim Metal, model, content, Delivery, listening, long-input, or end-to-end success without actual evidence. Commit and push main when complete.'

exec codex exec \
  --approve-for-me \
  --sandbox workspace-write \
  -C "$repo_root" \
  "$resume_prompt"
