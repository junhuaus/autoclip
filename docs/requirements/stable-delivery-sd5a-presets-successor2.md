# SD-5 A successor 2: verifiable provenance for completed preset create

This fresh isolated candidate inherits the exact source from formal
`20260914T065553Z-87aaf774`, which ended terminal BLOCKED at Coder with
zero edits and no Reviewer, Runner or Gateway. Its Coder session
`01a09eb8-3779-7c81-ae31-c783c3f8d64c` must not be resumed; never use
`--last`. The earlier formal `20260914T062211Z-a588ff44` also remains
terminal BLOCKED. No original publication has occurred.

The previous Coder correctly avoided unsupported edits. It could not
independently inspect full lineage and browser product-map evidence because
the outer Main receipts were outside its workspace. Trusted Main cloned all
2176 previous frozen source paths byte-for-byte to `a_successor2` and placed
read-only copies inside `docs/verification/`. Start with the small
`sd5a-successor2-provenance-index.json`. It names exact SHA-256s and sizes
for the accepted SD-4 clone receipt, first frozen map, first terminal
second-Coder source receipt, second frozen map, second terminal no-edit Coder
receipt, browser outer receipt, browser code-file map and retained screenshot.
The maps bind the path counts 2161→2166→2171→2176→2176 and preserve QA1012.
The browser receipt's product-code file-map SHA must equal the current
successor code map; the added provenance, task book, STATUS and freeze
receipts are Main-owned documentation, not a new browser-tested behavior.
Read/count/hash selected evidence rather than printing entire manifests.

The new exact Coder session ID is generated and recorded by the trusted
outer process **after** the new Coder role returns. It cannot be a
preexisting candidate file during that role. The prior two Coder IDs are
recorded in the provenance index and must remain distinct from the new one.
Likewise fixed Runner QA receipts are generated only after Tester selects
allowlisted command IDs; their pre-Runner absence is not a failed gate.
Report actual current evidence, do not assert future results.

The bounded SD-5 A product outcome remains: authenticated versioned short
highlight and mini-lesson preset listing, strict high-level create through
the existing durable Completion transaction, stable browser idempotency
identity across a lost response/reload, no premature ZIP URL, and a newly
created Project visible/openable without dashboard refresh. Existing
low-level routes retain their old wire behavior. The prior P1 late-response
race and P2 stale dashboard are fixed in the inherited code. Main's focused
Web 21/21, full lint/typecheck and disposable real Chrome+API+SQLite replay
PASS are diagnostic preformal evidence; only new formal Reviewer/Runner/
Gateway and independent accepted-source checks can grant acceptance.
The browser probe committed a manual mini-lesson 202, deliberately lost the
response, reloaded and retried with the same key, found one Project and the
same goal, opened it without refresh, and saw no download URL. The screenshot
and its SHA-256 are retained in the candidate; temporary media, database
and generated test credentials were removed.

The sole Coder may write only the existing scoped product paths if an actual
repair is necessary:
`src/liveclip/application/completion_presets.py`, `src/liveclip/api/app.py`,
`apps/web/src/api.ts`, `apps/web/src/App.tsx`, `apps/web/src/styles.css`,
`apps/web/src/CompletionCreate.tsx`, `tests/unit/test_completion_presets.py`,
`tests/integration/test_completion_presets_api.py`,
`apps/web/tests/completion-presets.test.tsx`,
`apps/web/tests/app-states.test.tsx`, `apps/web/tests/api.test.ts`.
No edit is needed merely to produce a nonempty diff. Any product edit
invalidates the preformal browser code-map match and needs fresh current
browser evidence before Main publication. Main owns shared contracts,
locks, migrations, ADR, ExecPlan, STATUS, QA and provenance receipts.
Planner/Reviewer/Tester/Gateway are fresh read-only sessions; only the exact
new recorded Coder session may resume within this run.

Fresh Tester should select the checked-in `lint` and `test` argv IDs, then
inspect correlated Runner logs for Python, Web and both browser scenarios;
the aggregate exit alone is insufficient. Existing Completion repository
tests establish durable idempotency, concurrency and fencing; the preset
API tests establish the new route's strict body, auth, same-key replay,
changed-key conflict, source disappearance, readiness change, manual/default
binding and current-authority rejection. Report any still-uncovered route
variant precisely. Runtime configuration changes are outside the promised
same-key replay because resolved configuration is part of persisted identity.
Gateway PASS cannot override failed, stale, mutated or uncorrelated Runner
evidence or unresolved P0/P1. Keep role output bounded and do not read,
copy or mutate `input/8-30.ts`, real Project data, credentials or cloud
providers. Synthetic proof does not establish content/audio/hardware quality.
