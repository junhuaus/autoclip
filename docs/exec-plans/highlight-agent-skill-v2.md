# LiveClip Highlight Agent Skill v2 Living ExecPlan

This plan follows `.agent/PLANS.md`. It governs the user-authorized optimization
of the runtime highlight-discovery Agent after the three-configuration benchmark
at `docs/research/model-benchmark-2026-08-17/`.

## Purpose / Big Picture

An editor should receive a more complete, less repetitive and more auditable
set of livestream highlights. The optimized Agent first evaluates every rough
candidate, then freely discovers Topics, then lets deterministic code select a
diverse portfolio, and only afterward writes titles and high-impact sentences.
Every published quote must be bound to the exact candidate text. The first
milestone is a research/shadow implementation and a blind v1-v2 comparison; it
does not change the production Pipeline, database, current Projects or model
default until evidence passes and the user approves integration.

## Context and Orientation

- Frozen baseline Skill: `docs/research/model-benchmark-2026-08-17/agent-v1/SKILL.md`.
- Baseline evidence/results: `docs/research/model-benchmark-2026-08-17/results/`.
- Architecture proposal: `docs/research/model-benchmark-2026-08-17/SKILL-ARCHITECTURE-PROPOSAL.md`.
- New work root: `docs/research/highlight-agent-skill-v2-2026-08-17/`.
- Production single-candidate editor: `src/liveclip/providers/llm/`,
  `src/liveclip/pipeline/editing.py`, and `src/liveclip/prompts/editing_v2.md`.
- Canonical media time remains integer source milliseconds. Runtime models have
  no authority over media boundaries, paths, commands, filters, SQL or code.

Five input filenames represent only three unique source SHA-256 values. The
aliases `8-16-2.ts`/`8.15-1.ts` and `8-16-1.ts`/`8.15-2.ts` must never receive
double statistical weight. The alternate old ASR/candidate evidence is a
zero-weight diagnostic, not a fourth source.

## Scope and explicit non-goals

In scope for iteration 1:

- Freeze a self-contained runtime Skill v2 with task-tier references.
- Define strict Tier 1 assessment, Tier 2 Topic inventory, Tier 4 copy and final
  result Schemas.
- Implement deterministic evidence normalization, exact quote span validation,
  all-candidate accounting, score calculation, Topic identity and portfolio
  selection.
- Replay all frozen v1 results through the v2 evidence Gate without model calls.
- Run fresh Sol Medium v1 and v2 on the three unique development sources, using
  exactly the same frozen evidence, model, effort and run block. Run two repeats
  per Skill/source (12 final pipelines total) and randomize v1/v2 execution
  order deterministically. Existing v1 outputs remain diagnostics, not the
  primary causal baseline, because model/backend date drift is uncontrolled.
- Generate a Skill Creator static viewer before interpreting qualitative
  outputs, then run anonymous dual-Judge comparison and deterministic analysis.
- Record latency, tokens, repair/degradation/escalation signals and limitations.

Non-goals for iteration 1:

- No production Prompt/provider/Schema/database/API/Web change.
- No source video, ASR, rendering, review decision or Delivery mutation.
- No fixed Topic answer list and no genre-specific Skill branch.
- No claim of absolute Topic recall or generalization from three homogeneous
  singing-instruction sources.
- No Sol High generation in the primary A/B. The runner records only
  `would_escalate` from deterministic triggers; an optional escalation study can
  start only after the primary matrix is complete.

## Architecture summary

```text
frozen candidates
  → Tier 0 deterministic input gate
  → Tier 1 Sol Medium assessment of every candidate in frozen batches
  → Tier 2 Sol Medium free Topic inventory and complete accounting
  → Tier 3 deterministic quality/diversity/overlap portfolio selection
  → Tier 4 Sol Medium editorial copy for selected candidates only
  → Tier 0 exact evidence/copy gate
  → anonymous dual Judge + human review viewer
```

Tier 5 is an independent audit role, not a privileged generator. Iteration 1
uses Sol Max and Terra Max as two anonymous comparative Judges. Each Judge sees
four opaque systems for one source (fresh v1 repeat 1/2 and v2 repeat 1/2), with
the identity commitment frozen before any Judge call. Any later repair or Sol
High escalation must return to the owning Tier, run at most once and pass the
same deterministic Gate.

## Milestones and progress

### S2-M0 — Contract and deterministic Gate

- [x] 2026-08-17 Receive user approval to begin v2 optimization while keeping production unchanged.
- [x] 2026-08-17 Re-read Product Spec, Solution, plan rules, both active ExecPlans, STATUS and Skill Creator instructions.
- [x] 2026-08-17 Verify clean synchronized `main`, Alembic head/drift and healthy configured API/provider chain.
- [x] 2026-08-17 Freeze Skill v2, Tier Schemas, risk/exclusion enums, normalization and scoring contracts.
- [x] 2026-08-17 Implement deterministic validators, portfolio selection and adversarial unit tests.
- [x] 2026-08-17 Replay the 30 frozen v1 results through the exact-quote/context Gate and save the audit.
- [x] 2026-08-17 Complete independent read-only architecture, Schema/security and eval-design audits.

### S2-M1 — Three-source v1-v2 development comparison

- [x] 2026-08-17 Freeze eval prompts for the three unique sources and bind all input/Skill/Schema/runner hashes.
- [x] 2026-08-18 Run and independently receipt-validate one fresh same-source
  v1/v2 Sol Medium sentinel pair (2/12 pipelines).
- [x] 2026-08-18 Populate the remaining ten fresh v1/v2 Sol Medium pipelines,
  preserving two repeats per source; receipt-only resume performed zero calls.
- [x] 2026-08-18 Run all v2 Tier calls with isolated, ephemeral, tool-disabled
  Sol Medium workers and resumable immutable artifacts.
- [x] 2026-08-18 Generate the static Skill Creator viewer before qualitative
  interpretation.
- [ ] Run two anonymous independent Judges per source and validate complete cluster membership.
- [ ] Aggregate source-first quality, evidence, duplication, coverage, latency and token metrics.
- [ ] Run independent read-only verification and fix any P0/P1 research-contract defect.

### S2-M2 — Decision and optional production design

- [ ] Present the viewer/report and record the evidence-based decision.
- [ ] If v2 passes preregistered development gates, freeze it and define a six-source/multi-genre holdout; otherwise revise into iteration 2.
- [ ] If v2 passes the gates, design and implement the production migration;
  otherwise keep production unchanged and document the failed gate.

## File ownership

The main Agent exclusively owns this ExecPlan, `STATUS.md`, shared schemas,
dependencies, migrations and any eventual production integration. Parallel
agents are read-only for S2-M0: one audits production integration, one audits
Schema/Gates and one audits the evaluation design. No agent may edit frozen v1
artifacts or the previous benchmark.

## Concrete commands and expected observations

From the repository root:

```bash
git status --short --branch
.venv/bin/pytest -q docs/research/highlight-agent-skill-v2-2026-08-17/test_contracts.py
.venv/bin/python docs/research/highlight-agent-skill-v2-2026-08-17/run_iteration.py --dry-run
.venv/bin/python docs/research/highlight-agent-skill-v2-2026-08-17/run_iteration.py
.venv/bin/python docs/research/highlight-agent-skill-v2-2026-08-17/analyze_iteration.py
make lint
```

Dry-run must freeze only research inputs and hashes. A resumed run must validate
the complete immutable contract before accepting an existing result. A changed
contract requires a new experiment directory; no `--force` overwrite is an
accepted recovery method.

## Validation and acceptance criteria

- Strict Schema, candidate ID and all-candidate accounting pass for every Tier.
- Every v2 `evidence_quote` is a normalized exact substring of its bound current
  candidate text, with recorded raw and normalized spans; outward hard failures
  are zero.
- Model-returned totals, Topic IDs, time bounds and executable fields are absent;
  deterministic code owns them.
- All assessable candidates appear in exactly one primary Topic; every unusable
  candidate appears exactly once in the derived excluded ledger.
- The final portfolio contains no duplicate candidate, respects configured
  quality/count/overlap constraints and gives every candidate a selection reason.
- v2 primary quality is no worse than v1 by more than 2/100. Two repeats measure
  sampling stability only; because candidate order is fixed, no order-robustness
  claim is allowed.
- All structural, ID, time, quote and accounting gates pass 100%; outward v2
  exact-quote failures are zero.
- v2 must not exceed 3x v1 aggregate elapsed time or token use without a
  separately documented quality justification.
- With no independent human Topic gold inventory, coverage is explicitly
  relative selected-union coverage, never absolute recall.
- Judge inputs hide system identity/model/effort/self-score/timing/token data.
- Runtime calls emit no tool event and use only an environment allowlist.
- The viewer contains both old-skill and with-skill outputs for all three evals.
- No product database/media/provider result is modified.

## Idempotency, retry, recovery and cancellation

Each call directory binds canonical input, rendered Tier instructions, frozen
Schema, runner bytes, model/effort and result/event hashes. Resume accepts a
call only when all bindings and validation still match. A structural failure may
receive one saved same-Tier repair; unknown IDs, input/hash mismatch or quote
misbinding fail without model repair. Interrupted calls leave no success marker
and may be retried. Completed iteration artifacts are immutable; improvements
write `iteration-2` rather than replacing iteration 1.

## Surprises and Discoveries

- 2026-08-17: Production editing is a per-candidate `EditPlan` loop, while the
  proposed v2 is a batch Topic/portfolio workflow. Direct substitution would
  reset real selections/revisions and cannot be called a shadow test.
- 2026-08-17: Production cache identity omits Tier, effort, Schema, evidence-set
  and upstream-result hashes. v2 must use a separate cache/manifest.
- 2026-08-17: Reusing the previous Sol Medium result as the only baseline would
  confound Skill effects with backend/date drift. A fresh paired v1/v2 block is
  required.
- 2026-08-17: Tier 1 must distinguish `unusable` evidence from merely low-value
  content. The latter stays assessable and is handled by deterministic scoring.
- 2026-08-17: The zero-model replay verified all 343 prior benchmark artifacts.
  Of 263 primary v1 `highlight_sentence` values, only 30 (11.41%) are an exact
  normalized substring of the bound candidate, two occur only in supplied
  context, one belongs to another candidate and 230 are unsupported as a quote.
  This is evidence-binding debt, not a retrospective judgment that the edited
  sentences are semantically bad.
- 2026-08-17: The current formal fresh A/B contract is
  `exp_31890c08e4b7eda69858` with SHA-256
  `31890c08e4b7eda698584a3502e440c7816b601dd74a1a3822db611284c4e797`.
  It contains three unique source hashes, two repeats, 12 paired pipelines and
  a balanced fixed seeded v1/v2 execution order. Dry-run made zero model calls.
- 2026-08-17: Independent review found and closed three P1 harness defects:
  empty portfolios now skip Tier 4 without a model call, Pipeline completion is
  bound to every Call receipt, and the deterministic output Gate rejects the
  expanded command/path/SQL/credential adversarial set. The reviewer returned
  PASS with no remaining P0/P1 after 88 tests.
- 2026-08-17: The first real sentinel attempt under contract
  `exp_0ae4e48cf661fa862d58` reached no model thread or turn. The outer sandbox
  denied local Codex app-server initialization, and the old runner incorrectly
  consumed its two same-Tier attempts. Its failure receipts are preserved and
  the experiment is explicitly aborted. The superseding runner performs a
  zero-model app-server preflight, separates bounded infrastructure failures
  from model repairs, binds all such receipts, and hard-fails any tool event
  without retry. Viewer and dual-Judge harnesses validate the same receipt chain.
- 2026-08-17: The integrated research suite now has 113 passing tests. The
  anonymous source-first viewer refuses partial 12-pipeline matrices, and the
  dual-Judge harness refuses partial generator evidence before any Judge call.
- 2026-08-17: The first zero-model preflight probe used `app-server --listen
  off`, which Codex 0.146 correctly rejected because it configured no
  transport. Contract `exp_1a2d7214d1a671d96c2c` is preserved and aborted.
  Preflight v2 uses stdio plus immediate EOF; the outer environment returned
  exit 0 with `model_started=false` and `model_attempt_consumed=false` under
  the current formal contract. The integrated suite now contains 114 tests.
- 2026-08-18: The real sentinel completed 2/12 pipelines with six model calls,
  no repair, no failure receipt, no unsafe tool event and no Sol High call. v2
  assessed all 45 candidates, discovered 14 Topics, selected 12 and passed 12/12
  exact evidence-quote Gates. Fresh v1 selected ten; all ten legacy
  `highlight_sentence` fields failed the quote-binding shadow audit. A second
  `--sentinel` invocation resumed both Pipeline receipts with zero new calls.
  The Viewer and Judge harnesses both refused the intentionally partial matrix.
- 2026-08-18: The full generator matrix completed 12/12 Pipelines and 36
  successful Call receipts. Six v2 Pipelines each selected 12 highlights and
  ended with zero outward exact-quote failures. Two first attempts required the
  single permitted same-Tier repair: one Tier 4 exact-quote mismatch and one
  Tier 2 duplicate primary-Topic membership; both repaired attempts passed.
  No unsafe tool event and no Sol High call occurred. Fresh v1 selected 8–11
  highlights per run and its legacy quote-binding shadow Gate failed 7–11 per
  run. A full-matrix resume accepted all immutable receipts and made zero new
  model calls.
- 2026-08-18: The anonymous static Viewer was generated at
  `eval-review/iteration-1` before semantic result inspection. The dual-Judge
  dry-run then froze six source/Judge inputs (three sources × two Judges), each
  with four opaque generator outputs. Blind inputs and Schemas contain no arm,
  Pipeline, Skill/model/effort, latency, token or self-score identity fields.
- 2026-08-18: The first real dual-Judge sentinel stopped before any Judge model
  result. Both permitted attempts for `judge_01/src_199c8497104d75ba` failed at
  Codex CLI argument validation with `Unknown feature flag: skills`; only a
  call contract, prompt hashes and two failure receipts were written. This is a
  Judge harness P1: unlike the generator runner, it lacked a zero-model
  compatibility preflight and incorrectly consumed repair slots for a
  pre-model infrastructure/configuration failure. The failed run
  `judge_da09efc4a848e5c8fc005b50` remains immutable. A superseding runner must
  use only current supported isolation flags, classify pre-model failures
  separately and create a new Judge-run identity before any retry.
- 2026-08-18: Judge runner v2 closes the failed-sentinel defect. It reuses the
  generator's current supported feature-disable profile, runs a stdio/EOF
  zero-model preflight, gives pre-model failures their own bounded immutable
  receipts and budget, hash-binds their complete inventory, and reserves the
  two attempts solely for model-started output/validation work. Unsafe tool
  events persist once and hard-fail forever; output-read failures after a turn
  are also receipted. Progress validates each completion before counting it.
  Focused tests pass 23/23, existing research regressions pass 129/129 and an
  independent final review reports P0/P1/P2 all zero. Runner hash changes force
  a new Judge-run ID; the failed `judge_da09...` tree remains byte-for-byte
  untouched.
- 2026-08-18: The deterministic analyzer/report contract was frozen while the
  new Judge run had only 1/6 completed calls and before interpreting comparative
  results. It verifies all generator/Judge/Pipeline/Call/preflight hashes and
  inventories before reading private arm identities, aggregates source-first,
  and labels selected-union coverage as relative. v2 exact quotes are recomputed
  from source candidates. Failed repair-attempt cost metadata is not bound by
  the generator completion receipt, so it is reported only as supplemental;
  any such repair makes the hard efficiency gate inconclusive rather than
  silently cheap. The HTML includes each source/Topic, both Judge verdicts and
  disagreements, system strengths/weaknesses and limitations. Analyzer tests
  pass 22/22, the full research suite passes 151/151, and independent review
  reports no P0/P1; its final empty-preflight/version P2 was also closed.
- 2026-08-18: New Judge run `judge_4ab64f09314583b7212ff934` passed its real
  stdio/EOF preflight with `model_started=false` and no consumed model attempt.
  The first-source dual-Judge sentinel then completed 2/2 without repair or
  failure: both Sol Max and Terra Max covered all 44/44 anonymous highlights
  exactly once across four systems, and both event logs contain only one
  `agent_message`. Re-running the sentinel kept one preflight check and two
  completions, proving receipt-only resume with zero new calls.

## Decision Log

- 2026-08-17: Implement and evaluate a research/shadow v2 before production
  integration. Rationale: the prior benchmark identifies architectural defects
  but does not prove a replacement Skill is better.
- 2026-08-17: Use fresh Sol Medium/medium for both v1 and v2, two repeats per
  unique source. Rationale: same-block pairing isolates the Skill/process change;
  prior outputs are not contemporaneous controls.
- 2026-08-17: Use task tiers, not genre branches. Rationale: all three current
  sources are one content family and cannot justify category-specific rules.
- 2026-08-17: Use the minimum defensible 12-pipeline matrix before any expanded
  order study. Rationale: it measures sampling variance within the current
  budget, but makes no order-stability or broad-generalization claim.
- 2026-08-17: Keep Sol High out of the primary comparison and only record frozen
  `would_escalate` signals. Rationale: otherwise model escalation confounds the
  Skill v1/v2 effect.
- 2026-08-18: The user authorized autonomous completion without further
  intermediate approval prompts. Production integration is therefore gated by
  the preregistered evidence and regression tests rather than a separate user
  confirmation; this does not authorize destructive or unrelated changes.

## Risks and mitigations

- Development-set overfitting: keep instructions generic, freeze before output
  review and require a later multi-genre holdout.
- Judge ceiling/same-family bias: retain both Terra Max and Sol Max raw scores,
  report disagreement and avoid treating sub-MAE deltas as proof.
- Hidden common omissions: explicitly state that selected-union Judge coverage
  is relative; require later human reference inventory for absolute recall.
- Excess model calls: batch Tier 1 deterministically, record per-Tier usage and
  stop after the three-source iteration before expanding orders/holdout.
- Prompt injection/data drift: untrusted boundaries, no tools and complete hash
  contract remain mandatory.

## Recovery Notes

Current first task: commit and push the successful 2/6 new Judge-run sentinel
receipts, then resume the same run without `--sentinel` to populate only the
remaining four source/Judge calls. Validate all six completions and full
membership before running the frozen analyzer. If interrupted, read this file and
`STATUS.md`, verify the experiment manifest and current source hashes, and
resume rather than deleting or forcing an artifact. Never rerun the completed
three-model benchmark or overwrite its artifacts.

## Outcomes and Retrospective

Not yet complete. This section will record whether v2 beat, tied or lost to v1,
what caused the outcome, and whether production/holdout work is justified.
