# SD-4 C1 isolated Worker acceptance — 2026-09-14

Formal successor run `20260914T001553Z-44675925` is `DONE` in isolated
`c1_successor2`; its fresh Planner READY, sole Coder IMPLEMENTED, Reviewer
PASS without findings, Tester READY, fixed Runner lint/test PASS and Gateway
PASS are retained with the run. The accepted source fingerprint is
`37a11972ef240e4b0c36a06e74301fd455b71218fe068a888cccdaf6b3e6f9dd`
over 2152 paths at HEAD `6009b23859564b2bfdc193eee366afd990b9ef5d`.
The exact Coder session was `01a09d49-d7ec-7d82-89e3-4544f30aae4e`; it
changed only `tests/integration/test_completion_worker.py` from the frozen
baseline. The inherited production `LeaseMonitor.stop()` joins the background
thread and drains foreground operations before inspection/runtime closure.

The combined disposable SQLite/Worker regression holds an independent writer
lock while the actual completion inspection monitor's background heartbeat
enters `BEGIN IMMEDIATE`. Its retained trace records a 2.202-second barrier
from stop entry to lock release, below SQLite's five-second busy timeout;
heartbeat renewal succeeds, the monitor terminates, inspection/runtime close
in order, and Worker returns 143. A negative control restoring the former
two-second timed background join while keeping foreground draining fails the
combined test at the live-thread assertion. After natural lease expiry, a
second Worker recovers the same intent with one ordinary retry and a distinct
attempt. Historical attempts, selection/action keys, Delivery ID/version and
bound Asset IDs/sizes/SHA-256 remain stable. The retained synthetic package
has an intact nonempty manifest, valid ZIP, decodable MP4 and matching SRT.

Fixed Runner lint `20260914T003238Z-8219` PASS and test
`20260914T003304Z-c21d` PASS used the same sealed source/toolchain/HEAD
before and after execution. The test command passed 2294 Python and 58 Web
tests, plus one mocked browser case and one real local API/Worker/FFmpeg
browser case, in 892.165 seconds. The two request/report IDs were appended
to original QA history after DONE, preserving all 1006 earlier IDs.
Independent `INDEPENDENT_DONE_SOURCE` PASS recomputed deterministic Gateway
conditions and byte-matched all 2152 accepted paths to the Runner assurance
source. A separate trusted read-only audit
`C1_SUCCESSOR2_CODER_RETAINED_OUTER` PASS checked the Coder source delta,
retained SQLite integrity, event order, attempt history and actual owned
Asset/manifest/ZIP/MP4 bytes. Both earlier C1 runs remain terminal BLOCKED;
their findings and diagnostics were not waived or relabeled.

This accepts C1 only inside the isolated candidate. C2 public goal API,
end-to-end SD-4 publication in the original worktree, SD-5 progress/presets,
real model/content/audio/hardware evidence and SD-7 release remain open.
The user source `input/8-30.ts` was not copied or mutated by this C1 run.
