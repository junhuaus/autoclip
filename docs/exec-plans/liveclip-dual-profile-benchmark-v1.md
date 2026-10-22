# LiveClip dual-profile benchmark v1 Living ExecPlan

Prepared 2026-09-18. This plan follows `.agent/PLANS.md` and uses
`liveclip_dual_profile_benchmark_v1.json` as the machine acceptance contract.

## Purpose / Big Picture

One semantic clipping run must independently execute `short_highlight` and
`mini_lesson`, preserve same-topic short/long variants, validate and cap each
Profile separately, render every eligible continuous interval, and expose an
auditable manifest whose counts are recomputed from final arrays. A fixed
evaluator measures the checked-in 110-minute transcript without leaking its
gold timestamps into production discovery.

## Context and current root cause

The current v12/v13 configuration has exactly one `clip_profile`. Bootstrap,
CLI/API presets and `StageHandlers._candidates` branch on that scalar; the
short and mini implementations therefore never enter the same PipelineRun.
The short path uses semantic-windowed 120/60 discovery and the mini path uses
the historical Topic-Chain route, so the successful short run could not have
executed a second candidate pool. Render output paths are also chosen from the
run-wide scalar Profile and the ordinary Delivery manifest contains clip rows
only, with no requested/executed Profile audit. This is a configuration and
orchestration defect, not merely a score or Prompt defect.

The attached transcript is the checked-in
`tests/fixtures/8-30-full-transcript.srt`, SHA-256
`29b8751643ecc38a7183ab0c837a011cbca1e70a56de0788cd66292dbf364120`.
Existing dirty SD-6 documentation/QA belongs to the user and must be preserved.

## Scope and non-goals

Implement a current dual-profile contract while retaining exact v8--v13
snapshot replay and Algorithm A/B v1 compatibility. Production code may use
only Agent decisions for semantic discovery, completeness and duplicate
relationships. Python may enforce schema, cue/time truth, duration, risk and
quality gates, independent Top-N, cache identity, retries, counting and
rendering. Benchmark time anchors are evaluator/fixture-only and may never be
imported by production modules.

## Progress

- [x] 2026-09-18 Verify attached benchmark/transcript identity and inspect the current single-Profile branch.
- [x] 2026-09-18 Record the initial root cause and recovery plan.
- [x] 2026-09-18 Add a versioned dual-profile service/CLI config contract with exact inclusive bounds.
- [x] 2026-09-18 Add independent 600-second/300-second-ownership mini Discovery and Profile-specific Prompts/schemas.
- [x] 2026-09-18 Execute independent discovery, boundary review, Global Review, dedup and Top-N pools in one run.
- [x] 2026-09-18 Carry Profile/variant/source lineage and terminal disposition through final artifacts and rendering.
- [x] 2026-09-18 Add cache and manifest provenance, recomputed counts and raw/final traceability.
- [x] 2026-09-18 Add the benchmark evaluator, script exporter and required unit/integration/mock regressions.
- [x] 2026-09-18 Run targeted tests, lint/type checks and the strongest compatible legacy suite (312 passed).
- [x] 2026-09-24 Run a fresh-cache full real-transcript dual-profile benchmark with saved-login Codex.
- [x] 2026-09-24 Render and inspect all 12 benchmark-matched short/long media candidates.
- [x] 2026-09-24 Update this plan and `STATUS.md` with exact results and the remaining unrelated test blocker.
- [x] 2026-10-20 Stage 1: make `scripts/evaluate_benchmark.py` and `scripts/evaluate_agent_benchmark.py` enforce the benchmark JSON/MD as written (source hash, manual-only semantic equivalence, negative-anchor padding, forbidden composites, RGR-02 opening/flags, `CONDITIONAL`, qualified boundary score, computed audit score, risk evidence cues, one-to-one matching, Agent v2 technical statuses). Fixture tests only; no real re-score.
- [x] 2026-10-20 Stage 1 fix round (reviewer CHANGES_REQUIRED on `bf83c80`): Controller decisions D1--D3, union padding allowance, Agent v2 mechanical/not-applicable/human-required split with derived executed Profiles, manual-only-risk selection gate, RGR-03 findings, augmenting-path and score-boundary tests, safe no-replace publication. Fixture tests only; no real re-score.
- [x] 2026-10-20 Stage 1 fix round 2 (reviewer ACCEPTED `d9e9dde`; Controller follow-ups): Agent reports published as one atomic no-replace directory via `publish_directory_no_replace_no_follow`, executed-Profile filter regression test, no semantic padding allowance with `outside_nearest_anchor_ms` diagnostics, restored historical Agent ExecPlan entry. Fixture tests only; no real re-score.
- [x] 2026-10-20 Stage 1 ACCEPTED at `6c465b767e3829152d0b07451edbe274980321b1` (reviewer ACCEPT; independent tester `make lint` and `make test` green, mock/fixture only; evidence in `STATUS.md`).
- [x] 2026-10-21 Stage 4 (branch `claude/liveclip-stage4-evaluator-rules`; ACCEPTED at `8b14aa3`, verified at tip `ca80fb7` on 2026-10-22; evidence in `STATUS.md`): apply operator decisions A (exact boundary = tolerance only) and B (`negative_anchor_output` with a per-anchor MD section 7 policy) in both evaluators; read-only cold-18 re-score FAIL 90.0. See the Decisions entries dated 2026-10-21 (Stage 4).
- [x] 2026-10-22 Stages 6 and 7 ACCEPTED at the integrated tip `996962b` (branch `claude/liveclip-stage7-claude-cli`; evidence in `STATUS.md`). The dual-profile understanding engine is now the local Claude Code CLI (subscription login only; Codex remains selectable).
- [x] (Historical next step.) Real Claude benchmark cold-21 via the `STATUS.md` runbook (new roots, frozen 2.1.308 binary, `--discovery-concurrency 3`, strict evaluator). 2026-10-22: cold-21 stopped on the subscription usage limit after 1576 s (115 calls cached); not a quality result.
- [x] 2026-10-22 Stage 8 ACCEPTED at `4f2c068` (branch `claude/liveclip-stage8-routing`; F1 quality-gate routing, F2 risk-pass rejected → blocked, F3–F5 review-stage fixes and `nested_pair_decisions`; evidence in `STATUS.md`). Real diagnostic runs: warm-22 strict FAIL 90.0, its F1+F2 offline replay FAIL 95.0, warm-23 stopped on the usage limit, warm-24 (Stage 8 code) strict FAIL 92.5 with no PASS blockers.
- [ ] Next: Stage 9, then warm-25 (diagnostic), then a fresh cold acceptance run (`cache_hits=0`, about 230 calls) right after a subscription usage-limit reset.
- [x] Follow-up (reviewer P2-b): pin the Agent report staging directory identity (`expected_identity`) and make cleanup fd-based. (2026-10-21: addressed by Stage 6 on `claude/liveclip-stage6-followups`, pending acceptance. 2026-10-22: Stage 6 ACCEPTED at the integrated tip `996962b`.)
- [x] Follow-up (reviewer P2-c): add an end-to-end rollback test after a real no-replace rename. (2026-10-21: addressed by Stage 6, pending acceptance. 2026-10-22: Stage 6 ACCEPTED at the integrated tip `996962b`.)
- [ ] Follow-up (earlier P2-5): Agent risk discovery counts only final candidates, which is stricter than necessary; consider raw/superseded candidates as discovery evidence. (2026-10-21: examined by Stage 6 and not changed. MD sections 3.8, 6 and 10 FAIL a risk candidate that disappears, and Agent v2 has no `manual_review`/`blocked` routing, so a Global-Review-dropped raw candidate is that disappearance; counting it needs an operator decision. Documented in `scripts/evaluate_agent_benchmark.py`.)
- [ ] Follow-up: the e2e harness is not idempotent. A second `make test` in the same worktree fails unless `apps/web/playwright-report/{completion,b2}-packages` are empty of prior packages (predates Stage 1).

## Work breakdown

1. Freeze existing v8--v13 behavior and add a new immutable config generation
   for `requested_profiles`, per-Profile duration/Top-N controls and prompt
   hashes. Keep the legacy scalar as a replay/compatibility projection only.
2. Add Profile-bearing candidate/final audit models. Every raw candidate must
   terminate in selected, manual, blocked, rejected, same-Profile duplicate or
   Profile-local Top-N exclusion.
3. Preserve short scanning. Add direct mini scanning over 600-second contexts,
   300-second half-open ownership and a deterministic tail window. The Agent
   sees full cues and directly proposes continuous >90--300-second teaching
   units; it does not receive benchmark anchors or short results.
4. Run boundary and Global Review per Profile with appropriate context and
   forbid cross-Profile dedup. Materialize only auto-eligible rows but retain
   manual/blocked/rejected evidence.
5. Namespace cache identity and output paths by Profile. Emit discovery-short,
   discovery-long, boundary, review, final and run-manifest audit artifacts.
6. Implement `scripts/evaluate_benchmark.py` as evaluation-only matching and
   hard-gate reporting.
7. Prove exact boundary behavior, long-window coverage, variant coexistence,
   quality/risk gates, count conservation, cache separation, FFmpeg duration
   support and legacy compatibility with mock providers.
8. Use a new isolated cache/output root for the real transcript run; retain
   Provider telemetry and never claim real PASS without actual calls/artifacts.

The implementation uses a separate `DualProfileRunConfig` and
`run_dual_profile_evaluation` application-service API, exposed by
`liveclip dual-profile-eval`, instead of mutating immutable v8--v13 replay
snapshots or the legacy database candidate schema. The paired render API is
`render_dual_profile_candidates`, exposed by `liveclip dual-profile-render`.
An explicit cross-Profile Variant Link stage changes only group labels and is
unable to score, retime, reject or deduplicate candidates.

## Validation and acceptance

Targeted unit/integration tests must cover all seventeen cases in the user
contract. `make lint` must pass. The benchmark evaluator must exit nonzero on
any hard gate and only report PASS at score >=85 with short >=7/8, long >=5/6,
L01/L02/L03 present, R01/R02 routed, zero automatic hard-quality failures and
fully reconciled raw/final arrays. Required rendered outputs are L01--L03 plus
S06/S07; ffprobe, full decode, SRT bounds, hashes and visual inspection are
recorded separately from semantic scoring. Human audio listening is reported
truthfully.

## Idempotency and recovery

All new semantic cache keys bind source hash, Profile, window range, Prompt
hash, model/settings and schema/algorithm version. Cold benchmark mode points
at a fresh cache root. A failed Provider unit preserves its call evidence and
uses only the existing bounded repair/retry contract. Historical PipelineRun
snapshots remain loadable. Rerunning the evaluator is read-only except for its
two deterministic report files.

## Decisions

- 2026-09-18: treat the scalar run-wide `clip_profile` as the primary root
  cause. Prompt-only changes cannot cause both branches to execute.
- 2026-09-18: replace mini discovery for the new dual contract with direct
  600/300 windows. Retain Topic-Chain v13 for immutable single-mini replay.
- 2026-09-18: keep benchmark matching outside production code and require
  explicit artifact schema validation before scoring.
- 2026-09-18: use a Discovery Coverage Audit to recover omitted contained
  lessons and risk chains. It remains a direct full-context discovery pass,
  not a short-result merger.
- 2026-09-18: use an Agent-only Variant Link pass after both Profile-local
  reviews. Python validates exact candidate coverage and never infers semantic
  relationships from overlap, time containment, keywords or punctuation.
- 2026-09-18: machine evaluation implements the benchmark's explicit
  cue/time semantic-equivalence allowance with a conservative 90% cue and time
  coverage rule; production selection does not use this matcher.
- 2026-09-24: an explicit local “step one is X” restart is a valid initiating
  premise for a multi-step unit even when earlier context contains a broader
  definition. This does not make a recap-only comparison complete; S07 still
  requires the first local weak-mix/breathy-mix premise and definition.
- 2026-09-24: `dual-profile-render` must resolve the configured data directory
  to an absolute forbidden root before source validation, matching the main
  pipeline security boundary.
- 2026-10-20 (supersedes the 2026-09-18 semantic-equivalence decision above,
  which is retained as history): the benchmark allows semantic equivalence only
  by manual adjudication (JSON
  `matching.semantic_equivalence_manual_adjudication_allowed`, MD section 9
  rule 4). The evaluators therefore count only exact-boundary hits (both edges
  within the Profile tolerance with full gold cue coverage, a matched decision
  and a legal duration), one-to-one per Profile. A candidate meeting only the
  former 90% cue/time rule is reported in `manual_adjudication_required` and is
  never counted; no input converts it into a hit. All other new gates
  (negative-anchor padding with the matched-anchor allowance, forbidden
  composite intervals for `mini_lesson`, RGR-02 opening/flag checks,
  `CONDITIONAL`, the qualified boundary fraction, the five computed audit
  items and risk evidence cues) are derived from benchmark JSON fields in the
  shared evaluation-only module `scripts/benchmark_gates.py`. The Agent v2
  evaluator emits only `TECHNICAL_PASS_HUMAN_PENDING`, `TECHNICAL_FAIL` or
  `INVALID_EVIDENCE`, and any gate its result model cannot evaluate is listed
  as `not_evaluable` and blocks the technical pass. (The padding allowance and
  the Agent v2 classification in this entry are refined by the fix-round
  entries below.)
- 2026-10-20 Controller interpretation D1 (pending operator confirmation): no
  threshold is changed or normalized. The Agent v2 score stays on the raw
  100-point scale with `pass_min_score` 85; components that do not apply to
  score-only Agent v2 (risk routing, 10 points; cache/repair audit item, 2
  points) score 0. With executed Profiles derived from the frozen Global
  Review, the applicable maximum is 88, so 85 stays reachable. Reports carry
  `raw_score` and `applicable_max_score`.
  **Confirmed by the operator on 2026-10-21.**
- 2026-10-20 Controller interpretation D2 (pending operator confirmation):
  negative-anchor padding and forbidden composite intervals are direct FAIL
  for every output decision in `matching.match_decisions` (`selected` and
  `manual_review`), per MD sections 3.7, 7 and the section 10 direct-FAIL list
  and JSON `direct_fail_conditions`. This is the strict, unconditional
  reading; Agent v2 applies the same rule to every final candidate.
  **Confirmed by the operator on 2026-10-21.**
- 2026-10-20 Controller interpretation D3 (pending operator confirmation):
  `acceptance.conditional` is applied literally. CONDITIONAL requires
  `min_score 70 <= score <= max_score 84`, so `84 < score < 85` is FAIL, and a
  score of at least 85 with any unmet PASS gate (for example 6/8 shorts) is
  also FAIL. This is the strict reading.
  **Confirmed by the operator on 2026-10-21.**
- 2026-10-20 fix round: the padding allowance is the union of the intervals,
  widened by the candidate's Profile tolerance, of every gold or
  `supplemental_mini_lesson` anchor the candidate matches at the exact
  boundary, independent of the one-to-one assignment and of the decision.
  One-to-one matching prefers qualified candidates (no forbidden flags, no
  padding) when duplicates compete; this steers but does not globally
  optimize the qualified set. Agent v2 reports split into
  `mechanical_failures` (the only blockers besides `INVALID_EVIDENCE`),
  `not_applicable` legacy-v1 concepts and `human_required` checks; executed
  Profiles come from the Global Review `requested_profiles` together with the
  tool-enforced per-Profile final-candidate invariant. The v1 evaluator also
  fails `selected` candidates carrying a manual/blocking-only risk tag
  (derived from anchor routing/allowed decisions), lists
  `title_hook_summary_must_be_source_faithful` under `human_required`, and
  reports RGR-03 bad-opening candidates as non-blocking findings because the
  JSON does not mark RGR-03 forbidden.
- 2026-10-20 Controller interpretation (pending operator confirmation): D2
  applies to semantic-only candidates; there is no semantic allowance. Padding
  findings also report `outside_nearest_anchor_ms`, the overlap outside the
  nearest unwidened gold anchor, for human inspection only.
  **Confirmed by the operator on 2026-10-21** (semantic-only candidates get
  no padding allowance).
- 2026-10-21 operator confirmation: the operator confirmed D1, D2 and D3 as
  written above; they are no longer pending. The separate reading "D2 applies
  to semantic-only candidates; semantic-only candidates get no padding
  allowance" was not part of that confirmation and remains a Controller
  interpretation **pending operator confirmation**. No evaluator code,
  threshold or benchmark JSON/MD changed with this confirmation.
- 2026-10-21 (later) operator confirmation: the operator also confirmed the
  semantic-only reading: D2 applies to semantic-only candidates, and they get
  no padding allowance. All Controller interpretations in this log are now
  operator-confirmed. No evaluator code, threshold or benchmark JSON/MD
  changed.
- 2026-10-21 (Stage 4) operator decision A, confirmed by the operator: an
  exact boundary hit is tolerance-only. Both edges within the Profile
  tolerance, inward or outward, inclusive (3000 ms short, 5000 ms long). MD
  basis: section 4 line 41, section 5 line 58 ("约3/5秒" either way) and
  section 9 rules 3--4.
  - This supersedes the earlier Controller interpretation in the 2026-10-20
    entry above, which also required full gold cue coverage. That entry is
    kept as history.
  - Beyond the tolerance, semantic equivalence still goes only to manual
    adjudication.
  - Padding allowance, matching, the boundary score and the Agent v2
    evaluator share the gate. RGR-02 and risk discovery keep their own rules.
- 2026-10-21 (Stage 4) operator decision B, confirmed by the operator: a
  negative-only output is a new direct-FAIL class, `negative_anchor_output`,
  distinct from `irrelevant_padding`.
  - Negative-only means: a `selected`, `manual_review` or Agent `final`
    candidate whose part not covered by the union of negative intervals is
    within its Profile tolerance, with no gold/supplemental time overlap and
    no exact or semantic match.
  - A candidate mixing gold, un-anchored or risk-anchor content with negative
    overlap beyond the allowance stays `irrelevant_padding`. Example:
    `ml_0005`, with 13,340 ms of N05.
  - Per-anchor policy from MD section 7, held in the evaluator table
    `NEGATIVE_ANCHOR_POLICIES` (each entry cites its MD row):
    - N01--N07, N10 and N11 hard-fail for both `selected` and
      `manual_review`. This default was confirmed by the operator on
      2026-10-21.
    - N08 ("不得自动作为教学片") hard-fails only automatic outputs: `selected`
      and Agent `final`. A `manual_review` output is an informational finding
      listed in `human_required`.
    - N09 ("只允许抽取 S08 的干净子区间") hard-fails every decision except the
      S08 clean sub-interval, which is the exact-match allowance.
  - The table is validated against `benchmark_id` and each anchor's `reason`
    and MD interval, and checks that S08 lies inside N09. Any mismatch, or an
    anchor with no entry, gets the strictest policy and is reported.
  - `negative_anchor_output` is added to the evaluators' direct-FAIL set; the
    benchmark JSON is unchanged.
  - Negative-only findings carry no nearest-gold diagnostic.
- 2026-10-21 (Stage 4) review history:
  - `30dc26b`: CHANGES_REQUIRED. P1: "entirely negative" was not checked, so
    un-anchored or risk content mixed with N08 escaped padding. P2: the Agent
    mismatch test could not fail; policy entries were not bound to their
    intervals.
  - `2abec1b`: ACCEPT.
  - `052cd46`: comment-only, recording the operator's confirmation of the
    default policy.
  - The branch was rebased onto the Stage 3 docs tip `427e80c`. The rebased
    commits are `2c4de9a`, `0440c17` and `8b14aa3`, with identical code
    diffs.

## Risks and mitigations

The persistent DB currently has no Profile column on candidates. A migration
or exact Profile-bearing persisted metadata is required before one run can
render both types safely; candidate-ID prefixes are not an acceptable source
of truth. Real 110-minute editorial execution may be expensive, so calls must
be bounded, observable and resumable, but the acceptance thresholds may not be
reduced. Existing user changes in STATUS/QA and ignored SD-6 artifacts must not
be overwritten.

## Recovery Notes

2026-10-20 Stage 1 evaluator strictness: the evaluators now enforce the
benchmark as written (see the 2026-10-20 decision). The retained cold-18
result below was scored by the earlier, looser evaluator, which counted
automatic semantic-equivalence hits and did not check negative anchors,
forbidden composites, the extended RGR-02 opening, RGR-02 required flags, the
source hash, risk evidence cues or computed audit items. It has **not** been
re-scored under the strict evaluator: its evidence lives outside this
worktree and re-scoring requires explicit operator authority. The cold-18
PASS 90.36 must therefore not be cited as a strict-evaluator PASS. Stage 1
evidence is fixture/unit-test only; no real model inference, rendering or
human review was performed.

Stage 1 was ACCEPTED at `6c465b767e3829152d0b07451edbe274980321b1`. D1--D3
and "D2 applies to semantic-only candidates" remain Controller
interpretations pending operator confirmation. The Agent evaluator's
`--output-dir` must be an absolute path with no symlink in its directory
chain (use `/private/tmp/...`, not macOS `/tmp`). The four open follow-ups
are listed in Progress. Before rerunning `make test` in the same worktree,
make sure `apps/web/playwright-report/{completion,b2}-packages` hold no prior
retained package. Move such a folder aside; never delete evidence.

2026-10-21: the operator confirmed D1--D3 (see the Decision Log); the
semantic-only padding reading is still pending operator confirmation. The
"move the report folders aside" step above is historical: Stage 2 on
`claude/liveclip-stage2-e2e-harness` (pending acceptance) retains each
real-browser package in a fresh identity-bound per-invocation scope, so prior
packages no longer need to be moved. See `STATUS.md`.

2026-10-21 (later): Stage 2 was accepted at `cfcff0d`, and the operator
confirmed the semantic-only no-padding-allowance reading. No interpretation
in the Decision Log remains pending.

2026-10-21 (Stage 4, pending acceptance): decisions A and B are applied. The
cold-18 evidence was re-scored read-only:

Cold-18 history (`data/evaluations/dual-profile-benchmark-20260924-final-cold-18`,
ignored local evidence, read-only):

  - Baseline evaluator at `7d2689c`: PASS 90.36, reproduced byte-identical.
  - Strict Stage 1 evaluator at `e51e353`: FAIL 80.0. The reviewer showed that
    80.0 depended on the then-unconfirmed full-cue-coverage rule.
  - Stage 4 evaluator: **FAIL 90.0**.
    - Short 6/8: S01 at +3420 ms exceeds the 3000 ms tolerance and goes to
      manual adjudication; S03 is missed.
    - Mini 5/6: L07 is missed because its only exact candidate was blocked.
      The missed required mini-lesson is L07, not L06 (L06 is supplemental).
    - Hard failures:
      - `irrelevant_padding`: `ml_0005_mixed_voice_types_637_746`, with
        13,340 ms of N05;
      - `negative_anchor_output`: the two N09 candidates
        `precision_mini_lesson_0017_c03` and
        `sh_0022_high_note_channel_01`.
    - Eight N08 `manual_review` negative-only candidates are informational
      findings listed in `human_required`.
    - PASS blocker: `short_recall_below_threshold`.

Branch-tip rule (Stage 4 ACCEPTED at `8b14aa3`, 2026-10-22): the branch
`claude/liveclip-stage4-evaluator-rules` is the accepted code `8b14aa3` plus
docs-only commits up to its tip `0bb4af4`; `git diff --name-only
8b14aa3..0bb4af4` must list only `STATUS.md`, `docs/**` and `tasks/**`.
(Corrected 2026-10-22 from `8b14aa3..HEAD`, which holds only on the Stage 4
branch; later stages add code on top of it.)

2026-10-22: Stage 6 (engineering follow-ups) and Stage 7 (Claude CLI
structured provider) are ACCEPTED at the integrated tip `996962b` on
`claude/liveclip-stage7-claude-cli` (tester PASS, reviewer ACCEPT; evidence
in `STATUS.md`). The understanding engine for dual-profile runs is now the
local Claude Code CLI through the claude.ai subscription login only (Codex
remains selectable). Next: the real Claude benchmark cold-21 via the
`STATUS.md` runbook — new evaluation and cache roots, the frozen 2.1.308
binary under `.cache/claude-cli/2.1.308/claude`, doctor and one
`smoke-claude` first, `dual-profile-eval --discovery-concurrency 3`, then the
strict (Stage 4) evaluator — compared with cold-18 (strict FAIL 90.0).

2026-10-22 (Stage 8 ACCEPTED at `4f2c068`): the final assembly now
downgrades `manual_review` rows with a gated merged quality flag to
`blocked` and retains rejected risk-discovery-pass records as `blocked`
(user-approved exception); the Global Audit must decide Python-listed
nested pairs (`nested_pair_decisions`). Real runs with the frozen Claude
CLI 2.1.308 (subscription login), strict evaluator:

  - cold-21: stopped on the subscription usage limit after 1576 s, 115
    calls cached; not a quality result.
  - warm-22 (diagnostic, `cache_hits` 115, 120 new calls): FAIL 90.0; short
    6/8, mini 6/6; R01 misrouted; padding x2; forbidden composite.
  - warm-22 F1+F2 offline replay: FAIL 95.0 (R01 matched by a blocked
    risk-pass record; remaining hard failure `irrelevant_padding`).
  - warm-23: stopped on the usage limit (73 of 75 new calls cached).
  - warm-24 (diagnostic, Stage 8 code, `cache_hits` 233, 2 new calls plus 1
    repair, 653 s): FAIL 92.5, no PASS blockers; short 7/8 (S03 blocked),
    mini 5/6 (L07 lost); R01/R02 routed; hard failures
    `negative_anchor_output` (`sh22_find_voice_from_phonation` in N09) and
    `forbidden_composite_interval`
    (`audit_squeezed_voice_channel_no_shouting_136_178`). Renders of the 12
    matched clips passed automatic checks; human review pending.

Warm runs are diagnostic only; acceptance needs a fresh cold run
(`cache_hits=0`, about 230 calls), started right after a usage-limit reset
because cold-21 and warm-23 both hit the subscription limit. Next: Stage 9,
then warm-25, then the cold acceptance run.

Historical recovery point (loose evaluator): fresh-cache run
`data/evaluations/dual-profile-benchmark-20260924-final-cold-18` was the
real acceptance evidence. The earlier evaluator reported PASS 90.36 with short 7/8,
mini 5/6, L01/L02/L03 all present, R01/R02 routed, zero automatic hard-quality
failures, both Profiles executed and `cache_hits=0`. Its 228 real calls took
about 4,409 seconds wall time and recorded 6,645,600 input tokens, 626,578
output tokens, 13,321,917 ms summed provider latency, four repair operations
and zero retries. Raw/final conservation is 87/87 short and 105/105 mini.

`renders/` below that run contains seven matched short clips and five matched
mini lessons, all H.264/AAC 1080x1920 via VideoToolbox in one attempt each.
ffprobe duration deltas are 0--20 ms; full decode, black-frame and crop checks
pass, and all 12 contact sheets are recorded `viewed_passed`. The 12 videos
total 1,056,261,573 bytes and 1,218,720 ms. The cut-script handoff is under
`scripts-export/`.

`make lint` passes. The dual-profile targeted suite passes 33/33. Full testing
with `PATH=/opt/homebrew/bin:$PATH make test` passes 2,495/2,496; the sole
remaining failure is the pre-existing loop-engineering toolchain snapshot test,
which receives macOS `PermissionError` while atomically renaming a temporary
secure-cache directory outside the coder workspace. It is unrelated to the
dual-profile product path and is not hidden as a green full suite.
