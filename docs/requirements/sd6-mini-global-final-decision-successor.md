# SD-6 mini Global final-decision successor

## Starting evidence

Formal run `20260915T215821Z-d1ef69c8` is terminal BLOCKED and must never be
resumed or published. Its sealed assurance source fingerprint is
`a0dec4913fece8b40478f2b5710925629d5c34597f5c25d883bb038679fa8fd4`.
That source already contains the intended Global Review Prompt and direct
two-profile regression. Fresh Reviewer found no findings and Tester selected
the fixed `lint`, `e2e` and `test` command IDs.

The first fixed Runner preserved three results. Lint failed with six `RUF001`
findings caused by literal full-width commas in the new Python assertions and
one E501 line. E2E passed in 353.738 seconds. Full test collected 2,471 tests
and showed only passing progress through 24 percent, but the loaded host made
insufficient progress before the fixed 2,400-second command timeout; Runner
terminated it and correctly recorded environment ERROR after 2,450.001
seconds. There is no failed test assertion and no Gateway decision.

Role-visible hashes and exact artifacts are indexed under
`docs/verification/sd6-global-final-successor-handoff/`.

## Authorized scope

The new sole isolated Coder may change exactly:

- `src/liveclip/clipping_skills/semantic_topic_chain_v1/stages/global_review.md`
- `tests/unit/test_semantic_lineage_prompts.py`

The Prompt is already substantively correct. Make the direct regression
lint-safe while preserving all four required clauses, both `general` and
`vocal_coach_live` parameters, the existing assertions and the Prompt bytes.
Changing the Prompt is permitted only if necessary to satisfy the original
final-Boundary contract; unrelated wording changes are forbidden.

Do not change validators, schemas, Python runtime, selection, scores, risks,
quality gates, model settings, retries, budgets, dependencies, Runner timeout,
allowlist, sandbox or Loop control plane. Do not weaken or skip full test.

## Required behavior

Both composed mini Global Review Prompts must continue to say that the supplied
`boundary_reviews` interval is final for this stage; Global decides it
independently; acceptable returns `keep`, otherwise `drop`; and current Global
must neither copy/return `repair_boundary` nor request a second boundary
repair. Existing score, quality, risk, publication, duplicate, evidence and
Top-N rules stay exact.

## Acceptance

Use fresh Planner, one newly recorded Coder, fresh read-only Reviewer and
Tester, the same fixed Runner command IDs and fresh Gateway. Lint, E2E and full
test must all PASS on one sealed source/toolchain. Host-load delay never counts
as PASS; if the fixed Runner again reports ERROR, preserve the successor and do
not publish. Main independently verifies exact session, path scope, baseline
negative behavior, fingerprints, all QA statuses and Gateway PASS before
compare-and-swap publication. This engineering gate implies no real mini
Delivery success.
