# LiveClip semantic quality gates v3

This Living ExecPlan records the implementation and acceptance evidence for the September 2026
quality-gate repair. It is maintained by the main agent and must remain factual: an item is checked
only after its code or runtime evidence exists.

## Purpose

Repair the `semantic_windowed` production path so Discovery remains high-recall, a separate
candidate boundary review evaluates the actual continuous source interval, Global Review separates
editorial value from publication safety, and Python applies non-compensable structured gates before
Top-N, rendering, and delivery. Preserve algorithm A, algorithm B v1, and installed semantic global
v1/v2 contracts.

## Authoritative inputs

- `docs/PRODUCT_SPEC.md` and `docs/PRODUCT_SPEC_V0.2.md`
- `docs/SOLUTION.md`
- `.agent/PLANS.md`
- `docs/exec-plans/liveclip-v1.md` and `docs/exec-plans/liveclip-v0.2.md`
- the user-supplied regression findings for `input/8-30.ts`
- immutable historical artifacts below `data/projects`; old Runs and Deliveries are read-only

## Scope and non-goals

In scope are versioned Prompt bundles, JSON/Pydantic wire contracts, candidate boundary-review
transport and caching, Global Review validation, deterministic selection/Top-N accounting,
assembler behavior, audit artifacts, tests, one new cold Run, and actual rendered-video inspection.
Python may validate only structured enums, cue existence, one continuous interval, duration, score,
counts, cache identity, and artifact integrity. It must not infer semantic quality from Chinese
keywords, punctuation, temporal overlap, or time gaps. Full-context processing and jump cuts are out
of scope.

## Milestones

- [x] 2026-09-09: Read all required product, solution, planning, and status documents.
- [x] 2026-09-09: Confirm latest 15-clip and earlier 13-clip Runs reuse the same transcript
  fingerprint; isolate the regression after ASR.
- [x] 2026-09-09: Trace production `auto` and confirm pre-Global boundary review is absent, manual
  review clips are assembled with automatic clips, and Top-N caps only the selected subset.
- [x] 2026-09-09: Add immutable `semantic_global_v3` Prompt and Schema contracts while retaining
  v1/v2 loaders.
- [x] 2026-09-09: Add separately cached Boundary Review before Global Review with candidate, local context,
  Discovery boundary facts, real opening/ending, and cue traceability.
- [x] 2026-09-09: Add candidate-level v3 Global Review and deterministic non-compensable gates, publication
  separation, duplicate audit, recomputed counts, and final-output Top-N.
- [x] 2026-09-09: Update the production assembler so only automatically publishable v3 results enter automatic
  delivery; manual/blocked/dropped results remain auditable.
- [x] 2026-09-09: Add focused regressions for all requested failure modes plus duration endpoints, count
  recomputation, risk recall, duplicate audit, A/B compatibility, and mock-only CI.
- [x] 2026-09-09: Run formatting, lint, focused tests, full tests, and `git diff --check`.
- [x] 2026-09-09: Reuse the fingerprint-identical verified transcript for a source-specific V3 gate
  run over the 20-candidate 13/15-result union; rerender its five automatic clips twice, reject the
  first loose-boundary attempt, and pass final checksum/ZIP/decode/stream/black-frame/contact-frame
  inspection on the corrected second attempt.
- [ ] Run a new uncached `input/8-30.ts` pipeline without overwriting earlier evidence; inspect
  generated videos and write the final comparison report.

## Implementation decisions

- Version v3 rather than mutate historical v1/v2 response contracts. New Runs default to v3;
  persisted old Runs continue loading their exact Prompt hash and response model.
- Boundary Review is part of the edit stage but precedes Global Review. Its cache identity includes
  transcript-local evidence, Prompt/Schema hash, provider/model settings, and Discovery output.
- Global Review receives all Discovery candidates, including boundary-dropped and risky candidates,
  so recall and rejection evidence remain visible. Python will not allow Global Review to override a
  boundary blocker without a concrete repaired interval.
- Top-N is applied once to the final ranked publishable set. The audit records pre-gate candidates,
  qualified results, manual/blocked results, dropped results, and results excluded only by Top-N.
- Repeated invalid structured output is deterministic after one local repair and must not trigger a
  paid full semantic rerun; successful Discovery and Boundary Review units remain independently
  cached.

## Acceptance commands

Run from the repository root using project-local dependencies:

    .venv/bin/ruff check src tests
    .venv/bin/pytest tests/unit/test_semantic_global.py tests/unit/test_stage_handlers.py
    .venv/bin/pytest
    git diff --check

The final real-media command must use a new project/run and disabled semantic cache reuse. The exact
command, model, Prompt hashes, call counts, retry reasons, timings, and artifact paths will be
recorded after execution. Passing unit tests is not a substitute for inspecting every rendered
continuous interval named in the user regressions.

## Risks and recovery

The worktree contains pre-existing uncommitted changes; do not discard or overwrite unrelated
edits. Changes are additive and versioned. If a real MLX/Codex call cannot run in the managed tool
environment, preserve completed local validation evidence, record the exact preflight failure, and
do not claim hardware or end-to-end success. Never reuse or modify an old Run or Delivery.

## Outcomes and discoveries

The baseline technical symptoms are 15 Discovery candidates, 15 approved, zero rejected, scores
77--83, three Discovery retries, two Global Review retries, about 13 minutes in Discovery and 39
minutes in Global Review. These counts are regression evidence only and are not production rules.

Implementation and offline validation are complete. `make lint` passes Ruff, format, strict MyPy,
EditPlan Schema drift and Web TypeScript. The final Python run passes 979 tests; the immediately prior
complete `make test` run passed 972 Python tests, 58 Web tests, Mock browser E2E and real
API/leased-Worker/SQLite/FFmpeg browser E2E. The seven later Python tests cover every unresolved v3
quality flag and prevent Global Review from silently replacing a kept Boundary Review interval.

The managed Codex process cannot complete the real-media milestone. Model snapshot inspection passes
with config hash `34982ce6ae286095000f82ae9583b3431639e8b092bf60c961f203745e6500e3`
and 3,083,520,416-byte weight hash
`05ff791ce3630fae47e7c51004e9666204d786246ec07cac6110af768099b40d`, and Codex login is ready, but
MLX raises `[metal::load_device] No Metal device available`. The exact new `auto` attempt consequently
failed preflight with `MLX_ASR_NOT_READY` before it created a Project or Run. No old Run, Delivery or
cache was modified. Actual candidate dispositions, timings and calls/tokens from a fully cold Provider
run remain deliberately unclaimed until the same command is run from an ordinary Metal-capable
Terminal. A distinct source-specific fallback acceptance is complete: the existing verified transcript
and current Codex session fed 20 structured candidate judgments to the production V3 validators,
which derived 5 automatic, 3 manual, 3 blocked and 9 rejected rows. The first five-video render was
rejected after subtitle inspection found two removable openings; the corrected second attempt
rerendered all five from source and passed hashes, ZIP, full decode, black-frame, A/V stream and
15-frame visual inspection. This proves deterministic gates and real media delivery, not new
ASR/Prompt stochastic stability. Evidence is under
`data/evaluations/8-30-quality-gates-v3-local-acceptance-2026-09-09/attempt-002/`.
