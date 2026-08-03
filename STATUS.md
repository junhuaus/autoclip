# LiveClip status snapshot

Updated: 2026-08-03
Current milestone: M3 — REST API, Web review and versioned delivery
Branch: `master`
Recent relevant commit: `09a6f10` (`milestone: complete LiveClip M2 persistent pipeline`)

## Completed

- Confirmed repository initially contained only `.git`; no user files or uncommitted changes.
- Completed three read-only startup reviews: environment/repo, architecture, and official-document verification.
- Confirmed macOS 26.4.1 arm64 on Apple M2/24 GB; target remains M3.
- Confirmed SQLite WAL/FK/busy-timeout/RETURNING and Chinese fonts.
- Confirmed FFmpeg 8.1.2 media capabilities and exact absence of subtitles/drawtext.
- Actually proved host VideoToolbox encode + ffprobe + full decode; sandbox VideoToolbox fails -12903 and libx264 fallback succeeds.
- Verified current official OpenAI Audio and Responses documentation without making a paid call.
- Created Product Spec, Solution, architecture/API/EditPlan docs, research notes, four ADRs, plan rules, Living ExecPlan and AGENTS guide.
- Installed project-local CPython 3.12.13 arm64, synchronized locked dependencies and generated `uv.lock`.
- Implemented Settings, CLI doctor, canonical time/EditPlan/caption models, deterministic raster text overlays, FFmpeg builder/fallback and media quality validation.
- Completed the first read-only M0 review. Fixed all six findings: complete pre-publication checks, atomic no-clobber publication, exception-safe codec fallback, shared font dependency, bounded EditPlan text policy, and stale recovery evidence.
- Completed the post-fix read-only M0 re-review with `VERDICT: PASS`; no evidence-backed residual blocker was found.
- Rendered and validated `/private/tmp/liveclip-m0-overlay-reviewed.Ot6m6j/vertical-overlay.mp4` with MP4/H.264/AAC, 540×960, exact 4.000-second duration, 491,732 bytes and full decode.
- Actually viewed `/private/tmp/liveclip-m0-overlay-reviewed.Ot6m6j/quality/contact-sheet.png`; title/captions/layout passed visual review and the quality report records `viewed_passed`.
- `make lint` passes and all 27 unit tests pass.
- Created the local M0 milestone commit `136d8bd` after staged whitespace/scope checks.
- Implemented secure allowed-root ingest, streamed SHA-256, ffprobe metadata, mutation checks and strict source models.
- Implemented resumable mono AAC/m4a preprocessing with three overlapped Demo chunks, `silencedetect`, cache keys, hash verification, cancellation boundaries and atomic checkpoints.
- Implemented Mock ASR/LLM ports, absolute transcript merge/de-duplication/cache, deterministic candidate scoring/de-duplication/fallback and strict EditPlans.
- Implemented immutable EditPlan revision/review/render history, old-render stale rules, renderer integration and safe versioned MP4/SRT/manifest/ZIP delivery.
- Implemented `liveclip demo`, `make demo`, guarded `liveclip clean-demo`, 68 unit tests and one real FFmpeg integration test.
- Ran two complete Demos; both reached `delivered` with distinct project IDs. The first final/contact/ZIP were fully inspected and retained below `data/demo`.
- Closed the `clean-demo` provenance gap: only marker-validated generated Demo project directories are removed; unknown and unmarked content is preserved.
- Completed the independent read-only M1 review with `VERDICT: PASS`; no M1 blocker remains.
- Created local M1 milestone commit `cfc8889` after staged scope/whitespace checks and Reviewer PASS.
- Implemented centralized PipelineRun/StageRun/Task/Asset/Review/Render/Delivery transitions and 20-table SQLAlchemy schema.
- Added Alembic initial migration `c0a0568060fb`, repeatable upgrade/downgrade, schema drift check, integrity check and foreign-key check.
- Added a WAL-safe embedded SQLite runtime gate, explicit transactions, `BEGIN IMMEDIATE`, foreign keys, busy timeout and `synchronous=FULL`; project Python embeds safe SQLite 3.53.1.
- Implemented atomic Task claims, heavy-work singleton, fenced lease tokens, independent heartbeat, expiry/crash recovery, bounded retry, durable cancellation and generation/revision checks.
- Implemented pending/committed Asset reservations, attempt-owned paths, hash/tamper checks, safe adoption and committed-Asset stage checkpoints.
- Implemented all six persistent Mock Stage handlers and a shared `StageTaskRunner`; only a committed stage creates the next Task from its real output fingerprint.
- Implemented `liveclip run --wait`, `status`, `clips`, `worker` and `liveclip-worker`; foreground CLI and Worker use the identical queue/runner path.
- Added cancellation-aware FFmpeg/ffprobe process groups; cancelling or losing a lease terminates owned subprocess work and cleans unpublished temporary files.
- Proved a real persistent 32-second Mock chain reaches `pending_review` with three actual 270×480 H.264/AAC proxies and durable DB facts.
- Proved a foreground/independent-Worker race executes every logical stage once, and a running durable cancel is observed and acknowledged by the lease owner.
- Closed the first M2 review findings with typed stage checkpoint validation, transaction-local stage mutation fences and cancellation-precedence handling.
- Closed the final M2 review findings by deriving Asset ownership from the active Task lease, rejecting cross-project/cross-generation/cross-revision publication and forbidding pending-Asset adoption across logical Tasks.
- Persisted proxy RenderJobs through `queued → running → succeeded|failed`; FFmpeg failure, cancellation and lease expiry now leave durable error evidence instead of disappearing before commit.
- Classified bounded ingest, preprocess and quality process timeouts as transient while keeping validation/parameter faults deterministic.
- Completed the final independent read-only M2 review with `PASS`; no P0/P1 issue remains. Reviewer-focused 82 tests and all 204 tests passed.
- Created the scoped local M2 milestone commit `09a6f10` after lint/type, staged whitespace and staged-scope checks.

## In progress

- M3 shared review/revision/rerender/delivery application services and REST API design/implementation.

## Not completed

- M3–M6 implementation/final acceptance.
- Review/rerender/delivery CLI commands remain M3 work with their shared application services; they are not separate CLI-only implementations.

## Verified

- `git status --short --branch` initially: `## No commits yet on master` and clean.
- Default `python3`: 3.9.6 arm64; existing `python3.12`: 3.12.4 x86_64 (unsuitable as native target).
- `uv`: 0.11.25 arm64.
- Default Node 26.0.0 non-LTS; `/usr/local/bin/node` 22.11.0 arm64 LTS Jod.
- FFmpeg/ffprobe 8.1.2; loudnorm/silencedetect/overlay/libx264/h264_videotoolbox present; subtitles/drawtext absent.
- Host VideoToolbox one-second H.264/AAC output passed ffprobe and full decode.
- No `OPENAI_API_KEY` or LiveClip allowed-root configuration is present.

## Not yet verified

- Pillow overlay performance on full 30–90 second clips and many cues.
- Full 30–90 second raster performance and many-cue clips.
- REST API, Web review, revision/final-render/delivery services and cloud calls.
- Apple M3-specific performance and 2–4 hour media behavior.
- True multi-process lease contention; the current independent runner proof uses separate runners/connections in one process.
- Generation-scoped canonical stage artifact paths for a second PipelineRun on the same Project.

## Recent commands and real results

- `git status --short --branch`: no commits on master; initially clean.
- environment version checks: succeeded; differences recorded above.
- FFmpeg filter/encoder/font checks: succeeded; text-filter gap recorded.
- real sandbox libx264 Spike: succeeded with full decode.
- approved host VideoToolbox Spike: succeeded with full decode; sandbox attempt failed OSStatus -12903.
- official documentation resolver: current model family resolved to GPT-5.6; official Audio/Structured Outputs pages read.
- `make setup`: exit 0; CPython 3.12.13 arm64, 53 dependencies installed and locked.
- `make doctor`: exit 0; READY with four truthful warnings (text-filter raster fallback, no allowed roots/key, sandbox VideoToolbox fallback).
- initial M0 Reviewer: blocked on six evidence-backed findings; every finding has a code/test/document fix in the current worktree.
- repeated `make setup`: exit 0 in 0.4s; native Python already installed, 53 packages checked, Python 3.12.13 arm64.
- product environment-name audit: corrected exact unprefixed Settings aliases and added a behavior test matching `.env.example`.
- post-fix M0 Reviewer: `PASS`; all six original blockers and the Settings alias correction have file-and-test evidence.
- `make lint`: exit 0; Ruff/format pass on 35 files and mypy passes on 27 source files.
- `make test`: exit 0; 27 passed in 0.15s.
- reviewed overlay Spike: exit 0; `/private/tmp/liveclip-m0-overlay-reviewed.Ot6m6j/vertical-overlay.mp4`, SHA-256 `4713a270416b9def76a023211fd5b40e9a72538739e33f9b1000b6e7d8e19e56`, 491,732-byte MP4/H.264/AAC, 540×960, 4.000s.
- independent ffprobe and complete FFmpeg decode passed with no decode output; pre-publication and durable automatic quality checks passed.
- `/private/tmp/liveclip-m0-overlay-reviewed.Ot6m6j/quality/contact-sheet.png` was actually viewed with correct portrait layout, background/foreground ratio, Chinese glyphs and safe areas; report records `viewed_passed` at `2026-08-03T07:27:16.848767+00:00`.
- media Agent: 19 targeted tests pass; actual 3-second ingest/preprocess/resume Spike produced three AAC mono 16 kHz chunks at `/private/tmp/liveclip-m1-media.Z9mTDh/audio-current`.
- content Agent: 9 targeted tests pass; strict mypy/Ruff pass; no network/subprocess execution in Mock content path.
- `make lint`: exit 0; Ruff/format pass on 62 files and mypy passes on 45 source files.
- `make test`: exit 0 before review; 69 passed in 21.60s, including the real local integration chain.
- first `make demo`: exit 0 in 22.28s; `demo_20260803T075537_0e3ca9f9`, 3 candidates, project status `delivered`.
- first final: `/Users/junhuaxu/Workspace/AGI/liveclip-ai/data/demo/projects/demo_20260803T075537_0e3ca9f9/renders/final/clip_01_bdc52e84/r002/final.mp4`; MP4/H.264/AAC 1080×1920, 12.000s, 3,411,094 bytes, full decode passed, SHA-256 `f1ddd09178868745ea88c82995b35a5f7ecd1542d7ba616e0559db7ab7ac2ddd`.
- first contact: `/Users/junhuaxu/Workspace/AGI/liveclip-ai/data/demo/projects/demo_20260803T075537_0e3ca9f9/renders/final/clip_01_bdc52e84/r002/final-quality/contact-sheet.png`; actually viewed and report records `viewed_passed` at `2026-08-03T07:56:21.348579+00:00`.
- first delivery ZIP: `/Users/junhuaxu/Workspace/AGI/liveclip-ai/data/demo/projects/demo_20260803T075537_0e3ca9f9/deliveries/v001/delivery.zip`; exactly one clip, one SRT and manifest; delivered copy hash equals final hash.
- state inspection proves revision 1 AI/approved/proxy→stale, revision 2 human/approved/final→succeeded, and Project `delivered`.
- second `make demo`: exit 0 in 23.57s; distinct `demo_20260803T075904_1fdd3288` and independent v001 delivery.
- latest `make doctor`: exit 0; READY with the same four truthful warnings.
- `clean-demo` provenance regression: targeted 5 tests pass; unknown files/directories and unmarked Demo-shaped directories are preserved.
- post-fix `make lint`: exit 0; Ruff/format pass on 62 files and mypy passes on 45 source files.
- post-fix `make test`: exit 0; 70 passed in 23.34s.
- independent M1 Reviewer: `PASS`; it independently reran the updated targeted tests/full suite/lint, inspected retained media/state/ZIP, and actually viewed the final contact sheet.
- `git commit`: local M1 checkpoint `cfc8889`; 31 scoped files, 4,963 insertions and no generated media.
- SQLite primary-source research: active `.venv` SQLite 3.53.1 passes the WAL-safety gate; system SQLite 3.51.0 is rejected as an unsafe branch.
- Alembic integration: upgrade twice, `command.check`, downgrade/base, re-upgrade, schema-head match, `PRAGMA integrity_check` and `foreign_key_check` all pass.
- persistent Mock integration: six Tasks succeeded; at least three rough candidates, exactly three selected EditPlans and three validated proxy RenderJobs persisted.
- CLI integration: `run --wait`, `status` and `clips` complete through an Alembic-created file database and real FFmpeg media.
- competition integration: independent Worker receives `idle` while foreground owns ingest; all six stage handler counts equal one and PipelineRun completes.
- cancellation tests: durable running cancel reaches `cancelled`; actual long child process terminates in under three seconds without writing its late marker.
- `uv lock --check` with project-local cache: exit 0; 56 packages resolved.
- pre-review `make lint`: exit 0; Ruff/format pass on 97 files and strict mypy passes on 66 source files.
- pre-review `make test`: exit 0; 185 passed in 40.93s, including five real local integration flows and no cloud calls.
- final M2 `make lint`: exit 0; Ruff/format pass on 99 files and strict mypy passes on 66 source files.
- final M2 `make test`: exit 0; 204 passed in 50.18s on the main integration snapshot; the independent Reviewer repeated it as 204 passed in 170.25s.
- final M2 focused review suite: exit 0; 82 passed in 28.30s, covering Asset ownership attacks, timeout taxonomy, RenderJob lifecycle, stale lease fences, cancellation precedence and recovery.
- final M2 `git diff --check`: exit 0.
- independent M2 Reviewer: `PASS`; no remaining P0/P1 issue. Residual P2 items are bounded ingest/ffprobe cancellation latency, generation-scoped paths and a future true multi-process race test.

## Current blockers

No product decision blocker. OpenAI credentials are absent, so cloud smoke is expected `not_run`. The FFmpeg text-filter gap is addressed by ADR-003 and the current raster replacement passed its M0 Spike.

## Worktree state

M0 is committed at `136d8bd` with status checkpoint `1dbed41`; M1 is committed at `cfc8889` with checkpoint `8d8004c`; M2 is committed at `09a6f10` and this status update is its documentation checkpoint. Generated Demo media is ignored and retained as evidence. Run `git status --short --branch` for the authoritative list.

## Next concrete task

Implement the shared M3 review/revision/rerender/delivery services, including generation-scoped persistent artifact paths, then expose them through the REST API and CLI.

## Resume prompt

```text
Resume the LiveClip long-running goal. Read AGENTS.md, docs/PRODUCT_SPEC.md, docs/SOLUTION.md, all of .agent/PLANS.md, docs/exec-plans/liveclip-v1.md, and STATUS.md. Check git status --short --branch and recent commits. Verify the latest STATUS evidence, then continue the single Next concrete task without repeating completed discovery. Keep ExecPlan and STATUS current and do not claim unrun validation.
```
