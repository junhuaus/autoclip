# LiveClip status snapshot

Updated: 2026-08-03
Current milestone: M3 — REST API, Web review and versioned delivery (Reviewer PASS; checkpoint pending)
Branch: `master`
Recent relevant commit: `589269c` (`docs: record M2 checkpoint`); M3 is intentionally uncommitted until Reviewer PASS

## Completed

- M0 Discovery/Solution/foundation, M1 real Mock vertical slice and M2 persistent Pipeline/queue are locally committed and independently reviewed. See the Living ExecPlan for historical evidence and commit IDs.
- M3 adds generation-scoped pipeline artifacts, import-only and later full generations, strict review DTOs, atomic EditPlan/caption revisions, review history and revision-epoch Render invalidation.
- Durable Render and Delivery tasks use the same SQLite lease/heartbeat/recovery queue as Pipeline stages and foreground CLI. Final delivery requires an approved current revision and its current successful final Render.
- Immutable Delivery `vNNN` directories contain copied MP4/SRT, manifest hashes and optional ZIP. Active Delivery snapshots fail atomically when an EditPlan revision or review decision changes; succeeded versions remain immutable.
- FastAPI implements every required `/api/v1` route plus Render polling and Delivery version listing. Creating routes return truthful 202 resources with `Location`/`Retry-After` and atomic hashed `Idempotency-Key` behavior.
- API security includes loopback defaults, optional Bearer auth, allowlisted CORS, stable error envelopes (including framework 404/405 and rejected preflight), correlation IDs, redaction and no arbitrary local-path response.
- Generated media is resolved by committed Asset ID. Signed URLs bind method/path/purpose/expiry; HTML5 media supports single HTTP Range with reopen identity fencing. Delivery ZIP is scoped to its owning successful Delivery.
- CLI implements `run --wait`, `status`, `clips`, atomic `review`, `rerender --wait` and versioned `deliver`. `clips` includes score/title/reason/risks plus verified proxy status and local path.
- React/Vite implements project creation/list, Pipeline states/retry/cancel, transcript, signed video, differential boundary/title/caption edits, approve/reject, stale history, rerender polling, approved counts and Delivery versions/download.
- Boundary-only Web edits omit unchanged relative captions; the backend rebuilds cue times from absolute TranscriptSegments. Empty or unsafe captions are rejected at API/application/domain boundaries.
- `make dev` serializes migration preparation before starting FastAPI, Worker and Vite, reports local URLs, and cleans all child processes on Ctrl+C.
- M3 independent review findings fixed so far: stable framework errors/CORS, signed-URL refresh, retry after failed Delivery, no-ZIP Delivery, Vite query redaction, fresh-DB migration serialization, stale Delivery invalidation, nonempty captions, CLI candidate evidence, differential boundary edits and review-decision invalidation.

## In progress

- Independent read-only M3 Reviewer returned `PASS` with no remaining P0/P1. It independently ran lint, 233 Python tests, 11 Web tests, 30 focused regressions and diff validation.
- Main Agent is reviewing/staging the exact integrated diff and creating the scoped local M3 commit.

## Not completed

- M4 real OpenAI ASR/Responses providers, bounded retry/cache/usage persistence, versioned prompt and strict cloud smoke.
- M5 long-media/recovery/security/quality hardening, including the user-authorized read-only videos under repository `input/`.
- M6 clean acceptance, complete docs and final Product Spec Verification Agent.

## Verified

- `make lint`: PASS; Ruff checks/format cover 126 files, mypy passes 87 source files, TypeScript project build passes.
- `make test`: PASS; 233 Python tests in 60.90s and 11 Vitest component/API tests in 1.61s; standard tests made no cloud call.
- `npm run build --prefix apps/web`: PASS; Vite 6.4.3 production build transformed 80 modules.
- `npm run e2e --prefix apps/web`: PASS on host Chrome; one create → Pipeline → transcript/video → edit boundary/title/caption → stale → approve → final render → Delivery → signed ZIP flow passed in 5.5s.
- Fresh empty database dev preflight applied both Alembic revisions once before API/Worker fan-out; health and Vite returned HTTP 200; Ctrl+C left ports 8765/5173 closed.
- Vite API-offline probe used a sentinel signed query; logs contained only the path and did not contain the signature.
- API integration runs a real generated Mock media chain through Range proxy, atomic review, final FFmpeg render, immutable ZIP download and safe errors.
- In-app Browser bootstrap completed but `agent.browsers.list()` returned no available browser. No in-app-browser visual claim is made; repository Playwright host Chrome evidence is recorded separately.
- `git diff --check`: PASS after current M3 changes.

## Not yet verified

- Real OpenAI calls; no `OPENAI_API_KEY` is configured, and cloud success has not been claimed.
- Apple M3 throughput (development host is Apple M2), representative 2–4 hour input runtime/memory/disk and full 30–90 second many-cue raster performance.
- A true separate-process SQLite claim race; current tests use independent runners/connections in one process. M5 owns this hardening item.
- Final clean-state `make doctor`, `make demo` and Product Spec-wide Verification run; these remain M6 acceptance even though earlier milestone runs passed.

## Current blockers

- No product or implementation blocker. M3 is ready for its scoped local commit.
- Missing cloud credentials block only the optional real cloud smoke, not M4 implementation or local acceptance.

## Worktree state

- Branch `master`; HEAD `589269c`.
- Worktree contains only the integrated M3 code, migration, Web app/tests, docs and configuration changes. Generated `node_modules`, `dist`, Playwright results, databases and media are ignored.
- No remote exists and nothing has been pushed. User media under `input/` has not been touched.

## Next concrete task

Review/stage the exact M3 diff and create the local milestone commit. Then record its hash in ExecPlan/STATUS and start M4 with the `openai-docs` skill.

## Resume instructions

Read `AGENTS.md`, `docs/PRODUCT_SPEC.md`, `docs/SOLUTION.md`, `.agent/PLANS.md`, `docs/exec-plans/liveclip-v1.md` and this file. Then run `git status --short --branch` and `git log -5 --oneline`. Do not repeat completed M3 gates without evidence that files changed; continue from the next concrete task above. After the M3 checkpoint, start M4 by applying the `openai-docs` skill and revalidating official OpenAI docs before provider code.
