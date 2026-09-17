# SD-6 mini Global final-decision successor 5

## Starting evidence

Formal runs `20260915T215821Z-d1ef69c8`,
`20260915T231518Z-3cc4a9a1`, `20260915T233253Z-b58e24b3`,
`20260916T203659Z-c84d35d7` and `20260916T213742Z-56deb953` are terminal
BLOCKED and unpublished. Successor 4 preserved the authenticated negative
baseline and correct Global Prompt bytes. Planner was READY, the sole Coder
made no changes, Reviewer passed with zero findings, Tester was READY, lint
and E2E passed, and all 2,471 Python tests passed. The Web suite passed 74 of
80 tests but six asynchronous UI tests across five files failed while waiting
for data or exceeded the default five-second test timeout. The exact Coder
correctly returned BLOCKED because frontend test infrastructure was outside
its two-path scope. No Gateway ran and nothing was published.

Trusted Main then reran all five affected Web files against the same sealed
candidate. Four files and 47 tests passed; `review-flow.test.tsx` still failed
because Testing Library's default one-second `findByRole` wait ended while the
workspace was loading. This authenticated focused failure means another
unchanged retry is not permitted.

## Authorized scope

The fresh sole isolated Coder may change exactly:

- `apps/web/tests/setup.ts`
- `apps/web/vite.config.ts`
- `src/liveclip/clipping_skills/semantic_topic_chain_v1/stages/global_review.md`
- `tests/unit/test_semantic_lineage_prompts.py`

Keep the already-correct Global Prompt and its regression unchanged unless an
independently verified defect remains. Repair the Web test infrastructure with
a small, central, bounded async-wait and per-test timeout policy that tolerates
the repository's observed full-suite host load. Do not weaken assertions,
skip tests, serialize the suite, change production UI behavior, edit any of
the five failing test bodies, or change the toolchain, Runner, allowlist,
sandbox, dependencies, model settings, semantic budgets, schemas or runtime.

## Required behavior

Both composed mini Global Review Prompts must continue to state that the
supplied `boundary_reviews` interval is final for this stage; judge it
independently; return `keep` when acceptable and `drop` otherwise; never copy
or return the upstream `repair_boundary`; and never request a second boundary
repair. The Web test environment must keep all existing assertions while
allowing asynchronous mocked requests enough bounded wall time to settle under
the load already observed in fixed Runner execution.

## Acceptance

Fresh Planner, exactly one new isolated Coder, fresh read-only Reviewer and
Tester, fixed Runner `lint`, `e2e`, `test`, and fresh Gateway must all agree on
one sealed source and toolchain. All 2,471 or more Python tests and all 80 or
more Web tests must pass. Main must independently audit all five blocked
parents, the reproduced focused failure, the exact Coder/session/path scope,
authenticated negative-baseline identity, source/toolchain fingerprints, QA
correlation and Gateway PASS before atomic compare-and-swap publication. No
real mini Delivery success is implied.
