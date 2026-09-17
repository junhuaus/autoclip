# SD-4 C1 successor: terminate completion lease monitor before cleanup

Start from the exact terminal C1 Coder source of blocked run
`20260913T233546Z-9bcf4349`, session
`01a09d28-16a5-7c52-9a30-d5e10bdeb173`. Preserve its 237-pass local
regressions and retained synthetic evidence as historical, non-Runner proof.
Trusted Main records a full per-path blocked-Coder hash manifest, exact clone
receipt, accepted-B2 ancestor manifest, named Main-owned document edits, same
HEAD/toolchain and preserved 1006-entry QA root before this successor's Coder.
The prior run stays BLOCKED and is never resumed with `--last`.

Fresh Reviewer P2 found that `LeaseMonitor.stop()` joins for roughly two seconds
while a SQLite heartbeat/observe can wait up to five seconds for a writer lock.
It can return while the monitor thread still runs, allowing late lease renewal
or runtime disposal before that operation completes. Change only the shared
monitor lifecycle and narrowly necessary completion integration. Stop must
signal the thread, wait until an already-running bounded database operation
finishes, verify the thread has terminated, and only then let completion
inspection close files/runtime resources. Do not hide exceptions, swallow
Worker shutdown, falsify a lease result or reset attempt/retry history.
Preserve stage/render/delivery monitor behavior and the accepted B2/C1
selection, immutable Delivery and rotating fairness contracts.

Test a real disposable SQLite writer lock held longer than the old two-second
join timeout while a completion inspection heartbeat is in flight. Trigger
shutdown, release the lock, and assert `stop()` waits for the monitor thread,
no heartbeat runs after stop returns, inspection handles close, and subsequent
Worker recovery preserves the exact intent, task/attempt and Delivery identities.
Also test lost lease/cancellation fencing and existing monitor users; a mock
thread that merely sleeps is insufficient for the SQLite race. Keep source
media read-only, generated artifacts atomic and model output untrusted.

Main pre-edits SOLUTION, ADR 045, recovery guide, STATUS and ExecPlan with the
C1 candidate dispatch/shutdown contract and the prior blocked result. The sole
isolated Coder edits the monitor and focused tests only; it must not change
those Main-owned documents, bootstrap, shared schema or migrations. Its
diagnostics can be retained under ignored `.loop/diagnostics`, but do not
replace the fixed Runner. Fresh independent Reviewer/Tester must confirm both
prior P2s are closed. Run only the checked-in deny-default Runner lint/test IDs,
then semantic Gateway and deterministic source/receipt verification. Publish
only an accepted isolated C1 successor; original-product SD-4 still awaits C2.
