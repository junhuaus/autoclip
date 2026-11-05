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
- [x] 2026-10-30 Stage 13c implemented, pending independent tester and reviewer; real run pending (Python only; audit prompt hash and cache keys unchanged): audit fallback keeps the shorter member first (representative count only breaks equal-duration ties, after the Controller decision in the second 13c commit; the first 13c commit `4543d0a` kept representatives first; wording corrected by Stage 13d) and records unavoidable orphans and every resolved pair; containment near-copy limited to the user-approved criteria (inner ≥ 9/10 or ends within tolerance; starts removed); Python-only reason prefixes reserved and reverse-checked; manifest diagnostic for Global Review-level duplicates of persisted-flag representatives. warm-28 cache-copy replays: exactly 3 calls; forced fallback has no unrecorded orphan and a byte-identical warm rerun. Evidence and a keep-order trade-off in `STATUS.md`.
- [x] (Historical next step; done 2026-10-30 at `6089884`.) Independent tester and reviewer for Stage 13c, then a real run with the user's go-ahead (warm-29 below).
- [x] 2026-10-30 Stage 13c ACCEPTED at `608988463c9e98a7eb861e28a5a80360ea29366d` (code `4543d0a` and `6089884`; tester PASS: backend 2986 passed, vitest 80, e2e 4, targeted 255; reviewer ACCEPT, no P0/P1; P3s for Stage 13d: stale "representatives first" wording, reserved-prefix test gaps, audit fallback test gaps).
- [x] 2026-10-30 warm-29 (real Claude CLI at `6089884`, pinned 2.1.308, warm from a byte-identical `cp -Rp` copy of the warm-28 cache, 306 files, diagnostic only): FAILED CLOSED after 263 s in the short Global Audit (`deterministic validation still failed after one repair and one regeneration: duplicate candidate must be retained as a rejected audit row`); no provider-calls, manifest or new cache file; raw model outputs unrecoverable. Root cause: the pair validator accepts a `blocked` duplicate for any candidate while final assembly accepts it only for risk-discovery records, and the audit prompt gives no guidance for a pair whose members both carry persisted flags. Not a quality result. Details in the Recovery Notes and `STATUS.md`.
- [x] (Historical next step; implemented 2026-11-01, pending verification, see below.) Stage 13d.
- [x] 2026-11-01 Stage 13d implemented, pending independent tester and reviewer; real run pending (code `6e1152c` and the following commit): validation exhaustion raises `DualProfileValidationExhaustedError` and writes `failed-<profile>-<stage>.json`, a partial `provider-calls.json` and `failure-manifest.json` to the run directory only (CLI still exits 1); candidate-naming validator messages that report every violation; final assembly accepts a duplicate as `rejected` or `blocked` for any candidate (a retained duplicate stays a hard error, never coerced); merged-audit assembly and pair errors are reported together and only a pair-rule-only failure reaches the fallback; only `global_audit.md` changed (short `686a9fbafa60…`, mini `bdb7ff0545a9…`); Stage 13c reviewer P3s. warm-29 cache-copy replays: sentinel 230 hits and exactly 3 calls; forced fallback unchanged and byte-identical warm; the analyst's 11 warm-29 what-ifs: 10 accepted, 1 (retained duplicate) fails closed with evidence in the run directory and the cache untouched. Evidence in `STATUS.md`.
- [x] (Historical next step; done 2026-11-01 at `bc150c5`, then warm-29b below.) Independent tester and reviewer for Stage 13d, then a real run with the user's go-ahead.
- [x] 2026-11-01 Stage 13d ACCEPTED at `bc150c5f5fc772f574e09c305ba0d7d5d9991bc9` (code `6e1152c` and `bc150c5`; tester PASS: lint rc 0, backend 3000 passed in 1663.46 s, vitest 14/80, e2e 4, targeted 327, no sleep 19:50–20:22; reviewer ACCEPT, no P0/P1: only the Global Audit hashes changed (short `686a9fba…`, mini `bdb7ff05…`), 11 of 12 mutants killed, sims reproduced, strict evaluator on cold-27/warm-28 byte-identical, Decision 3 legitimate (a blocked duplicate can count as R01/R02 routing like any blocked candidate); P2/P3 findings for Stage 13e).
- [x] 2026-11-01 warm-29b (real Claude CLI at `bc150c5`, pinned 2.1.308, warm from a `cp -Rp` copy of the warm-29 cache, 306 files, attempt start epoch 1793593441; **diagnostic only, not acceptance evidence**): eval rc 0 in 666 s; 230 hits, exactly 3 new calls plus 1 repair (4 records), 0 retries, tokens in 1,773,780 / out 81,778; cache 306 → 309 with 0 pre-existing files changed; no stale resolution, no boundary or audit fallback. Strict **PASS 95.0** (short 8/8 with S06; mini 5/6, L07 still missed; R01 blocked, R02 manual_review; no hard failures, no PASS blockers). Both warm-28 N07 failures cleared. 14 renders rc 0 in 266 s, automatic checks pass; human review pending. Details in the Recovery Notes and `STATUS.md`.
- [x] (Historical next step; implemented 2026-11-01, pending verification, see below.) Stage 13e reviewer follow-ups.
- [x] 2026-11-01 Stage 13e implemented, pending independent tester and reviewer (Python and tests only; every prompt hash and cache key unchanged versus `bc150c5`): the reviewer's assembly-only audit probe is a regression test (fails when the merged-audit `raise assembly_error` is deleted); the failure-evidence writer catches any `Exception` and notes it; concurrently exhausted units of one stage all reach the failure evidence (`concurrent_exhausted_units`, their records in the partial `provider-calls.json`, `concurrent_failed_subject_ids`); the account-identity wording names the Claude CLI provider only; the duplicate test mode `keep_lesson_blocked` is merged into `blocked_dup`. Sentinel replay on a scratchpad copy of the warm-29b cache: 233 hits, 0 calls, outputs byte-identical to warm-29b. Evidence in `STATUS.md`.
- [x] 2026-11-01 Stage 13e ACCEPTED at `194ba653b0abd9712bc750eaf2d6aada594a61c3` (tester PASS: backend 3003 passed, vitest 80, e2e 4, concurrency test 5/5; reviewer ACCEPT with an offline cold simulation, no blocker).
- [x] (Historical next step; cold-30 ran at `194ba65`, below; the Stage 13e reviewer P3 nits are fixed in Stage 14.) Independent tester and reviewer for Stage 13e, then cold-30 (fresh cold run at the final code) as the acceptance run.
- [x] 2026-11-01 cold-30 (fresh cold acceptance attempt, real Claude CLI at `194ba65`, pinned 2.1.308, attempt start epoch 1793597156): eval rc 0; `cache_hits` 0; 231 calls plus 3 Boundary Review repairs; 0 content-identical cache files versus 24 earlier roots. Strict **FAIL 92.5** (`missing_any_p0_mini_lesson`): short 7/8 (S03 +12440 ms); mini 5/6 (L01 missed only by Discovery padding-flag persistence on the exact candidate; L07 hit for the first time); R01/R02 blocked; all 8 N07-overlapping candidates blocked or rejected. 12 renders rc 0, automatic checks pass, human review pending. Evidence in `data/evaluations/dual-profile-strict-eval-20261101-claude-cold-30/evidence/`; details in the Recovery Notes and `STATUS.md`.
- [x] 2026-11-01 Stage 14 implemented in `fc31907266ee07485567580f5b125ced76775cfe`, pending independent tester and reviewer (user decision "Padding follows BR + prompt"): routing policy `quality-gate-risk-routing-v5` persists only structural Discovery gated flags; padding flags follow Boundary Review; shared `main.md` gains the microphone/demonstration rule and the padding-is-edge definition; Global Review/Audit wording updated; every stage prompt hash changed; CLI exhaustion summary keeps the evidence-writer note. Offline replay of the four runs: cold-27 PASS 95.0, warm-28 FAIL 95.0 (unchanged), warm-29b PASS 95.0, cold-30 PASS 97.5 (routing evidence only). Evidence in `STATUS.md`.
- [x] (Historical next step; Stage 14 accepted below.) Next: independent tester and reviewer for Stage 14, then a fresh cold run only with the user's go-ahead; human review of the cold-27, warm-28, warm-29b and cold-30 renders and of the L07 gap.
- [x] 2026-11-02 Stage 14 ACCEPTED at `2c088fe1af349cb4a93502fe10a5ba8769ef9183` (code `fc31907`, docs `2c088fe`; tester PASS: lint rc 0, `make test` backend 3042 passed, vitest 80, e2e 4/4, concurrency test 5/5, no sleep; reviewer ACCEPT with nits, no P0–P2; replay cold-27 PASS 95.0, warm-28 FAIL 95.0 unchanged, warm-29b PASS 95.0, cold-30 PASS 97.5). The P3 nits become Stage 14b.
- [x] 2026-11-02 Stage 14b implemented in `9664efe5b14c410984e452e339b7c245db480e14`, pending independent tester and reviewer (prompts and tests only; routing policy stays `quality-gate-risk-routing-v5`, gate semantics unchanged): Boundary Review, Global Review and Global Audit say interior audibility/lag/network/playback trouble is `material_interruption` (a padding flag may be added alongside, never instead), padding stays edge material as in `main.md`; Risk Discovery and Coverage Audit name `material_interruption` (or `topic_switch_inside`) for interior interruptions of a risk chain. Changed hashes (both Profiles): coverage_audit, risk_discovery, boundary_review, global_review, global_audit; unchanged: discovery, precision_audit, precision_confirmation, variant link. New integration test: a padding-only Discovery-flagged candidate (Boundary Review cleared, no trim) validates like an unflagged candidate under the representative rule, a blocked duplicate and the pair fallback keep order. Evidence in `STATUS.md`.
- [x] (Historical next step; Stage 14b REJECTED below.) Next: independent tester and reviewer for Stage 14b, then the fresh cold run cold-31 only with the user's go-ahead; human review of the cold-27, warm-28, warm-29b and cold-30 renders and of the L07 gap.
- [x] 2026-11-02 Stage 14b reviewer REJECT on docs commit `66265e2e79d36a08e98e46c857ae71a490da2049` (P2, docs only): the `STATUS.md` Stage 14b hash table listed intermediate-draft global_review/global_audit hashes for both Profiles; code at `9664efe` unaffected.
- [x] 2026-11-02 Stage 14c implemented, pending independent tester and reviewer (prompt, test and docs; routing policy stays `quality-gate-risk-routing-v5`, gate semantics unchanged): `boundary_review.md` cross-references interior audibility/lag/playback trouble as `material_interruption` and says interior chat kept for duration flags `padded_with_irrelevant_content` alongside the interior flag, never instead (boundary_review hashes change for both Profiles; all others unchanged); new test pins the full service-recorded boundary_review, global_review and global_audit hashes for both Profiles and the variant link; `STATUS.md` Stage 14b hash table corrected, full Stage 14c table added. Self-check: lint rc 0, targeted pytest 277 passed.
- [x] (Historical next step; Stage 14c accepted and cold-31 ran, below.) Next: independent tester and reviewer for Stage 14c, then the fresh cold run cold-31 only with the user's go-ahead; human review of the cold-27, warm-28, warm-29b and cold-30 renders and of the L07 gap.
- [x] 2026-11-02 Stage 14c ACCEPTED at `867d1cf669ffb9d8eccce40ba97d84fd44e016ef` (tester PASS: lint rc 0, backend 3056 passed, vitest 80, e2e 4, concurrency test 5/5, no sleep; reviewer ACCEPT with nits).
- [x] 2026-11-02 cold-31 (fresh cold acceptance attempt, real Claude CLI at `867d1cf`, pinned 2.1.308, attempt start epoch 1793609949): eval rc 0; 242 provider records, `cache_hits` 0, 0 content-identical cache files versus 25 earlier roots, every recorded prompt hash equals Stage 14c. Strict **FAIL 87.5** (`missing_any_p0_mini_lesson`: L02): short 7/8 (S03 +12440 ms); mini 4/6 (L01/L03/L04/L05 hit; L02's exact base candidate blocked only by the Stage 9 twin union copying `material_interruption` from its risk-discovery twin; L07 missed by representative-choice variance); R01/R02 blocked; all N07-overlapping rows blocked; N08 `manual_review` informational. 11 renders rc 0, human review pending. Evidence `data/evaluations/dual-profile-strict-eval-20261102-claude-cold-31/evidence/`; analysis in `STATUS.md`.
- [x] 2026-11-04 Stage 15 implemented in `289530eba3b59f89325ede5c268f9064f8cb5257`, pending independent tester and reviewer (user decisions "Ignore risk-twin tags", `material_interruption` threshold, self-promotion rule): routing policy `quality-gate-risk-routing-v6` — the same-interval twin union no longer uses risk-discovery records as flag sources (they keep their own flags and still receive non-risk twins' flags) through the shared helper `same_interval_twin_flags`, which also drives the new manifest diagnostic `risk_twin_flags_not_propagated` and its `validate_against` cross-check; `main.md`, `risk_discovery.md`, `coverage_audit.md` state the threshold (only content that breaks the teaching or claim logic; a brief passed-over audience acknowledgement is neither an interruption nor padding), `boundary_review.md` aligned, `precision_audit.md` defers to it; Boundary Review, Global Review and Global Audit reject a candidate whose central objective is the speaker's own credentials, pricing, course sales or schedule. Every stage hash except the variant link changed (table in `STATUS.md`). Offline replay: cold-27 PASS 95.0, warm-28 FAIL 95.0, warm-29b PASS 95.0, cold-30 FAIL 92.5 (all unchanged versus v5), cold-31 PASS 92.5 (L02 restored; routing evidence only). Self-check: lint rc 0, targeted pytest 308 passed.
- [x] (Historical next step; Stage 15 accepted and Stage 15b followed, below.) Next: independent tester and reviewer for Stage 15, then a fresh cold run (cold-32) only with the user's go-ahead; human review of the cold-27 through cold-31 renders and of the L07 gap.
- [x] 2026-11-04 Stage 15 ACCEPTED at `8af759ad2ac9866d9ef08b82fae49136f9cc068f` (code `289530e`; tester PASS: lint rc 0, backend 3087 passed, vitest 80, e2e 4/4, concurrency test 5/5, no sleep; reviewer ACCEPT with nits: no P0–P2, 8 mutation checks with 7 caught and 1 equivalent, replay byte-identical, hashes match).
- [x] 2026-11-04 Stage 15b implemented in `11df4c61a829dc80f24929013019d6aff88f2d45`, pending independent tester and reviewer (user decision "Add: drop to manual review"): routing policy `quality-gate-risk-routing-v7` — after the twin union and before Top-N, a non-risk row still `selected` whose identical interval has a risk-discovery twin carrying an `AUTO_BLOCKING_RISK_TAGS` tag becomes `manual_review` with the Python-only prefix "Deterministic risk-twin review: " (source twins and tags recorded in the reason, no tag copied); shared helper `risk_twin_review` also drives the new manifest diagnostic `risk_twin_review_downgrades` and its `validate_against` cross-check. Reviewer P3s: v6 trade-off stated precisely, Boundary Review duration test reconciled with the `material_interruption` threshold, `main.md`/`global_audit.md` long lines re-wrapped, no-op filter removed, `final_profile_rows` reused, cold-30 replay note reconciled. Every `main.md`-loading stage hash changed (table in `STATUS.md`). Offline replay identical to v6 (cold-27 PASS 95.0, warm-28 FAIL 95.0, warm-29b PASS 95.0, cold-30 FAIL 92.5, cold-31 PASS 92.5; downgrade diagnostic 0/0 in every run). Self-check: lint rc 0, targeted pytest 322 passed, 12/12 mutations caught.
- [x] (Historical next step; Stage 15b accepted, cold-32 started, and Stage 15c followed, below.) Next: independent tester and reviewer for Stage 15b, then a fresh cold run (cold-32) only with the user's go-ahead; human review of the cold-27 through cold-31 renders and of the L07 gap.
- [x] 2026-11-04 Stage 15b ACCEPTED at `e960414b381d6086151f8fe0572feb5d2b8784f9` (code `11df4c6`; tester PASS: lint rc 0, backend 3101 passed, vitest 80, e2e 4/4, concurrency test 5/5, no sleep; reviewer ACCEPT with nits: no P0–P2, 8 of 9 independent mutations caught (R5b, a service diagnostic computed as `len(sources)`, survived), replay byte-identical, every documented hash matches).
- [x] 2026-11-04 cold-32 (fresh cold run, real Claude CLI) started at `e960414` (routing v7); result pending, not evidence for Stage 15c.
- [x] 2026-11-04 Stage 15c implemented in `b026c64b42fb92e66841150d69d8167655b99c61`, pending independent tester and reviewer (user decision "when a risk twin has a high-risk tag, its twin can't be auto-published"): routing policy `quality-gate-risk-routing-v8` — risk-twin review downgrades ANY row still `selected` after the twin union, a risk-discovery record included, whose identical interval has a DIFFERENT risk-discovery record carrying an `AUTO_BLOCKING_RISK_TAGS` tag (never its own source); position, prefix, diagnostic and `validate_against` unchanged through `risk_twin_review`. Reviewer nit 2: a service test now catches mutation R5b. Nit 3 (a selected row next to a non-risk twin with an automatic-blocking tag is not downgraded; risk tags have never been shared between non-risk twins) is an accepted residual. No prompt, hash, algorithm version or cache-key change. Offline replay identical to v7 (cold-27 PASS 95.0, warm-28 FAIL 95.0, warm-29b PASS 95.0, cold-30 FAIL 92.5, cold-31 PASS 92.5; downgrades 0/0). Self-check: ruff/mypy clean, targeted pytest 325 passed, full backend 3103 passed, 1 failed (`test_stage_runner.py::test_running_stage_observes_durable_cancel_and_acknowledges_it`, a 3 s/5 s thread-wait test in code this stage does not touch, run while cold-32 loaded the host; it and its module pass in isolation, 3 passed), 13/13 mutations caught.
- [ ] Next: independent tester and reviewer for Stage 15c; record the cold-32 result; human review of the cold-27 through cold-31 renders and of the L07 gap.
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
- 2026-10-30 (Controller decision, Stage 13c, supersedes the keep-order part
  of the entry above): the audit fallback keep order is no persisted
  Discovery gated flag → shorter duration → more resolved duplicates →
  earlier start → smaller ID. Rationale: representative-first kept the 169 s
  `ml0007…core` (cause of warm-28's N07 padding FAIL) and blocked the 142 s
  L04 match under a forced fallback; the user-approved dedup policy is "keep
  the shortest independently complete version", and a duplicate count is
  only a proxy. The P2-A orphan risk is accepted; orphans are recorded,
  never promoted.
- 2026-10-30 (Controller decisions after warm-29, Stage 13d): (1) when
  validation is exhausted after repair and regeneration in any stage, a
  typed error carries every attempt's structured output, error and provider
  call records, and the service writes `failed-<profile>-<stage>.json`, a
  partial `provider-calls.json` and a failure manifest to the run directory
  only (never the cache), then re-raises; (2) validator messages name the
  candidate IDs, current status, duplicate target and allowed statuses, and
  report every violation at once where feasible; (3) final assembly accepts
  a duplicate as `rejected` or `blocked` for any candidate, matching the
  pair validator (both are non-output); a `selected`/`manual_review`
  duplicate stays a hard error and is never coerced; (4) only
  `global_audit.md` changes: a duplicate ends `rejected` or `blocked`,
  Python blocks only retained rows with gated or persisted flags and never
  changes a rejected row, and a pair whose members both carry persisted
  flags is `distinct_objective` or both become duplicates of a
  non-persisted representative; the stale containment-starts wording is
  fixed in the same edit; (5) check the audit validation order for the
  fallback; (6) the Stage 13c reviewer P3s.
- 2026-11-01 (Stage 13d implementation choices): the typed error is a
  `ValueError` subclass, so existing callers and the CLI keep failing the same
  way; failure evidence is written only when this run created the run
  directory, with the manifest last; a `StructuredProviderError` from the
  repair or regeneration call is not covered (provider failure, not a
  validation exhaustion). When both members of a near-identical pair carry
  persisted flags, the audit prompt asks for both to be `blocked` by the
  audit itself, because the near-identical rule is checked before routing.
  The prefix exemption for fallback-blocked rows moved into
  `reject_reserved_reason_prefixes(..., fallback_blocked=...)` unchanged in
  behavior, so it can be tested directly.
- 2026-11-01 (Stage 13e implementation choices): concurrently exhausted
  units are collected on the run's resolution audit, not by draining the
  executor's futures, so every stage pool is covered without changing its
  control flow; they share the first unit's failure file (same profile and
  stage) under `concurrent_exhausted_units`, because the evidence files are
  write-once. Units that end with any other error stay unlisted. The
  evidence writer catches `Exception` (never `BaseException`), so a
  cancellation still propagates.
- 2026-11-01 (Stage 13d acceptance and warm-29b): the reviewer judged
  Decision 3 legitimate: a blocked duplicate can count as R01/R02 routing,
  exactly like any blocked candidate. warm-29b is warm and diagnostic only;
  acceptance requires a fresh cold run at the final code (cold-30), after
  the Stage 13e reviewer follow-ups are verified.
- 2026-11-01 (user decision after cold-30, Stage 14): option "Padding
  follows BR + prompt". Discovery gated-flag persistence (Stage 13 Fix 1)
  is restricted to structural flags (`material_interruption`,
  `topic_switch_inside`, `topic_not_closed`, `asr_uncertain_blocks_meaning`);
  padding flags (`device_or_waiting_padding`, `sales_or_cta_padding`,
  `padded_with_irrelevant_content`) describe edge material, which Boundary
  Review judges with the surrounding context, so they follow Boundary
  Review. Routing policy `quality-gate-risk-routing-v5`. The microphone /
  demonstration rule moves to the shared `main.md` so every Discovery pass
  sees it. Rationale: the reviewer's replay of four runs found 0 true
  positives and 9 gold-overlapping sole blocks from padding persistence,
  while structural persistence caught the only real N07 problem. Accepted
  risk: a run in which Discovery correctly flags edge padding and both
  Boundary Review and Global Review miss it would output it (observed 0
  times in four runs).
- 2026-11-01 (Stage 14 implementation choices): every gated flag is
  classified (no third class); a module-level check keeps the two classes an
  exact partition of `MANUAL_REVIEW_BLOCKING_QUALITY_FLAGS`. The shared
  padding definition keeps the Boundary Review Profile-minimum test:
  `padded_with_irrelevant_content` may be added to an interior
  `material_interruption`/`topic_switch_inside` when only off-topic
  material meets the minimum, never used instead of it. The Discovery-family
  frozen prompt hashes are re-pinned deliberately (cold Discovery cache).
- 2026-11-02 (Stage 14b implementation choices): the review and risk
  prompts now say what the shared `main.md` says: interior unrelated
  content, including audibility checks, lag and network or playback trouble
  between on-topic cues, is `material_interruption` (or
  `topic_switch_inside`), and padding flags may only accompany it. Because
  every flag involved is gated, routing outcomes do not change; the wording
  only stops a review stage from naming interior trouble with an edge-only
  padding flag that Boundary Review could later clear. The Discovery-family
  pins for coverage_audit and risk_discovery are re-pinned deliberately.
- 2026-11-02 (Stage 14c): review-stage prompt identities (boundary_review,
  global_review, global_audit, both Profiles) and the variant link are now
  pinned by full hash in a test, alongside the frozen Discovery-family pins,
  so a documented hash table cannot drift from the shipped prompts
  unnoticed. Review prompts may still evolve; each change re-pins the test
  and the `STATUS.md` table together. Hashes are always recomputed with
  `load_dual_profile_prompt` (the value the service records).
- 2026-11-04 (user decisions after cold-31, Stage 15): (1) routing option
  "Ignore risk-twin tags": in the same-interval twin union, records of the
  dedicated risk-discovery pass (structural provenance) are no longer flag
  sources; they keep their own flags and status and still receive their
  non-risk twins' flags; non-risk twins share flags as before. Routing
  policy `quality-gate-risk-routing-v6`. Rationale: the risk pass is told
  to preserve and flag interior interruptions of a risk chain so the
  record is routed to `blocked`; in cold-31 that flag (over a one-cue
  viewer thank-you) blocked the clean, gold-exact base twin whose own
  reviews judged the cue harmless. Replays: cold-31 PASS 92.5, the four
  earlier runs unchanged. Accepted trade-off: the Stage 9 invariant "same
  media -> same gated flags" is weakened only in the risk-record ->
  non-risk direction, so a base twin whose own reviews miss a real interior
  interruption that only the risk pass caught is no longer blocked by the
  union (the base twin's own Discovery flags still persist). (2) The
  `material_interruption` threshold ("actually breaks the teaching or claim
  logic"; a brief passed-over audience acknowledgement is neither an
  interruption nor padding) is restored in `main.md` and mirrored in the
  risk and coverage passes, fixing a Stage 14/14b over-broadening. (3) A
  candidate whose central objective is the speaker's own credentials,
  qualifications, pricing, course sales or schedule is rejected in the
  review stages, not merely flagged. Implementation choice: a single helper
  computes the twin rule, the manifest diagnostic counts (candidate, flag)
  pairs not propagated, and `validate_against` re-derives both when the
  risk membership is supplied (the service supplies it; delivery does not).
- 2026-11-04 (Stage 15 reviewer P3-a, precise statement of the v6
  trade-off; user decision "Add: drop to manual review", Stage 15b): risk
  tags were never shared between same-interval twins in any routing
  version. In v3–v5, a risk-discovery twin's gated flag blocked a selected
  non-risk twin only as a side effect of the flag union, and that side
  effect was what kept such a twin from automatic publication when its own
  reviews found no risk; v6 removed it. Stage 15b (routing policy
  `quality-gate-risk-routing-v7`) closes the automatic-publication part: a
  non-risk row still `selected` after the twin union whose identical
  interval has a risk-discovery twin with an automatic-blocking risk tag
  becomes `manual_review` (never `blocked`; tags not copied; prefix
  "Deterministic risk-twin review: "). Position: after the twin union (a row
  blocked by a non-risk twin's flag stays blocked) and before Top-N (Top-N
  ranks only rows that already obey the rule, so no slot is spent on a
  downgraded row and no replacement can violate it). Accepted remainder: a
  base twin whose own reviews miss an interior interruption that only the
  risk pass caught is still not blocked by the union; it reaches a human as
  `manual_review` when the risk twin carries an automatic-blocking tag.
  Implementation choice: the single helper `risk_twin_review` drives
  assembly, the manifest diagnostic `risk_twin_review_downgrades` and its
  `validate_against` cross-check.
- 2026-11-04 (Stage 15b reviewer nit 1; user decision "when a risk twin
  has a high-risk tag, its twin can't be auto-published", Stage 15c):
  routing policy `quality-gate-risk-routing-v8` extends the receivers of
  risk-twin review from non-risk rows to every row, so a `selected`
  risk-discovery record whose identical interval has a DIFFERENT
  risk-discovery record with an automatic-blocking tag also becomes
  `manual_review`; a record is never its own source. Accepted residual
  (nit 3, outside the decision): a selected row next to a NON-risk twin
  with an automatic-blocking tag is not downgraded; risk tags have never
  been shared between non-risk twins, and such a twin is never `selected`
  itself.

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

2026-10-30 (Stage 13c ACCEPTED at `6089884`; warm-29 failed closed): tester
PASS (backend 2986 passed; vitest 80; e2e 4; targeted 255); reviewer ACCEPT
with no P0/P1 (P3s become Stage 13d). warm-29 (real Claude CLI, warm,
diagnostic) at `6089884`:

  - Roots `data/evaluations/dual-profile-benchmark-20261030-claude-warm-29`
    and `data/evaluations/dual-profile-cache-20261030-claude-warm-29` (a
    `cp -Rp` copy of the warm-28 cache, 306 files, byte-identical); pinned
    Claude CLI 2.1.308; attempt start epoch 1793401583; evidence in
    `data/evaluations/dual-profile-strict-eval-20261030-claude-warm-29/evidence/`.
  - eval rc 1 after 263 s in the short Global Audit, the first uncached
    call: `deterministic validation still failed after one repair and one
    regeneration: duplicate candidate must be retained as a rejected audit
    row`. 0 new, 0 removed and 0 changed cache files; no provider-calls,
    manifest or final result; only `discovery-short.json` in the run
    directory. The raw model outputs are unrecoverable (the Claude CLI runs
    without session persistence and the service wrote nothing on failure).
  - Root cause (read-only reconstruction of the short audit payload and
    offline what-if simulations): `validate_nested_pair_decisions` accepts
    a `blocked` duplicate for any candidate and says so in its message,
    while `assemble_final_profile_result` accepts it only for risk-discovery
    records (the short Profile has none). The audit prompt says a candidate
    with persisted flags "will be blocked" without saying a duplicate stays
    rejected, and gives no guidance for the nested pair
    `sh0018_nasal_highnote_diag` ⊃ `sh0018_nasal_highnote_core`, whose
    members both carry persisted flags. A `blocked` non-risk duplicate
    reproduces the exact stderr; the model can oscillate between the two
    messages. The audit fallback handles only `AuditPairRuleError`, and
    this was a plain `ValueError` from the merged-audit assembly check,
    which runs before the pair rules.
  - Decisions: see the 2026-10-30 Controller decisions after warm-29
    (Stage 13d) in the Decisions section.

2026-11-01 (Stage 13d implemented, pending verification): code `6e1152c`
(observability, messages) and the following commit (duplicate-status
alignment, audit prompt, fallback order, P3s). Offline only, on fresh
scratchpad copies of the warm-29 cache (source cache unchanged): sentinel
replay 230 hits and exactly 3 calls; forced-fallback replay 5 near-identical
records and 2 orphans with a byte-identical warm rerun; the analyst's 11
warm-29 what-ifs: 10 accepted (4 at the first attempt, 6 through the
downgrade-only persisted-representative fallback), 1 retained duplicate
fails closed with `failed-short_highlight-global_audit.json`, a partial
`provider-calls.json` and `failure-manifest.json` in the run directory and
the cache untouched (at `6089884`: 7 failed, 4 accepted). Recovery: a
failed real run now leaves its attempts in the run directory; the next
real run needs only the 2 audits and the variant link (the audit hashes
changed; all other entries hit).

2026-11-01 (Stage 13d ACCEPTED at `bc150c5`; warm-29b strict PASS 95.0):
tester PASS (lint rc 0; backend 3000 passed in 1663.46 s; vitest 14/80;
e2e 4; targeted 327); reviewer ACCEPT with no P0/P1 (P2/P3s become Stage
13e). warm-29b (real Claude CLI, warm, diagnostic, not acceptance evidence)
at `bc150c5`:

  - Roots `data/evaluations/dual-profile-benchmark-20261101-claude-warm-29b`
    and `data/evaluations/dual-profile-cache-20261101-claude-warm-29b` (a
    `cp -Rp` copy of the warm-29 cache, 306 files); pinned Claude CLI
    2.1.308; attempt start epoch 1793593441; strict-eval output and evidence
    in `data/evaluations/dual-profile-strict-eval-20261101-claude-warm-29b`.
  - eval rc 0 in 666 s; 230 hits; exactly 3 new calls (short audit 108.5 s,
    mini audit 456.7 s, variant link 48.2 s) plus 1 short-audit repair, 4
    records; 0 retries, no 429/529/limit; tokens in 1,773,780 / out 81,778;
    cache 306 → 309, 0 pre-existing changed, all new files after the start;
    stale 0, `boundary_opening_fallbacks` and `audit_pair_fallbacks` empty,
    `persisted_flag_representative_duplicates` mini 6 / short 0.
  - Strict PASS 95.0 (short 20, mini 25, risk 10, boundary 15, both 15,
    audit 10): short 8/8 (S06 `sh0009_balanced_mix_step5`); mini 5/6 (L07
    missed: exact `precision_yuge…` rejected, `confirm_6001180…` starts
    −30540 ms); R01 blocked, R02 manual_review, no misroutes. Both warm-28
    N07 failures cleared: `audit_sh0009_throat_tight_strong_mix_diagnosis`
    blocked by flag persistence (`topic_switch_inside`); the audit made
    `ml0007_strong_mix_vs_yanyin_core` a rejected near-identical overlap
    duplicate of `audit_ml0008_yanyin_myth_core_chain` (L04 hit, stays
    manual_review), without a fallback.
  - Audit pairs: short 6 (nested 2 dup + 2 distinct; overlap 2 distinct);
    mini 59 (nested 21 dup / 23 distinct; overlap 3 near-identical dup / 10
    distinct; containment 2 near-identical dup). Unflagged manual_review
    rows short 36, mini 16 (warm-28 41/19); twin gated disagreement 0/21.
  - 14 renders rc 0 in 266 s, automatic checks pass; human review and the
    L07 gap listening are pending with the user.
  - Comparison: cold-27 PASS 95.0; warm-26 PASS 97.5; warm-28 FAIL 95.0
    (N07 ×2); warm-29 failed closed; warm-29b PASS 95.0.
  - Recovery: the next step is Stage 13e (Python and tests only; every
    prompt hash and cache key unchanged, so a warm-29b cache-copy replay
    must hit all 233 entries with 0 calls), then cold-30 as the acceptance
    run with the user's go-ahead.

2026-11-01 (cold-30 strict FAIL 92.5; Stage 14 implemented, pending
verification):

- cold-30 (fresh cold run, real Claude CLI at `194ba65`, pinned 2.1.308,
  attempt start epoch 1793597156; acceptance attempt): eval rc 0;
  `cache_hits` 0; 231 calls (Discovery family 158, Boundary Review 52,
  Global Review/Audit 20, variant link 1) plus 3 Boundary Review repairs,
  0 retries, no rate-limit marker; tokens in 10,899,690 / out 1,085,708;
  0 content-identical cache files versus 24 earlier cache roots. Strict
  **FAIL 92.5** (`missing_any_p0_mini_lesson`): short 7/8 (S03 start
  +12440 ms outside tolerance); mini 5/6: L01 missed only because Discovery
  padding-flag persistence blocked the exact candidate
  `precision_ml_0005_breathy_mix_vs_leak_vs_breathy_voice` (cues 690–746),
  and L07 hit for the first time
  (`confirm_high_note_nasal_loop_through_rhinitis_qualification`); R01 and
  R02 blocked; all 8 N07-overlapping candidates blocked or rejected. 12
  renders rc 0, automatic checks pass; human review pending. Roots
  `data/evaluations/dual-profile-{benchmark,cache,strict-eval}-20261101-claude-cold-30`;
  evidence in
  `data/evaluations/dual-profile-strict-eval-20261101-claude-cold-30/evidence/`.
- L01 chain in cold-30: the precision_audit Discovery pass raised
  `device_or_waiting_padding` for cues 694–698 (a brief remark about having
  no sound card and moving closer right before a live vocal demonstration);
  Boundary Review cleared it explicitly without trimming; the initial
  Global Review kept it `manual_review` (80); the Global Audit, seeing
  `persisted_discovery_gated_flags=[device_or_waiting_padding]`, replaced
  the row with `blocked` "to match routing"; v4 persistence would have
  blocked it anyway. The microphone/demonstration exception lived only in
  `stages/discovery.md` and `stages/boundary_review.md`; the
  precision_audit, risk_discovery and coverage_audit passes never loaded it.
- Reviewer replay analysis (read-only, real assembler and strict evaluator
  on stored stage outputs of cold-27, warm-28, warm-29b, cold-30): padding
  flags were the sole blocker on 9 persisted rows, all overlapping gold
  (S04/L01, R01, L07), none overlapping a negative anchor; every true
  padding case was also gated by Boundary or Global Review itself.
  Structural persistence produced the only true positives (the N07
  `topic_switch_inside` short row in warm-28/warm-29b). Policy "structural
  flags persist, padding flags follow Boundary Review" predicted cold-27
  PASS 95.0, warm-28 FAIL 95.0 (unchanged; its mini N07 padding row is
  covered by the Stage 13 pair audit, not persistence), warm-29b PASS 95.0,
  cold-30 PASS 97.5 (L01 hit, mini 6/6).
- User decision (2026-11-01): option "Padding follows BR + prompt" →
  Stage 14.
- **Status: implemented, pending independent tester and reviewer**. Code,
  prompts and tests in `fc31907266ee07485567580f5b125ced76775cfe`; this docs commit follows. Not pushed or
  merged. No evaluator, threshold, benchmark, algorithm version
  (`dual-profile-direct-v1`) or cache-key schema change.
- Routing policy `quality-gate-risk-routing-v5`: Discovery flag persistence
  applies only to `PERSISTED_STRUCTURAL_GATED_FLAGS`
  (`material_interruption`, `topic_switch_inside`, `topic_not_closed`,
  `asr_uncertain_blocks_meaning`), still unless Boundary Review shrank an
  edge, still with the reason prefix "Deterministic flag persistence: ".
  `PADDING_GATED_FLAGS` (`device_or_waiting_padding`,
  `sales_or_cta_padding`, `padded_with_irrelevant_content`) are not
  persisted; they follow Boundary Review and any flag Global Review or the
  audit sets, and still gate when kept. The two classes partition
  `MANUAL_REVIEW_BLOCKING_QUALITY_FLAGS` exactly (checked at import; no
  gated flag is in neither class). `discovery_persisted_flags` remains the
  single function behind final assembly, the audit payload
  `persisted_discovery_gated_flags`, the persisted-flag representative rule,
  the pair fallback keep order and the manifest diagnostic. v1–v4 and
  unmarked artifacts still load.
- Prompts: the shared `main.md` (loaded by every Discovery pass and by
  Boundary Review) now states the microphone/demonstration rule and that
  padding flags describe edge material only (unrelated interior content is
  `material_interruption` or `topic_switch_inside`;
  `padded_with_irrelevant_content` may be added when only off-topic material
  meets the Profile minimum, never instead of the interior flag). The
  duplicate sentence in `stages/discovery.md` is removed; the richer
  Boundary Review wording stays. `global_review.md` and `global_audit.md`
  say that only structural Discovery flags persist and that a candidate is
  not blocked "to match routing" for a padding flag Boundary Review cleared.
  Every stage prompt hash changed (cold cache for all stages):
  - Short Highlight: discovery `c3b72870…`, coverage_audit `e98ed2f7…`,
    precision_audit `1c65af1b…`, precision_confirmation `8bdbe2f6…`,
    risk_discovery `eba1cd91…`, boundary_review `db074ead…`, global_review
    `b84f4e82…`, global_audit `f60fcde6…`.
  - Mini Lesson: discovery `7500e47a…`, coverage_audit `edf10867…`,
    precision_audit `0377c54e…`, precision_confirmation `17eccbac…`,
    risk_discovery `bb219de4…`, boundary_review `c40eadb0…`, global_review
    `cf624569…`, global_audit `bb1a3e32…`.
  - Variant link unchanged (`def25b05…`).
- CLI P3: the bounded exhaustion summary now includes the exception notes
  (for example "failure evidence could not be written: …", truncated to 160
  characters) when the evidence writer itself failed.
- Offline replay (the reviewer's simulator against the Stage 14 code, no
  tracked file touched, no model call): identical to the predicted policy:
  cold-27 PASS 95.0, warm-28 FAIL 95.0 (`irrelevant_padding`,
  `ml0007_strong_mix_vs_yanyin_core`, unchanged), warm-29b PASS 95.0,
  cold-30 PASS 97.5 (L01 hit, mini 6/6). Counterfactual caveats from the
  analysis apply (Global Review/Audit rows written because of persistence
  are reverted to the initial review; a real run re-decides the L07 pair
  group and the prompts changed, so this is routing evidence only, not a
  benchmark pass).
- Recovery: Stage 14 changes every stage prompt hash, so the next real run
  is cold for every stage (about 231 calls). Earlier caches stay valid for
  their own prompt hashes and must not be modified.

2026-11-02 (Stage 14 accepted at `2c088fe`; Stage 14b implemented, pending
verification):

- Stage 14 ACCEPTED at `2c088fe1af349cb4a93502fe10a5ba8769ef9183`: tester
  PASS (lint rc 0, backend 3042 passed, vitest 80, e2e 4/4, concurrency
  test 5/5, no sleep); reviewer ACCEPT with nits (no P0–P2), replay
  unchanged from the prediction above. Stage 13e was ACCEPTED at
  `194ba653b0abd9712bc750eaf2d6aada594a61c3` (backend 3003 passed, vitest
  80, e2e 4, concurrency test 5/5; reviewer ACCEPT with an offline cold
  simulation, no blocker).
- Stage 14b (`9664efe5b14c410984e452e339b7c245db480e14`, prompts and tests
  only) aligns the review and risk prompts with the `main.md` padding-is-edge
  rule and adds the padding-only persisted-set integration test. Changed
  prompt hashes and the unchanged list are in `STATUS.md`.
- Recovery: Stage 14 already changed every stage hash, so cold-31 is cold
  for every stage either way; earlier caches stay valid for their own
  prompt hashes and must not be modified.

2026-11-02 (Stage 14b REJECTED on docs hashes; Stage 14c implemented,
pending verification):

- Reviewer REJECT on `66265e2` (P2, docs only): the Stage 14b hash table in
  `STATUS.md` gave wrong global_review/global_audit values. Stage 14c
  corrects it in place (history noted) and adds a full-hash table recomputed
  with `load_dual_profile_prompt`.
- Stage 14c also applies the reviewer's `boundary_review.md` P3 wording
  nits (boundary_review hashes change for both Profiles) and adds the
  review-stage hash pin test.
- Recovery: cold-31 remains cold for every stage; nothing in Stage 14c
  touches caches, routing or evaluator code.

2026-11-04 (Stage 14c accepted at `867d1cf`; cold-31 strict FAIL 87.5;
Stage 15 implemented, pending verification):

- Stage 14c ACCEPTED at `867d1cf669ffb9d8eccce40ba97d84fd44e016ef` (tester:
  lint rc 0, backend 3056 passed, vitest 80, e2e 4, concurrency test 5/5,
  no sleep; reviewer ACCEPT with nits).
- cold-31 (fresh cold at `867d1cf`): strict FAIL 87.5, L02 lost to the twin
  union (details and the reviewer's analysis in `STATUS.md`). Roots
  `data/evaluations/dual-profile-{benchmark,cache,strict-eval}-20261102-claude-cold-31`
  (ignored, local only).
- Stage 15 (`289530eba3b59f89325ede5c268f9064f8cb5257`): routing v6,
  threshold and self-promotion prompts, tests; offline replay script in the
  session scratchpad (`stage15-sim/replay.py`).
- Recovery: Stage 15 changes every stage hash except the variant link
  (whose payload still depends on the run), so cold-32 is cold; earlier
  caches stay valid for their own prompt hashes and must not be modified.
  v1–v5 artifacts still load; reverting to v5 is a revert of `289530e`.

2026-11-04 (Stage 15 accepted at `8af759a`; Stage 15b implemented, pending
verification):

- Stage 15 ACCEPTED at `8af759ad2ac9866d9ef08b82fae49136f9cc068f` (tester:
  lint rc 0, backend 3087 passed, vitest 80, e2e 4/4, concurrency test 5/5,
  no sleep; reviewer ACCEPT with nits).
- Stage 15b (`11df4c61a829dc80f24929013019d6aff88f2d45`): routing v7
  risk-twin review, reviewer P3 prompt/code/doc fixes, tests; offline replay
  and mutation scripts in the session scratchpad (`stage15b-sim/`).
- Recovery: Stage 15b changes every stage hash that loads `main.md` (the
  variant link is unchanged), so cold-32 is cold; earlier caches stay valid
  for their own prompt hashes and must not be modified. v1–v6 artifacts
  still load; reverting to v6 is a revert of `11df4c6`.

2026-11-04 (Stage 15b accepted at `e960414`; cold-32 started there;
Stage 15c implemented, pending verification):

- Stage 15b ACCEPTED at `e960414b381d6086151f8fe0572feb5d2b8784f9`
  (tester: lint rc 0, backend 3101 passed, vitest 80, e2e 4/4,
  concurrency test 5/5, no sleep; reviewer ACCEPT with nits).
- cold-32 was started at `e960414` (routing v7); result pending.
- Stage 15c (`b026c64b42fb92e66841150d69d8167655b99c61`, branch `claude/liveclip-stage15c`): routing v8
  risk-twin review receivers, R5b service test, tests; replay, hash and
  mutation scripts in the session scratchpad (`stage15c-sim/`).
- Recovery: no prompt hash changes, so every cache (cold-32 included)
  stays valid; v1–v7 artifacts still load; reverting to v7 is a revert
  of `b026c64`.

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
