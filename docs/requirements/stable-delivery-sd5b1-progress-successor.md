# SD-5 B1 successor: cancellation race and actual Worker restart

Status: bounded new formal requirement; no B1 acceptance or original
publication. First formal `20260914T100238Z-15c257d5` is terminal BLOCKED
after one sole Coder implemented eight authorized paths. Its read-only
Reviewer found two P2 acceptance gaps, and Tester correctly refused Runner
commands. Trusted `a_successor` contains exactly the first Coder's 2186
source paths from the independent assurance snapshot, plus Main-owned
handoff documents. It excludes input media, real Project data, credentials
and prior Loop state. The [role-visible handoff index](../verification/sd5b1-first-blocked-handoff-index.json)
binds both exact source maps, four structured role artifacts and 1017
accepted QA requests. The [Main owner freeze](../verification/sd5b1-successor-owner-freeze.json)
maps every successor source path except that self-referential receipt and
identifies exactly 14 Main-only document/evidence changes from the blocked
source. Read bounded slices/hashes instead of full manifests.
This run gets a fresh sole Coder; only its newly recorded exact session may
resume, never `--last`.

Preserve the first Coder's fenced progress sink, real copy/hash, metadata,
ZIP, verification and Asset counters, authorized Completion read and
per-attempt migration. Main's DTO, ORM, migration, Web type, policy,
ExecPlan, STATUS and QA are frozen and cannot be edited by Coder. Close the
two confirmed findings and the separate full-lint defect:

Successor preflight also exposed one Coder-owned full-lint defect before
formal Runner: `make lint` fails MyPy because
`current_delivery_progress_authority` in `delivery_repository.py` has no
return type annotation. Add the precise transport-neutral `RowMapping`
return annotation without changing repository behavior. The first Coder's
scoped lint claim did not cover this full project MyPy check.

1. `DeliveryProgressLostLease` can arise because the current Task has a
   persisted cancellation request just after the monitor's check. Then
   `DeliveryTaskRunner` must attempt the queue's existing ownership-fenced
   `acknowledge_cancel(lease)` before returning. It may report CANCELLED
   only if that exact lease owns the cancellation. If replaced, the old
   Worker reports LOST_LEASE without mutating the successor. Add a test
   that writes the database cancellation flag immediately before a
   progress event, without toggling a local monitor boolean, and proves
   prompt cancellation and untouched successor ownership.
2. Add a disposable independent *OS process* Worker and fresh-process
   reader/restart test. Observe a nonzero intermediate copy or ZIP event
   while the first Worker process is alive, with no download URL; stop it
   after the durable event and read through a fresh process. Start a second
   independent Worker process for bounded retry/recovery. Assert a new
   TaskAttempt ID/counter, suppression of the old attempt's incomplete
   count, safe adoption or fresh package creation, and exact final
   manifest/ZIP/Asset binding. Exercise real synthetic FFmpeg MP4/SRT
   media; inspect readable SRT and playable retained MP4. A thread pool,
   reopened SQLite connection or same-process manual retry alone does
   not satisfy this finding. An injected recoverable producer interruption
   is allowed, but Worker and reader lifetimes must be separate OS
   processes. Do not persist or print credentials, even fixture secrets.

The sole Coder may change only
`src/liveclip/application/delivery_runner.py`,
`src/liveclip/db/delivery_repository.py` only for that missing annotation,
`tests/integration/test_delivery_progress.py`, and, only if the new
interruption test proves an orphan temporary-package cleanup defect,
`src/liveclip/delivery/package.py`. No other repository or shared contract,
secure-file primitive, migration, API/Web, QA or control-plane change is
authorized. Use fixed literal test argv and temporary fixture paths; never
execute model-generated paths, commands, SQL, scripts or filtergraphs.
Source media remains read-only, package publication atomic, and FFmpeg
uses validated argv with `shell=False`.

Run focused fault/OS-process diagnostics and adjacent compatibility.
Fresh read-only Reviewer/Tester must find no unresolved acceptance gap;
fixed deny-default Runner then runs allowlisted `lint` and full `test`
with correlated QA. Gateway PASS cannot waive failed, mutated, stale or
uncorrelated deterministic evidence. Main independently checks sealed
source, retained SQLite/MP4/SRT/ZIP bytes and handoff before trusted exact
publication. This requirement itself claims no B1, B2, real content/audio,
hardware or 2h/4h acceptance.
