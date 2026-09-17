# ADR047: Observable durable Completion progress

Status: B1 shared contract, implementation and bounded synthetic engineering
accepted and published on 2026-09-14. B2 client observation and Worker
lifecycle remain separate. Baseline: accepted SD-5 A.

## Decision

`CompletionSnapshot.delivery_progress` is an optional strict version-one
read projection. It is `null` until a Delivery exists. A queued Delivery
has phase `queued` and no work counter. An active Delivery has one current
attempt, phase-local unit, actual completed count and optional exact total.
Terminal `succeeded`, `failed` or `cancelled` comes only from the bound
Delivery/Task/Completion outcome and has no work counter. Clients must not
compose a whole-Delivery percentage or use elapsed time, heartbeats or
Pipeline stage weights as packaging progress. A ZIP URL requires committed
manifest and ZIP Assets. Unknown totals remain indeterminate.

The fixed work phases are `copying_hashing`/bytes,
`writing_metadata`/files, `writing_zip`/uncompressed pinned source bytes,
`verifying_package`/members and `committing_assets`/Assets. The immutable
video copier hashes and writes in one loop. Count a copied block only after
its whole write; the later source binding check may still fail. Metadata
files count after safe publication, ZIP bytes after the archive writer
accepts them, verified members after exact reread/hash, and Assets after
each fenced commit returns. These are work counts, not a substitute for
final validation. Existing-package adoption skips work it does not repeat.
The current builder interleaves subtitle writes and video copy; already
written subtitles may enter the metadata phase together after the copy
loop, never before their actual writes.

The transport-neutral contract lives in
`src/liveclip/application/delivery_progress.py`. Producer events carry only
phase, unit, absolute completed count and optional total. They cannot carry
paths, filenames, transcripts, lease tokens, model output or commands. The
API/TypeScript snapshot adds the opaque current attempt ID, business
advancement time, Worker heartbeat and derived lease freshness. The
existing Completion blocking code remains the safe blocking reason.

`delivery_progress` has composite `(delivery_id, task_attempt_id)` primary
key and a unique Task attempt. Its row binds attempt number, expected
generation, revision epoch and immutable package fingerprint. Every write
must check current Delivery/Task identity, live running status, worker ID,
exact lease token, unexpired lease and those bindings. Within an attempt,
phases move forward and counts never decrease; a published exact total
cannot change. An unknown total may become exact once. A retry gets a new
row and counter. Reads join only the current owned attempt after actor
authorization. Old attempts remain audit history; reads never wake work.

The first event, every phase boundary and final phase count are required
durable writes. Intermediate byte events may be coalesced by bounded time
or byte thresholds and must never run ahead of the producer. Each write is
a short independent SQLite transaction; none spans media I/O. A stale
callback raises `DeliveryProgressLostLease`, stopping the old Worker
without failing the new owner's Task. A current owner's transient write
error raises `DeliveryProgressWriteFailed`, cleans its temporary package
and follows bounded retry. A post-Asset-commit write failure cannot undo
the Asset; Completion stays incomplete until retry validates existing
package bytes and Asset bindings. Cancellation keeps its explicit SD-4
authority path.

If a progress callback loses authority because the current owned Task has
a newly persisted cancellation request, the runner attempts the existing
ownership-fenced `acknowledge_cancel` before returning. It reports
cancellation only if that exact lease still owns it; a successor lease
remains untouched. This closes the race between the monitor's check and
the progress sink's database fence.

## Lock order and boundaries

`DeliveryTaskRunner` returns from `start_delivery` before the handler runs.
Asset reservations complete before `create_delivery`; the builder holds
the no-follow `.delivery.lock` during copy/ZIP. Its only production caller
is the handler; the API only enqueues. Demo and semantic-delivery callers
do not hold a SQLite writer transaction. The handler validates/commits
Assets after `create_delivery` releases the file lock. A callback may take
a short DB writer lock while the file lock is held only while no DB writer
path waits for that same file lock. Preserve this order; never introduce
DB-to-package lock acquisition. SQLAlchemy stays in the repository; the
secure file/ZIP functions receive typed counters only.

B1 acceptance needs disposable SQLite/Worker/FFmpeg faults, authorized
reads, no premature ZIP and retained exact media/manifest/ZIP hashes, then
fresh formal gates. B1 does not claim CLI/TUI/Web watch, real Chinese
content/audio, hardware or 2h/4h performance. B2 freezes those client and
Worker semantics separately; current `auto` remains foreground until then.
