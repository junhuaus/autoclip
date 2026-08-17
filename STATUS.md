# LiveClip status snapshot

Updated: 2026-08-16 22:42 PDT

Package compatibility baseline: `0.1.0`

Current milestone: V2-M6 project discovery/private saved views are implemented
at `fa395f6`. The transport-stream A/V synchronization correction is implemented
at `0a266f3`. Branch `main` tracks `origin/main`; both implementation checkpoints
and their first recovery snapshot are pushed, and this final note records that
synced state.

## Current user-visible result

LiveClip still provides the complete local long-video pipeline, clean review
proxies, exact EditPlan revisions, multi-user Project governance, collaboration
comments, editor handoff, release planning and immutable Delivery.

The editor dashboard now adds server-authorized Project search, filters, stable
keyset pagination, counts/facets and private per-user saved views. Search cannot
leak a private Project through counts, evidence or stale cursors; saved-view
create/retry and update/delete use idempotency/CAS fences.

Real Project `8-16-1` (`953ae56cf15f486cb61ab5b53046ebb5`)
processed `input/8-16-1.ts` through the existing production path:

- source: 2.2 GiB MPEG-TS, 5042.717 seconds, HEVC 1088×1920 plus AAC;
- 60/60 OpenRouter `openai/whisper-large-v3` chunks succeeded;
- 45/45 local Codex `gpt-5.6-terra` editorial analyses succeeded;
- 15 current candidates have titles, Hooks, reasons, captions and clean videos;
- the first render exposed an A/V sync defect caused by non-keyframe HEVC seek
  plus independent source-stream `STARTPTS` resets;
- renderer v4 now decodes a bounded ten-second preroll, performs an accurate
  output seek and preserves one shared source PTS timeline;
- all 15 proxies were regenerated as immutable v4 artifacts without repeating
  ASR or Codex. The Web/CLI now resolve those latest artifacts.

The existing `8.15-1`, `8.15-2` and `7.28` Projects remain visible and their
previous successful proxies remain available. Their prior immutable offline
review packages remain unchanged and ignored by Git.

## Implementation checkpoints

- `e01820f`: revision-bound collaboration comments.
- `fa395f6`: authorized Project discovery and private saved views, migration
  `f3b6d9a2c841`, API/Web/tests and ADR-018.
- `0a266f3`: bounded accurate transport-stream seek, shared A/V timeline,
  renderer contract `ffmpeg-renderer-v4.av-sync-preroll`, regression tests and
  ADR-019.

The sync fix is in `src/liveclip/renderer/ffmpeg.py`. It uses an input-side seek
at `source_start - min(source_start, 10s)`, decodes the preroll, then uses an
output-side accurate seek. Video/audio source filters no longer independently
subtract `STARTPTS`; overlay/fade windows are shifted onto the preroll timeline.

## Real database and artifact evidence

- Live database: `data/projects/liveclip.sqlite3` at Alembic
  `f3b6d9a2c841 (head)`; `alembic check` reports no pending operation.
- Pre-search WAL-safe backup:
  `data/projects/database-backups/liveclip-pre-project-search-3b1e1c0ad7304d7689452e6ff920c3bd.sqlite3`
  with SHA-256
  `1ed77aca699800797f1a09d3b33004657f6ae1b6ccdb47e0c165913c46883460`.
- Current integrity: `quick_check=ok`, zero foreign-key rows, zero active
  PipelineRuns and zero active Tasks.
- Current protected counts: 4 Projects, 4 SourceMedia, 6 PipelineRuns,
  176 candidates, 90 RenderJobs and 458 ApiUsage rows.
- `8-16-1` latest proxy rows: 15/15 `succeeded`, exact renderer contract v4.
- Each latest MP4 is 540×960 H.264/AAC; all 15 automatic reports, black-frame
  checks and full decodes pass.
- Measured latest MP4 stream-start deltas are either 0 ms or 40 ms (one 25-fps
  video frame), replacing the old content displacement of up to about 2.04 s.
- Timestamp evidence does not alone prove semantic lip sync; the user should
  still play representative clips before formal approval/delivery.

## Latest actual validation

- `make lint`: passed Ruff/format over 223 files, mypy over 136 source files,
  EditPlan schema verification and TypeScript typecheck.
- `make test`: passed 726 Python tests with 13 existing warnings, 57 Web tests,
  Mock Google Chrome E2E 1/1 and isolated real
  FastAPI/leased-Worker/SQLite/FFmpeg Google Chrome E2E 1/1.
- Post-compatibility adjustment: 44 renderer/contract/settings/Pipeline tests
  and `make lint` passed again.
- Real source spike at 1368 seconds: the old direct seek did not decode video
  until about 2.04 seconds after audio; the v4 path starts video at 40 ms and
  audio at 0 ms while preserving the shared source timeline.
- API and Web are running at `127.0.0.1:8765` and `127.0.0.1:5173`.

## Known observations and remaining scope

- Candidate ranks 2/4 overlap 34.4 seconds; ranks 6/12 overlap 8.3 seconds.
  This was observed but not changed during the synchronization repair.
- Real ASR contains some obvious lexical errors such as “强魂” and “甲瘤”;
  captions remain editable and no text was silently rewritten.
- Semantic lip-sync review of all 15 videos is still a human observation; no
  unsupported automatic mouth-motion claim is made.
- Existing older Projects were not rerendered under v4 because the user scoped
  the operational repair to `8-16-1`; their videos were not hidden or changed.
- Cross-Project optimistic bulk assignment is the next v0.2 collaboration
  slice. Native Jianying/CapCut draft import remains unverified; current editor
  handoff truthfully provides standards-based MP4/SRT metadata packages.
- Persisted `TaskAttempt.temp_identity` propagation through every synchronous
  cleanup call remains the documented cleanup P2.

## Security and worktree

- Never stage `.env`, `.env.local`, `OPENROUTER_SETUP.md`, `input/`, `data/`,
  SQLite/WAL, media, browser artifacts or offline packages.
- No source video was overwritten. Corrected proxies use fingerprinted new
  paths; historical proxy bytes remain immutable.
- No OpenRouter or Codex call was repeated for the 15 corrected renders.
- Source/test/docs commits are `fa395f6` and `0a266f3`; generated/private paths
  remain ignored and unstaged.

## Next concrete task

Have the user play at least the rank-3 and rank-8 v4 proxies in the `8-16-1`
Web workspace. If they confirm lip sync, continue human review or create an
offline review package. Do not rerun ASR/LLM.

For product development after that confirmation, implement revision-fenced
cross-Project bulk assignment without changing the working video pipeline.

## Resume instructions

Read `AGENTS.md`, both Product Specs, `docs/SOLUTION.md`, `.agent/PLANS.md`,
both Living ExecPlans and this file. Run `git status --short --branch`,
`git log -5 --oneline`, `.venv/bin/alembic current`, `.venv/bin/alembic check`
and confirm API/Web health. Preserve all four real Projects, both database
backups and existing offline-review packages. Verify `fa395f6` and `0a266f3`
are present/pushed. Open `8-16-1`, confirm the latest proxy path contains an
`s-.../t-.../review.mp4` segment and test rank 3 before any new processing.
