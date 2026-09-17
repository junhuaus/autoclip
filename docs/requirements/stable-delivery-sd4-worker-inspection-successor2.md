# SD-4 C1 successor 2: prove real inspection-monitor shutdown and recovery

Start from the exact terminal C1 successor Coder source of blocked run
`20260914T000226Z-edd128f3`, recorded Coder session
`01a09d3e-5694-7352-948d-c9985cc39396`. Preserve that run's Reviewer FAIL
and Tester BLOCKED evidence; it made no fixed Runner request. The monitor
implementation and Main's C1 architecture/recovery documents are inherited.
Trusted Main binds a full 2149-path final-Coder hash manifest, the accepted-B2
ancestor, the first blocked C1 source, exact clone receipt, named Main documents,
HEAD/toolchain, 1006 per-ID QA records and no copied source media in a fresh
isolated candidate. A terminal run is never silently reused; only this fresh
run's exact recorded Coder session may resume.

The previous standalone test held a SQLite writer lock against a *foreground*
`refresh()` on a separate monitor whose background heartbeat interval was 30
seconds. It did not reproduce the completion inspection monitor's background
heartbeat, WorkerShutdown, stop-before-close ordering or recovery identities.
The existing separate shutdown test had no writer contention. Those tests
remain useful but cannot close the actual P2. Add one combined disposable
SQLite/Worker regression that would fail if the background monitor reverted
to its former two-second timed join even while foreground draining remained.

Create a real generated synthetic delivery goal with a succeeded bound package.
Use the actual CompletionRepository path invoked by `run_worker`, not a
standalone LeaseMonitor. Configure a short valid lease/heartbeat interval,
for example 15/5 seconds, so the background completion inspection monitor
attempts a heartbeat during the test. Hold `DeliveryInspectionRequired.inspect`
open with events. After its initial foreground refresh and inspection entry,
hold an independent `BEGIN IMMEDIATE` writer transaction on the same disposable
database. Instrument `before_cursor_execute` or an equivalent actual SQLite
call boundary to prove a thread named `liveclip-completion-inspection-*`
entered its own heartbeat's `BEGIN IMMEDIATE` while the writer lock is held;
a foreground test thread does not count. The monitor callback must complete
successfully after the lock is released, not merely return through its broad
exception handler. Keep the writer lock held beyond the former join deadline
but below SQLite's configured busy timeout.

Only after the background heartbeat is blocked, release the inspection gate
by raising WorkerShutdown(SIGTERM) on the Worker thread. Observe entry to the
actual completion monitor `stop()`. While the writer lock remains held for
more than 2.1 seconds, prove stop has not returned, `DeliveryInspectionRequired`
handles have not closed, the Worker runtime has not disposed its engine and
the Worker has not returned. Release the writer lock; prove the heartbeat
finished, then the monitor thread terminated, then inspection handles and
runtime closed, then Worker returned the normal signal exit code. No monitor
heartbeat/observe/refresh may run after stop returns. Bounded `finally`
cleanup must release locks and join helper threads even on assertion failure.

Snapshot before and after interruption: exact intent/project/run/generation,
completion Task ID, historical TaskAttemptRow IDs, selection checkpoint and
action keys, bound Delivery ID and immutable version, and bound Asset IDs,
sizes and SHA-256. The interrupted attempt must remain visible and truthful.
After normal lease expiry, start another Worker with no client and recover the
same goal. Assert a distinct recovery attempt is appended, historical IDs are
unchanged, retry accounting follows the existing bound, Delivery version/Asset
hashes remain identical and no second Delivery is created. Verify the final
package still has nonempty manifest, valid ZIP/MP4/SRT and owned Asset bytes.
Keep source media read-only and do not use paid/cloud inference.

The sole isolated Coder owns only the focused Worker integration test and any
narrow monitor correction it exposes. It must not edit Main-owned STATUS,
ExecPlan, SOLUTION, ADR, recovery guide, bootstrap, schema or migrations.
Retain real disposable evidence under ignored diagnostics when practical.
Fresh independent Reviewer and Tester must explicitly close the background
monitor and attempt/artifact P2s before the checked-in deny-default Runner
executes lint/test. Gateway and independent receipt/source checks follow.
C1 publication is isolated; C2, original SD-4 and real-content acceptance
remain pending.
