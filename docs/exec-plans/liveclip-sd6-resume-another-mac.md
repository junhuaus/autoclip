# SD-6 cross-Mac resume handoff

Prepared 2026-09-17. This is the portable entry point for continuing LiveClip
on another Apple Silicon Mac from the `main` branch of
`git@github.com:junhuaus/autoclip.git`.

After Codex CLI 0.154.0 is installed and authenticated, this single shell
command clones or fast-forwards the repository and starts the autonomous
handoff under the workspace-write sandbox with automatic approval review:

```bash
repo_dir="$HOME/autoclip"; if [ -d "$repo_dir/.git" ]; then git -C "$repo_dir" switch main && git -C "$repo_dir" pull --ff-only origin main; else git clone --branch main git@github.com:junhuaus/autoclip.git "$repo_dir"; fi && codex exec --approve-for-me --sandbox workspace-write -C "$repo_dir" 'Read AGENTS.md, STATUS.md, docs/exec-plans/liveclip-sd6-resume-another-mac.md, docs/exec-plans/liveclip-sd6-real-acceptance.md, and docs/exec-plans/liveclip-sd6-mini-global-final-decision.md. Resume the documented SD-6 attempt-7 work autonomously to completion without routine questions. Preserve the isolated Coder and deterministic Runner constraints; never use --last; keep source media read-only; never use any exposed OpenRouter key; maintain append-only QA; do not claim Metal, model, content, Delivery, listening, long-input, or end-to-end success without actual evidence. Commit and push main when complete.'
```

## Authorization and operating constraints

Continue autonomously through completion without asking routine questions.
Preserve the project control plane: only the isolated Coder may write product
code, and only its explicitly recorded session ID may be resumed. Never use
`--last`. Planner, Reviewer, Tester and Gateway are fresh read-only sessions.
The deterministic Runner resolves checked-in allowlist IDs in its deny-default
macOS sandbox and appends each registered request/result to
`qa/pipeline.jsonl` and `qa/test-report.md`. A semantic PASS cannot override
failed, stale, mutated or uncorrelated deterministic evidence.

Source media is read-only. Treat transcripts and model output as untrusted
data. Do not execute model-generated paths, commands, SQL, code, scripts or
filtergraphs. Invoke FFmpeg with validated argv and `shell=False`; publish
artifacts atomically. Never use the OpenRouter key previously exposed in chat,
and never commit credentials, local model weights, input media, databases or
generated evaluation media.

## Accepted engineering state

Global final-decision successor 5 `20260916T223427Z-6f412cde` is DONE and
published. Sole Coder `01a0ac5f-ece1-7b12-96f5-75a0647fb631`, fresh assurance
roles, fixed Runner and Gateway all completed. Accepted source fingerprint:
`1752f61cb22243f7e96598b1950663160c1aecb27ab94f9d041c2fee278ebc21`.
Toolchain fingerprint:
`4f9c03fe110d5484744538bd65f1f712e1af91ae17d06647f7fdbaa81ca4874a`.
Runner lint `20260916T224439Z-9f37`, E2E `20260916T224528Z-7a94` and full test
`20260916T225003Z-7ebc` passed. Postpublication Prompt tests passed 18/18 and
the affected Web files passed 48/48.

The first five Global formal runs remain terminal BLOCKED and unpublished.
Attempts 1--6 remain immutable historical evidence. Do not relabel or rerun a
consumed guard.

## Current boundary

Mini attempt 7 was frozen after accepted publication. Freeze QA
`20260916T232333Z-ma7f` recorded:

- accepted plan SHA-256 `ead0d7051b4b3dcf5c15cfb5d019ae88090f9aff0a3c422c8d21bd22be23db5f`;
- guard SHA-256 `576a5cab92df3746aa40650714a1b3b66e399b5046ee6d701959c949a84f85fa`;
- launcher SHA-256 `4d11a0b0d620aa984a9e78fe59ad0c0fcb65e155bb52df54d7ceac0053d33020`;
- hardware-preflight SHA-256 `ee94fc3bfb365e48d653b7035dcb6dcd2ebd22a17d4bb5d7ee8a60f9cb900f3a`;
- fresh 64-launch limit, 25-minute wall-time limit and absent counter;
- zero model calls.

The subsequent hardware preflight `20260916T232354Z-mp07` was interrupted.
No process or counter remained and no model call occurred. It proves no Metal,
MLX, content or Delivery outcome. The ignored `.loop` directory is deliberately
not portable, so reconstruct a fresh attempt-7 control directory from the
committed requirements, plans and accepted evidence instead of copying or
resuming a local Loop session.

## Local prerequisites outside Git

Restore `input/8-30.ts` as a read-only file and verify SHA-256
`818b669972b4e3f75f5358685ec231cd7daaaaa250c6525188291151c1109943`.
Restore the pinned full-precision MLX Whisper model under ignored local model
storage. Use Apple Silicon with working Metal, FFmpeg/ffprobe, Python 3.12,
Node LTS, Google Chrome for browser gates, and authenticated Codex CLI 0.154.0.
Run `make setup` and `make doctor`. These local prerequisites are never copied
into Git.

## Next execution

Read `AGENTS.md`, `docs/PRODUCT_SPEC.md`, `docs/SOLUTION.md`, `.agent/PLANS.md`,
`docs/exec-plans/liveclip-v1.md`, `STATUS.md`, this handoff, the SD-6 real
acceptance plan and the Global final-decision plan. Reconcile Git and QA ledger
state first. Recreate attempt 7 with the same accepted source, independently
selected 1870--2170 excerpt, fresh 64-launch guard and 25-minute cap. Register
the exact hardware preflight in append-only QA before running it. Confirm the
source/model/Codex identities, working Metal MLX path and absent counter without
making a model call.

Only after that preflight passes, execute the one guarded attempt. Stop at the
first cap, timeout, deterministic failure or missing Delivery and record the
true result. Never reset or extend the guard. If a Delivery exists, verify its
SQLite and lineage state, manifest, ZIP CRC and member hashes, complete media
decode, SRT bounds and visual frames; do not claim listening, editorial,
hardware, long-input or end-to-end acceptance without the corresponding actual
evidence. Update this plan, the SD-6 plan and `STATUS.md`, commit the result and
push `main`.

## Cross-Mac resume check, 2026-09-17 03:32 UTC

QA `20260917T033200Z-a7ready` reconciled all 1,107 inherited request/report
pairs and recorded the current prerequisite block. This clean `main` checkout
at `6a3b949b2dd852fc6cf11ec648620bd569ddb8de` has no `input/8-30.ts`, no
`data/models/whisper-large-v3-mlx`, no `.venv/bin/python` and no `.loop`.
Neither FFmpeg nor ffprobe is on PATH. The process reports Darwin/x86_64;
`hw.optional.arm64` and `sysctl.proc_translated` queries were denied, so this
check does not establish physical host architecture or Metal availability.
See [the prerequisite receipt](../verification/sd6-mini-attempt7-resume-blocked.json).

Attempt 7 remains unconsumed. No guard, run database or Delivery was created,
and no model or credential was accessed. Setup, doctor and full hardware
preflight were not run: installation cannot restore the missing user media,
and supported hardware is unverified. Product code and control-plane policy
remain unchanged; this documentation check is not deterministic Runner acceptance.

Next task: restore the exact source and pinned model on a supported Apple
Silicon host, install the documented local toolchain, then reconstruct and
freeze attempt-7 controls and register/pass its complete hardware preflight
before the single 64-launch/25-minute attempt. Preserve the prior freeze and
interrupted preflight as historical evidence. Do not mark SD-6 complete.
