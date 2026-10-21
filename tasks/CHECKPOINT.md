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
