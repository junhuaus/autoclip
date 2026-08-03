# LiveClip v1 Living ExecPlan

This plan follows `.agent/PLANS.md`. It is the durable implementation and recovery record for the product contract in `docs/PRODUCT_SPEC.md` and the decisions in `docs/SOLUTION.md`.

## Purpose / Big Picture

A user on Apple Silicon macOS can import a local Chinese livestream by absolute path, process it through a recoverable local pipeline with OpenAI or deterministic Mock providers, review and revise accurate vertical highlight clips from CLI/Web, and create an immutable verified ZIP delivery. Completion is observable through real playable media, database state, HTTP/UI flows and reproducible commands—not interface stubs.

## Context and Orientation

The repository began empty on 2026-08-03 with an initialized Git repository, `master`, no commits/remotes and a clean worktree. M0 discovery found macOS 26.4.1 on Apple M2/24 GB; the target remains M3. Default Python 3.9 is unsupported and the existing Miniconda 3.12 is x86_64, so setup will install a project-local native arm64 Python 3.12 through uv. Default Node 26 is not LTS; `/usr/local/bin/node` 22.11.0 is arm64 LTS.

The host FFmpeg 8.1.2 has the media/layout/audio filters, AAC, libx264 and VideoToolbox needed except `subtitles`/`drawtext`. ADR-003 chooses Pillow-rendered RGBA text with FFmpeg overlay. VideoToolbox actually encoded on the host but returns OSStatus -12903 in the Codex sandbox; libx264 succeeds there.

Important paths:

- Product contract: `docs/PRODUCT_SPEC.md`
- Architecture: `docs/SOLUTION.md`, `docs/architecture.md`, `docs/adr/`
- Python package: `src/liveclip/`
- Entry adapters: `apps/api`, `apps/worker`, `apps/web`, `src/liveclip/cli`
- Tests: `tests/unit`, `tests/integration`, `tests/e2e`
- Runtime data: ignored `data/demo` and `data/projects`

## Scope

All M0–M6 requirements remain in scope. Milestones may close independently, but no later feature is treated as complete merely because a type or route exists. The current implementation focus after M0 is the real-media Mock vertical slice (M1).

## Architecture Summary

CLI/API/Worker call shared application commands/queries and a fixed pipeline executor. Pure domain models enforce canonical integer-millisecond timing, state transitions, immutable EditPlan revisions and delivery eligibility. SQLAlchemy/SQLite, local filesystem/FFmpeg, OpenAI/Mock and delivery are adapters behind ports. Tasks use fenced leases. Artifacts are validated immutable nodes published atomically. The Web is an API client.

## Milestones and progress

### M0 — Discovery, Solution and foundation

- [x] 2026-08-03 Inspect empty repository, Git state and existing conflicts.
- [x] 2026-08-03 Run three read-only agents: Explorer, Architecture Critic, Verifier/Documentation Researcher.
- [x] 2026-08-03 Inspect OS/runtime/SQLite/FFmpeg/fonts and run host/sandbox codec spikes.
- [x] 2026-08-03 Verify current official OpenAI Audio/Responses documentation without a paid call.
- [x] 2026-08-03 Create Product Spec, Solution, research notes, ADR baseline and architecture diagrams.
- [x] 2026-08-03 Create ExecPlan rules, Living ExecPlan, AGENTS and initial STATUS.
- [x] 2026-08-03 Create Python/project command skeleton and native arm64 3.12 environment.
- [x] 2026-08-03 Spike Pillow Chinese RGBA overlays through FFmpeg and visually inspect output.
- [x] 2026-08-03 Run M0 targeted lint/tests and initial read-only milestone review.
- [x] 2026-08-03 Fix all six initial review findings and add regression coverage (27 tests pass, including exact environment-name behavior).
- [x] 2026-08-03 Run post-fix read-only M0 re-review; verdict PASS with no residual blocker.
- [x] 2026-08-03 Create local M0 commit `136d8bd` after staged scope and whitespace checks.

### M1 — Mock minimum end-to-end vertical slice

- [x] 2026-08-03 Generate copyright-free H.264/AAC Demo video with visual motion, audio and measured silence.
- [x] 2026-08-03 Securely ingest, ffprobe and stream-hash source.
- [x] 2026-08-03 Extract mono compressed audio into three overlapped chunks and emit recoverable silence/chunk manifest.
- [x] 2026-08-03 Mock Chinese transcript with absolute times, cache identity and overlap deduplication.
- [x] 2026-08-03 Generate three deterministic candidates and Mock-edited strict EditPlans.
- [x] 2026-08-03 Render and validate three 540×960 proxies with captions/title.
- [x] 2026-08-03 Create a human title revision, preserve history and prove old proxy stale.
- [x] 2026-08-03 Reapprove revision 2 and render/validate 1080×1920 final plus relative SRT.
- [x] 2026-08-03 Atomically create v001 manifest and path-safe delivery.zip with verified media hash.
- [x] 2026-08-03 Generate and actually view final contact sheet; record `viewed_passed` and UTC time.
- [x] 2026-08-03 Run `make demo` twice; each succeeds with a distinct project and required absolute paths.
- [x] 2026-08-03 Add 68 unit plus one real integration test; lint/type and all 69 tests pass.
- [x] 2026-08-03 Run independent read-only M1 review; fix the clean provenance gap and receive `VERDICT: PASS` with 70 tests green.
- [x] 2026-08-03 Create local M1 checkpoint `cfc8889` and record its hash.

### M2 — Domain persistence, Pipeline, CLI and Worker

- [ ] Implement full entities, central transitions and SQLAlchemy repositories/UoW.
- [ ] Add Alembic initial schema with WAL/FK/busy-timeout integration.
- [ ] Implement Task claim/lease token/heartbeat/expiry/crash recovery and concurrency tests.
- [ ] Implement stage fingerprints/checkpoints/cancel/retry and source mutation detection.
- [ ] Implement required CLI commands through shared services.
- [ ] Implement independent Worker and foreground `--wait` ownership/polling behavior.
- [ ] Review, fix and commit M2.

### M3 — REST API, Web review and versioned delivery

- [ ] Implement all required `/api/v1` routes, DTOs, 202/idempotency/error/auth/CORS.
- [ ] Implement generated-asset HTTP Range service.
- [ ] Implement React/Vite review console and complete UI states.
- [ ] Implement revision subtitle editing, decisions, stale/rerender and delivery versions.
- [ ] Add API, component and Playwright core E2E tests.
- [ ] Review, fix and commit M3.

### M4 — Real OpenAI providers

- [ ] Lock and contract-test official SDK.
- [ ] Implement timestamp-capable OpenAI ASR, usage, retries, cache and resume.
- [ ] Implement Responses strict parsing, refusal/incomplete, one repair and degradation.
- [ ] Version prompt and persist prompt/model/request/usage metadata.
- [ ] Implement strict no-Mock `make smoke-cloud` preflight and execution.
- [ ] Run cloud smoke only if configuration exists; otherwise record not-run.
- [ ] Review, fix and commit M4.

### M5 — Long media, recovery, security and quality hardening

- [ ] Exercise multi-chunk streaming, interruption recovery and cancellation.
- [ ] Test traversal/symlink/source replacement/media Range/ZIP/redaction adversaries.
- [ ] Measure 2–4 hour memory/disk/runtime where representative input is available.
- [ ] Cover VFR, rotation, multi-audio and font/layout edge cases.
- [ ] Complete decode/contact-sheet/black-frame/safe-area validation and log bounds.
- [ ] Review, fix and commit M5.

### M6 — Independent acceptance and documentation

- [ ] Complete README, API/EditPlan/architecture/operations/troubleshooting documentation.
- [ ] Run frontend tests and browser E2E.
- [ ] Run `make doctor`, `make lint`, `make test`, `make demo` from a clean setup.
- [ ] Run cloud smoke when credentials exist; otherwise document precise unverified state.
- [ ] Run independent read-only Verification Agent against every Product Spec item.
- [ ] Fix verified gaps, rerun affected checks and record final artifact paths/results.
- [ ] Create final local commit/checkpoint and report truthful Git state.

## Work breakdown and file ownership

The main agent exclusively edits shared schemas, dependencies/locks, Alembic head, `AGENTS.md`, `STATUS.md`, `.agent/PLANS.md`, this plan, `docs/SOLUTION.md` and cross-module integration. Read-only reviewers never edit. Parallel implementation, when used, receives disjoint directories and may not edit these shared files.

M1 dependency order:

1. Foundation/config/domain types and tests.
2. Media ingest/preprocess and renderer primitives.
3. Mock providers/candidates/EditPlan.
4. Demo application service and review revision flow.
5. Delivery/quality validation.
6. CLI/Make target integration and real artifact inspection.

Active M1 file ownership (recorded before delegation):

- `m1_media`: only `src/liveclip/media/models.py`, `ingest.py`, `preprocess.py`, and `tests/unit/test_ingest.py`, `test_preprocess.py`.
- `m1_content`: only `src/liveclip/providers/asr/base.py`, `mock.py`, `src/liveclip/providers/llm/base.py`, `mock.py`, `src/liveclip/pipeline/transcript.py`, `candidates.py`, and `tests/unit/test_transcript.py`, `test_candidates.py`.
- Main Agent: shared domain schemas, Settings/dependencies, Demo/review/render/delivery integration (including `src/liveclip/delivery/package.py`), CLI/Makefile, all persistent planning documents and cross-module tests. A third write delegation was not started because the agent thread limit was reached.

Agents may read the full repository but may not modify another owner's files. The main Agent integrates and reviews all returned changes before any test or checkpoint claim.

M2 introduces persistence behind the M1 service ports rather than creating an alternate pipeline. M3 and M4 can proceed on separate adapters after M2; M5 integrates both.

## Concrete commands and expected observations

From repository root:

```bash
make setup
```

Expected: project-local `.python` contains a native arm64 Python 3.12; `.venv/bin/python` reports 3.12 and arm64; Python dependencies are locked/installed; frontend dependencies install when its lock exists; data roots exist. A repeat run changes nothing material.

```bash
make doctor
```

Expected on the discovery host: overall Mock-ready result; Python/Node/SQLite/data checks pass; `subtitles`/`drawtext` are reported absent with raster fallback; a real VideoToolbox attempt may fail in sandbox and must report verified libx264 fallback; OpenAI is unconfigured without revealing any value. M2 versus target-M3 performance is a documented limitation, not a doctor capability failure.

```bash
make lint
make test
```

Expected: nonzero on any Ruff/type/unit/integration failure; output states test count and skips. Standard tests make no cloud request.

```bash
make demo
```

Expected: exit zero only after the real-media M1/M6 acceptance chain, and print project ID plus absolute final, contact-sheet and ZIP paths. Re-running creates a separate Demo project/version and does not overwrite an immutable delivery.

```bash
make smoke-cloud INPUT=/absolute/path/to/short.mp4
```

Expected now: nonzero, with missing variable names and `not_run`, because no OpenAI key/model environment is configured. With configuration it must prove both real provider calls and never instantiate Mock.

## Validation criteria

Each milestone validates observable outputs described in its checklist. Media success requires ffprobe, full decode and hashes; UI success requires rendered browser behavior; queue success requires competing workers and expired-token evidence; cloud success requires persisted real provider/request metadata. Interface-only or mocked subprocess assertions do not satisfy end-to-end criteria.

## Idempotency, retry and recovery

Setup and Demo generation use isolated/generated targets. A stage re-run compares input fingerprints and validated output manifests. Tasks use fenced leases and bounded retries. Temp files have attempt identities and never count as success. Immutable revisions/deliveries are never overwritten. Failed cloud smoke preserves accurate failure status and cannot downgrade. Recovery starts from the first unsucceeded current-generation stage after validating prior checkpoints.

## Surprises and Discoveries

- 2026-08-03: Repository was completely empty; there are no user changes or compatibility constraints.
- 2026-08-03: Installed Python 3.12 is x86_64 despite arm64 host; project-local native Python is required.
- 2026-08-03: Node 22 LTS exists but default Node 26 is non-LTS.
- 2026-08-03: FFmpeg help for an unknown filter can still exit zero. Doctor must parse the actual filter list.
- 2026-08-03: FFmpeg lacks both common text filters but has overlay; this led to the safer raster-overlay design.
- 2026-08-03: VideoToolbox fails only inside the Codex sandbox and succeeds on host; capability claims need real context.
- 2026-08-03: Current general ASR recommendation lacks required timestamps; v1 defaults to the older timestamp-capable model rather than fabricate alignment.
- 2026-08-03: First viewed overlay contact sheet revealed a false truncation ellipsis caused by trimming a wrap-boundary space. The wrap algorithm now tracks actual truncation; a regression test and second viewed render pass.
- 2026-08-03: Initial M0 review found six concrete gaps. Publication now validates container/codecs/decode/frames/edges/safe bounds before exposure, uses an atomic hard-link no-clobber operation, and falls back on VideoToolbox runtime exceptions. Font detection no longer points from renderer into CLI, and EditPlan tests cover generic paths, shell commands and FFmpeg option fragments.
- 2026-08-03: The post-review render `/private/tmp/liveclip-m0-overlay-reviewed.Ot6m6j/vertical-overlay.mp4` passed MP4/H.264/AAC, exact 540×960/4.000s, full decode, automatic quality and actual contact-sheet inspection. Its SHA-256 is `4713a270416b9def76a023211fd5b40e9a72538739e33f9b1000b6e7d8e19e56`.
- 2026-08-03: Settings initially applied the `LIVECLIP_` prefix to fields whose public contract is explicitly unprefixed (`ASR_CHUNK_SECONDS`, `DEFAULT_TOP_N`, and peers). Explicit validation aliases and an environment behavior test now keep runtime parsing aligned with `.env.example`.
- 2026-08-03: M1 uses a 32-second generated source and explicit 8–12 second candidate limits so a full local acceptance finishes in about 23 seconds; configured product defaults remain 30–90 seconds. It still exercises three overlapped audio chunks, three proxies, revision invalidation, a 1080×1920 final and ZIP delivery.
- 2026-08-03: The first full Demo `demo_20260803T075537_0e3ca9f9` reached `delivered`. Final MP4 is H.264/AAC 1080×1920, 12.000s, 3,411,094 bytes, SHA-256 `f1ddd09178868745ea88c82995b35a5f7ecd1542d7ba616e0559db7ab7ac2ddd`; complete decode and actual visual review passed.
- 2026-08-03: A second `make demo` created distinct project `demo_20260803T075904_1fdd3288`, proving rerun isolation rather than overwriting the first immutable v001.
- 2026-08-03: M1 review identified that directory confinement alone did not prove `clean-demo` ownership. Cleanup now requires both a generated project-name shape and a valid `.phase.json` marker; unknown and unmarked content is preserved. The independent Reviewer returned PASS after 70 tests, lint and retained-artifact inspection.

## Decision Log

- 2026-08-03: Choose modular monolith/ports and adapters; rationale: three entry points need one business implementation.
- 2026-08-03: Choose integer milliseconds; rationale: exact revision, SQLite, JSON, SRT and FFmpeg conversions.
- 2026-08-03: Choose fenced SQLite Task leases plus immutable atomic artifacts; rationale: CLI/Worker crash/race safety.
- 2026-08-03: Choose Pillow RGBA overlays; rationale: host compatibility and strong text/filter syntax separation.
- 2026-08-03: Choose `whisper-1` as capability-driven v1 default; rationale: official real segment/word timestamps.
- 2026-08-03: Choose stateless strict Responses with no tools and at most one repair; rationale: privacy and deterministic safety boundary.
- 2026-08-03: Publish validated renderer output with `link(2)` from a same-directory private temp name and fail if the destination exists; rationale: `os.replace` can overwrite a competing immutable revision artifact after an `exists()` race.

## Risks and Mitigations

- Raster overlay performance: Spike with multiple Chinese cues and measure before M1 closes; use one static image per cue, not per frame.
- Sandbox VideoToolbox false-negative: always implement and test libx264 fallback; record host doctor separately.
- Long-media resource use: streaming I/O, bounded chunks/logs, single heavy worker and M5 measurement.
- Source reference mutation: stat identity/re-hash checkpoints and deterministic failure.
- SQLite/filesystem split-brain: immutable paths, lease/revision fencing, hashes, validation and atomic publish.
- Model/schema drift: pinned SDK, configurable models, contract smoke, local validation and deterministic fallback.
- Visual heuristics overclaim: quality report distinguishes automatic from actual viewed status.

## Recovery Notes

Current first task: implement and table-test centralized domain state transitions, then add the SQLAlchemy SQLite engine/ORM/UoW foundation for PipelineRun, StageRun and fenced Task leases.

Before resuming, read the five files listed in `AGENTS.md`, run `git status --short --branch` and inspect the last five commits. Verify the most recent command recorded in `STATUS.md`; do not repeat completed discovery.

## Outcomes and Retrospective

M0 is complete at commit `136d8bd`. M1 is complete at commit `cfc8889`: two bounded subagent implementations integrated, 70 tests pass, two real Demos reached `delivered`, the first final was fully decoded and actually viewed, its immutable ZIP/hash/state were inspected, and the independent Reviewer returned PASS. M2 has started with centralized state and persistence as the first dependency.
