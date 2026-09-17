# SD-7 release mutation version synchronization

## Problem and user-visible outcome

Formal hermetic-B2 repair run `20260915T002909Z-a9483528` is terminal
BLOCKED. Its fixed Runner lint and standalone E2E passed, and full `make test`
passed 2426 Python and 78 Web tests plus Mock Chrome. The first real-service
release workspace then exposed an existing client race: saving release
settings returned HTTP 200 with authoritative `management_version=2`, but the
card only started an asynchronous list refetch. An immediate, valid click on
“提交发布审核” sent stale `expected_management_version=1`; the server correctly
returned `409 STATE_CONFLICT`. Preserve that failure and the server-side CAS.

After any successful release-item mutation, the next action in that card must
use the exact returned snapshot and management version without depending on
the timing of a background GET. Keep the background refresh for convergence,
signed URL renewal and cross-client updates. Do not retry or conceal a real
409, weaken optimistic concurrency, or invent a client-side version.

## Exact scope and ownership

The new sole isolated Coder may edit only:

- `apps/web/src/ReleaseWorkspace.tsx`
- `apps/web/tests/release-workspace.test.tsx`

The successor inherits the prior reviewed hermetic changes to
`scripts/run_real_browser_e2e.sh` and
`tests/unit/test_b2_synthetic_worker.py`; those files are read-only in this
slice. `scripts/b2_synthetic_worker.py`, API/repository state transitions,
schemas, migrations, dependencies, Runner configuration and credentials must
remain unchanged. Main owns requirements, plans, STATUS, QA integration and
trusted publication. Planner, Reviewer, Tester and Gateway are fresh read-only
sessions. Only the one newly recorded Coder session may write in the isolated
successor; never use `--last`.

## Required behavior and evidence

1. Merge an authoritative successful `ReleaseItemSnapshot` into the existing
   `['releases', project_id]` query data before exposing another card action.
   Preserve the response's surrounding preview-URL map and then invalidate or
   refetch for server convergence.
2. Apply the rule to setting save, approval and status transitions so chained
   actions always consume the last successful server version. Package polling
   and metric behavior must retain their existing contracts.
3. Add a regression where the release-list refetch is deliberately delayed or
   absent: settings save returns version 2 and the immediately following
   approval request must carry version 2. Cover at least one following state
   transition or prove the shared synchronization path rather than adding a
   test-only delay.
4. Keep action pending/error UX coherent. A true stale conflict remains visible
   and does not auto-retry.
5. Fixed deny-default Runner `make lint`, `make e2e` and full `make test` must
   pass from one sealed source/toolchain identity. Real browser evidence must
   include the release flow and retained Completion/B2 packages.
6. Fresh Reviewer has no unresolved P0/P1; semantic Gateway PASS plus complete,
   correlated and unmutated deterministic evidence is required. Publication is
   forbidden before formal DONE and independent audit.

## Recovery

The predecessor Runner failure QA `20260915T004233Z-e801` remains FAIL and is
never relabeled. If this successor fails, preserve its exact run/session/QA
evidence and derive any later successor from the last justified assurance
source. Trusted Main may publish only the final accepted source paths by
compare-and-swap, then must prove ordinary original-worktree `make test`
without shell credential overrides.
