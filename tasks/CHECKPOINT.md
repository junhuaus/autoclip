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

