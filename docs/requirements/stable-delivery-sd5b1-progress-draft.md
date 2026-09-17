# SD-5 B1: durable, honest Delivery packaging progress

Status: shared contract frozen in an isolated candidate after accepted
SD-5 A; formal Coder, gates, publication and user-visible acceptance pending.
The visible outcome is an authorized Completion read reporting actual
Delivery copy/hash, metadata, ZIP, verification and Asset-commit work while
the Worker runs, surviving refresh/restart without inventing a percentage
or successful download. This slice excludes CLI/TUI/Web watch and real
content/audio/hardware/long-duration acceptance.

Trusted Main cloned accepted SD-5 A source and QA into `a_candidate`
([role-visible exact source receipt](../verification/stable-delivery-sd5b1-clone-source.json)),
excluding input media, real Project data, credentials and old Loop state.
Main owns `src/liveclip/application/delivery_progress.py`, the optional
`CompletionSnapshot.delivery_progress`, matching Web type, ORM table,
Alembic revision `c84f5d1a702e`, schema/contract tests, ADR047, ExecPlan,
STATUS, QA and control-plane policy. The sole Coder may not edit these.
Planner/Reviewer/Tester/Gateway are fresh read-only sessions. Only the
recorded Coder session may resume, never `--last`; only the trusted outer
process may publish after every deterministic and semantic gate passes.

Implement a fenced repository progress sink from `DeliveryTaskRunner`
through `DeliveryTaskHandler.execute` to actual package operations. Its
event is an absolute phase-local `(phase, unit, completed, total?)` with no
path or secret. Phase/unit pairs and strict snapshot are frozen in the
shared contract. The first event, each phase boundary and final phase
count persist; intermediate byte writes may be throttled at bounded
time/byte intervals but never precede the producer action. A known exact
total is immutable in a phase. Progress may skip stages on existing-package
adoption but never regress within an attempt. A retry gets a new Task
attempt/counter; a stale old callback cannot write or appear in reads.

Every write resolves `TaskAttemptRow.id` and verifies current Task/Delivery
and Project generation, revision epoch, immutable package fingerprint,
attempt number, worker ID, exact live lease token and expiry. Use a short
independent writer transaction, none across media I/O. A
`DeliveryProgressLostLease` stops the old Worker without failing a new
owner; `DeliveryProgressWriteFailed` follows bounded transient recovery
after temporary package cleanup. A post-Asset-commit failure cannot roll
back the Asset: leave Completion incomplete until retry validates the
existing package and Asset bindings. Preserve cancellation, atomic
publication and no-follow checks. ADR047 proves the file-lock then short
DB-write order; no DB writer may wait for `.delivery.lock`.

Copy/hash counts bytes after complete immutable-copy block writes; final
source size/inode/digest binding remains required. ZIP counts uncompressed
pinned bytes accepted by its writer, not predicted compressed size.
Verification counts exact members after reread/hash. Metadata and manifest
count after safe publication; Assets after fenced commits. The builder
interleaves subtitle writes and video copy: metadata may show those
already-written subtitles when that phase begins, never before the writes.
Existing-package recovery reports only work it performs. Callbacks cannot
carry model-generated paths, commands, SQL, scripts or filtergraphs. FFmpeg
remains validated argv with `shell=False`; source media remains read-only.

Authorized `GET /api/v1/completion-goals/{intent_id}` exposes the optional
version-one projection after its existing actor check. Before a Delivery
exists it is `null`; queued Delivery is `queued` without count. Active
progress uses only the currently owned attempt and derives heartbeat/lease
freshness from Task state separately from business advancement. Terminal
phase follows authoritative Delivery/Task/Completion state and has no
counter. Existing safe Completion blocking code remains the reason. Reads
never enqueue, retry or cancel. No ZIP URL appears before bound manifest
and ZIP Assets commit. Existing low-level API defaults remain compatible
aside from this new nullable field. Web displays no new progress UI in B1.

The sole Coder may change only
`src/liveclip/application/delivery_runner.py`,
`src/liveclip/db/delivery_repository.py`,
`src/liveclip/db/completion_repository.py`,
`src/liveclip/delivery/task_handler.py`,
`src/liveclip/delivery/package.py`,
`src/liveclip/media/secure_files.py`,
`tests/unit/test_secure_files.py`,
`tests/integration/test_completion_delivery.py`,
`tests/integration/test_completion_worker.py`,
`tests/integration/test_completion_api.py`, and a new
`tests/integration/test_delivery_progress.py`. No control-plane, policy,
shared DTO, migration, lock, QA or unrelated edit is permitted. Main must
freeze a new candidate for any protected-file need.

Acceptance needs disposable SQLite/Worker/FFmpeg media large enough to
observe intermediate counters and inspect retained MP4/SRT/manifest/ZIP
hashes. Inject copy/hash and ZIP failure, expired lease, late old-worker
callback, Worker restart, cancellation and existing-package adoption.
Assert monotonic within attempt, reset across attempts, exact current
authority, read-only observation, no false URL, and transient/lost-lease
classification. Run focused diagnostics, then fresh formal Reviewer/Tester,
fixed allowlisted sandbox Runner lint/full test, Gateway and independent
sealed-source/artifact audit before trusted exact publication. A semantic
PASS cannot waive failed, stale, mutated or uncorrelated deterministic
evidence. Keep role outputs bounded; truncated results are not evidence.
