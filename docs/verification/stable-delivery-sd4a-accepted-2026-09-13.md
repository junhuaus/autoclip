# SD-4 A bounded engineering acceptance — 2026-09-13

Durable completion identity and processing-only reconciliation are accepted in the
isolated SD-4 candidate, not yet published to the original product worktree.
The formal run `20260913T195517Z-dbc6dc0c` reached DONE with Planner READY,
exact Coder `01a09c59-9669-7ae0-ba05-c14f3d76222f` IMPLEMENTED and no source
edits, fresh independent Reviewer PASS without findings, Tester READY, fixed Runner
lint/test PASS and fresh Gateway PASS. Independent deterministic Gateway evaluation
with retained-file verification passed with no reasons. Accepted source fingerprint
`f28edbcdfd9a62543d8d9f4164fe9e597f67a1087daaf5ecc5e7c2aa3cc078c7`,
toolchain fingerprint
`e46a160a0d9059c95463c16cf9010d272516a943bdd70ed3e29f8779ecc9707b`,
HEAD `6009b23859564b2bfdc193eee366afd990b9ef5d`. All 2122 source paths in
the candidate and assurance snapshot match; the Runner source/toolchain fingerprints
were unchanged before and after both commands.

Fixed Runner lint `20260913T200157Z-e21c` PASS in 28.104 seconds. Full test
`20260913T200226Z-9379` PASS in 595.585 seconds: 2149 Python tests,
58 Web tests, one mock browser test and one real local API/Worker/FFmpeg browser
test. The current synthetic browser run retained delivery/release ZIPs; both match
the manifest SHA256 and sizes, pass archive CRC and safe-path inspection, and contain
one MP4 and one SRT each. A current 120-second synthetic contact sheet was viewed;
its color-block imagery is test media, not real content quality evidence.

Additional isolated diagnostic `20260913195316Z-de98` passed 151 targeted
completion/migration/queue/cancellation tests before the formal run. Read-only
inspection of its retained disposable SQLite fixtures found direct and provided-
connection populated upgrades at head `b71d4c9a20e5` with one Project/Run,
two Tasks, one TaskAttempt, one Asset and one invocation each, with zero FK
violations. The completed-response-loss fixture retains one `succeeded/processed`
intent, one succeeded completion Task/attempt and retry count zero. These local
fixtures support inspection but do not substitute for the formal Runner receipts.

The first A run `20260913T190010Z-7534e06c` remained BLOCKED after a Reviewer
found a Main-protected processing-cancellation defect. Main corrected that defect
in a new isolated successor. The second A run `20260913T192617Z-2fb21a52`
remained BLOCKED after fixed Runner found a historical migration test querying
the new completion table at a pre-completion revision; its Coder fixed an unrelated
line length and added a post-commit reconnect test without crossing scope. Main
froze that historical test's legacy-present table set and moved Alembic model parity
checking to current head in another new isolated successor. Both BLOCKED states,
failed Runner receipts and their consumed budgets remain retained. One local QA
diagnostic wrapper NameError was recorded as ERROR before executing a test.

This accepts only bounded A: atomic idempotent project/run/intent creation,
current-authority replay and versioned resume/cancel, one identity-bound CHEAP
completion Task, truthful DEFERRED/WAITING lease accounting, process-only
completion and the additive migration. Delivery targets remain pending in A.
SD-4 still needs B1 selection, B2 immutable delivery, C1 persistent Worker,
C2 public API/CLI integration, actual new end-to-end artifact inspection, recovery
documentation and trusted original CAS publication. No user database, supplied
`input/8-30.ts`, credentials, global settings or real/paid inference were used.
Synthetic engineering evidence is not SD-6 model/content/audio/hardware acceptance.
