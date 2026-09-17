# SD-5 B1 accepted: durable Delivery progress

Status: **accepted for the bounded synthetic engineering contract** on
2026-09-14. This is not SD-5 B2 operator-flow or SD-6 real-content acceptance.

The accepted `CompletionSnapshot.delivery_progress` is a versioned,
authorized, read-only view of durable work by the current Delivery Task
attempt. The producer records real phase-local copy/hash, metadata, ZIP,
verification and Asset-commit counts. A missing total remains unknown;
heartbeat does not masquerade as business progress. A replaced lease cannot
write another attempt's progress. Cancellation arriving during a callback is
acknowledged only when the old Worker still owns that lease. The generated
package is published atomically and the source remains read-only.

Formal successor `20260914T103344Z-8075efd1` reached `DONE` from a frozen
isolated candidate. The sole recorded Coder session
`01a09f7e-5bc5-7021-8563-c9399d4013d9` changed only
`delivery_runner.py`, `delivery_repository.py` and
`test_delivery_progress.py`. Fresh Reviewer was PASS with zero findings,
Tester READY, fixed Runner lint `20260914T110326Z-8381` PASS and full test
`20260914T110405Z-ce5b` PASS, then the read-only Gateway PASS. Full test
ran **2378 Python tests**, **70 Web tests**, Mock Chrome and two
real-service Chrome E2E cases. Independent deterministic Gateway
reevaluation and byte-for-byte candidate/assurance comparison matched all
2198 source paths at fingerprint
`f0d1e371667763149e31433a38ed352e7081f50127623ab4b18a749749dc3519`.
The [first B1 blocked run](stable-delivery-sd5b1-first-blocked-2026-09-14.md)
remains terminal and was not relabeled.

The retained disposable Worker fixture used independent OS processes for
Worker A, an authorized API reader, another reader after interruption,
Worker B and its reader. Worker A's intermediate durable count was visible
while it remained alive; after its injected interruption the current view
returned to queued. Worker B used attempt 2, recovered the same Delivery
and completed it. Main copied each 16-file Coder and Runner fixture with
matching SHA-256 before temporary cleanup. Independent SQLite integrity,
foreign-key, attempt/progress lineage, ZIP members, checksums, committed
Asset hashes, unchanged source hash, SRT text and full source/delivery MP4
decode all passed; the synthetic contact sheet was visually inspected.
The Runner ZIP SHA-256 was
`83ec7aa758b18d4d6ef3e3841dff379b4d952d7009ac06c6a823505b053cad3d`.
Scans of retained text/SQLite found no old OpenRouter-key prefix or Bearer
header. The local ignored audit receipts are
`.loop/development/sd5b1-progress-20260914/sd5b1-successor-independent-done-source-receipt.json`
and `sd5b1-runner-media-audit.json` beside it.

Trusted CAS publication compared the original 499-path SD-5 A code map
with the accepted candidate, then atomically published exactly **17**
declared code/test paths (**4** new). The postpublication 503-path code map
matched the accepted source. The two formal QA IDs were appended to the
original append-only logs. Original `make lint` QA
`20260914T112732Z-c085` PASS and 29 targeted progress/contract/migration
tests QA `20260914T112800Z-4840` PASS. Original QA now has 1021 unique
request/report IDs, plus one earlier supplemental report heading. A separate
trusted document CAS published 17 frozen B1 plan/requirement/evidence files;
the original STATUS, API and recovery instructions were then advanced to
this accepted state.

The accepted evidence uses synthetic media. Neither preset is promoted
beyond experimental status. `auto` and Web do not yet expose the durable
watch flow; that is SD-5 B2. Real Chinese content/audio, a legitimate
bounded model batch, Apple Silicon performance and distinct 2h/4h inputs
remain SD-6 acceptance work. The supplied read-only `input/8-30.ts` is
about 110m34s and cannot stand in for a 2h or 4h case.
