# SD-6 mini Global final-decision successor 4

## Starting evidence

Formal runs `20260915T215821Z-d1ef69c8`,
`20260915T231518Z-3cc4a9a1`, `20260915T233253Z-b58e24b3` and
`20260916T203659Z-c84d35d7` are terminal BLOCKED and unpublished. The fourth
run preserved the authenticated negative baseline and correct product bytes.
Planner was READY, sole Coder `01a0abf3-7ea5-73a3-9234-f7c09fcd8b59` made no
changes, Reviewer passed with zero findings, Tester was READY, lint and E2E
passed, and all 2,471 Python tests passed. The Web suite passed 79 of 80 tests;
`apps/web/tests/review-board.test.tsx:377` could not find `编辑详情` while the
rendered workspace still showed loading states. System load rose above 180
during the run. The exact Coder correctly returned BLOCKED because that path
was outside its two-path scope. No Gateway ran and nothing was published.

Successor 4 starts from the fourth run's sealed assurance product source
fingerprint `a054f8b716108d468251b19a23de4c1f40e5a6a1d2467356695328767c910cae`.
Before formal initialization, trusted Main must run the exact failed Web test
against this successor and record the request/report. A PASS establishes only
that the predecessor failure is not reproducible under the diagnostic load;
it does not override the predecessor FAIL or replace fresh formal full-test
coverage. If the diagnostic fails, do not start formal execution and preserve
the result for a separately authorized frontend repair.

## Authorized scope

The fresh sole isolated Coder may change exactly:

- `src/liveclip/clipping_skills/semantic_topic_chain_v1/stages/global_review.md`
- `tests/unit/test_semantic_lineage_prompts.py`

No product change is expected. Independently verify the Prompt, direct
regression, inherited negative-baseline evidence and predecessor diagnostics.
If and only if a defect remains in those two paths, repair it there. Do not
change the frontend test, product UI, toolchain, Runner, timeout, allowlist,
sandbox, dependency, validator, schema, runtime, selection, score, risk,
quality, retry or budget setting.

## Required behavior

Both composed mini Global Review Prompts must state that the supplied
`boundary_reviews` interval is final for this stage; judge it independently;
return `keep` when acceptable and `drop` otherwise; never copy or return the
upstream `repair_boundary`; and never request a second boundary repair. Keep
all existing editorial gates and both profile cases exact.

## Acceptance

Fresh Planner, one new Coder, fresh read-only Reviewer and Tester, fixed Runner
`lint`, `e2e`, `test`, and fresh Gateway must all agree on one sealed source and
toolchain. All Runner commands and Gateway must PASS. Main independently audits
all four blocked parents, exact Coder/session/path scope, negative-baseline
identity and behavior, diagnostic provenance, source/toolchain fingerprints,
QA correlation and Gateway PASS before atomic compare-and-swap publication.
No real mini Delivery success is implied.
