# LiveClip status snapshot

Updated: 2026-08-03
Current milestone: M4 — final gates passed; scoped commit pending
Branch: `master`
Recent relevant commit: `60c7922` (`docs: record M3 completion checkpoint`)

## Completed

- M0–M3 are locally committed and independently reviewed. Their architecture, persistence, CLI/API/Web, review/render and immutable delivery evidence remains in the Living ExecPlan.
- M4 implements pinned official `openai==2.52.0` adapters: timestamp-capable Chinese `whisper-1` transcription and stateless Responses strict structured editing with no tools, one repair and deterministic degradation.
- OpenAI retries are application-owned with SDK retries disabled, bounded exponential jitter, capped Retry-After, exact attempt counts, cancellation and deterministic auth/parameter/quota classification.
- Immutable ASR/edit caches use anchored component-by-component `openat`/`O_NOFOLLOW`, canonical result hashes and fail-closed validation before provider calls. Pipeline config v2 fingerprints every cloud-affecting setting and provider/Prompt/schema contract.
- Secret-free `ApiUsage`, exact historical-attempt cancellation evidence, Mock/OpenAI runtime fencing and strict no-Mock cloud-smoke evidence validation are integrated.
- Both independent M4 review passes are complete. The final OpenAI Reviewer returned `PASS` with no P0/P1/P2.
- A post-review intermittent FFmpeg timeout was retained and diagnosed. Raster inputs are now finite frames held by fixed overlay semantics, normal filter/libx264 threads are capped at 2/4, a timeout receives one 1/1-thread retry, and bounded partial stderr survives timeout termination.

## In progress

- Final scoped diff/stage review and local M4 milestone commit.

## Not completed

- M5 long-media, separate-process contention, interruption/recovery, security and media-quality hardening, including user-authorized read-only videos under repository `input/`.
- M6 real-backend browser composition, clean acceptance, final documentation audit and Product Spec-wide Verification Agent.

## Verified

- `make lint`: PASS after renderer hardening; Ruff check/format over 140 files, mypy over 95 source files and frontend TypeScript all passed.
- `make test`: PASS with explicit exit code 0; 328 Python tests passed in 46.61 seconds with one third-party Starlette deprecation warning, then 11 Vitest tests passed.
- Renderer regression: 13 process/renderer unit tests passed. Three successive real `test_demo_pipeline.py` runs each produced a distinct valid `delivery.zip`; an additional isolated run passed.
- Post-hardening `make demo`: PASS as project `demo_20260804T054112_c87bf8bc`, status `delivered`, three candidates.
- Demo final: `/Users/junhuaxu/Workspace/AGI/liveclip-ai/data/demo/projects/demo_20260804T054112_c87bf8bc/renders/final/clip_01_bdc52e84/r002/final.mp4`.
- Demo contact sheet: `/Users/junhuaxu/Workspace/AGI/liveclip-ai/data/demo/projects/demo_20260804T054112_c87bf8bc/renders/final/clip_01_bdc52e84/r002/final-quality/contact-sheet.png`; actually viewed after the fix. Title/captions remain in safe areas, portrait layout/aspect are correct and no apparent black/blank/severe-crop issue exists. The report records `viewed_passed`.
- Demo delivery ZIP: `/Users/junhuaxu/Workspace/AGI/liveclip-ai/data/demo/projects/demo_20260804T054112_c87bf8bc/deliveries/v001/delivery.zip`.
- `make doctor`: most recent run READY; macOS arm64/Python/FFmpeg/SQLite/fonts and actual libx264 fallback pass, with expected warnings for Node 26 non-LTS, raster-replaced text filters, missing allowed roots/key and sandbox VideoToolbox failure.
- Strict cloud preflight: `not_run` and nonzero with provider, key, allowed roots and missing input named; no database/provider opened and no paid call occurred.
- Wheel build includes both versioned Prompt Markdown files. `git diff --check` passed before the latest documentation update and will be rerun before commit.

## Not yet verified

- Real OpenAI account/model entitlement, Chinese cloud quality, provider usage variants, rate limits and latency: no `OPENAI_API_KEY` is configured, so paid cloud smoke is honestly `not_run`.
- Apple M3 throughput (current host is Apple M2), representative 2–4 hour runtime/memory/disk, VFR/rotation/multi-audio behavior and 30–90 second many-cue rendering.
- A true separate-process SQLite claim race and browser-to-real-FastAPI/Worker composition.

## Current blockers

- No product or implementation blocker.
- Missing cloud credentials block only real cloud verification, not implementation or local acceptance.

## Worktree state

- Branch `master`; HEAD `60c7922` before the M4 milestone commit.
- M4 provider/runtime/cache/config/tests/docs plus the renderer reliability fix are intentionally uncommitted pending final scoped review. Generated databases/media/deliveries remain ignored.
- No remote exists and nothing has been pushed. Repository `input/` user media has not yet been opened.

## Recent actual commands

- `make lint` → exit 0.
- PTY `make test` → exit 0; 328 Python + 11 Web tests.
- Three repeated real Demo integration executions → all created delivery ZIPs without failure records.
- `make demo` → exit 0; project `demo_20260804T054112_c87bf8bc` delivered.
- Actual contact-sheet view plus `record_visual_inspection` → `viewed_passed`.

## Next concrete task

Run `git diff --check`, inspect the complete M4 diff and staged scope, create the scoped local M4 commit, record its hash, then inspect `input/` metadata read-only and begin M5 long-media/recovery validation.

## Resume instructions

Read `AGENTS.md`, `docs/PRODUCT_SPEC.md`, `docs/SOLUTION.md`, `.agent/PLANS.md`, `docs/exec-plans/liveclip-v1.md` and this file. Run `git status --short --branch` and `git log -5 --oneline`, then execute the next concrete task above. Do not call OpenAI unless the environment is explicitly configured for `make smoke-cloud`; never substitute Mock for a claimed cloud success.
