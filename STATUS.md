# LiveClip status snapshot

Updated: 2026-08-15 CST

Current product baseline: `0.1.0`

Current milestone: v0.2 V2-M3 selective editor handoff complete except external Jianying/CapCut import acceptance

Branch: `main` tracking `origin/main`

Latest pushed implementation checkpoints: `727bfba` (`feat: add selective editor handoff packages`) and `d995c9e` (`fix: normalize MPEG-TS silence intervals`)

## Current user-visible result

Local API, single leased Worker and Web are running through `make dev` at
`127.0.0.1:8765` and `http://127.0.0.1:5173/`. Health is `ok` in real
`openrouter-codex` mode.

Two requested long videos now exist as separate private Projects and have
completed their current generation-2 PipelineRuns:

- `8.15-1`: Project `67e827b4c0c8493b9804241e517cc5fe`, run
  `f0187e64fdbe44cdad62e4ae7afd9bd7`, status `pending_review`, 15 proxies.
- `8.15-2`: Project `4e3bf22ebf2f4b6a81f5ae5a0e552a46`, run
  `a4228d3ca597476685c11b52a1202309`, status `pending_review`, 15 proxies.

Project `7.28` remains ID `f91cb996f7534a6682aa5e5f01374b7b`
and was not reprocessed or modified.

## Completed v0.2 work

- V2-M0: product/research contract, ADR-014 and phased Living ExecPlan.
- V2-M1: local accounts, Argon2id credentials, opaque sessions, CSRF,
  administrator user management, private Projects, role/capability policy and
  ownership transfer.
- V2-M2: professional lifecycle independent of technical Pipeline state,
  assignment, priority, due date, archive/restore, activity history and dashboard
  filters.
- V2-M3: exact current MP4/SRT downloads; independent review/export selections;
  immutable selected `EditPackage`; clean MP4/SRT, CSV/JSON descriptions,
  thumbnails, checksums, Chinese import guide and ZIP; authorization,
  revision/producer/Asset fences and durable leased execution.
- Real migration `b95f3e6a1c27` and both requested long-input E2Es are complete.

## Long-input E2E evidence

- Both current runs: 6/6 stages, tasks and attempts succeeded; 100% complete.
- OpenRouter `openai/whisper-large-v3`: 55/55 and 60/60 chunks succeeded,
  zero retries.
- Transcripts: 202 and 210 source-absolute segments.
- Each Project: 45 rough candidates, 15 selected clips, zero degraded plans,
  15/15 successful proxies and 15/15 automatic quality reports passed.
- Codex CLI `gpt-5.6-terra`: `8.15-1` had 44 valid initial results plus one
  invalid result whose single repair succeeded; `8.15-2` had 45/45 valid initial
  results. There are zero Mock usage rows.
- Representative clips independently passed ffprobe and full decode. Their
  contact sheets were actually viewed: native portrait source composition,
  consistent framing, no blurred background, no thumbnail foreground, no added
  LiveClip title/subtitle, black frame or severe crop.
- Full report: `docs/verification/long-input-e2e-2026-08-15.md`.

Generation-1 runs remain as intentional failure evidence. Their import stages
succeeded, then preprocess exposed 1–2 ms overlapping silence events from the
MPEG-TS timestamps. The fixed parser unions intervals; complete scans of both
sources and 16 preprocess tests pass. The system correctly refused a blind retry
of deterministic unchanged input, so generation-2 runs were created without
deleting audit history.

## Real database evidence

- Database was backed up before V2-M3 migration at
  `data/projects/migration-backups/liveclip-pre-b95f3e6a1c27-20260815T144143+0800.sqlite3`.
- Backup SHA-256:
  `0b6701d00aaa3da45e46bbd93e2816505acb479a849eac19977fdaaf940c7024`.
- Migration from `a84e2d7c9f10` to `b95f3e6a1c27` succeeded; pre-existing Project,
  run, candidate, render and API-usage counts were unchanged.
- Latest `PRAGMA quick_check` is `ok`; foreign-key check is empty.

## Latest validation

- `make doctor`: READY with three non-blocking warnings: active Node is not LTS,
  FFmpeg uses deterministic raster text fallback, and actual VideoToolbox probe
  falls back successfully to libx264.
- `make lint`: Ruff/format, mypy for 121 source files, EditPlan JSON Schema and
  TypeScript passed.
- `make test`: 584 Python tests and 29 Web tests passed; Mock Chrome E2E and real
  FastAPI/leased-Worker/SQLite/FFmpeg Chrome E2E each passed once.
- Two representative long-input proxies independently passed ffprobe and full
  decode.
- The Browser plugin discovered no controllable instance. Chrome was running,
  but the selected profile lacked the Codex Chrome Extension. No plugin was
  installed and MCP Chrome success is not claimed.

## Still pending

- Human review of the 30 new candidates; no clip was auto-approved and no formal
  Delivery was created.
- External Jianying/CapCut Desktop import acceptance for a selected EditPackage.
- V2-M4 release presets, release metadata/checklists/calendar and manually
  recorded publication outcomes.
- V2-M5 retention/storage policy and final v0.2 independent verification.
- Threaded timecode comments, reusable saved views and cross-Project bulk
  assignment remain staged production-workflow enhancements.

## Security and worktree

- Never stage `.env`, `.env.local`, `OPENROUTER_SETUP.md`, `input/`, SQLite,
  media, caches, deliveries, E2E output or migration backups.
- No credential value was printed, persisted or staged. The source videos remain
  read-only references beneath the configured allowed media root.

## Next concrete task

Open `http://127.0.0.1:5173/`, review the 15 candidates in each new Project, and
select exact current revisions for an editor handoff package. If Jianying/CapCut
Desktop is available, import its basename-matched MP4/SRT files and record the
external acceptance result; otherwise proceed to V2-M4 without claiming native
draft compatibility.

## Resume instructions

Read `AGENTS.md`, `docs/PRODUCT_SPEC.md`, `docs/PRODUCT_SPEC_V0.2.md`,
`docs/SOLUTION.md`, `.agent/PLANS.md`, `docs/exec-plans/liveclip-v0.2.md`,
`docs/verification/long-input-e2e-2026-08-15.md` and this file. Run
`git status --short --branch`, `git log -5 --oneline`, `.venv/bin/alembic current`,
`.venv/bin/liveclip status 67e827b4c0c8493b9804241e517cc5fe` and
`.venv/bin/liveclip status 4e3bf22ebf2f4b6a81f5ae5a0e552a46`.
Do not reprocess the completed Projects; continue with “Next concrete task”.
