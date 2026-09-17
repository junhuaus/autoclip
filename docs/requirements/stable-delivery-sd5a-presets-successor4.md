# SD-5 A successor 4: repair the legacy Mock browser fixture

Formal `20260914T072351Z-e2c8da4b` is terminal BLOCKED with no Gateway
or original publication. Its sole exact Coder session
`01a09ed1-6db0-79b3-b34f-302b3dbd53db` must not be resumed in this
new run; never use `--last`. The three earlier terminal blocked runs also
remain intact. Trusted Main cloned all 2199 frozen source paths
byte-for-byte and restored this successor's QA control baseline from the
1012 accepted original request/report IDs. The failed run's later lint
and test QA IDs remain in its old candidate, not silently promoted into
the new accepted baseline.

Start with role-visible
`docs/verification/sd5a-successor4-failure-index.json`. It hashes the
exact failed Runner test log, request/report, command result, terminal
Coder artifact, fresh Reviewer and Tester artifacts, and the blocked
source clone. The full Runner log is only about 21 KB, with 2349 Python
tests and 70 Web unit tests PASS, then one Mock Chrome E2E FAIL because
its strict route fixture rejected `GET /api/v1/completion-presets`. The
real browser cases did not run in that fixed command. The prior repair
Coder correctly returned BLOCKED with zero edits because its role
workspace omitted the Runner failure log and its write scope excluded
the E2E fixture. This successor makes that precise evidence inspectable
inside the role workspace. Read/count/hash selected files with bounded
output; do not print whole historical manifests or QA reports.

Trusted Main added the missing read-only presets response to
`apps/web/e2e/review-delivery.spec.ts`, using the same two immutable
experimental summaries as the unit fixture. This is the only new source
change from the failed frozen candidate. The
`sd5a-successor4-test-only-browser-binding.json` maps all 498 current
code paths, identifies that one E2E test change and proves all 349
non-test production paths are byte-identical to the predecessor. The
predecessor's binding already proves that its only difference from the
retained manual real-browser code map was the direct API conflict test.
Thus no product runtime code has changed since the disposable manual
mini-lesson lost-response/reload probe. Any new runtime edit requires
fresh current browser evidence before publication.

Before formal freeze, the repaired Mock Chrome case passed 1/1. Both
disposable real browser scenarios also passed independently: the legacy
API/Worker/FFmpeg Delivery flow 1/1, and the manual Completion after
browser disconnect 1/1, with downloaded ZIP hash equal to committed ZIP
and identity-bound temporary fixture cleanup. Local lint/typecheck PASS
is diagnostic only. Fresh formal Planner, sole Coder, read-only Reviewer
and Tester, fixed allowlisted Runner `lint` and `test`, Gateway and
independent sealed-source audit are still mandatory. Tester should
inspect component results separately, including 2349 Python, 70 Web,
one Mock Chrome and both real Chrome cases, rather than trusting an
aggregate exit code.

The bounded product outcome remains authenticated versioned preset
listing, strict high-level create through durable Completion, same-key
replay after lost response/reload, no premature ZIP URL and a newly
created Project visible/openable without dashboard refresh. Low-level
routes keep their historical wire behavior. The sole new Coder may edit
only `apps/web/e2e/review-delivery.spec.ts` if a demonstrated fixture
defect remains. No nonempty diff is required. Any product-code defect
requires a new scoped owner integration and browser proof before formal
acceptance. Main owns shared schemas, migrations, ADR, ExecPlan, STATUS,
QA, failure provenance and final code-only CAS publication. The new
Coder session ID is recorded by the trusted outer process only after
its role returns; new Runner QA IDs arise only after Tester.

No source media or real Project data enters this candidate. Do not use
the previously exposed OpenRouter key, any credential, paid cloud calls
or model-generated commands. Synthetic browser/FFmpeg evidence does not
establish real Chinese content, audio, cloud-provider or Apple hardware
quality. A semantic Gateway PASS cannot override failed, stale, mutated
or uncorrelated Runner evidence or unresolved P0/P1 findings.
