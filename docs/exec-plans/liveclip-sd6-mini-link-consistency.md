# SD-6B mini Link Review consistency Living ExecPlan

Prepared 2026-09-15. This plan follows `.agent/PLANS.md`, ADR050 and the
real-acceptance plan.

## Purpose / Big Picture

Link Review initial and repair Prompts state the same relationship/boolean
truth table already enforced by `LinkReviewV4`. A structurally inconsistent
relationship can be repaired without changing the Agent's semantic boolean
judgments, weakening validation or adding retries.

## Evidence and scope

QA `20260915T045700Z-mn02` is immutable FAIL. It completed local MLX ASR and
used only 9/64 bounded Codex launches. Two discovery units succeeded after one
repair each; three link units succeeded; one link unit exhausted its single
repair. Both invalid outputs used linking enum `next_step_same_lesson` while
the two booleans were not both true. Evidence is in
`docs/verification/sd6-mini-attempt2-failure.json`.

The isolated Coder may change only the Link Review stage Prompt, the shared V4
repair Prompt and one direct prompt-contract test file. No Python validator,
schema, model, algorithm, retry, guard, security profile or control-plane code
is in scope.

## Progress

- [x] Preserve mini attempts 1 and 2, their counters, databases, outcome Assets
  and FAIL reports.
- [x] Derive the actual fan-out and freeze a finite attempt-2 budget before its
  model calls.
- [x] Isolate the repeated structural contradiction and retain its exact
  initial/repair evidence without transcript or credential disclosure.
- [x] Clone the current delivery source into a fresh candidate with no input,
  model data, Project or prior Loop state.
- [x] Run the self-contained requirement through fresh Planner, sole Coder,
  Reviewer, Tester, fixed Runner and Gateway roles.
- [x] Independently audit formal DONE and publish only accepted Prompt/test
  paths by compare-and-swap.
- [x] Pass focused original prompt/validator regression.
- [x] Freeze each new real mini guard identity and call budget before any new
  inference; preserve the result and inspect a package only if Delivery passes.

## Acceptance

The composed initial Prompt must partition all seven relationship enums into
the exact linking/non-linking sets and tie the set choice to both booleans. The
repair Prompt must give deterministic structural guidance only for the named
contradiction while preserving boolean semantic judgments. Tests must protect
both content and hash identity. Existing validator behavior must stay exact.

Formal lint/e2e/full-test, Reviewer and Gateway must all pass from the same
sealed source/toolchain identity. Semantic prose cannot override failed,
missing, stale, mutated or uncorrelated deterministic evidence.

## Recovery

Formal failure is terminal and unpublished; create a successor from the last
justified assurance source. Rollback restores exact Prompt/test bytes from the
publication receipt. Do not normalize inconsistent output in Python, add a
second repair, reset a consumed guard, use `--last`, expose credentials or run
model inference through the development Runner.

## Outcomes and Retrospective

Formal run `20260915T050655Z-621eb79d` is DONE. Sole Coder
`01a0a379-2003-7d60-8d56-413bb4ec3062` changed exactly the two Prompts and
one direct test authorized above, then resumed by exact session ID to repair
the first fixed-Runner failures. Final lint/E2E/full-test QA
`20260915T175902Z-1271`, `20260915T175955Z-d74f` and
`20260915T180448Z-0f93` passed on source fingerprint
`91967814bb52d65d5403291507f10285ba2aa5145934f75bbcc9e4e9f25ccdf4`;
fresh Reviewer and Gateway passed with zero findings. Trusted Main audited the
complete failure/success lineage, published only the three authorized paths by
compare-and-swap, appended only the accepted Runner QA to Main history and
passed 45 focused postpublication tests. Superseded failures remain FAIL.

Postpublication attempt 4 proved that the original relationship/boolean
contradiction no longer recurred across 13 successful Link Reviews. It still
produced no complete mini candidate above the editorial threshold. Attempt 5
produced two high-scoring candidates but correctly blocked one for a meaning
reversal and exposed a separate Global Review final-Boundary decision gap in
the other. Attempt 6 found no complete closed topic. These are preserved
negative real-content outcomes; none created a Delivery, and none weakens the
accepted SD-6B structural correction.
