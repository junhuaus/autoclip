# SD-7 hermetic B2 browser environment

## Problem and user-visible outcome

On the accepted original worktree, `make test` QA
`20260914T235154Z-d6b3` passed 2425 Python tests, 78 Web tests, Mock Chrome,
the legacy real-service Chrome scenario and the durable Completion Chrome
scenario. The final B2 real-service fixture then failed closed before browser
launch. `scripts/run_real_browser_e2e.sh` explicitly selected the Mock
Provider and cleared `OPENAI_API_KEY`, but inherited a nonempty
`OPENROUTER_API_KEY` from the developer's ignored `.env.local`. The dedicated
B2 Worker correctly rejects any disposable Mock fixture carrying either
Provider credential.

Make the checked-in real-browser harness hermetic with respect to both cloud
ASR credentials. An ordinary `make test` must not depend on or use a developer's
local OpenRouter key. Preserve the existing fail-closed Worker validation,
temporary-root identity, source/Asset/package verification, fixed ports,
explicit Mock provider, generated test-only credentials and cleanup behavior.

## Exact scope and ownership

The sole isolated Coder may edit only:

- `scripts/run_real_browser_e2e.sh`
- `tests/unit/test_b2_synthetic_worker.py`

Add the smallest regression that proves the harness explicitly clears both
`OPENAI_API_KEY` and `OPENROUTER_API_KEY` before starting any fixture process.
Do not weaken `scripts/b2_synthetic_worker.py`, change product Provider
readiness, read `.env.local`, expose credential values, alter Runner command
IDs/argv/sandbox, or edit dependencies, migrations, schemas, production
Python/Web code, QA history or generated artifacts.

Main retains ownership of Product Spec, Solution, ADRs, shared plans, STATUS,
QA integration and trusted publication. Planner, Reviewer, Tester and Gateway
are fresh read-only sessions. Only the one recorded Coder session may write or
be resumed, only inside its isolated candidate; never use `--last`.

## Acceptance and evidence

The candidate must satisfy all of the following:

1. Static regression verifies that the E2E harness exports both Provider key
   variables as empty values while retaining `LIVECLIP_AI_PROVIDER=mock`.
2. The B2 Worker continues to reject a fixture if either key is nonempty.
3. Fixed Runner `make lint`, `make e2e` and full `make test` pass from sealed
   source/dependency snapshots under the deny-default macOS sandbox.
4. B2 real Chrome still observes durable phase progress, reconnects without
   driving work, downloads exactly the bound authorized ZIP, and leaves
   retained SQLite/Asset/ZIP/full-MP4 evidence after owned fixture cleanup.
5. Fresh Reviewer has no unresolved P0/P1; semantic Gateway PASS and all
   deterministic evidence correlations are required. Any failed, stale,
   mutated, uncorrelated or missing result blocks publication.
6. Trusted Main may publish only the accepted declared paths by compare-and-swap
   after formal `DONE`. Earlier failed QA remains FAIL and is never relabeled.

## Recovery

If a gate fails, keep the exact run/session/QA evidence and resume only the
recorded Coder session when the state machine permits. Do not work around a
failed candidate by changing the original script. A later original-worktree
rerun uses a new QA ID and proves ordinary `make test` without a shell-level
credential override.
