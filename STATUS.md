# LiveClip status snapshot

Updated: 2026-08-15 19:58 CST

Current product baseline: `0.1.0`

Current milestone: v0.2 V2-M5 hardening and final acceptance

Branch: `main` tracking `origin/main`

Latest implementation checkpoint: `06b7054` (`feat: add release planning and platform packages`)

## Current user-visible result

V2-M4 is complete and checkpointed. The authenticated Project workspace
now includes a “短视频发布运营” queue and calendar. Owners and editors can create
one task per high-point/platform/account before content approval, edit release
copy, assignee, planned time, caption mode, cover and checklist, preview the
exact clean proxy or burned final render against the task's historical platform
safe zone, and generate/download an immutable complete platform ZIP after
preflight passes. Owners/reviewers can approve, return or revoke approval.
Operators can record the exact package used for an external publication, its
actual time and URL/ID, notes and metric snapshots. LiveClip does not upload to
social platforms and stores no platform credential.

The three existing real Projects remain intact and were not reprocessed:

- `8.15-1`: Project `67e827b4c0c8493b9804241e517cc5fe`, current run
  `f0187e64fdbe44cdad62e4ae7afd9bd7`, 15 validated clean proxies.
- `8.15-2`: Project `4e3bf22ebf2f4b6a81f5ae5a0e552a46`, current run
  `a4228d3ca597476685c11b52a1202309`, 15 validated clean proxies.
- `7.28`: Project `f91cb996f7534a6682aa5e5f01374b7b`; unchanged.

## Completed v0.2 work

- V2-M0: product/research contract, ADR-014 and phased Living ExecPlan.
- V2-M1: local accounts, Argon2id credentials, opaque sessions, CSRF,
  administrator user management, private Projects, role/capability policy and
  ownership transfer.
- V2-M2: professional lifecycle separate from technical Pipeline state,
  assignment, priority, due date, archive/restore, activity and dashboard
  filters.
- V2-M3: exact current MP4/SRT downloads and immutable selective editor package
  with clean media, captions, metadata, thumbnails, checksums, guide and ZIP.
- V2-M4: append-only current/historical presets; ReleaseItem approval/status/
  audit/metrics/publication evidence; durable ReleasePackage lease/recovery;
  exact clean/burned media; cover/safe-zone/checklist/preflight; platform ZIP;
  signed downloads; REST API; queue/calendar Web UI.

## V2-M4 correctness decisions

- Prior-content similarity uses source overlap plus normalized n-grams over
  immutable succeeded package/EditPackage/Delivery evidence. It is a warning,
  never a blocker on intentional cross-platform reuse.
- Dynamic duplicate evidence is excluded from the material current fingerprint.
  Enqueue-time full preflight, Project display name and requester username are
  frozen for deterministic artifact bytes and crash recovery. An item excludes
  its own package history from duplicate warnings.
- Every ReleaseItem version change fails its queued/creating package and
  cancels/fences the Task. Clip revision increments the Project epoch, so it
  invalidates every active ReleasePackage in that Project. A new PipelineRun
  does the same. Successful package versions remain immutable history.
- Recording `published` requires the exact current successful package plus an
  actual time and external URL or ID. Immutable evidence stores package/item/
  preset/caption versions and video/manifest/ZIP hashes.

## Real database evidence

- Real database `data/projects/liveclip.sqlite3` is at Alembic
  `d8f3a6b1c420 (head)`; `alembic check` reports no pending operations.
- WAL-safe pre-d8 backup:
  `data/projects/migration-backups/liveclip-pre-d8f3a6b1c420-20260815T194643+0800.sqlite3`.
- Backup SHA-256:
  `af49cc9219a1444ed6de0b2f83fb179cc6d012e4bf62056167c4723dbec24ace`.
- Post-migration `PRAGMA quick_check` is `ok`; foreign-key check is empty.
  Protected counts are unchanged: 3 Projects, 3 source media, 5 PipelineRuns,
  131 candidates, 55 EditPlan revisions, 60 renders, 365 Assets, 353 API usage
  rows, 1 workspace user and 3 memberships. New release tables are empty.
- API, Worker and Vite were restarted after migration. `/api/v1/health` reports
  `ok`, OpenRouter ASR ready and Codex CLI editing ready without exposing keys.

## Latest actual validation

- `make doctor`: ready; all required checks pass. Expected warnings are missing
  FFmpeg text filters with the tested Pillow-overlay fallback, and failed
  VideoToolbox probe with a successful `libx264` fallback.
- `make lint`: passed Ruff check/format over 207 files, mypy over 127 source
  files, EditPlan schema verification and TypeScript.
- `make test`: passed 641 Python tests, 45 Web component tests across 8 files,
  Mock Google Chrome E2E 1/1, and isolated real Google Chrome + FastAPI + leased
  Worker + SQLite + FFmpeg E2E 1/1.
- A final privileged real-Chrome rerun passed in 19.5 seconds and generated
  `apps/web/test-results/real-backend/review-delivery-real-drive-894df-nd-FFmpeg-through-delivered/delivered.png`.
  The main Agent viewed the full screenshot and focused crops: lifecycle,
  horizontal high-point review, subtitles-last layout, edit handoff, immutable
  Delivery and release queue were readable with no clipping or column overlap.
- The in-app MCP Browser was initialized according to its skill, but reported no
  controllable browser instances. MCP success is not claimed; the actual host
  Google Chrome Playwright evidence above is the distinct fallback result.
- Independent read-only V2-M4 review: PASS, P0=0 and P1=0. It independently
  passed diff, Ruff, mypy, 88 targeted Python tests, 22 Web tests, Mock Chrome
  E2E and real Chrome E2E.

## Non-blocking M5 hardening

- Bound publication/metric timestamps to a reasonable clock window, require
  metric capture at or after publication, and cap integer metrics for SQLite.
- Immediately before recording publication, re-hash pinned manifest/ZIP bytes
  rather than relying only on the Asset-row hashes. Download already re-hashes
  and rejects tampered bytes, so this does not block the M4 checkpoint.
- Run external Jianying/CapCut Desktop import acceptance; it remains honestly
  unverified and LiveClip does not claim native draft generation.
- Complete storage/retention controls and final v0.2 Product Spec verification.

## Security and worktree

- Never stage `.env`, `.env.local`, `OPENROUTER_SETUP.md`, `input/`, `data/`,
  SQLite/WAL, media, caches, deliveries, E2E output or migration backups.
- No credential was printed, persisted or staged. V2-M4 tests used Mock/
  isolated fixtures and did not invoke paid ASR/LLM.
- The reviewed V2-M4 implementation is committed as `06b7054`; only this status
  checkpoint follows it. Generated/private paths remain ignored and unstaged.

## Next concrete task

Implement the two independent-review P2 hardening items: reasonable publication
and metric time/value bounds, then physical manifest/ZIP re-hashing immediately
before publication evidence is accepted. Add boundary, tamper and API tests
before running the V2-M5 repository gates.

## Resume instructions

Read `AGENTS.md`, `docs/PRODUCT_SPEC.md`, `docs/PRODUCT_SPEC_V0.2.md`,
`docs/SOLUTION.md`, `.agent/PLANS.md`, `docs/exec-plans/liveclip-v0.2.md` and
this file. Run `git status --short --branch`, `git diff --check`, `git log -5
--oneline`, `.venv/bin/alembic current` and `.venv/bin/alembic check`. Preserve
the three real Projects and the pre-d8 backup. Confirm `06b7054` is present on
`origin/main`, then continue from “Next concrete task”; do not reprocess real
inputs or invoke paid Providers for M5 hardening.
