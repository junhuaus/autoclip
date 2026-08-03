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

All M0–M6 requirements remain in scope. Milestones may close independently, but no later feature is treated as complete merely because a type or route exists. M0 and M1 are committed; M2 passed independent review, and the current implementation focus is M3 REST/review/delivery services and Web.

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

- [x] 2026-08-03 Implement 20 persistent entities, central transition tables and SQLAlchemy repositories/UoW.
- [x] 2026-08-03 Add a drift-checked Alembic initial schema plus WAL/FK/busy-timeout/FULL integration and an unsafe-runtime gate.
- [x] 2026-08-03 Implement atomic Task claim, random lease token, heartbeat, expiry/crash recovery, bounded retry and generation fences.
- [x] 2026-08-03 Implement real six-stage Mock handlers with committed Asset checkpoints, exact downstream fingerprints, cancellation and resume.
- [x] 2026-08-03 Implement pipeline CLI `run --wait`, `status`, `clips`, and `worker` through shared services. Review/rerender/delivery CLI commands remain paired with their M3 application services; product scope is unchanged.
- [x] 2026-08-03 Implement independent Worker and foreground ownership/polling with a real competition integration test proving one execution per stage.
- [x] 2026-08-03 Replace long FFmpeg validation/extraction/render calls with process-group cancellation; cancellation never publishes a successful artifact.
- [x] 2026-08-03 Run migration round-trip/drift/integrity checks, strict lint/types and 204 local tests including real persistent media and CLI chains.
- [x] 2026-08-03 Complete two independent read-only review passes, fix every P0/P1 finding and receive final `PASS` with 82 focused and 204 full tests green.
- [x] 2026-08-03 Create scoped local M2 milestone commit `09a6f10`; record it in the documentation checkpoint.

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

Active M2 file ownership (recorded before delegation):

- Main Agent: `domain/state_transitions.py`, shared ORM/entity schemas, repositories/UoW, Task queue integration, Alembic head, application services, CLI/Worker integration, dependencies and persistent planning documents.
- `m1_media`: only `src/liveclip/db/engine.py` and `tests/unit/test_db_engine.py`; implement SQLite connection/transaction configuration without editing Settings, ORM models or migrations.
- `m1_content`: read-only M2 state/lease/idempotency/crash-recovery acceptance matrix; no file changes.
- `verifier_researcher`: read-only primary-source check of current SQLAlchemy 2, Alembic and SQLite behaviors relevant to `BEGIN IMMEDIATE`, pragmas and atomic claim; no file changes.

No delegated M2 task may modify shared schemas, migrations, dependencies or status documents. Main integrates returned evidence before declaring any persistence behavior.

M2 integrated shape:

1. `PipelineService` creates a Project, immutable PipelineRun config, six visible StageRuns, and only the dependency-free ingest Task.
2. `StageTaskRunner` is shared by foreground CLI and Worker. It claims a fenced lease, starts a stage, heartbeats on an independent connection, executes external I/O without a DB transaction, and commits through one repository boundary.
3. Each handler reserves Assets before I/O, writes under an attempt identity, validates and atomically publishes bytes, commits Asset hashes, then completes the Stage. Only then is the next Task created from the actual upstream output plus config fingerprint.
4. The persistent Mock chain stores source metadata, audio chunks, transcript rows, rough candidates, selected immutable EditPlan revisions, captions and real validated proxy RenderJobs.
5. CLI review/rerender/deliver commands intentionally remain unimplemented until M3 supplies the shared revision/render/delivery services; adapters will not grow duplicate domain logic to make M2 appear complete.
6. Asset scope is derived inside the reservation/commit transaction from TaskAttempt → Task → PipelineRun → Project. Caller-provided project/generation/revision values are assertions, not authority; only the same logical Task may recover its failed/lost pending reservation.
7. Typed stage checkpoint validation proves both committed artifacts and required domain rows before stage success. Stage/Task/Run/Project updates share an active lease and generation fence under `BEGIN IMMEDIATE`.
8. Proxy RenderJobs are durable before media I/O and transition through the centralized state model. Failure, cancellation and lease expiry persist a safe error code; success requires every associated Asset to be committed.

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
- 2026-08-03: SQLite 3.51.0 on the system runtime is inside an officially disclosed WAL-reset race range; the project CPython embeds SQLite 3.53.1. Setup, doctor and runtime now reject known-unsafe branches instead of trusting the standalone `sqlite3` executable.
- 2026-08-03: Pre-creating all six Tasks produced false downstream input fingerprints. M2 now pre-creates StageRuns for visibility but creates each downstream Task only after validating the prior stage's committed Asset hashes.
- 2026-08-03: Chunk-boundary cancellation was insufficient for a long FFmpeg call. A shared `Popen(..., shell=False, start_new_session=True)` runner polls the durable heartbeat signal and terminates the owned process group on cancellation, lease loss or timeout.
- 2026-08-03: The real persistent Mock pipeline produces three 270×480 H.264/AAC proxies from six leased stages; a separate foreground/Worker race test observes one handler execution for every stage and no duplicate claim.
- 2026-08-03: Initial M2 review demonstrated that an arbitrary committed Asset could satisfy a stage and that StageStateStore mutations were not lease-fenced. Completion now uses typed per-stage domain checkpoints and all related mutations validate Task/Attempt/Run/Project generation in one immediate transaction.
- 2026-08-03: Final M2 review demonstrated that caller-supplied Asset scope could cross project/revision boundaries and that proxy render rows appeared only after successful I/O. Asset scope is now database-derived, cross-logical-Task adoption is forbidden, and observable RenderJobs persist through running/failure/cancel/lease-expiry states.
- 2026-08-03: Ingest, preprocess and quality subprocess timeout paths are explicitly transient. Argument, media-contract and validation errors remain deterministic, so bounded retry does not conceal bad inputs.
- 2026-08-03: The independent final M2 Reviewer returned `PASS` after 82 focused tests, lint, 204 full tests and whitespace validation. It retained three P2 risks for M3/M5: non-interruptible in-process fingerprint/ffprobe latency, non-generation-scoped canonical paths and lack of a true separate-process contention test.

## Decision Log

- 2026-08-03: Choose modular monolith/ports and adapters; rationale: three entry points need one business implementation.
- 2026-08-03: Choose integer milliseconds; rationale: exact revision, SQLite, JSON, SRT and FFmpeg conversions.
- 2026-08-03: Choose fenced SQLite Task leases plus immutable atomic artifacts; rationale: CLI/Worker crash/race safety.
- 2026-08-03: Choose Pillow RGBA overlays; rationale: host compatibility and strong text/filter syntax separation.
- 2026-08-03: Choose `whisper-1` as capability-driven v1 default; rationale: official real segment/word timestamps.
- 2026-08-03: Choose stateless strict Responses with no tools and at most one repair; rationale: privacy and deterministic safety boundary.
- 2026-08-03: Publish validated renderer output with `link(2)` from a same-directory private temp name and fail if the destination exists; rationale: `os.replace` can overwrite a competing immutable revision artifact after an `exists()` race.
- 2026-08-03: Gate the active Python SQLite library on officially fixed WAL branches and use `synchronous=FULL`; rationale: durability and lease correctness depend on the embedded library, not a separate CLI version.
- 2026-08-03: Create only the next dependency Task after stage commit; rationale: its idempotency identity must include actual validated upstream output.
- 2026-08-03: Use one cancellation-aware process-group runner for pipeline FFmpeg/ffprobe work; rationale: a durable cancel must stop owned work before any success publication.
- 2026-08-03: Treat caller Asset scope only as a checked assertion and derive authority from the active TaskAttempt graph; rationale: API/service bugs must not widen a lease into another project, generation, candidate or revision.
- 2026-08-03: Persist proxy RenderJob intent and running state before FFmpeg I/O; rationale: failure, cancellation and crash recovery must remain user-observable and retryable.
- 2026-08-03: Use explicit transient exception types for bounded process timeouts; rationale: retry behavior must not depend on fragile message matching or generic runtime exceptions.

## Risks and Mitigations

- Raster overlay performance: Spike with multiple Chinese cues and measure before M1 closes; use one static image per cue, not per frame.
- Sandbox VideoToolbox false-negative: always implement and test libx264 fallback; record host doctor separately.
- Long-media resource use: streaming I/O, bounded chunks/logs, single heavy worker and M5 measurement.
- Source reference mutation: stat identity/re-hash checkpoints and deterministic failure.
- SQLite/filesystem split-brain: immutable paths, lease/revision fencing, hashes, validation and atomic publish.
- Model/schema drift: pinned SDK, configurable models, contract smoke, local validation and deterministic fallback.
- Visual heuristics overclaim: quality report distinguishes automatic from actual viewed status.
- Canonical stage paths currently omit PipelineRun generation: M3 will make run/generation part of persistent pipeline artifact names before supporting a second run on one Project; immutable collision remains fail-closed meanwhile.
- Current ownership race test uses two independent runners/connections in one process: add a spawned-process contention/lease-expiry test in M5; database fencing, not the test topology, is the correctness mechanism.
- Stream hashing and the Python-side ffprobe wrapper cannot be interrupted mid-call: bounded subprocess timeouts and late-publication fences cap correctness impact; M5 will measure cancellation latency and add polling where practical.

## Recovery Notes

Current first task: implement M3 shared review/revision/rerender/delivery services, including generation-scoped persistent artifact paths, then expose them through REST routes and CLI.

Before resuming, read the five files listed in `AGENTS.md`, run `git status --short --branch` and inspect the last five commits. Verify the most recent command recorded in `STATUS.md`; do not repeat completed discovery.

## Outcomes and Retrospective

M0 is complete at commit `136d8bd`. M1 is complete at commit `cfc8889`: two bounded subagent implementations integrated, 70 tests pass, two real Demos reached `delivered`, the first final was fully decoded and actually viewed, its immutable ZIP/hash/state were inspected, and the independent Reviewer returned PASS. M2 is complete at commit `09a6f10` with independent `PASS`: Alembic and the persistent six-stage pipeline are real, foreground/Worker ownership is shared and fenced, cancellation terminates subprocess groups, Asset authority is database-derived, RenderJob failures are durable, and 204 tests pass. M3 implementation is active.
