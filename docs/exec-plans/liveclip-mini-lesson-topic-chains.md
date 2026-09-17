# LiveClip mini-lesson Topic Chain Living ExecPlan

This plan follows `.agent/PLANS.md`. It is the durable implementation and recovery record for the
independent `mini_lesson` clipping profile requested on 2026-09-10. Historical semantic-global and
semantic-windowed contracts remain immutable compatibility evidence.

## Purpose / Big Picture

A user can keep LiveClip's default 45--90 second `short_highlight` behavior or explicitly select a
90--300 second `mini_lesson` profile. Mini-lessons recover one complete teaching objective across
multiple 120-second logical windows by asking an Agent to link boundary fragments into a Topic Chain,
then independently review boundaries, score, gate, cap, and render that profile. Time proximity routes
evidence to an Agent but never decides semantic identity.

## Context and Orientation

The current recommended path is `semantic_windowed`: 120-second logical windows, 60-second stride,
four-window/300-second Discovery batches, deterministic ownership, optional 180-second boundary
transport, V3 candidate Boundary Review, V3 Global Review, deterministic gates, and FFmpeg. Relevant
code is in `src/liveclip/pipeline/semantic_global.py`, `stage_handlers.py`, `semantic_cache.py`,
`src/liveclip/providers/llm/structured.py`, `src/liveclip/application/pipeline.py`, `bootstrap.py`, and
the versioned resources below `src/liveclip/clipping_skills` and `src/liveclip/schemas/clipping`.

The worktree already contains extensive user and prior-session changes. All work in this milestone is
additive and versioned. No old PipelineRun, Delivery, database row, Provider cache, or source media is
to be overwritten.

## Scope and non-goals

In scope: immutable profile configuration, Discovery boundary/fragments, Agent Link Review, iterative
Topic Chain assembly, Agent-owned natural splitting, per-candidate Boundary Review, per-profile Global
Review and Top-N, deterministic validation/audit, stage-local caches and retries, Mock-provider tests,
real-SRT regression, CLI selection, documentation, and an environment-eligible real run.

Out of scope: whole-transcript single-call processing, Python semantic heuristics, multi-interval clips,
jump cuts, deleting middle sentences, hard-coded source timestamps/phrases, cross-profile competition,
and fabricated Provider or media success.

## Milestones and progress

- [x] 2026-09-10 Read the required Product Spec, Solution, planning, v0.2, and STATUS documents.
- [x] 2026-09-10 Inspect the dirty worktree and current V3 semantic/Prompt/cache/stage boundaries.
- [x] Add immutable profile types/config and preserve `short_highlight` as the default behavior.
- [x] Add versioned V4 Discovery, Link Review, Topic Chain, Boundary Review, and Global Review models,
  checked-in Schemas, and Prompt bundles.
- [x] Implement deterministic routing/validation/chain assembly without semantic time or text rules.
- [x] Integrate mini-lesson processing, per-stage caching/local repair, audit artifacts, and auto-only
  rendering into the existing six-stage Pipeline.
- [x] Add all requested unit/integration/mock/real-SRT regressions and retain old compatibility tests.
- [x] Run formatting, focused tests, full lint/tests, and inspect an actual Mock-driven mini-lesson
  FFmpeg artifact plus the isolated real local API/Worker/SQLite/FFmpeg browser artifact.
- [x] Start a non-overwriting mini PipelineRun for `input/8-30.ts`, preserve its successful real ASR,
  and record the managed-session nested-Codex blocker without inventing editorial results.
- [x] Update Product Spec, Solution, ADR, this plan, and STATUS with exact final evidence.

## Work breakdown and ownership

The main Agent owns every file in this milestone: shared models/config, Prompt and JSON Schema
contracts, Pipeline integration, tests, migration decision, Product/Solution/ADR, this plan, and
STATUS. No parallel writer is active.

Implementation dependency order:

1. Define pure profile/V4 wire and deterministic result contracts.
2. Add Prompt/Schema loaders and Mock structured outputs.
3. Add Link routing, Agent-result-only graph assembly, natural split validation, per-profile gates,
   audit accounting, and cache identities.
4. Add Pipeline config/CLI/bootstrap compatibility and stage orchestration.
5. Add fixture/unit/integration tests, then documentation and real acceptance.

## Concrete commands and expected observations

From the repository root:

    .venv/bin/ruff check src tests
    .venv/bin/pytest tests/unit/test_semantic_profiles.py tests/unit/test_semantic_global.py \
      tests/unit/test_stage_handlers.py tests/integration/test_persistent_mock_pipeline.py
    make lint
    make test
    git diff --check

Mock tests must make no paid request. A real host run, if possible, must allocate new Project/Run IDs,
record exact Provider evidence, and never overwrite old data. The default `liveclip auto VIDEO` must
still resolve to `short_highlight`; the explicit mini-lesson command is recorded after CLI integration.

## Validation and acceptance

Acceptance requires exact inclusive duration endpoints (45/90 for short; 90/300 for mini), strict
score `>75`, one continuous cue interval, `content_decision=keep`, no blocking quality facts, structured
risk publication status, auto-only render scheduling, separate Top-N accounting, no forced count,
complete discovery-to-final audit, iterative links across more than one boundary, and Agent-authorized
natural splits only above 300 seconds. The three strong early real-SRT anchors must be reached by
Discovery/Topic Chain regression; risky later anchors must remain visible for manual/blocked audit.

## Idempotency, retry, and recovery

Every new cache identity binds source/input hash, profile, unit/boundary/chain/candidate ID, Provider,
model settings, Prompt hash, response Schema hash, and schema version. A local structure/domain failure
gets only the corresponding bounded repair. Successful sibling batches/links/candidates are written
before a peer failure propagates. Pipeline retry reuses exact validated upstream checkpoints; file
existence alone is never success.

## Surprises and Discoveries

- 2026-09-10: The current `--profile` option means content-domain guidance (`general` or
  `vocal_coach_live`), so clip length/unit selection needs a distinct `--clip-profile` contract.
- 2026-09-10: Candidate rows have no profile column. An immutable run-level clip profile plus prefixed
  candidate IDs can preserve database compatibility for separate short/mini runs; any combined-profile
  run would need a separate persistence decision rather than overloading existing fields.
- 2026-09-11: The real cold mini run completed all 78 OpenRouter Whisper calls and persisted an
  835-segment transcript, then all 28 concurrently scheduled Discovery batch processes were denied
  before model execution because a managed Codex app-server cannot nest Codex CLI. This is an
  execution-environment restriction, not a semantic or Schema failure; Pipeline retry can reuse the
  verified upstream stages from an ordinary Terminal.
- 2026-09-11: The real-SRT acceptance fixture and the newly generated OpenRouter transcript are not
  byte-identical and have different cue granularity. Fixture acceptance is therefore reported as
  deterministic regression evidence, never as the live model's editorial result.

## Decision Log

- 2026-09-10: Version V4 additively and leave V1--V3 loaders untouched. Rationale: historical cache and
  PipelineRun fingerprints are immutable evidence.
- 2026-09-10: Treat 180 seconds as one link-decision evidence transport, never as the maximum chain
  span. Rationale: a 270-second lesson is recovered by multiple Agent-approved links.
- 2026-09-10: Keep clip profile distinct from the existing semantic content profile. Rationale: length
  and content-unit invariants are orthogonal to domain-specific editorial guidance.

## Risks and Mitigations

- Large change over a dirty V3 tree: use new versioned modules/resources, inspect diffs, and run old
  compatibility tests before broad integration.
- Model drift: strict per-stage Schemas, Agent evidence, local recomputation, cache identities, and Mock
  CI; no output-count expectation is encoded.
- Long-topic overmerge: only explicit Agent `same_topic` plus `same_central_objective` links join a
  chain; Python uses no text/time similarity.
- Hidden publication risk: only `publish_status=auto` reaches automatic revisions/rendering; all other
  results stay in final audit arrays.

## Recovery Notes

Retry PipelineRun `30eba26459e34b8187fa15900670c78a` from an ordinary Terminal. That reuses the
successful source, 78 audio chunks, 78 ASR results, and transcript while running only the failed and
later stages. Inspect all live semantic artifacts and videos before accepting their content quality.

## Outcomes and Retrospective

The code milestone is complete. It adds two independent Profiles, V4 semantic contracts, iterative
Agent-approved Topic Chains, candidate Boundary Review, per-Profile Global Review/Top-N, deterministic
validation/audit, local caches/repair, and auto-only continuous rendering. `make lint` passed; `make
test` passed 1006 Python tests, 58 frontend tests, Mock browser E2E, and isolated real local
API/Worker/SQLite/FFmpeg browser E2E. The mini integration rendered and probed one >=90-second MP4.

The real `8-30.ts` cold mini run is intentionally not claimed complete. Project
`e725b1a24c2d4975b1399674517219f1`, PipelineRun `30eba26459e34b8187fa15900670c78a`
completed real OpenRouter ASR (78/78, zero retries, 835 segments, approximately USD 0.137724) and then
failed at Discovery with `CANDIDATES_CODEX_NESTED_SESSION`. Successful editorial calls and editorial
tokens are zero; no real candidate count or FFmpeg output exists. Exact evidence and explicit
not-executed envelopes are under
`data/evaluations/8-30-mini-lesson-topic-chain-2026-09-11/`.
