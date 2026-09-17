# SD-4 C2 successor: authenticated browser completion acceptance

Continue from the exact terminal Coder source of BLOCKED C2
`20260914T010215Z-97882c96`, session
`01a09d75-2fed-7151-9327-fb70859010fa`, copied by trusted Main into the
isolated `c2_successor`. That terminal run is immutable and must not be
resumed. The parent C2 public integration requirement remains in force.
The prior local API and Worker diagnostics are useful context, not acceptance.

Before a fresh sole Coder starts, trusted Main seals its owner files and a
full per-path hash manifest of the blocked final source. Main alone owns
`scripts/e2e_fixture.py`, `scripts/run_real_browser_e2e.sh`,
`apps/web/package.json`, `tests/unit/test_e2e_fixture.py`, shared API DTO/
service/repository/bootstrap files, SOLUTION/ADR/recovery, ExecPlan/STATUS,
QA journals and integration. The Coder may change only
`src/liveclip/api/app.py`, `tests/integration/test_completion_api.py`,
`tests/integration/test_completion_api_recovery.py`, and add
`apps/web/e2e-real/completion-goal-real.spec.ts`. It may leave unchanged
inherited files as appropriate. No concurrent writer touches the sealed
candidate, and the Coder edits only its isolated candidate workspace.

Main has provided a distinct `completion` real-browser fixture scenario.
Keep the historical scenario's exact one-project/nine-task/one-Delivery
checks. The completion scenario uses one project/run/goal, six succeeded
stages, one completion task with deferred lease evidence before manual
selection, one delivery task, one bound v001 Delivery, all committed Asset
hashes, decodable MP4, non-empty SRT, and a verified ZIP/manifest. The
checked-in `make test` path runs both scenarios through the deterministic
Runner allowlist; neither model output nor Coder output supplies executable
commands. Coder sandbox inability to bind localhost is a diagnostic limit,
not a waiver of the fixed Runner/browser gate. Implement the browser case
and report it as pending deterministic execution; do not mark the Coder role
BLOCKED solely because its local sandbox cannot bind localhost. The later
fixed Runner must actually pass the case.

Add one real Playwright browser case that uses the isolated mock source and
actual local API/Worker/FFmpeg runtime. Issue an authenticated new-project
manual-selection goal with explicit JSON enum strings and an idempotency
key. Disconnect observation while the Worker reaches `waiting_selection`,
replay the same key and verify the same intent/run/generation. Submit the
selected current clip revision as a JSON array with the expected version;
poll through a delivered terminal goal. In the browser page context fetch
the returned signed Delivery URL, verify HTTP success, ZIP media type/
disposition and non-empty bytes, then verify replay/read does not create a
second Delivery. The browser need not expose a new Web UI; SD-5 owns the
presets/progress UI. Do not claim a synthetic Mock result is real content
quality evidence.

Strengthen the existing recovery integration check so it does not silently
skip missing committed Asset paths; every current committed Asset must have
an inspected owned file and matching size/hash. Preserve invalid JSON,
changed-source, readiness, authority, stale generation, actor-revocation,
empty selection, cancellation and recovery coverage from the parent C2
requirement. Explicit JSON enum and selected-array wire cases must pass
without loosening DTO strictness. Fresh Planner, Reviewer, Tester, fixed
Runner lint/test and Gateway must correlate with one sealed successor source.
Retain real browser ZIP/evidence, independently inspect source/artifacts,
append only accepted Runner QA requests/reports, then trusted CAS publish
full accepted SD-4 to the original worktree. No paid provider, actual
`input/8-30.ts` processing or unsupported content/hardware claim.
