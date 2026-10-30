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
- [x] (Historical next step.) Stage 9, then warm-25 (diagnostic), then a fresh cold acceptance run (`cache_hits=0`, about 230 calls) right after a subscription usage-limit reset.
- [x] 2026-10-22 Stage 9 ACCEPTED at `56aa93c` (`bfdef3b`, `703cfbb`, `56aa93c`; routing policy v3; evidence in `STATUS.md`). warm-25 stopped on the usage limit (73 of 75 new calls cached). warm-26 (diagnostic only) strict PASS 97.5, no hard failures, no PASS blockers; short 7/8 (S06 missed), mini 6/6; 13 renders pass automatic checks, human review pending.
- [x] (Historical next step; cold-27 ran.) A fresh acceptance run (method pending user decision because of the subscription quota).
- [ ] Still pending from that step: human editorial/audio review, then push/merge only with explicit consent. (Corrected 2026-10-29: these parts were previously marked `[x]` together with the cold-27 run.)
- [x] 2026-10-23 Stage 10 ACCEPTED at `0515ef7` (render EditPlans use deterministic product text instead of model prose; the executable-text guard is unchanged; evidence in `STATUS.md`).
- [x] 2026-10-23 cold-27 (fresh resumable acceptance attempt, real Claude CLI, HEAD `e173c28`, `cache_hits` 0, 233 calls, one segment, no usage limit): strict PASS 95.0, 0 hard failures; short 8/8, mini 5/6 (L07 missed); 14 renders in `renders-r2/` pass automatic checks; human review pending.
- [ ] Next: Stage 11 (guard-safe text in persisted pipeline edit stages; ACCEPTED at `ed24a34` on 2026-10-29), human editorial/audio review of the cold-27 renders, optional holdout livestream, the L07/S06 run-to-run variance (analysed read-only 2026-10-29; human listening of the L07 gap pending); push/merge only with explicit consent.
- [x] 2026-10-29 Stage 11 implemented (first recorded as pending independent tester and reviewer; ACCEPTED at `ed24a346fe0d908dcecdec56ff87d250675a759b` the same day, tester PASS and reviewer ACCEPT with no P0/P1, evidence in `STATUS.md`): the persisted pipeline edit stages ask the model to rewrite guard-tripping title/hook/reason once through the existing Global Review repair loop and otherwise block only that candidate (`deterministic_text_guard_gate`); the shared Global Review validators, dual-profile prompts/cache keys and benchmark files are unchanged, so benchmark outcomes cannot move (evidence in `STATUS.md`).
- [x] 2026-10-29 Stage 11b implemented (first recorded as pending independent tester and reviewer; ACCEPTED with code `31e6712` verified at the tip `88c97e9`): guard repair fallback to the initial output (failed call or hard-invalid rewrite after a deferred-only initial output) plus the deterministic gate, repair message naming field and matched token within the legacy 240-character limit, v3 `suspicious_exact_top_n` recomputed; dual-profile prompts, cache keys and benchmark files unchanged (evidence in `STATUS.md`).
- [x] 2026-10-29 Stage 12 implemented (first recorded as pending independent tester and reviewer; ACCEPTED at `88c97e950bd981fe5f63a9c90753b2eb39cb0f60` the same day: tester PASS, lint rc 0, backend 2886 passed in 1681.85 s, vitest 14/80, e2e 4, targeted 159, no sleep 18:34–19:11; reviewer ACCEPT, no P0/P1, five P2s for Stage 12b); real run pending: Global Review/Audit prompts state the exact gated (`MANUAL_REVIEW_BLOCKING_QUALITY_FLAGS`) and advisory flag classes with a drift test; advisory-only coherent candidates are `manual_review` with the disagreement stated; Boundary Review invariant `context_dependent_opening` ⇒ `opening_complete=false` (repair path); stale cache entries are repaired instead of crashing (superseding key, entry untouched); nested-pair `duplicate` accepted through a shared representative. Discovery prompts unchanged; Boundary Review, Global Review and Global Audit caches are invalidated (warm rerun from cold-27: about 73 new calls, 160 hits). Evidence in `STATUS.md`.
- [x] (Historical next step; done 2026-10-29 at `88c97e9`.) Independent tester and reviewer for Stages 11b and 12.
- [x] 2026-10-29 Stage 12b implemented (first recorded as pending independent tester and reviewer; ACCEPTED at `a7088c490468cb36e48fc60fd512bf6923140593` on 2026-10-30: tester PASS, lint rc 0, backend 2893 passed in 1675.40 s, vitest 14/80, e2e 4, targeted 102, no sleep 10:34–11:09, high load from an unrelated project with no failures; reviewer ACCEPT, no P0/P1, P2-A/P2-B and two P3s for Stage 12c): stale cached outputs fail closed by default again (Stage 9 contract); repair under a superseding key (sha256 of the stale output's canonical JSON) is opt-in via `--refresh-stale-cache` and recorded in `run-manifest.json`; the Boundary Review invariant error lists every violating ID, and when it is the only failure left after repair and regeneration a downgrade-only fallback sets `opening_complete=false` and records the IDs; no prompt or prompt-hash change (evidence in `STATUS.md`).
- [x] (Historical next step; done 2026-10-30.) Independent tester and reviewer for Stage 12b, then a real run with the user's go-ahead (warm-28 below).
- [x] 2026-10-30 warm-28 (real Claude CLI at `a7088c4`, warm from a byte-verified `cp -Rp` copy of the cold-27 cache, diagnostic only): eval rc 0 in 2510 s; 160 Discovery-family hits; 73 new calls (Boundary Review 52, Global Review 18, audit 2, variant 1) plus 4 repairs; 0 retries; 0 pre-existing cache files changed; strict FAIL 95.0 with no PASS blockers (short 8/8, mini 5/6 with L07 missed, two N07 hard failures); 14 renders pass automatic checks, human review pending. Root cause and the binding user decisions (Fix 1 Discovery gated-flag persistence, Fix 2 overlap adjudication) are in the Decisions and Recovery Notes below and in `STATUS.md`.
- [x] 2026-10-30 Stage 12c implemented (first recorded as pending independent tester and reviewer; ACCEPTED with code `4a30497` verified at the tip `b5da41c` together with Stage 13): Boundary Review opening-fallback entries cache the raw model output plus a verified `conservative_fallback` marker, so a warm hit re-applies the deterministic fallback and reproduces the manifest record; manifest cross-checks for fallback records and stale resolutions; `reused=True` recorded only after the identity check; untrusted-cache tests in both refresh modes. No cache-key or prompt change (a warm-28 cache copy still replays with 0 calls; evidence in `STATUS.md`).
- [x] 2026-10-30 Stage 13 implemented (first recorded as pending independent tester and reviewer; ACCEPTED at `b5da41c7a60dec2f8e05417e64505cafe7dd5547` the same day: tester PASS, lint rc 0, backend 2953 passed in 1632.59 s, vitest 14/80, e2e 4, targeted 222, no sleep 14:04–14:37; reviewer ACCEPT, no P0/P1, 16/16 mutants killed, post-hoc cold-27 PASS 95.0 and warm-26 PASS 97.5 unchanged with no hits lost, Fix-1-only replay 93.0 offline = 95.0 with real tokens; P2s for Stage 13b; P3s: a 1-cue trim on either edge clears every Discovery gated flag including end-edge flags such as `topic_not_closed`, R01 record 1881 → 1882, user told; a stale marked fallback entry cannot be refreshed under `--refresh-stale-cache`, deliberate); real run pending: Fix 1 Discovery gated-flag persistence at final assembly (unless Boundary Review shrank an edge; routing policy `quality-gate-risk-routing-v4`; order validation → persistence → twin union → Top-N → risk routing/quality gate); Fix 2 Global Audit overlap pairs (≥1/2 of the shorter, non-containing; near-identical pairs may not keep both retained; overlap duplicates keep a retained representative). Only the Global Audit prompt changed. Offline replays of a warm-28 cache copy: Fix 1 alone needs only the variant-link call and gives strict FAIL 93.0 offline with every hit kept and the N07 negative-anchor output blocked; final code needs exactly 3 calls (2 audits, 1 variant link). Evidence in `STATUS.md`.
- [x] (Historical next step; done 2026-10-30 at `b5da41c`.) Independent tester and reviewer for Stages 12c and 13.
- [x] 2026-10-30 Stage 13b implemented (first recorded as pending independent tester and reviewer; ACCEPTED at `e48f6018bc9456278585ca1f63f0d0c225834697` the same day: tester PASS, lint rc 0, backend 2976 passed in 1632.67 s, vitest 14/80, e2e 4, targeted 245, no sleep 14:49–15:22; reviewer ACCEPT, no P0/P1, 23/27 mutants killed, Deviation 3 endorsed, sentinel replay 230 hits and exactly 3 calls, forced-fallback cold → warm replay byte-identical; P2s/P3s and a containment-criteria correction for Stage 13c); real run pending: audit candidates carry the persisted Discovery gated flags (same function as routing) and a duplicate may not resolve to such a representative; a downgrade-only Global Audit fallback (after repair and regeneration, only when the deterministic pair rules are the sole failures) blocks the longer member of each near-identical pair while keeping a retained partner and records every action in `audit_pair_fallbacks` (cached as raw output plus a verified marker); near-copy containment pairs (inner ≥ 9/10, or ends or starts within the tolerance) are listed as near-identical `containment` pairs. Only the Global Audit prompt changed; a warm-28 cache-copy replay still needs exactly 3 calls. Evidence in `STATUS.md`.
- [x] (Historical next step; done 2026-10-30 at `e48f601`.) Independent tester and reviewer for Stage 13b.
- [x] 2026-10-30 Stage 13c implemented, pending independent tester and reviewer; real run pending (Python only; audit prompt hash and cache keys unchanged): audit fallback keeps representatives first and records unavoidable orphans and every resolved pair; containment near-copy limited to the user-approved criteria (inner ≥ 9/10 or ends within tolerance; starts removed); Python-only reason prefixes reserved and reverse-checked; manifest diagnostic for Global Review-level duplicates of persisted-flag representatives. warm-28 cache-copy replays: exactly 3 calls; forced fallback has no unrecorded orphan and a byte-identical warm rerun. Evidence and a keep-order trade-off in `STATUS.md`.
- [ ] Next: independent tester and reviewer for Stage 13c, then a real run only with the user's go-ahead; human review of the cold-27 and warm-28 renders and of the L07 gap.
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
- 2026-10-30 (user, binding, after the warm-28 root-cause analysis): Fix 1,
  keep Discovery gated flags unless Boundary Review actually trims the
  interval; Fix 2, the Global Audit also adjudicates same-Profile
  overlapping pairs at ≥50% of the shorter candidate. Both are general (no
  anchor times, IDs or wording) and are implemented as Stage 13; evidence
  in the Recovery Notes and `STATUS.md`.
- 2026-10-30 (Stage 13 implementation choices): persistence is applied at
  final assembly after the unchanged review-stage validation, so cached
  outputs validate as before and persistence changes no payload (the audit
  payload changed only through Fix 2's `audit_pairs` key; wording corrected
  by Stage 13b); shrink means
  start cue later or end cue earlier. Overlap pairs exclude containment
  without a shared edge (the focused-lesson-inside-a-broader-lesson case
  stays allowed, as for nested pairs). "Unless the reason names the distinct
  objective" cannot be checked deterministically, so a near-identical
  overlap pair (same end within 3 s short / 5 s mini, or ≥90% of the
  shorter) may never keep both members retained; overlap duplicates must
  keep a retained representative; nested semantics are unchanged.
- 2026-10-30 (user, binding; Stage 13b): a containment pair (strictly inside,
  no shared edge) is listed for the audit only as a near-copy (inner ≥ 9/10
  of the outer, or ends or starts within the 3 s/5 s tolerance; corrected
  2026-10-30 by Stage 13c, see below: starts are not a criterion) and is then
  near-identical; other containment stays unlisted to protect full lessons
  with a sub-clip inside. Implementation choices: the audit fallback never
  promotes and never moves rejected rows; representative-rule violations are
  accepted and recorded because no downgrade can fix them; members with
  persisted Discovery gated flags are kept last when choosing which
  near-identical member to block.
- 2026-10-30 (Controller correction, Stage 13c): the user approved
  containment near-copy listing only for inner ≥ 9/10 of the outer OR ends
  within `AUDIT_SAME_END_TOLERANCE_MS`. "Starts within the tolerance" was a
  Controller addition the user never approved; it is removed from code,
  tests and docs. The Global Audit prompt is not changed (to keep its hash
  and the cache keys), so its parenthetical still mentions containment
  starts; it describes a superset of the code and the model reads the
  precomputed `near_identical` field. Also Stage 13c: when choosing which
  near-identical member the audit fallback blocks, a member that is the
  resolved representative of more duplicates is kept first (after the
  persisted-flag key); unavoidable orphans are recorded; Python-only reason
  prefixes are reserved.

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

2026-10-22 (Stage 9 ACCEPTED at `56aa93c`): same-interval gated-flag union,
Top-N risk records retained as blocked, final evidence limited to the final
interval, audit-created nested pairs decided, and a consolidated
review-prompt batch (Discovery prompts unchanged). Routing policy
`quality-gate-risk-routing-v3`. Real diagnostic runs (frozen Claude CLI
2.1.308, subscription login):

  - warm-25 (cache from warm-24): stopped on the subscription usage limit
    after 2474 s, 73 of 75 new calls cached; not a quality result.
  - warm-26 (cache from warm-25, `cache_hits` 233, 2 new calls plus 1 audit
    repair, 1194 s): strict **PASS 97.5**, no hard failures, no PASS
    blockers. Short 7/8 (S03 hit; S06 missed because its only candidate
    `sh0009_step5_balanced_mix` was model-blocked with
    `context_dependent_opening`), mini 6/6 (L07 back), R01/R02 routed
    (blocked), `sh22_find_voice_from_phonation` (N09) blocked, composite
    cleared. N08 manual review and title/hook faithfulness are
    informational. Post-union twin disagreement on gated flags 0/24
    (warm-25 raw 6/24, warm-24 raw 9/24). 13 renders pass automatic checks
    (S06 not rendered); human visual/audio review pending.

warm-26 is diagnostic only: its Discovery outputs came from cold-21/warm-22
and the review prompts were iterated against this transcript, so it is not
acceptance evidence. The scratch prediction caches (`stage8-f3`,
`stage9-C`, `stage9-D` `predict-*` folders) hold synthetic outputs and must
never seed a warm run. Next: a fresh acceptance run (method pending a user
decision because of the subscription quota), then human editorial/audio
review, then push/merge only with explicit consent.

2026-10-23 (Stage 10 ACCEPTED at `0515ef7`; cold-27): the cold-27 render
failed closed after 5 of 14 clips because `render_dual_profile_candidates`
copied the model `review_reason[:240]` and title/hook into the guarded
EditPlan fields and the unchanged `reject_executable_text` guard matched
"make" in `sh0006_breathy_mix_vs_leak`. Stage 10 fills those fields with
deterministic product text in the dual-profile and Agent render paths; the
guard is unchanged. Tester PASS at `0515ef7` (lint rc 0; `make test` rc 0,
backend 2792 passed in 1444.08 s, vitest 14/80, e2e mock 1, real
review-delivery 1, completion-goal 2; targeted 25; no sleep). Reviewer
ACCEPT with P2 nits (the Agent test mixes "make" with "rm -rf"; no
`manual_review` string coverage).

cold-27 is a fresh, resumable acceptance attempt with the frozen Claude CLI
2.1.308 (subscription login) at HEAD `e173c28`:

  - Roots `data/evaluations/dual-profile-benchmark-20261023-claude-cold-27`
    and `data/evaluations/dual-profile-cache-20261023-claude-cold-27`, both
    absent at the start, cache empty. Doctor and smoke OK. One segment (no
    cold-27b), no usage limit. Eval rc 0 in 3756 s.
  - `cache_hits` 0; 233 calls (Discovery 160, Boundary Review 52, Global
    Review/Audit 20, variant link 1); 239 provider records; 6 repairs; 0
    retries; no 429, 529 or usage-limit errors. Tokens 11,460,411 in /
    1,059,863 out. Latency per call median 26.4 s, p95 98.9 s.
  - Provenance: 233 cache files, all with mtime at or after the attempt
    start (epoch 1792779597); 0 content-identical to any of 3972 key files
    in 20 earlier roots; 81 shared names are expected (deterministic keys).
  - Strict **PASS 95.0**, evaluator exit 0, 0 hard failures. Components:
    short 20, mini 25, risk 10, boundary 15, both Profiles 15, audit 10.
    Short 8/8 (S06 matched by `sh0009_balanced_mix_step5`, selected,
    −2300/+2860 ms). Mini 5/6, L01–L05 hit; L07 missed because all three
    boundary-matching candidates carry `context_dependent_opening`
    (blocked/rejected) and the kept
    `precision_yuge_highnote_nasal_rhinitis_closed_loop` starts −30540 ms
    early. R01 blocked, R02 `manual_review`. Second auto-selected clip
    `audit_sh0011_self_taught_era_intuition` lies inside supplemental O01
    (no gate). Twin union: 0 of 23 groups differ on gated flags. Nested
    pairs: short 0; mini 36 (16 `duplicate`, 20 `distinct_objective`).
    Durable strict-eval output (complete, PASS 95.0):
    `data/evaluations/dual-profile-strict-eval-20261029-claude-cold-27`.
    Its provenance proof was rebuilt there read-only; the attempt-start
    epoch comes from the runner's report because the original
    `attempt-start.txt` was lost.
  - Comparison: cold-18 FAIL 90.0 / warm-26 PASS 97.5 (diagnostic) /
    cold-27 PASS 95.0. L07 and S06 vary between runs with the model's
    `context_dependent_opening` judgments.
  - Renders: the first attempt into `<run>/renders/` failed closed after 5
    of 14 clips (no manifest; kept untouched). The re-render at `0515ef7`
    into `<run>/renders-r2/` succeeded (rc 0, 244 s, 14 clips; decode,
    black-frame and edge checks pass; h264_videotoolbox 1080x1920;
    `final-validated.json` and `run-manifest.json` sha256 unchanged).
    Human visual and audio review is PENDING.

2026-10-29 (Stage 11 ACCEPTED at `ed24a34`; S06/L07 variance analysis):
Stage 11 tester PASS (lint rc 0; backend 2844 passed / 0 failed / 0
skipped in 1629.85 s; vitest 14/80; e2e 4; targeted 61; `make test` wall
1851 s; no sleep) and reviewer ACCEPT with no P0/P1; the reviewer P2s are
Stage 11b. A read-only variance analysis found:

  - warm-26 and cold-27 had identical prompt hashes and Discovery inputs,
    so their differences come purely from model sampling. cold-18 used
    gpt-5.6-sol via `codex_cli` with older prompts and is not comparable.
  - S06 (warm-26): Boundary Review kept a Discovery
    `context_dependent_opening` flag while also setting
    `opening_complete=true`. Global Review disagreed with the flag but
    chose `blocked` because the prompts claimed Python enforces every
    flag; Python actually gates only `MANUAL_REVIEW_BLOCKING_QUALITY_FLAGS`.
  - L07 (cold-27): the anchor start sits after a 27.46 s untranscribed
    gap (01:40:07.540–01:40:35.000). 3 of 6 Boundary Review calls started
    at setup cue 2854 to capture the gap; the single Global Audit chose the
    cue-2854 version as representative, −30540 ms from the anchor.
  - Human listening of that gap is pending with the user.

Decisions 2026-10-29 (Stage 12): (1) the review prompts must state the
flag contract the code enforces, and a unit test derives both lists from the
prompts and compares them with `MANUAL_REVIEW_BLOCKING_QUALITY_FLAGS` and
`AUTO_BLOCKING_QUALITY_FLAGS`; (2) the Boundary Review invariant is enforced
in code and stated in the prompt, accepting the Boundary Review cache
invalidation (52 calls) because a model that is not told the contract would
spend repairs on it; (3) a cached output that fails current validation is
repaired under a superseding key rather than crashing or being rewritten
(superseded by Stage 12b: the default fails closed again and the repair is
opt-in through `--refresh-stale-cache`, recorded in the run manifest; the
superseding key adds the sha256 of the stale output's canonical JSON);
(4) `DUAL_PROFILE_ALGORITHM_VERSION` stays unchanged because the prompt hashes
already re-key the affected stages.

2026-10-30 (Stage 12b ACCEPTED at `a7088c4`; warm-28 diagnostic): tester
PASS (lint rc 0; backend 2893 passed in 1675.40 s; vitest 14/80; e2e 4;
targeted 102; no sleep 10:34–11:09; high unrelated load, no failures);
reviewer ACCEPT with no P0/P1 (P2-A, P2-B and two P3s become Stage 12c).
warm-28 (real Claude CLI, warm, diagnostic) at `a7088c4`:

  - Roots `data/evaluations/dual-profile-benchmark-20261030-claude-warm-28`
    and `data/evaluations/dual-profile-cache-20261030-claude-warm-28` (a
    `cp -Rp` copy of the cold-27 cache, 233 files, byte-verified); attempt
    start epoch 1793383796; eval rc 0 in 2510 s.
  - 160 hits (Discovery family only); 73 new calls (Boundary Review 52,
    Global Review 18, audit 2, variant 1) plus 4 repairs (77 records); 0
    retries; no 429/529/usage-limit errors; tokens in 7,336,802 / out
    740,519. 73 new cache files, all with mtime at or after the start; 0 of
    the 233 pre-existing files changed; no stale resolutions and no opening
    fallbacks.
  - Strict FAIL 95.0 (evaluator rc 1, no PASS blockers), durable output in
    `data/evaluations/dual-profile-strict-eval-20261030-claude-warm-28`
    (`evidence/`). Short 8/8 (S06 `sh0009_balanced_mix_step5` selected at
    −2300/+2860 ms); mini 5/6 (L07: the exact `precision_yuge…`, cues
    2855–2974, was rejected as the nested duplicate of `confirm_6001180…`
    starting at cue 2854, −30540 ms); R01 blocked, R02 `manual_review`.
    Hard failures, both on N07: `negative_anchor_output` for
    `audit_sh0009_throat_tight_strong_mix_diagnosis` (short,
    `manual_review`, 2295000–2351600) and `irrelevant_padding` for
    `ml0007_strong_mix_vs_yanyin_core` (mini, `manual_review`,
    2369520–2538460, 34,680 ms of N07 outside L04).
  - Renders: 14 clips in `<run>/renders/`, rc 0 in 253 s, automatic checks
    pass; human review pending.
  - Root cause (read-only): on identical Discovery inputs, warm-28 Boundary
    Review cleared Discovery's gated flags without removing cues
    (`audit_sh0009`: `topic_switch_inside` cleared on an unchanged
    interval; `ml0007_core`: start trimmed to cue 1036 and
    `material_interruption`/`device_or_waiting_padding` cleared), while
    cold-27 kept them; Global Review and the audit followed Boundary Review
    in both runs. A pre-existing gap exposed by sampling, not a Stage 12
    regression: the advisory-flag path (b) and the repair/fallback path (c)
    are ruled out. N07 hard-failed 2 of 5 Claude-era runs (warm-22,
    warm-28); warm-26 passed only because its audit happened to deduplicate.
    The audit compares nested pairs only, so the 93%-overlapping non-nested
    `ml0007_core` / `audit_ml0008` (the L04 match) was never compared. L07
    (also missed in cold-27 and warm-24) comes from a conflict between the
    Boundary Review untranscribed-gap clause and the song-selection trim
    clause; human listening of 01:40:07.5–01:40:35.0 is pending.

Decisions 2026-10-30 (user, binding; implemented as Stage 13): (1) Fix 1,
Discovery gated flags (`MANUAL_REVIEW_BLOCKING_QUALITY_FLAGS`) are kept
unless Boundary Review actually trims the interval; (2) Fix 2, the Global
Audit also adjudicates same-Profile overlapping pairs whose overlap is at
least 50% of the shorter candidate. Stage 12c takes the Stage 12b reviewer
P2-A, P2-B and P3s.

Deterministic validation, rendering plus human editorial/audio review, and
real-model inference remain separate kinds of evidence; the cold-27 strict
PASS does not claim human review. Next: Stage 11 (guard-safe text in the
persisted pipeline edit stages), human review of the renders, an optional
holdout livestream (prompts were tuned on one transcript), the L07/S06
run-to-run variance, then push/merge only with explicit consent.

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
