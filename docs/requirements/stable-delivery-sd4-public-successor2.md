# SD-4 C2 second successor: correlated browser and owned Asset evidence

Continue from the exact 2164-path final isolated Coder source of terminal
BLOCKED run `20260914T013347Z-dfaec00b`, sole session
`01a09d90-d19c-7e22-9ac2-bf3c3a20be88`, fingerprint
`0af49373e28a8c2f612bbe8196df2b99339bce0b2e798c0cc09bbde5378e66c1`.
Preserve that run, its Reviewer FAIL/Tester BLOCKED findings and empty Runner
results. Do not resume its session or use `--last`. The parent C2 and first
successor requirements remain in force except where this document makes
the evidence contract more precise.

Before the fresh sole Coder edits, trusted Main freezes the protected
`scripts/e2e_fixture.py`, `scripts/run_real_browser_e2e.sh`,
`tests/unit/test_e2e_fixture.py`, shared contracts, STATUS/ExecPlan/recovery,
new requirement and per-path blocked-source baseline. Main alone owns these
files, QA and original publication. The new Coder may change only
`apps/web/e2e-real/completion-goal-real.spec.ts` and
`tests/integration/test_completion_api_recovery.py`. No second writer edits
the sealed candidate or Coder cache. Fresh read-only Planner/Reviewer/
Tester/Gateway and the deterministic allowlisted Runner keep their existing
roles and budgets.

Close all three P2 findings without waiving the old browser case. The
completion runner now exports three trusted fixture paths under its
identity-bound temporary root:

- `LIVECLIP_E2E_OBSERVER_CLOSED_MARKER`: after the original page has actually
  closed, the browser test atomically writes only
  `{schema_version: "liveclip.completion-observer-closed.v1", project_id,
  run_id, intent_id, generation, closed_unix_ms}`. Do not store credentials
  or signed URLs. The protected read-only SQLite watcher checks that this
  goal is still before completed processing, then waits for six succeeded
  stages, `waiting_selection`, one WAITING completion Task and a persisted
  deferred lease attempt. It atomically writes the second marker.
- `LIVECLIP_E2E_WAIT_MARKER`: while the browser remains disconnected, poll
  this file with Node filesystem reads only; do not open a new page, issue
  an API request, execute a subprocess or submit selection before it exists.
  Check its schema `liveclip.completion-waiting.v1`, identities, generation,
  Task/deferred count and close/observation ordering against the created
  goal. Then reconnect, replay the same key, verify no Delivery yet and
  submit the current selected clip revision.
- `LIVECLIP_E2E_DOWNLOAD_RECEIPT`: compute SHA-256 over the **actual bytes
  returned to the page context** by the signed Delivery URL and atomically
  write only `{schema_version: "liveclip.completion-browser-download.v1",
  project_id, run_id, intent_id, delivery_id, observer_closed_unix_ms,
  waiting_observed_unix_ms, response_status, content_type,
  content_disposition, size_bytes, sha256}`. The protected final verifier
  rejects missing/extra fields, wrong identities/order/status/media headers,
  or any byte count/hash different from the bound ZIP Asset. It retains
  safe evidence with the verified synthetic ZIP. Never persist the token or
  signed URL. A signed URL may legitimately rotate on read; compare saved
  Delivery identity rather than exact URL text.

The recovery test must anchor current Asset inspection to the canonical
data root while preserving the unresolved project ID/path components for
`open_pinned_regular_file`, which rejects symlinks in every component.
Inspect every committed Asset, including empty-selection processing assets,
with exact size/hash/MP4/SRT checks. Add a meaningful negative case that
replaces the project directory with a symlink to an external directory
containing matching Asset bytes and proves inspection refuses the escape.
The existing missing-file negative case remains. Do not make a test pass by
catching an unrelated broad exception or skipping an Asset.

Local Coder tests/TypeScript/Ruff are diagnostics. Require fresh Reviewer
PASS with the three P2s closed, Tester READY, fixed Runner lint/test PASS on
one sealed source/toolchain including the legacy and completion real-browser
cases, retained receipt/ZIP/Asset inspection, and Gateway PASS. Independently
verify source and artifact hashes, append only accepted Runner QA identities,
then trusted CAS publish the full SD-4 package to the original worktree.
No real-provider/content/hardware claim or processing of `input/8-30.ts`.
