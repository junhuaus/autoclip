# SD-4 B1 bounded acceptance — 2026-09-13

The durable selection checkpoint is accepted in isolated candidate
`b1_successor4`, not yet published to the original product worktree. Formal
run `20260913T213239Z-1b3efdca` reached DONE: Planner READY, sole Coder
session `01a09cb4-9845-7123-b402-7358e030a5e3` IMPLEMENTED, fresh
Reviewer PASS with no findings, Tester READY, fixed Runner lint/test PASS and
fresh Gateway PASS with no blockers. The Coder changed only the completion
repository and its focused SQLite regression. An explicit empty selection
keeps `no_selected_clips` even if eligibility later disappears.

Fixed lint QA `20260913T214209Z-7891` PASS in 30.261 seconds. Fixed test QA
`20260913T214239Z-788a` PASS in 687.304 seconds: 2207 Python tests,
58 Web tests, one mock browser and one real local API/Worker/FFmpeg browser
flow. Both Runner commands used source fingerprint
`ee8a0cef500329512a2dcc96deadb46776e2fb43bbeefe3ed76cdd29914eb47f`,
sealed toolchain fingerprint
`998617e5a5777fd6eb3e2dcea914f3d84ab74c905d312ae0de5eaae8acc296e1`
and HEAD `6009b23859564b2bfdc193eee366afd990b9ef5d`; command-side
source and toolchain remained unchanged. The trusted outer process published
the accepted source into this isolated candidate only after final gates PASS.

Independent deterministic Gateway evaluation with retained-file verification
PASS had no reasons. The accepted candidate and read-only assurance snapshot
matched on all 2133 source paths and hashes. Six retained same-candidate
synthetic SQLite fixtures matched their recorded SHA256 and size, current
Alembic revision, `quick_check=ok` and zero foreign-key violations. The
[retained fixture index](../../.loop/development/sd4-durable-completion-20260913/b1_successor4/docs/verification/stable-delivery-sd4b1-retained-sqlite.json)
records selected, empty and rollback goal/checkpoint/task/attempt/decision/
Delivery states. Its SHA256 is
`fd62d18a2c60cadcadd00ff5b366ae15e5f3d723afecc5b4b021a607276d2eb0`.
The independent outer receipt is ignored local evidence under
`.loop/development/sd4-durable-completion-20260913/b1_successor4-independent-done-receipt.json`.
The 54-case retained diagnostic `20260913213114Z-956d` was run before the
final Coder's additional empty-eligibility fix; the fresh fixed Runner tested
that final source. The diagnostic is supporting state inspection, not a
substitute for final Runner evidence.

Four earlier B1 formal runs remain terminal BLOCKED with their own evidence:
`20260913T201908Z-dd0630c1`, `20260913T202937Z-0515231b`,
`20260913T211217Z-428f0959` and `20260913T212143Z-e7316970`.
Their failures and retry budgets were not erased. This acceptance covers
atomic default/manual decisions, current-authority replay, stable strict
version-one selection checkpoints, legal task wake, empty outcomes and
bounded nonempty deferral. It does not claim delivery coordination, persistent
Worker dispatch, public goal API/CLI, full SD-4, real-content quality or
2-hour/4-hour performance. Next work is B2 from this exact DONE snapshot.
