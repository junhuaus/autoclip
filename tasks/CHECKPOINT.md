# Controller checkpoint — 2026-10-20

Paused by operator request. No code has been changed; this file is the only
addition on the WIP branch.

## Where we are

- Base branch: `claude/liveclip-handoff-20261020`, base HEAD
  `7d2689c1fd99525859369565aa9962979d3e0cc2`. The upstream showed 0/0 at the
  last check; `origin/main` is `ee20d75`.
- WIP branch: `wip/controller-checkpoint-20261020`. Its only commit adds this
  file. It is local only: not pushed, not merged.
- Current candidate: **none yet**. The coder has not been dispatched, so the
  only SHA under evaluation is the base HEAD above.
- Roles run as in-process subagents of the Controller session: coder (the only
  writer), tester (runs tests only), reviewer (read-only). Mock/fixture only:
  no real or paid models, no access to `/Users/junhuaxu/autoclip`, no push or
  merge to main.
- Toolchain: `NODE_LTS_BIN=/opt/homebrew/opt/node@22/bin` (v22.23.2, arm64),
  `PYTHONDONTWRITEBYTECODE=1`.

## Baseline evidence at 7d2689c (tester)

- Precheck: HEAD matched the target and the worktree was clean.
- `make lint` exit 0:
  - ruff: "All checks passed"; 444 files formatted.
  - mypy: 228 files OK.
  - schema check: OK.
  - web `tsc`: OK.
- `make test` exit 0:
  - backend pytest: 2545 passed, 15 warnings (deprecations only) in 1427.92s.
  - Web vitest: 14 files / 80 tests passed.
  - e2e:mock: 1 passed.
  - e2e:real (the script forces the mock AI provider): 3 passed.
- No failures. Post-run worktree still clean; only ignored caches and
  Playwright reports were added.
- Logs (session scratchpad, may not persist):
  `/private/tmp/claude-501/-Users-junhuaxu-autoclip-claude/11442fc6-5e35-49d6-afb1-e25ebe8c47b5/scratchpad/baseline-7d2689c/`

## Last findings (reviewer, same SHA; Controller spot-checked the code)

The benchmark JSON and MD, the evaluators, and their tests are untouched by
the handoff commit. Production code under `src/` and `apps/` hardcodes no gold
timestamps, cue IDs or source hash.

The evaluators are **looser than the benchmark contract**. The retained PASS
of 90.36 (cold-18) was therefore scored by a looser evaluator, and it cannot
be re-scored here because the evidence lives outside this worktree.

P1:

1. `scripts/evaluate_benchmark.py:86-92` (also
   `scripts/evaluate_agent_benchmark.py:84-90`) counts "semantic equivalence"
   as an automatic hit, with edge slack up to `max(2*tol, 10% of gold
   duration)`, about 27 s for L02. The spec allows semantic equivalence only
   by **manual** adjudication (JSON
   `matching.semantic_equivalence_manual_adjudication_allowed`, MD section 9).
   As a result, candidates padded with N06 or N07 can count as hits.
2. Neither evaluator reads `negative_anchors` (N01–N11) or
   `forbidden_composite_intervals`. The direct-FAIL condition
   `irrelevant_padding` is detected only through flags the system sets on
   itself. Note: N09 carries an S08 exception
   (`device_network_and_phone_playback_chaos_with_S08_exception`), and the
   composite intervals allow clean short subclips.
3. RGR-02 is detected only within ±3 s of 2070980–2124380 on both edges. The
   extended version ending at 2160060 can be auto-selected undetected, and
   `required_quality_flags` are never checked.
4. The v1 evaluator never compares `result.source_hash` with
   `benchmark.source.sha256`.
5. The Agent v2 evaluator emits a plain `PASS` under the v1 `benchmark_id` and
   drops several v1 gates (risk routing, a hard RGR-02 failure, the score>75
   and flag gates, the padding check). The acceptance doc
   `docs/requirements/liveclip-agent-runtime-v2-acceptance.md:40,164-185`
   requires the statuses `TECHNICAL_PASS_HUMAN_PENDING`, `TECHNICAL_FAIL` or
   `INVALID_EVIDENCE`. This is already an open gap at
   `docs/exec-plans/liveclip-agent-runtime-v2.md:8617`.

P2:

- The evaluator never emits `CONDITIONAL`.
- The boundary score uses `15*hits/14` instead of the qualified fraction of
  hits.
- The audit score is hardcoded to 10.
- Risk matching ignores evidence cues.
- The benchmark tests are thin (2 tests in
  `tests/unit/test_benchmark_evaluator.py`).

## Next step (Stage 1, not started)

Check out the WIP branch or the base branch and confirm a clean worktree. Then
dispatch the coder to make the evaluators enforce the benchmark **as written**,
without editing `liveclip_dual_profile_benchmark_v1.json` or `.md`:

1. Fix all five P1 items above, plus the P2 items CONDITIONAL, boundary
   formula, computed audit score and risk evidence cues.
2. Derive every rule from JSON fields; nothing may be hardcoded. Honor the N09
   S08 exception and the clean-subclip allowance of the composite intervals.
3. Count semantic-equivalence-only matches as "manual adjudication required",
   never as automatic hits.
4. Add fixture regressions for each gate: RGR-02 extended, source-hash
   mismatch, padding, semantic-only, score exactly 75, risk misrouting, and
   duration 44999/90001.
5. Update the Decision Log in
   `docs/exec-plans/liveclip-dual-profile-benchmark-v1.md`, where the
   2026-09-18 semantic-equivalence decision is superseded, and update
   `STATUS.md`. Record that cold-18 has not been re-scored.
6. The coder commits a checkpoint. The tester (`make lint` + `make test`) and
   the reviewer then check the **same** SHA. Iterate until there are zero P0/P1
   findings and the tests are green.

## Stage 1 accepted at 6c465b7 (2026-10-20)

Stage 1 (benchmark evaluator strictness) is ACCEPTED at
`6c465b767e3829152d0b07451edbe274980321b1` on
`claude/liveclip-stage1-evaluator`. The reviewer returned ACCEPT, and the
independent tester's `make lint` and `make test` were green (mock/fixture
only). Rounds, evidence, open follow-ups and caveats are in the Stage 1
section of `STATUS.md`. Next: operator confirmation of D1--D3 and the
Stage 2 choice. Not pushed.
(Update 2026-10-21: the operator confirmed D1--D3 and chose Stage 2, the
real-browser e2e harness idempotency fix; the semantic-only padding reading
is still pending operator confirmation.)

Branch tip: `claude/liveclip-stage1-evaluator` is `6c465b7` (the accepted
code) plus docs-only commits that record the acceptance, the first being
`87bd6b2`. To verify, run `git diff --name-only 6c465b7..HEAD`; it must list
only `STATUS.md`, `docs/**` and `tasks/**`. The branch is local only and has
no upstream.

## Stage 2 in progress (2026-10-21)

Stage 2 (real-browser e2e harness idempotency) is in progress on local branch
`claude/liveclip-stage2-e2e-harness`, created from `8b4e66c`. The coder has
committed candidate `bae901c` that retains each harness invocation's package in a
fresh identity-bound report scope, so a second `make test` no longer fails on
an earlier run's package and earlier evidence is preserved. It is pending the
independent tester and reviewer on the reported SHA. The operator confirmed
D1--D3 on 2026-10-21; the semantic-only padding reading is still pending.
Details are in the Stage 2 section of `STATUS.md`. Not pushed.

Stage 2 P2 fix round (2026-10-21): `c391ced` passed the tester (lint, two
`make test` runs green) and the reviewer (ACCEPT, 3 P2). The P2 fixes are in
code commit `cfcff0d`, pending tester and reviewer verification. Not pushed.

## Stage 2 accepted at cfcff0d (2026-10-21)

Stage 2 (real-browser e2e harness idempotency) is ACCEPTED at code commit
`cfcff0dbea66cc291456fcecca800ee9c6313dfe`, verified at tip `58cb055`.
- Tester: round r1 was environment-invalid (host sleep during the 30 s-lease
  tests). Round r2 PASS: `make test` twice under `caffeinate -dims`, both
  green.
- Reviewer: ACCEPT, 0 P0/P1.

The Stage 1 harness non-idempotency follow-up is resolved.

Correction: the allocation fix takes the identity from the held handle; a
residual window between `mkdir` and `open` remains as an accepted risk.

Open follow-ups are in the Stage 2 section of `STATUS.md`.

Branch tip: `claude/liveclip-stage2-e2e-harness` is `cfcff0d` plus docs-only
commits. `git diff --name-only cfcff0d..HEAD` must list only `STATUS.md`,
`docs/**` and `tasks/**`. Local only; not pushed.

## Stage 3 in progress (2026-10-21)

The operator approved Stage 3 (cleanup) and confirmed the semantic-only
no-padding-allowance reading on 2026-10-21. Stage 3 is in progress on local
branch `claude/liveclip-stage3-cleanup`, created from `e51e353`. Code commit
`ce43f5e` covers three items:
- the single run-directory `lstat`;
- the renamed allocation swap test;
- lease tests that survive host suspend (a 24 h test-only lease, no `src/`
  change).

It is pending the independent tester and reviewer. Details are in the
Stage 3 section of `STATUS.md`. Not pushed.

## Stage 3 accepted at ce43f5e (2026-10-21)

Stage 3 (cleanup) is ACCEPTED at code commit `ce43f5e`.
- Tester at `2421df3`: `make test` twice under `caffeinate`, both green.
- Reviewer: ACCEPT, 0 P0/P1, 3 P2.

The P2s are fixed in test-only commit `f51f696`, which is verified with the
Stage 4 round.

Operator authorizations on 2026-10-21:
- Real pipeline runs need no per-run consent (Codex CLI and local ASR,
  nothing paid).
- Local assets may be copied from `/Users/junhuaxu/autoclip` into ignored
  paths.
- Push and merge still need explicit consent.

Details are in `STATUS.md`. Not pushed.

## Stage 4 in progress (2026-10-21)

Stage 4 (benchmark evaluator rules: operator decisions A and B, both
confirmed) is on local branch `claude/liveclip-stage4-evaluator-rules`,
rebased onto Stage 3 tip `427e80c`. The code commits are `2c4de9a`,
`0440c17` and `8b14aa3`.

The reviewer accepted round 2. Acceptance on the rebased tip is pending.

Cold-18 re-scores FAIL 90.0:
- short 6/8;
- mini 5/6, with L07 missed;
- `irrelevant_padding` (`ml_0005`) and `negative_anchor_output` (two N09
  candidates).

Details are in `STATUS.md`. Not pushed.

## Stage 4 accepted at 8b14aa3 (2026-10-22)

Stage 4 (benchmark evaluator rules) is ACCEPTED at code commit `8b14aa3`,
verified at tip `ca80fb7`.
- Tester r1: lint 0; 126 benchmark tests passed; the cold-18 re-score FAIL
  90.0 matched exactly with hash-identical inputs. Run #1 passed (2668
  backend); run #2 was invalidated by a clamshell sleep on battery.
- Tester r2 on AC: two `make test` runs, both exit 0, 2668 backend each,
  vitest 80/80, e2e 4/4 each; lease set 39 passed x 3; 0 sleep events; 1143
  report files hash-identical.
- Reviewer: ACCEPT at `ca80fb7`, no findings; the rebase is byte-identical
  to the reviewed code. Stage 3's P2 commit `f51f696` was verified here.

Branch-tip rule: on `claude/liveclip-stage4-evaluator-rules`,
`git diff --name-only 8b14aa3..0bb4af4` lists only `STATUS.md`, `docs/**`
and `tasks/**`. (Corrected 2026-10-22 from `8b14aa3..HEAD`, which holds
only on the Stage 4 branch.) Not pushed.

## Stage 6 in progress (2026-10-21)

(2026-10-22: Stage 6 is ACCEPTED; see the last section.)

Stage 6 (engineering follow-ups) is on local branch
`claude/liveclip-stage6-followups`, based on the Stage 4 docs tip `ca80fb7`.
The code commit is `a22f9d3`; acceptance is pending.

- `LeaseMonitor` renews immediately after a detected wall-clock versus
  monotonic jump; an expired lease is still refused.
- Stage 1 P2-b and P2-c: pinned staging identity, descriptor-based cleanup
  and real-rename rollback tests for the Agent report publication.
- `--output-dir` help documents the symlink restriction.
- Stage 1 P2-5 is kept strict; the operator question is recorded.

Details are in `STATUS.md`. Not pushed.

Stage 6 review round 1: reviewer ACCEPT at `670478e`, 0 P0/P1, 3 P2. Fix
round 2 (code commit `039c998978ac197b12aef18c9f04ca1e6ad16247`) is pending acceptance:
deterministic suspend tests, a remaining-lease renewal rule, and an operator
note on the `--output-dir` restrictions.

Stage 6 review round 2: reviewer ACCEPT at `fc06b3e`, one P2 and one nit.
Fix round 3 (code commit `7de47601a39852aafd2ed93061c11e53a16a7ebc`) is pending acceptance; it
also fixes a false jump from a descheduled monitor thread, found under load.

## Stage 7 in progress (2026-10-21)

(2026-10-22: Stage 7 is ACCEPTED; see the last section.)

Operator directive: the dual-profile understanding engine moves to the local
Claude Code CLI after Codex 429 failures in cold-19 and cold-20. Stage 7 adds
`ClaudeCliStructuredLLMProvider`, selected with
`LIVECLIP_STRUCTURED_PROVIDER=claude-cli`.
- Default model: `claude-opus-5-5`; CLI pinned to `2.1.307`.
- Subscription login only: the child env is allowlisted and API-key logins
  are refused.
- Context isolation without `--bare`.
- Bounded 429/529 backoff that names the real cause.

It is on local branch `claude/liveclip-stage7-claude-cli` (from `ca80fb7`),
code commit `84fe07efda188fcf49008908129f93571a74f0cd`, pending tester and reviewer. `smoke-claude` and
three real Discovery windows passed. The full benchmark was not run. Details
are in `STATUS.md`. Not pushed.

Stage 7 review round 1 (`7340355`): CHANGES_REQUIRED, 2 P1. Fix commit
`fe4350a`:
- per-call subscription check;
- CLI re-reviewed and pinned at 2.1.308;
- `DISABLE_AUTOUPDATER=1` forced;
- all P2s.

It is pending tester and reviewer. The first Claude benchmark uses
`--discovery-concurrency 3`.

Stage 7 review round 2 (`8ca7bba`): ACCEPT with 3 P2s, fixed in round 3
`ad30372`. Before a Claude benchmark:
- freeze the reviewed CLI binary to `.cache/claude-cli/2.1.308/claude`;
- point `LIVECLIP_CLAUDE_EXECUTABLE` at it;
- run doctor and `smoke-claude`;
- use `--discovery-concurrency 3`.

The runbook is in `STATUS.md`.

## Stages 6 and 7 integrated (2026-10-22)

Stages 6 and 7 are rebased onto accepted Stage 4 (`0bb4af4`) on local branch
`claude/liveclip-stage7-claude-cli`, now checked out in the main worktree.
Non-doc diffs are byte-identical to the reviewed ones; one message-only test
commit `fc13163` was added for Stage 6. The frozen Claude CLI 2.1.308 binary
is in the ignored `.cache/`. The scratch worktrees were removed. (History:
pending the integrated test and review round.) Not pushed.

## Stages 6 and 7 accepted at 996962b (2026-10-22)

Stage 6 (code `a22f9d3` rebased to `cef7d4b`..`437ebb8`, plus diagnostics
`fc13163`) and Stage 7 (code through `4e2bf8f`, docs `db2bc32`) are
ACCEPTED, both verified at the integrated tip `996962b`.
- Tester PASS on AC, 0 sleep/wake entries in every window: lint 0;
  `make test` x2 exit 0, backend 2752 passed / 0 failed / 0 skipped each
  (1411.10 s, 1413.74 s), vitest 14 files / 80 tests, e2e 4/4 both runs;
  lease and suspend set 51 x 3; provider tests 76; benchmark tests 130;
  doctor `claude_cli` pass with the frozen path (2.1.308, `claude.ai`,
  subscription true, contract `...d65edfc7...`, 0 email matches); 1323
  report files hash-identical. Logs: `/private/tmp/claude-501/-Users-junhuaxu-autoclip-claude/11442fc6-5e35-49d6-afb1-e25ebe8c47b5/scratchpad/integrated-996962b/`.
- Reviewer ACCEPT at `996962b`: code byte-identical to the reviewed
  commits, no Stage 6 x Stage 7 interaction. Three doc P2s are fixed in
  the following docs-only commit: the Stage 4 tip-rule range, the
  authorization rationale (Claude CLI engine via the claude.ai
  subscription login only; possible charges if paid extra usage is
  enabled), and the isolation canary re-run against the frozen binary (no
  drift; frozen-path `smoke-claude` 4190 ms).

(Historical next step.) The real Claude benchmark cold-21 via the
`STATUS.md` runbook (new roots, frozen binary, `--discovery-concurrency 3`,
strict evaluator), compared with cold-18 (strict FAIL 90.0). Not pushed.

## Stage 8 accepted at 4f2c068 (2026-10-22)

Branch `claude/liveclip-stage8-routing` (from `b3a4fbe`), local only:
F1 `28c9ca1`, F2 `1b18ec1`, F3–F5 `4f2c068`. Tester PASS at `4f2c068`
(lint 0; `make test` x2 exit 0, backend 2778 passed / 0 failed / 0 skipped,
1425.50 s and 1442.41 s; vitest 14/80; e2e 4/4 both; targeted 170; AC, no
sleep). Reviewer ACCEPT, no P0/P1, six P2s. User decisions: the F2
rejected → blocked exception for risk-pass records is approved;
context-only candidates stay blocked. Routing-policy marker
`quality-gate-risk-routing-v2`; Global Audit `nested_pair_decisions`
contract. Real runs (frozen 2.1.308, subscription): cold-21 and warm-23
stopped on the usage limit; warm-22 FAIL 90.0 (F1+F2 replay 95.0); warm-24
FAIL 92.5 with no PASS blockers (diagnostic only). Details in `STATUS.md`.

(Historical next step.) Stage 9, then warm-25 (diagnostic), then a fresh
cold acceptance run right after a subscription usage-limit reset. Not pushed.

## Stage 9 accepted at 56aa93c (2026-10-22)

Branch `claude/liveclip-stage8-routing`, local only: `bfdef3b` (twin
gated-flag union, Top-N risk → blocked, evidence filter, audit-created
pairs), `703cfbb` (review-prompt batch), `56aa93c` (review fix: cache-hit
leniency removed, equipment/audibility carve-out, duration-minimum
wording, softened untranscribed-gap rule, twin-flag comment). Reviewer
round 1 at `703cfbb` CHANGES_REQUIRED (P1 warm-run crash on cached audits;
P2 anchor risks L01/S04, S08, rule C); re-review ACCEPT for
`4f2c068..56aa93c`. Tester PASS at `56aa93c` (lint 0; `make test` x2 exit
0, backend 2790 passed / 0 failed / 0 skipped, 1433.30 s and 1421.72 s;
vitest 14/80; e2e 4/4 both; targeted 182; AC, no sleep). Routing policy v3.

Real diagnostic runs: warm-25 stopped on the usage limit (73 of 75 new
calls cached); warm-26 strict PASS 97.5, no hard failures, no PASS
blockers, short 7/8 (S06 missed), mini 6/6, 13 renders pass automatic
checks, human review pending. Warm runs are diagnostic only (Discovery
from cold-21/warm-22; prompts iterated on this transcript). Scratch
prediction caches are synthetic and must never seed a warm run.

(Historical next step; cold-27 ran.) A fresh acceptance run (method
pending user decision because of the subscription quota), then human
editorial/audio review, then push/merge only with explicit consent. Not
pushed.

## Stage 10 accepted at 0515ef7; cold-27 PASS 95.0 (2026-10-23)

Branch `claude/liveclip-stage8-routing`, local only. Stage 10 code commit
`0515ef7`: render EditPlans (dual-profile and Agent paths) carry
deterministic product text instead of the model `review_reason[:240]` and
title/hook, which had tripped the unchanged `reject_executable_text` guard
on the word "make". Tester PASS at `0515ef7` (lint rc 0; `make test` rc 0,
backend 2792 passed in 1444.08 s; vitest 14/80; e2e mock 1, real
review-delivery 1, completion-goal 2; targeted 25; no sleep). Reviewer
ACCEPT with P2 nits (Agent test mixes "make" with "rm -rf"; no
`manual_review` string coverage) and a user-decided P1 for Stage 11.

cold-27 (real Claude CLI, fresh resumable acceptance attempt at `e173c28`,
`cache_hits` 0, 233 calls, one segment, no usage limit, 3756 s): strict
PASS 95.0, 0 hard failures; short 8/8, mini 5/6 (L07 missed on
`context_dependent_opening`); R01 blocked, R02 `manual_review`. Render
re-run at `0515ef7` into `renders-r2/` (14 clips) passes automatic checks;
the partial `renders/` directory is kept untouched. Human visual/audio
review is PENDING and not claimed. Details in `STATUS.md`.

Next: Stage 11 (guard-safe text in persisted pipeline edit stages), human
review of the renders, optional holdout livestream, the L07/S06 variance;
push/merge only with explicit consent. Not pushed.

## Stage 11 implemented, pending verification (2026-10-29)

Branch `claude/liveclip-stage8-routing`, local only. The Stage 11 code
commit follows docs commit `d6b90c6`. Persisted pipeline edit stages (V5 and
legacy mini-lesson, `semantic_global`/`semantic_windowed`, and the V5
replay) now send guard-tripping Global Review title/hook/reason back through
the existing repair loop once; a rewrite that still trips the unchanged
guard, or a cached/durable output with no repair left, blocks only that
candidate (`deterministic_text_guard_gate`; legacy `semantic_global`:
`rejected` with `deterministic_text_guard_changed_kept_to_rejected`). The
rest of the run completes. Shared validators, guard patterns, dual-profile
prompts/cache keys and benchmark files are unchanged. New tests: 13 unit,
37 integration (mock only). Details in `STATUS.md`.

Next: independent tester and reviewer on the Stage 11 SHA, human review of
the cold-27 renders, then push/merge only with explicit consent. Not pushed.

## Stage 11 accepted at ed24a34 (2026-10-29)

Stage 11 is ACCEPTED at `ed24a346fe0d908dcecdec56ff87d250675a759b` on
`claude/liveclip-stage8-routing` (local only). Tester PASS: `make lint` rc
0; backend 2844 passed / 0 failed / 0 skipped (1629.85 s); vitest 14
files / 80; e2e 4 (mock review-delivery 1, real review-delivery 1,
completion-goal-real 2); targeted 61; `make test` wall time 1851 s; no
sleep 17:29–18:03 PDT. Reviewer ACCEPT, no P0/P1 (independently ran
backend 2844 passed); its P2s become Stage 11b.

The cold-27 strict-eval output
`data/evaluations/dual-profile-strict-eval-20261029-claude-cold-27` is
complete (PASS 95.0); its provenance proof was rebuilt there read-only with
the attempt-start epoch from the runner's report (the original
`attempt-start.txt` was lost). A read-only S06/L07 variance analysis is in
`STATUS.md`: warm-26 vs cold-27 differ only by model sampling; S06 was lost
to a prompt claim that Python enforces every flag (it gates only
`MANUAL_REVIEW_BLOCKING_QUALITY_FLAGS`); L07 was lost to a representative
chosen −30540 ms early across a 27.46 s untranscribed gap. Human listening
of that gap is pending with the user.

Next: Stage 11b (reviewer P2s), Stage 12 (general flag-contract
alignment), human review of the cold-27 renders. Not pushed.

## Stage 11b implemented, pending verification (2026-10-29)

Branch `claude/liveclip-stage8-routing`, local only. Reviewer P2s from
Stage 11: a deferred-only initial Global Review output whose repair call
fails or whose rewrite is hard-invalid now falls back to the initial output
plus the deterministic block/reject gate (durable executor, local V4 loop,
local `semantic_global` helper), with a `repair_fallback` validation event;
the guard repair message names the field and matched token and keeps its
instruction within the legacy 240-character truncation; the v3
`suspicious_exact_top_n` counter is recomputed after demotion. Tests: unit
13 → 21, integration 37 → 58 (mock only). Details in `STATUS.md`.

Next: independent tester and reviewer on the Stage 11b SHA. Not pushed.

## Stage 12 implemented, pending verification; real run pending (2026-10-29)

Branch `claude/liveclip-stage8-routing`, local only, after Stage 11b
`31e6712`. General dual-profile flag-contract alignment (no anchor tuning):
Global Review/Audit prompts list the exact gated flags
(`MANUAL_REVIEW_BLOCKING_QUALITY_FLAGS`) and advisory flags, with a unit test
that keeps them equal to the code; advisory-only coherent candidates go to
`manual_review` with the disagreement stated; Boundary Review must not keep
`context_dependent_opening` with `opening_complete=true` (validation error,
existing repair); stale cached outputs are repaired under a superseding key
instead of crashing; nested-pair `duplicate` is accepted through a shared
representative (three-way clusters). Discovery prompts unchanged. A warm
rerun from the cold-27 cache would make about 73 new calls (Boundary Review
52, Global Review/Audit 20, variant link 1) with 160 Discovery hits.
Details in `STATUS.md`.

Next: independent tester and reviewer on the Stage 11b and Stage 12 SHAs;
a real run only with the user's go-ahead. Not pushed.

## Stages 11b and 12 accepted at 88c97e9 (2026-10-29)

Stage 11b (code `31e6712`) and Stage 12 (code
`88c97e950bd981fe5f63a9c90753b2eb39cb0f60`) are ACCEPTED at the tip
`88c97e9` on `claude/liveclip-stage8-routing` (local only). Tester PASS:
lint rc 0; backend 2886 passed in 1681.85 s; vitest 14/80; e2e 4 passed;
targeted 159; no sleep 18:34–19:11. Reviewer ACCEPT, no P0/P1, five P2s,
which become Stage 12b. Real run still pending the user's go-ahead.

## Stage 12b implemented, pending verification (2026-10-29)

Branch `claude/liveclip-stage8-routing`, local only, on top of the docs
commit that accepted Stages 11b and 12. Reviewer P2s: stale cached
dual-profile outputs fail closed by default again (Stage 9); the repair
under a superseding key is opt-in through `--refresh-stale-cache` and every
resolution plus a count is recorded in `run-manifest.json`; the Boundary
Review invariant error lists every violating ID, with a downgrade-only
fallback (`opening_complete=false`, IDs in the manifest) only when it is
the sole failure left after repair and regeneration. No prompt or
prompt-hash change, so the warm-rerun estimate (about 73 calls) holds.
Details in `STATUS.md`.

Next: independent tester and reviewer on the Stage 12b SHA. Not pushed.


## Stage 12b accepted at a7088c4; warm-28 diagnostic FAIL 95.0 (2026-10-30)

Stage 12b is ACCEPTED at `a7088c490468cb36e48fc60fd512bf6923140593` on
`claude/liveclip-stage8-routing` (local only). Tester PASS: lint rc 0;
backend 2893 passed in 1675.40 s; vitest 14/80; e2e 4; targeted 102; no
sleep 10:34–11:09; high load from an unrelated project, no failures.
Reviewer ACCEPT, no P0/P1; P2-A (opening fallback provenance lost on a warm
cache hit), P2-B (manifest does not cross-check fallbacks/resolutions) and
two P3s become Stage 12c.

warm-28 (real Claude CLI, warm from a byte-verified copy of the cold-27
cache, diagnostic only) at `a7088c4`: eval rc 0 in 2510 s; 160 hits, 73 new
calls plus 4 repairs, 0 retries, 0 pre-existing cache files changed.
Strict FAIL 95.0 (rc 1, no PASS blockers): short 8/8, mini 5/6 (L07
missed), two N07 hard failures (`audit_sh0009…` negative-anchor output,
`ml0007…core` padding). 14 renders pass automatic checks; human review
pending. Root cause: Boundary Review cleared Discovery gated flags without
trimming, and the audit never compares non-nested overlapping pairs.
User decisions (binding): Fix 1 Discovery gated-flag persistence, Fix 2
overlap adjudication at ≥50% of the shorter candidate (Stage 13). Details
in `STATUS.md`.

Next: Stage 12c and Stage 13, then independent tester and reviewer; a real
run only with the user's go-ahead. Not pushed.

## Stage 12c implemented, pending verification (2026-10-30)

Branch `claude/liveclip-stage8-routing`, local only, after the docs commit
that accepted Stage 12b. Reviewer P2-A: opening-fallback cache entries keep
the raw model output plus a verified `conservative_fallback` marker, so a
warm hit re-applies the fallback and reproduces the manifest record (raw
only was rejected: it cannot be told apart from a stale entry that must
fail closed). P2-B: manifest cross-checks for fallback records and stale
resolutions. P3s: `reused=True` after the identity check; untrusted-cache
tests in both refresh modes. No cache-key or prompt change. Details in
`STATUS.md`.

Next: Stage 13, then independent tester and reviewer. Not pushed.

## Stage 13 implemented, pending verification; real run pending (2026-10-30)

Branch `claude/liveclip-stage8-routing`, local only, after Stage 12c. Fix 1:
Discovery gated flags persist unless Boundary Review shrank an edge
(selected/manual_review → blocked, "Deterministic flag persistence: ";
routing policy v4; order validation → persistence → twin union → Top-N →
risk routing/quality gate). Fix 2: the Global Audit also decides
same-Profile overlap pairs at ≥1/2 of the shorter candidate; near-identical
pairs (same end within 3 s/5 s or ≥90%) cannot keep both retained; overlap
duplicates keep a retained representative. Only `global_audit.md` changed.
Offline warm-28 cache-copy replays: Fix 1 alone → 1 call (variant link),
strict FAIL 93.0 offline with every hit kept and the N07 negative-anchor
output blocked; final code → exactly 3 calls (2 audits + variant link).
Details in `STATUS.md`.

Next: independent tester and reviewer on the Stage 12c and Stage 13 SHAs;
a real run only with the user's go-ahead. Not pushed.

## Stages 12c and 13 accepted at b5da41c (2026-10-30)

Stage 12c (code `4a30497`) and Stage 13 (code
`b5da41c7a60dec2f8e05417e64505cafe7dd5547`) are ACCEPTED at the tip
`b5da41c` on `claude/liveclip-stage8-routing` (local only). Tester PASS:
lint rc 0; backend 2953 passed in 1632.59 s; vitest 14/80; e2e 4; targeted
222; no sleep 14:04–14:37. Reviewer ACCEPT, no P0/P1: 16/16 mutants
killed; Fix-1-only replay FAIL 93.0 offline (95.0 post-hoc with real
tokens, identical rows); post-hoc cold-27 PASS 95.0 and warm-26 PASS 97.5
unchanged, no hits lost; evaluator output on cold-27/warm-28
byte-identical. P2s become Stage 13b. P3s: a 1-cue trim on either edge
clears every Discovery gated flag, including end-edge flags (R01 record
1881 → 1882; user told); a stale marked fallback entry cannot be refreshed
under `--refresh-stale-cache` (deliberate). Real run still pending.

## Stage 13b implemented, pending verification; real run pending (2026-10-30)

Branch `claude/liveclip-stage8-routing`, local only, after the docs commit
that accepted Stages 12c and 13. Reviewer P2s: audit candidates carry
their persisted Discovery gated flags (same function as routing) and a
duplicate may not resolve to such a representative; a downgrade-only
Global Audit fallback (only when the deterministic pair rules are the sole
failures after repair and regeneration) blocks the longer member of each
near-identical pair while keeping a retained partner, accepts
representative-rule violations unchanged, records everything in
`audit_pair_fallbacks` and round-trips through the cache marker; near-copy
containment pairs are listed as near-identical. Only `global_audit.md`
changed; a warm-28 cache-copy replay still needs exactly 3 calls. Details
in `STATUS.md`.

Next: independent tester and reviewer on the Stage 13b SHA; a real run only
with the user's go-ahead. Not pushed.

## Stage 13b accepted at e48f601 (2026-10-30)

Stage 13b is ACCEPTED at `e48f6018bc9456278585ca1f63f0d0c225834697` on
`claude/liveclip-stage8-routing` (local only). Tester PASS: lint rc 0;
backend 2976 passed in 1632.67 s; vitest 14/80; e2e 4; targeted 245; no
sleep 14:49–15:22. Reviewer ACCEPT, no P0/P1: 23/27 mutants killed;
Deviation 3 (accept representative-rule duplicates unchanged) endorsed;
sentinel replay 230 hits and exactly 3 calls, no fail-closed; a
forced-fallback cold → warm replay byte-identical. Follow-ups and a
containment-criteria correction become Stage 13c, which must land before
the real run. Real run still pending.

## Stage 13c implemented, pending verification; real run pending (2026-10-30)

Branch `claude/liveclip-stage8-routing`, local only, after the docs commit
that accepted Stage 13b. Python only (audit prompt hash and cache keys
unchanged; 3-call estimate holds); must land before the real run. The audit
fallback keeps representatives first (superseded, see below) and records unavoidable orphans and
every resolved pair; containment near-copy listing follows the user
decision exactly (inner ≥ 9/10 or ends within tolerance; the starts
criterion is removed as a Controller correction); Python-only reason
prefixes are reserved and reverse-checked; a manifest diagnostic counts
Global Review-level duplicates of persisted-flag representatives. Offline:
exactly 3 calls; forced fallback has no unrecorded orphan and a
byte-identical warm rerun. Open trade-off: under a forced fallback,
representative-first keeps `ml0007…core` over the L04 match. Details in
`STATUS.md`. (Resolved in the second 13c commit by the Controller decision
"length before representative count": the forced fallback now keeps the L04
match and records the 2 orphaned duplicates of `ml0007…core`.)

Next: independent tester and reviewer on the Stage 13c SHA; a real run only
with the user's go-ahead. Not pushed.

## Stage 13c accepted at 6089884; warm-29 failed closed (2026-10-30)

Stage 13c is ACCEPTED at `608988463c9e98a7eb861e28a5a80360ea29366d` on
`claude/liveclip-stage8-routing` (local only). Tester PASS: backend 2986,
vitest 80, e2e 4, targeted 255. Reviewer ACCEPT, no P0/P1; P3s (stale
"representatives first" wording, reserved-prefix and fallback test gaps)
become Stage 13d.

warm-29 (real Claude CLI at `6089884`, pinned 2.1.308, warm from a
byte-identical copy of the warm-28 cache, 306 files; attempt start epoch
1793401583) FAILED CLOSED after 263 s in the short Global Audit:
`deterministic validation still failed after one repair and one
regeneration: duplicate candidate must be retained as a rejected audit
row`. No provider-calls, manifest or new cache file; raw outputs
unrecoverable. Root cause: the pair validator accepts a `blocked` duplicate
for any candidate while final assembly accepts it only for risk-discovery
records, and the audit prompt gives no guidance for a pair whose members
both carry persisted flags; the audit fallback never saw the plain
`ValueError`. Controller decisions (Stage 13d) in `STATUS.md`.

Next: Stage 13d, then independent tester and reviewer; a real run only
with the user's go-ahead. Not pushed.

## Stage 13d implemented, pending verification; real run pending (2026-11-01)

Branch `claude/liveclip-stage8-routing`, local only, after the docs commit
`56690c0`. Code `6e1152c` (failure observability and validator messages,
Python only) and the following commit (duplicate-status alignment, audit
prompt, fallback order, Stage 13c reviewer P3s). A validation exhaustion now
writes `failed-<profile>-<stage>.json`, a partial `provider-calls.json` and
`failure-manifest.json` to the run directory only (never the cache); a
duplicate may be `rejected` or `blocked` for any candidate, a retained
duplicate stays a hard error; only `global_audit.md` changed (short
`686a9fbafa60…`, mini `bdb7ff0545a9…`). Offline on warm-29 cache copies:
sentinel 230 hits and exactly 3 calls; the analyst's warm-29 what-ifs 10
accepted, 1 retained duplicate fails closed with run-directory evidence.
Details in `STATUS.md`.

Next: independent tester and reviewer on the Stage 13d SHA; a real run only
with the user's go-ahead. Not pushed.

## Stage 13d accepted at bc150c5; warm-29b strict PASS 95.0 (2026-11-01)

Stage 13d is ACCEPTED at `bc150c5f5fc772f574e09c305ba0d7d5d9991bc9` on
`claude/liveclip-stage8-routing` (local only). Tester PASS: lint rc 0,
backend 3000 passed in 1663.46 s, vitest 14/80, e2e 4, targeted 327, no
sleep 19:50–20:22. Reviewer ACCEPT, no P0/P1: only the Global Audit hashes
changed, 11 of 12 mutants killed, sims reproduced, strict evaluator on
cold-27/warm-28 byte-identical, Decision 3 legitimate. Reviewer P2/P3s
become Stage 13e.

warm-29b (real Claude CLI at `bc150c5`, pinned 2.1.308, warm from a copy of
the warm-29 cache, 306 files; attempt start epoch 1793593441; diagnostic
only, NOT acceptance evidence): eval rc 0 in 666 s; 230 hits, exactly 3 new
calls plus 1 repair; cache 306 → 309, 0 pre-existing changed; no fallback.
Strict PASS 95.0: short 8/8, mini 5/6 (L07 still missed), R01 blocked, R02
manual_review; both warm-28 N07 failures cleared. 14 renders rc 0,
automatic checks pass; human review and the L07 listening pending. Roots
`data/evaluations/dual-profile-{benchmark,cache,strict-eval}-20261101-claude-warm-29b`.

Next: Stage 13e reviewer follow-ups (Python and tests only), independent
verification, then cold-30 (fresh cold run at the final code) as the
acceptance run, only with the user's go-ahead. Not pushed.

## Stage 13e implemented, pending verification (2026-11-01)

Branch `claude/liveclip-stage8-routing`, local only, after the docs commit
`7bf1bb7` (Stage 13d accepted, warm-29b recorded). Python and tests only;
every prompt hash and cache key unchanged versus `bc150c5`. Reviewer P2: the
assembly-only audit probe is a regression test. P3s: the failure-evidence
writer catches any `Exception`; concurrently exhausted units all reach the
failure evidence (`concurrent_exhausted_units`,
`concurrent_failed_subject_ids`, every exhausted unit's records in the
partial `provider-calls.json`); account-identity wording limited to the
Claude CLI provider; `keep_lesson_blocked` merged into `blocked_dup`.
Sentinel replay on a scratchpad copy of the warm-29b cache: 233 hits, 0
calls, outputs byte-identical. Details in `STATUS.md`.

Next: independent tester and reviewer on the Stage 13e SHA, then cold-30 as
the acceptance run, only with the user's go-ahead. Not pushed.
(Historical; Stage 13e was ACCEPTED at `194ba65`, recorded below.)

## cold-30 strict FAIL 92.5; Stage 14 implemented, pending verification (2026-11-01)

cold-30 (fresh cold acceptance attempt, real Claude CLI at `194ba65`,
pinned 2.1.308, attempt start epoch 1793597156): eval rc 0, `cache_hits` 0,
231 calls plus 3 Boundary Review repairs, 0 content-identical cache files
versus 24 earlier roots. Strict FAIL 92.5: short 7/8 (S03 +12440 ms); mini
5/6 with L07 hit for the first time and L01 missed only because Discovery
padding-flag persistence blocked the exact candidate (a `device_or_waiting_padding`
flag from the precision_audit pass on a microphone remark before a live
demo, cleared by Boundary Review without a trim); R01/R02 blocked; all 8
N07-overlapping candidates blocked or rejected. 12 renders rc 0, human
review pending. Evidence
`data/evaluations/dual-profile-strict-eval-20261101-claude-cold-30/evidence/`.

The reviewer's replay showed padding persistence produced 0 true positives
and 9 gold-overlapping sole blocks, while structural persistence caught the
real N07 problem. User decision: "Padding follows BR + prompt".

Stage 14 (`fc31907266ee07485567580f5b125ced76775cfe`, local only): routing policy
`quality-gate-risk-routing-v5` persists only structural Discovery gated
flags; padding flags follow Boundary Review. Shared `main.md` carries the
microphone/demonstration rule and padding = edge material; Global
Review/Audit wording updated; every stage prompt hash changed (cold cache);
CLI exhaustion summary keeps the evidence-writer note; doubled "Stage"
heading fixed. Offline replay: cold-27 PASS 95.0, warm-28 FAIL 95.0
(unchanged), warm-29b PASS 95.0, cold-30 PASS 97.5 (routing evidence only).
Details in `STATUS.md`.

Next: independent tester and reviewer on the Stage 14 SHA, then a fresh cold
run only with the user's go-ahead. Not pushed.
(Historical; Stage 14 was ACCEPTED at `2c088fe`, recorded below.)

## Stage 13e and Stage 14 accepted; Stage 14b implemented, pending verification (2026-11-02)

Stage 13e was ACCEPTED at `194ba653b0abd9712bc750eaf2d6aada594a61c3`
(tester: backend 3003 passed, vitest 80, e2e 4, concurrency test 5/5;
reviewer ACCEPT with an offline cold simulation, no blocker). Stage 14 is
ACCEPTED at `2c088fe1af349cb4a93502fe10a5ba8769ef9183` (tester: lint rc 0,
backend 3042 passed, vitest 80, e2e 4/4, concurrency test 5/5, no sleep;
reviewer ACCEPT with nits, no P0–P2; replay cold-27 PASS 95.0, warm-28 FAIL
95.0 unchanged, warm-29b PASS 95.0, cold-30 PASS 97.5).

Stage 14b (`9664efe5b14c410984e452e339b7c245db480e14`, local only, prompts
and tests): Boundary Review, Global Review and Global Audit call interior
audibility/lag/network/playback trouble `material_interruption` (padding
flags may be added alongside, never instead); Risk Discovery and Coverage
Audit name `material_interruption` (or `topic_switch_inside`) for interior
interruptions of a risk chain. Routing policy stays
`quality-gate-risk-routing-v5`; gate semantics unchanged. Changed hashes
(both Profiles): coverage_audit, risk_discovery, boundary_review,
global_review, global_audit; unchanged: discovery, precision_audit,
precision_confirmation, variant link. New integration test for a
padding-only Discovery-flagged candidate (empty persisted set, validates
like an unflagged candidate). Details in `STATUS.md`.

Next (historical; Stage 14b REJECTED below): independent tester and
reviewer on the Stage 14b SHA, then cold-31 (fresh cold run) only with the
user's go-ahead. Not pushed.

## Stage 14b rejected (docs hashes); Stage 14c implemented, pending verification (2026-11-02)

Reviewer REJECT on docs commit `66265e2e79d36a08e98e46c857ae71a490da2049`
(P2, docs only): the `STATUS.md` Stage 14b hash table listed
intermediate-draft global_review/global_audit hashes for both Profiles.
Code at `9664efe` was unaffected.

Stage 14c (local only, prompt, test and docs): `boundary_review.md`
cross-references interior audibility/lag/playback trouble as
`material_interruption` and says interior chat kept for duration flags
`padded_with_irrelevant_content` alongside the interior flag, never instead
(boundary_review hashes change for both Profiles; all others unchanged). New
test `test_review_stage_prompt_identities_match_pins` pins the full
service-recorded review-stage and variant-link hashes. The Stage 14b hash
table is corrected and a full Stage 14c table is in `STATUS.md`. Routing
policy stays `quality-gate-risk-routing-v5`; gate semantics unchanged.
Self-check: lint rc 0, targeted pytest 277 passed.

Next: independent tester and reviewer on the Stage 14c SHA, then cold-31
(fresh cold run) only with the user's go-ahead. Not pushed.
(Historical; Stage 14c was ACCEPTED at `867d1cf`, recorded below.)

## Stage 14c accepted; cold-31 strict FAIL 87.5; Stage 15 implemented, pending verification (2026-11-02/04)

Stage 14c was ACCEPTED at `867d1cf669ffb9d8eccce40ba97d84fd44e016ef`
(tester: lint rc 0, backend 3056 passed, vitest 80, e2e 4, concurrency test
5/5, no sleep; reviewer ACCEPT with nits).

cold-31 (fresh cold at `867d1cf`, pinned 2.1.308, attempt start epoch
1793609949): eval rc 0, 242 provider records, `cache_hits` 0, 0
content-identical cache files versus 25 earlier roots, every prompt hash =
Stage 14c. Strict FAIL 87.5 (`missing_any_p0_mini_lesson`: L02): short 7/8
(S03 miss); mini 4/6 (L01/L03/L04/L05 hit; L02's exact clean base candidate
blocked only by the Stage 9 twin union copying `material_interruption` from
its risk-discovery twin, a flag over a one-cue viewer thank-you; L07 missed
by representative-choice variance); R01/R02 blocked; all N07-overlapping
rows blocked; N08 `manual_review` informational. 11 renders rc 0, human
review pending. Evidence
`data/evaluations/dual-profile-strict-eval-20261102-claude-cold-31/evidence/`.
Reviewer replays: v5/v4/no-persistence all FAIL 87.5; union ignoring
risk-record sources PASS 92.5 with the four earlier runs unchanged. Stage
14/14b wording raised Discovery `material_interruption` counts (mini 55–60
→ 76, short 15–20 → 32).

User decisions: "Ignore risk-twin tags", restore the `material_interruption`
threshold, reject self-promotion as a central objective.

Stage 15 (`289530eba3b59f89325ede5c268f9064f8cb5257`, local only): routing
policy `quality-gate-risk-routing-v6` (risk-discovery records are not flag
sources in the twin union; shared helper `same_interval_twin_flags`; manifest
diagnostic `risk_twin_flags_not_propagated` cross-checked by
`validate_against`); threshold sentence in `main.md`, `risk_discovery.md`,
`coverage_audit.md`, Boundary Review aligned, precision_audit defers to it;
self-promotion rule in Boundary Review, Global Review and Global Audit.
Every stage hash except the variant link changed (table in `STATUS.md`).
Offline replay: cold-27 PASS 95.0, warm-28 FAIL 95.0, warm-29b PASS 95.0,
cold-30 FAIL 92.5 (unchanged versus v5), cold-31 PASS 92.5 (routing evidence
only). Self-check: lint rc 0, targeted pytest 308 passed.

Next: independent tester and reviewer on the Stage 15 SHAs, then cold-32
(fresh cold run) only with the user's go-ahead. Not pushed.
(Historical; Stage 15 was ACCEPTED at `8af759a`, recorded below.)

## Stage 15 accepted; Stage 15b implemented, pending verification (2026-11-04)

Stage 15 was ACCEPTED at `8af759ad2ac9866d9ef08b82fae49136f9cc068f` (code
`289530e`; tester: lint rc 0, backend 3087 passed, vitest 80, e2e 4/4,
concurrency test 5/5, no sleep; reviewer ACCEPT with nits: no P0–P2, 8
mutation checks with 7 caught and 1 equivalent, replay byte-identical,
hashes match).

User decision: "Add: drop to manual review".

Stage 15b (`11df4c61a829dc80f24929013019d6aff88f2d45`, local only): routing
policy `quality-gate-risk-routing-v7` (after the twin union and before Top-N,
a non-risk row still `selected` whose identical interval has a
risk-discovery twin with an automatic-blocking risk tag becomes
`manual_review` with the Python-only prefix "Deterministic risk-twin review:
"; no tag copied; shared helper `risk_twin_review`; manifest diagnostic
`risk_twin_review_downgrades` cross-checked by `validate_against`). Reviewer
P3s: v6 trade-off stated precisely, Boundary Review duration test reconciled
with the `material_interruption` threshold, long prompt lines re-wrapped,
no-op filter removed, `final_profile_rows` reused, cold-30 replay note
reconciled. Every `main.md`-loading stage hash changed (table in
`STATUS.md`). Offline replay identical to v6 (cold-27 PASS 95.0, warm-28 FAIL
95.0, warm-29b PASS 95.0, cold-30 FAIL 92.5, cold-31 PASS 92.5; downgrade
diagnostic 0/0 in every run). Self-check: lint rc 0, targeted pytest 322
passed, 12/12 mutations caught.

Next: independent tester and reviewer on the Stage 15b SHAs, then cold-32
(fresh cold run) only with the user's go-ahead. Not pushed.
(Historical; Stage 15b was ACCEPTED at `e960414`, recorded below.)

## Stage 15b accepted; cold-32 started; Stage 15c implemented, pending verification (2026-11-04)

Stage 15b was ACCEPTED at `e960414b381d6086151f8fe0572feb5d2b8784f9` (code
`11df4c6`; tester: lint rc 0, backend 3101 passed, vitest 80, e2e 4/4,
concurrency test 5/5, no sleep; reviewer ACCEPT with nits: no P0–P2, 8 of
9 independent mutations caught with R5b surviving, replay byte-identical,
hashes match). cold-32 (fresh cold run) was started at `e960414`; its
result is pending.

User decision: "when a risk twin has a high-risk tag, its twin can't be
auto-published".

Stage 15c (`b026c64b42fb92e66841150d69d8167655b99c61`, branch `claude/liveclip-stage15c`, local
only): routing policy `quality-gate-risk-routing-v8` (risk-twin review
downgrades ANY selected row, risk records included, on the identical
interval of a DIFFERENT risk-discovery record with an automatic-blocking
tag; never its own source; same helper, prefix, position, diagnostic and
cross-check). Reviewer nit 2: a service test now catches mutation R5b.
Nit 3 (non-risk tagged twin) is an accepted residual. No prompt, hash,
algorithm version or cache-key change. Offline replay identical to v7 for
cold-27, warm-28, warm-29b, cold-30 and cold-31. Self-check: ruff/mypy
clean, targeted pytest 325 passed, full backend 3103 passed, 1 failed (`test_stage_runner.py::test_running_stage_observes_durable_cancel_and_acknowledges_it`, a 3 s/5 s thread-wait test in code this stage does not touch, run while cold-32 loaded the host; it and its module pass in isolation, 3 passed), 12/12
mutations caught (originally recorded as 13/13; the script runs twelve).

Next: independent tester and reviewer on the Stage 15c SHAs; record the
cold-32 result. Not pushed.

(Historical; cold-32 was interrupted and Stage 15c integrated, recorded below.)

## cold-32 interrupted; Stage 15c integrated and re-verified (2026-11-04)

cold-32 (started at `e960414`, routing v7, real Claude CLI) was **interrupted by a machine sleep**: the lid was closed and the charger unplugged at 15:56 PST; the evaluation exited rc 1 at 16:37 with stderr only "structured model output could not be validated" and no `failed-*.json` was written. The `short_highlight` stage cache (discovery, coverage_audit, boundary_review, global_review) is preserved. The run is **environment-invalid** (no benchmark result, no evidence for or against any stage); a continuation run **cold-32b** on the preserved cache is planned.

Stage 15c (`b026c64`, docs `c99d198`) was fast-forwarded into
`claude/liveclip-stage8-routing`; the isolated worktree and the
`claude/liveclip-stage15c` branch were removed. Re-verification after integration (main checkout at `c99d198`, before this docs commit): `make lint` rc 0; targeted pytest (the five files above) 325 passed; all 17 prompt hashes equal the Stage 15b table; mutation script re-run on scratch copies of the main checkout's `src` (`/private/tmp/claude-501/-Users-junhuaxu-autoclip-claude/11442fc6-5e35-49d6-afb1-e25ebe8c47b5/scratchpad/stage15c-sim/mutate_main.py`, `mutation_results_main.txt`): 12 of 12 caught, R5b by `test_service_risk_twin_review_diagnostic_counts_downgrades_not_tagged_twins` and the v7 receiver restriction by three tests; offline replay re-run from the main checkout (`/private/tmp/claude-501/-Users-junhuaxu-autoclip-claude/11442fc6-5e35-49d6-afb1-e25ebe8c47b5/scratchpad/stage15c-sim/replay_main.py`, `replay_output_main.txt`) identical to the table above. Deterministic validation only.

Next: independent tester and reviewer on the Stage 15c SHAs; cold-32b
(continuation on the preserved cache). Not pushed.

(Historical; Stage 15c was ACCEPTED at `b758f71` and Stage 16 followed, recorded below.)

## Stage 15c accepted; cold-32 root cause; cold-32b started; Stage 16 implemented, pending verification (2026-11-04)

Stage 15c was ACCEPTED at `b758f7172f6cecebadb4afc82de502788d26de9e` (code
`b026c64`; tester: lint rc 0, backend 3104 passed, vitest 80, e2e 4/4,
concurrency test 5/5, no sleep in the test window; reviewer ACCEPT: 7 of 7
independent mutations caught, offline replay identical).

cold-32 root cause (reviewer Part B): `short_highlight` Global Review hit two
consecutive wall-clock `PROVIDER_TIMEOUT`s during the machine sleep. The
provider message map reported every unlisted code as "structured model
output could not be validated", and only an exhausted validation wrote
evidence, so no `failed-*.json`, `provider-calls.json` or
`failure-manifest.json` existed and every completed call record was lost
(reviewer P3 nit). The cold-32 cache was verified valid by a read-only check
(99 files). cold-32b (continuation on that cache) was started at `b758f71`;
its result is pending and is not evidence for Stage 16.

Stage 16 (`b1f11ecbea257488815fce3f8636bc853078ba2f`, local branch
`claude/liveclip-stage16`, isolated worktree): provider failures in a unit
become `DualProfileProviderFailureError` and write
`failed-<profile>-<stage>.json` (`provider_failed`), a partial
`provider-calls.json` and `failure-manifest.json` (`provider_failure`) to the
run directory only, concurrent failures of either kind kept together; any
other exception after the run directory exists writes an `unexpected_error`
manifest; always re-raised. Fixed provider messages ("could not be
validated" only for `STRUCTURED_OUTPUT_INVALID`; timeouts name the
configured seconds). `ProcessInterruptedBySleep` /
`PROVIDER_INTERRUPTED_BY_SLEEP` when the wall clock ran more than 60 s ahead
of the monotonic clock and only the wall-clock deadline fired; never
semantically retried. The CLI prints code, stage, profile, subject and
evidence path. No prompt, hash, routing, algorithm-version or cache-key
change. Self-check: ruff/mypy clean, targeted pytest 581 passed, full backend pytest tests 3138 passed (3104 at b758f71 plus 34 new),
12/12 scratch-only mutations caught, 17/17 prompt hashes equal the Stage 15c table.

(Historical next step; the reviewer accepted Stage 16 with nits, Stage 16b
and the cold-32b result follow below.) Next: independent tester and reviewer on the Stage 16 SHAs; record the
cold-32b result. Not pushed.

## Stage 16 reviewer ACCEPT with nits; cold-32b FAIL 92.5; Stage 16b implemented, pending verification (2026-11-04)

Stage 16 (`b1f11ec` code, `58186f5` docs) was fast-forwarded into
`claude/liveclip-stage8-routing` (its worktree is left for the Controller).
Reviewer ACCEPT with nits: no P0–P2; 7 of 8 independent mutations caught
(R7, a regeneration-phase provider failure labelled `repair`, survived).

cold-32b: continuation of cold-32 at `b758f71` (routing `quality-gate-risk-routing-v8`, real Claude CLI): eval rc 0; 99 cache hits from the preserved cold-32 cache plus 182 fresh provider records; 0 sleep during the run; provenance clean (0 content-identical cache files vs 26 other cache roots). Strict **FAIL 92.5**. Hard failures: (1) `missing_any_p0_mini_lesson` (L02): the base `ml_0006_steps_1_to_4_numbered` kept its Discovery `topic_not_closed` flag through structural persistence after Boundary Review cleared it without a trim; Global Review rejected it as a duplicate of its risk twin `risk_curriculum_steps_1_to_4_claim_chain`, and the twin union passed the gated flag to that risk receiver, so the quality gate blocked it; (2) `forbidden_composite_interval` (new): three `ml_0003_*` mini candidates routed `manual_review` overlap 1099200–1351000 ms. Short 7/8 (S03 missed); mini 5/6 (L01, L03, L04, L05, L07 hit); R01 blocked, R02 `manual_review`; every N07/N08-overlapping row blocked or rejected; Discovery `material_interruption` mini 69 / short 21. 12 renders rc 0, human editorial/audio review pending. Evidence `data/evaluations/dual-profile-strict-eval-20261104-claude-cold-32b/evidence/`. Analysis pending.

Stage 16b (`b5d8def745d468863917ae04d1c2d1dd314004c2`) fixes the six P3 nits: regeneration-phase tests (R7
now caught), timing pass-through in the v1 aggregate and stage rewraps,
fixed budget/internal/cancelled messages, a backstop manifest without
exception text, the Darwin `CLOCK_MONOTONIC_RAW` sleep gap, and a bounded
CLI evidence path. No prompt (17/17 hashes equal), routing,
algorithm-version or cache-key change. Self-check: `make lint` rc 0,
targeted pytest 999 passed (29 files), 12/12 scratch-only mutations caught.
Deterministic validation only.

(Historical next step; cold-32b was analysed and Stage 17 follows below;
Stage 16b is verified together with Stage 17.) Next: independent tester and reviewer on the Stage 16b SHAs; cold-32b
analysis; human review of the renders. Push and merge still need explicit
consent.

## cold-32b analysed; Stage 17 implemented, pending verification (2026-11-05)

cold-32b analysis (independent read-only reviewer): L02 is a deterministic
rule contradiction (a persisted Discovery `topic_not_closed` that Boundary
Review cleared without a shrink while attesting all four facts; the audit
representative rule plus the v6 union then blocked the identical-interval
risk twin). The forbidden composite came from the Stage 15 exemption being
applied to interior calls to action, platform prompts, chat reading and
presentation troubleshooting (n = 1). Failure-mode table and fragility
estimate in `STATUS.md`.

User decisions (2026-11-05): "Both" fixes (P-a plus prompt narrowing; P-b'
not approved) and "Freeze, 2 cold PASS in a row".

Stage 17 (`2932b7c15af600a900a8838deed4cfcf08a9c95b`): routing `quality-gate-risk-routing-v9` releases an
attested, Boundary-cleared Discovery `topic_not_closed` on an unshrunk
candidate (interior structural flags unchanged); `main.md` narrows the
exemption to a single-cue passed-over thanks, greeting or name call-out,
mirrored in coverage audit, risk discovery, Boundary Review, Global Review
and Global Audit. 16 of 17 prompt hashes change (table in `STATUS.md`).
+51 tests, 8/8 scratch-only mutations caught, `make lint` rc 0, targeted
494 passed, full backend 3208 passed. Replay: only cold-32b changes (FAIL
97.5, composite only, mini 6/6); no negative-anchor change. Deterministic
validation only; no real model call.

Acceptance policy from Stage 17: after acceptance, code and prompts are
frozen; two consecutive fresh cold strict PASS runs on the frozen SHA are
required; a failed run is analysed before any change; a continuation
segment (cold-Nb) counts as one run. Stage 16b (`b5d8def`) stays pending
verification, together with Stage 17.

(Historical next step; the Stage 17 reviewer accepted with nits, which
became Stage 17b below.) Next: independent tester and reviewer on the Stage 16b and Stage 17 SHAs;
freeze; two fresh cold runs. Not pushed. Push and merge still need explicit
consent.

## Stage 17 reviewer ACCEPT with nits; Stage 17b implemented, pending verification (2026-11-05)

Stage 17 reviewer (Stage 16b + Stage 17 candidate at `66b7555`): ACCEPT
with nits, no P0/P1; 13 of 13 recorded reviewer mutations caught (Stage 16b
A1–A7, including the former R7 survivor; Stage 17 B1–B5 plus a B4 variant);
the reviewer's six-run replay equals the Stage 17 table. P2: "gifts" was
listed as a platform prompt, conflicting with the single-cue thanks
exemption. P3: `risk_discovery` brief-greeting wording; Boundary Review
duration test silent on board-writing and the live-demo remark; imprecise
freeze and fresh-cold definitions.

Stage 17b (`50232af0cb0b0194fb663528b569998a8a2fd79b`): the platform-prompt list reads "requests for
fan badges, follows, likes or gifts, homepage plugs, requests for viewers to
join on microphone" in `main.md`, coverage audit, risk discovery, Boundary
Review and Global Review; every exemption statement (also Global Audit)
includes "a single-cue thanks for a gift or follow"; risk discovery uses the
single-cue wording; Boundary Review's duration test keeps board-writing and
the live-demo equipment remark inside the lesson. 16 of 17 prompt hashes
change (table in `STATUS.md`). Flag contract tests 86 → 102; `make lint` rc
0; targeted 677 passed; full backend 3224 passed (3208 at Stage 17 plus 16 Stage 17b items); six-run replay identical
to Stage 17. Routing v9, algorithm version, cache-key schema and Python
behaviour unchanged. Deterministic validation only; no real model call.

Acceptance policy definitions (user decision unchanged): FROZEN = the
code/prompt tree (empty `git diff <freeze-sha> -- src tests scripts config
tools apps migrations pyproject.toml uv.lock alembic.ini Makefile
liveclip_dual_profile_benchmark_v1.json liveclip_dual_profile_benchmark_v1.md`,
no untracked file there) plus the recorded 17 prompt hashes, routing v9 and
algorithm `dual-profile-direct-v1`; docs-only commits do not reset the
count. Fresh cold = new empty cache root plus provenance check (corrected
at freeze acceptance, reviewer P2: run-manifest `cache_hits == 0` and every
cache file's mtime at or after the attempt start; a continuation copies
only from the immediately previous segment of the same run, with
`cache_hits` equal to the copied entries, carried files byte-identical and
new files' mtimes at or after the segment start; content identity versus
other roots is informational only. The Stage 17b text required 0
content-identical files vs earlier roots). A run aborted by a
provider/environment failure without a strict evaluation counts neither
way; a strict FAIL resets the count. Human editorial/audio review is a
separate evidence category, not part of strict PASS. The freeze SHA is
`50232af0cb0b0194fb663528b569998a8a2fd79b` once its tester and reviewer accept.

(Historical next step; freeze accepted, below.) Next: independent tester and reviewer on `50232af0cb0b0194fb663528b569998a8a2fd79b`; freeze; two
consecutive fresh cold strict PASS runs. Not pushed. Push and merge still
need explicit consent.

## FREEZE ACCEPTED at 50232af (Stage 16b + Stage 17 + Stage 17b) (2026-11-05)

Freeze SHA `50232af0cb0b0194fb663528b569998a8a2fd79b`. Tester at `c5e9f96`:
`make lint` rc 0, backend 3224 passed, vitest 80, e2e 4/4, concurrency 5/5,
media-process 3/3, freeze-diff rc 0; `caffeinate` held for the full suite (a
40 s maintenance sleep occurred only during lint, not under `caffeinate`).
Reviewer: Stage 17 ACCEPT with nits (13/13 mutations, replay identical);
Stage 17b ACCEPT with nits; FREEZE-READY yes (8/8 prompt mutations caught,
prompt hashes = `STATUS.md` = test pins, replay byte-identical).
Consecutive cold strict PASS count: 0/2.

Reviewer P2 (provenance, docs only): a fresh run has run-manifest
`cache_hits == 0`, its cache root is new or empty at start, and every cache
file's mtime is at or after the run's attempt start; a continuation segment
(cold-Nb) has `cache_hits` equal to the number of entries copied from the
immediately previous segment of the same run, every carried file
byte-identical to that segment and every new file's mtime at or after the
segment start; content identity versus other roots is reported for
information only (identical model outputs under identical frozen prompts
legitimately produce identical cache files).

Reviewer P3 (environment pinning): the two counted runs need equal
run-manifest `provider`, `model`, `prompt_hashes`, final-validated routing
policy and algorithm version; the same pinned Claude CLI binary (sha256
`ca923c86ac84b30574a82331a05b6e066c27477a926ceaffe46a845a33e4dd37`, version 2.1.308);
the same effective Settings (no `.env`/`.env.local` override of
`LIVECLIP_CLAUDE_*` model, timeout or attempt settings; record
`ls -la .env .env.local` presence and only the `LIVECLIP_` key names of a
present file, never values). At this commit `.env` is absent and
`.env.local` has no `LIVECLIP_CLAUDE_*` or `LIVECLIP_STRUCTURED_PROVIDER`
key. `.gitignore` is added to the freeze path list.

Accepted residuals (reviewer P3, unchanged by decision): the `main.md` line 8
and `global_review.md` duration-minimum sentences do not restate the
single-cue exemption; the `global_audit.md` exemption lacks "without leaving
the topic". Recorded for a future prompt revision.

(Historical next step; done, below.) Next: cold-33, the first counted fresh cold run, at the frozen tree. Not
pushed. Push and merge still need explicit consent.

## cold-33 strict PASS 92.5 on frozen 50232af (2026-11-05) — consecutive cold strict PASS 1/2

Counted fresh cold run 1 of 2 (real Claude CLI, single segment) at HEAD
`feef1e5`; freeze-diff to `50232af0cb0b0194fb663528b569998a8a2fd79b` (incl. `.gitignore`) rc 0 with
empty porcelain before and after. Eval rc 0, wall 7479 s (05:08:29 to
07:13:08 local), 0 sleep/wake events, AC power throughout. Roots
`data/evaluations/dual-profile-{benchmark,cache,strict-eval}-20261105-claude-cold-33`
(the strict-eval root holds `benchmark-result.json`, `benchmark-report.md`
and `evidence/`).

Strict PASS 92.5: both_profiles 15, short 17.5, mini 25, boundary 15, risk
10, audit 10; no hard failure, PASS blocker, forbidden-composite, padding or
negative-anchor finding; `source_hash_matches` true. Short 7/8 (S03
missed); mini 5/6 (L01, L02, L03, L04, L07 hit; L05 (P1) missed); R01
blocked, R02 `manual_review`; N07, N08 and composites 562000–847000 and
1099200–1351000 have no selected or `manual_review` mini output (the
cold-32b composite is clean).

Provenance (fresh-cold definition met): `cache_hits` 0; roots new at
attempt start; 272 cache files, all mtimes after the start; 0
content-identical files in 28 other roots (informational); every
`prompt_hash` equals the Stage 17b table; stale refresh off. 272 provider
records, all first attempt; 0 repairs, retries or usage-limit markers;
tokens in 10,677,798 / out 2,011,664.

Fingerprint cold-34 must match: CLI 2.1.308 sha256
`ca923c86ac84b30574a82331a05b6e066c27477a926ceaffe46a845a33e4dd37`; model `claude-opus-5-5`; algorithm
`dual-profile-direct-v1`; routing `quality-gate-risk-routing-v9`; Settings
fingerprint sha256 `c81f0ece91debb4f1637ba5eecc3af64a91da256f586917408de458317d170d1`; run
fingerprint sha256 `04f5de6e76150fd763c5669be38aed69a32376097e5c2f874c902f89052b9cc5`; no
`LIVECLIP_CLAUDE_*` override in `.env` or `.env.local`.

Misses (observations only; no patch per the acceptance policy): S03, the
in-tolerance audit row was rejected by Global Review and Global Audit as a
duplicate of `sh_0005_yawn_compare_with_choice` (start +12440 ms), as in
cold-30, cold-31 and cold-32b; L05, all three in-tolerance rows blocked for
`material_interruption` over the suspected pen-failure remark at cues
2337–2340 (cold-32b hit L05; new fragility).

12 renders rc 0, automatic checks pass; human editorial/audio review
pending (separate evidence category).

(Historical next step; done, below.) Next: cold-34 (consecutive run 2 of 2) on the same frozen tree with the
same fingerprint; a cold-Nb continuation counts as one run. Not pushed.
Push and merge still need explicit consent.

## cold-34 strict PASS 92.5 on frozen 50232af (2026-11-05) — consecutive cold strict PASS 2/2; benchmark v1 strict acceptance satisfied

Counted fresh cold run 2 of 2 (real Claude CLI, single segment) at HEAD
`a8ab7cd` (docs-only commits `c5e9f96`, `feef1e5`, `a8ab7cd` on top of the
freeze); freeze-diff to `50232af0cb0b0194fb663528b569998a8a2fd79b` (incl. `.gitignore`) rc 0
with empty porcelain before and after. Eval rc 0, wall 7170 s (07:25:56 to
09:25:26 local), 0 sleep/wake events, AC power throughout. Roots
`data/evaluations/dual-profile-{benchmark,cache,strict-eval}-20261105-claude-cold-34`
(the strict-eval root holds `benchmark-result.json`, `benchmark-report.md`
and `evidence/`).

Strict PASS 92.5: both_profiles 15, short 17.5, mini 25, boundary 15, risk
10, audit 10; no hard failure, PASS blocker, direct-fail condition,
forbidden-composite, padding, negative-anchor, duration or regression
finding; `source_hash_matches` true. Short 7/8 (S03 missed); mini 5/6 (L01,
L02, L03, L04 exact 0/0 ms; L07 0/+1980 ms; L05 (P1) missed); R01 blocked,
R02 `manual_review`, both routed correctly; N07, N08 and composites
562000–847000 and 1099200–1351000 have no selected or `manual_review` mini
output.

Provenance (fresh-cold definition met): `cache_hits` 0; roots absent at
attempt start; 268 cache files, all mtimes after the start; 0
content-identical files in 29 other roots (informational); every
`prompt_hash` equals the Stage 17b table; stale refresh off. 272 provider
records, all first attempt; 0 retries or usage-limit markers; 4 successful
repairs (cold-33: 0); tokens in 10,475,368 / out 1,939,183.

Fingerprint identical to cold-33: CLI 2.1.308 sha256
`ca923c86ac84b30574a82331a05b6e066c27477a926ceaffe46a845a33e4dd37`; model `claude-opus-5-5`; algorithm
`dual-profile-direct-v1`; routing `quality-gate-risk-routing-v9`; Settings
fingerprint sha256 `c81f0ece91debb4f1637ba5eecc3af64a91da256f586917408de458317d170d1`; run
fingerprint sha256 `04f5de6e76150fd763c5669be38aed69a32376097e5c2f874c902f89052b9cc5`. The run manifest, and therefore
the run fingerprint, carries the 14 executed-stage prompt hashes
(short_highlight `precision_audit`, `precision_confirmation` and
`risk_discovery` are not executed); all 14 equal Stage 17b. Separately, all
17 prompt identities recomputed from the tree equal the Stage 17b table
(`evidence/step0-tree-prompt-hashes.txt`). No `LIVECLIP_CLAUDE_*` override
in `.env` or `.env.local`.

Misses (observations only; no patch per the acceptance policy; known
residual fragility for future work, not a defect requiring action now):
S03, Discovery never proposed the full 470–506 span and Global Review and
Global Audit kept the 476–499 duplicate (a different mechanism from cold-33,
where an in-tolerance row existed but was rejected as a duplicate; S03 has
missed in every cold run since cold-30); L05, all in-tolerance rows blocked
for `material_interruption` over the pen-failure remark at cues 2337–2340,
as in cold-33. Discovery `material_interruption` flags mini 92 / short 51
(cold-33: 102/59).

12 renders (7 short, 5 mini) rc 0, automatic checks pass; visual and audio
review pending (separate evidence category).

Consecutive cold strict PASS count 2/2 (cold-33, cold-34): the dual-profile
benchmark v1 acceptance policy (2 consecutive fresh-cold strict PASSes on
the frozen tree) is satisfied, so strict benchmark acceptance is complete.
Still pending as separate acceptance activities: human editorial/audio
review of the renders of cold-27 r2, warm-28, warm-29b, cold-30, cold-31, cold-32b, cold-33 and cold-34, and
the L07 listening check of `input/8-30.ts` 1:40:07–1:40:35. The pending
human review also covers the evaluator's `human_required` check
`title_hook_summary_must_be_source_faithful`, which lists 68 candidate IDs
for cold-33 and 64 for cold-34 (exactly the `manual_review` rows of both
profiles); both runs auto-select 0 candidates in both profiles, so every
short and mini match is `manual_review` (R01 is `blocked`).

Next: that human review and listening check (user). Not pushed or merged
to `main`. Push and merge still need explicit user consent.

## Stage 18 implemented ("L05 only"), pending verification; freeze broken (2026-11-06)

User decision 2026-11-06, "L05 only": a brief, passing remark that a pen or
marker has failed is not `material_interruption`; genuine presentation
troubleshooting (stopping to wait for, test, request or change a pen or
colour, fixing glare, asking whether viewers can see) stays
`material_interruption` even when brief. This partly re-widens the Stage 17
narrowed exemption by explicit user decision. S03 is deferred and measured
only (reviewer root cause: window-ownership edge, shortest-complete
prompts, Discovery variance).

Branch `claude/liveclip-stage18-l05` from `origin/main` `701f540` (tree equal
to `ef07143`). Code commit `f525338ed9427b0fcac9925bac6075d60af13e69`: prompts (`main.md`,
`coverage_audit`, `risk_discovery`, `boundary_review`, `global_review`,
`global_audit`) and tests only; no routing, evaluator, threshold,
short-profile file or Python change. 16 of 17 prompt hashes change (Stage
18b table in `STATUS.md`; variant link unchanged); 13 pins re-pinned. Flag
contract 102 → 119. `make lint` rc 0; targeted 392 passed; prompt-loading
files 1077 passed; full backend 3241 passed (3224 + 17). 5/5 scratch mutations caught.
Evaluator replay of the stored cold-33/cold-34 outputs byte-identical
(PASS 92.5 each). Deterministic validation only; no real model call.

Freeze broken: the `50232af` acceptance (cold-33/cold-34, 2/2) stays the
historical baseline. The Stage 18 tree needs a new freeze SHA (candidate
`f525338ed9427b0fcac9925bac6075d60af13e69` after tester and reviewer accept) and 2 new consecutive
fresh-cold strict PASSes (count 0/2). Per-run watch items: L05 hit;
N07-overlapping mini rows (genuine pen-testing pause) status and
`material_interruption` reasons; composite rows; L04 representative; S01
and S04 offsets; S03 (measured only).

(Historical next step; done, below.) Next: independent tester and reviewer on `f525338ed9427b0fcac9925bac6075d60af13e69`. Not pushed. Push
and merge still need explicit user consent.

## FREEZE ACCEPTED at f525338 (Stage 18) (2026-11-06)

Freeze SHA `f525338ed9427b0fcac9925bac6075d60af13e69`. Tester at `2812985` (freeze-diff to
`f525338` empty): `make lint` rc 0, backend 3241 passed, vitest 80, e2e 4/4,
concurrency 5/5, media-process 3/3, flag contract 3/3 repeats (119 passed
each), no sleep during the suite. Reviewer at `2812985`: ACCEPT with nits,
no P0/P1. Consecutive cold strict PASS count for `f525338`: 0/2.

FROZEN (same path list as for `50232af`, now against `f525338`):
`git diff --quiet f525338 -- src tests scripts config tools apps migrations
pyproject.toml uv.lock alembic.ini Makefile
liveclip_dual_profile_benchmark_v1.json liveclip_dual_profile_benchmark_v1.md
.gitignore` must be 0. Also: the 17 Stage 18b prompt identities (table in
`STATUS.md`); routing `quality-gate-risk-routing-v9`; algorithm
`dual-profile-direct-v1`; the same pinned CLI 2.1.308 (sha256
`ca923c86ac84b30574a82331a05b6e066c27477a926ceaffe46a845a33e4dd37`); the same Settings fingerprint
(sha256 `c81f0ece91debb4f1637ba5eecc3af64a91da256f586917408de458317d170d1`); the same no-override
`.env`/`.env.local` rule; fresh-cold provenance rules as before; a cold-Nb
continuation counts as one run; the run fingerprint is expected to differ
from `04f5de6e76150fd763c5669be38aed69a32376097e5c2f874c902f89052b9cc5` only through `prompt_hashes`.

Per-run watch items (reviewer): (1) L05 in-tolerance rows: status and
`material_interruption` reasons, and whether any reason still cites the pen
remark; (2) N07-overlapping mini rows (1023–1130 / 1023–1172 class, 998–1048
risk row, 1028–1172 row) stay `blocked` or rejected for the pen-testing
pause, with no `irrelevant_padding` or negative-anchor finding, noting
whether any reason invokes the carve-out; (3) composites 562000–847000 and
1099200–1351000: no selected or `manual_review` mini output; (4) L04
representative; (5) S01/S04 offsets; (6) S03 outcome (measured only); (7)
provenance and hashes; (8) Discovery `material_interruption` flag counts
against cold-34 (mini 92 / short 51).

Accepted residuals (reviewer P2, no prompt edit; any prompt edit breaks the
freeze): P2-1 the item list says "wait for, test, request or change" but the
carve-out says "wait for, test or replace" (a passing request for another
pen is ambiguous); P2-3 "The only exemption is…" next to the carve-out
(`main.md:28`, `risk_discovery.md:16`, `coverage_audit.md:34`); P2-4
`global_audit.md` lines 62–72 semicolon-list punctuation; P2-6
edge-position pen remarks. Docs nits fixed: P2-2 (`docs/PRODUCT_SPEC.md`
Stage 18 amendment now "general wording, motivated by the L05 miss"); P2-5
(`STATUS.md` Stage 18 recovery now "the `50232af` frozen-path and prompt
tree; docs differ").

Next: cold-35, the first counted fresh-cold run on `f525338`. Not pushed.
Push and merge still need explicit user consent.
