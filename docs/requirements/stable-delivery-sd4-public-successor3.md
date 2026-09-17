# SD-4 C2 third successor: deterministic shared-source concurrency fixture

Continue from terminal BLOCKED `20260914T015534Z-11dec4c4`, sole Coder
`01a09da3-5bc9-7041-9822-dbbe3ab08ff7`. Preserve its Planner READY,
Coder IMPLEMENTED then BLOCKED, Reviewer PASS, Tester READY, Runner lint
PASS `20260914T020528Z-c72d` and test FAIL `20260914T020553Z-7dab`.
The failed `make test` ran 943.041 seconds: 2325 Python passed and one
concurrent-create fixture failed before Web/browser execution. It raised
`FileNotFoundError` because both callers in the test fixture could create
and delete one `synthetic.mp4`. Do not reclassify that FAIL as a product PASS
or append it to the original accepted QA history.

Trusted Main has cloned the exact 2168-path failed assurance source into an
ignored isolated successor, with fingerprint
`fa93ecf59248b6b082f3ef346ba3aa065a014253caaf74c0596f2717f411fc3c`,
same HEAD/toolchain and no input media. Main alone owns the protected
`tests/integration/test_completion_identity.py`, shared contracts, fixture
runner, requirement/docs, original QA and publication. Before formal roles,
Main pre-creates the synthetic source for the one concurrent-create test so
neither thread owns deleting it; ten fresh focused invocations passed. Do
not weaken the assertion that two concurrent same-key calls commit one
project, run, intent, idempotency record and completion task. Preserve other
identity, lost-response, authority and recovery cases.

The fresh sole Coder may edit only
`apps/web/e2e-real/completion-goal-real.spec.ts` and
`tests/integration/test_completion_api_recovery.py` if a concrete finding
requires it. No edit is expected: the prior Reviewer closed all three
offline-observer, page-byte ZIP and project-symlink findings, and the failed
Python run did not reach either browser case. Coder must not alter Main's
concurrency fixture or any other protected file. Planner, Reviewer, Tester
and Gateway are fresh read-only sessions; only the explicit recorded Coder
session may be resumed by the trusted loop, never `--last`.

All C2 predecessor requirements remain in force. Require fresh Reviewer
PASS with no P0/P1 or inherited P2, Tester READY, fixed allowlisted Runner
lint/test PASS on one sealed source/toolchain, and actual Python, Web, Mock
browser, legacy real browser and completion real browser execution. The
completion browser must prove processing after observer closure and before
reconnect, replay the same intent, submit current selection, retain exactly
one bound immutable Delivery, and calculate actual page-response ZIP
SHA-256/size equal to the committed ZIP Asset. Inspect retained ZIP/manifest,
decoded MP4 and SRT, all owned Asset hashes, strict marker/download
identities, lease/deferred evidence and no credential or signed-URL
persistence. A passing suite is insufficient without current artifact
inspection and Gateway PASS.

Independently verify accepted source/path/HEAD/toolchain and QA correlation;
append only the newly accepted Runner QA identities to the original history.
Trusted Main then CAS-publishes the exact full 43-path SD-4 product/test
package, updates API/recovery/Solution/ADR/ExecPlan/STATUS and records an
acceptance report. No real-provider/content/hardware claim or processing of
the read-only `input/8-30.ts` belongs to this engineering gate.
