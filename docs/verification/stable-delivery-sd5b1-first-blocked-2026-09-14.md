# SD-5 B1 first formal block and successor provenance

First formal `20260914T100238Z-15c257d5` ended terminal BLOCKED at
Tester. Planner READY; sole Coder `01a09f61-e297-7cc0-989d-d8f91ffbf0a6`
reported IMPLEMENTED and changed exactly eight authorized paths. Its
local diagnostics reported 86 focused, 46 compatibility and 101 earlier
regression tests PASS, plus an eight-second synthetic MP4 and Asset hash
inspection. These were Coder-local claims, not fixed Runner evidence.
Reviewer FAIL found two P2 gaps: a persisted cancellation flag could make
a progress callback return LOST_LEASE without ownership-fenced cancellation
acknowledgement, and no test interrupted/restarted an independent Worker
process after a persisted intermediate count. Tester BLOCKED; no Runner,
Gateway, original publication or B1 acceptance occurred.

Trusted Main compared the first frozen 2185-path source map with Coder
execution and Reviewer assurance snapshots. The two 2186-path snapshots
matched byte-for-byte; exactly the Coder-declared eight paths differed
from frozen baseline. New isolated `a_successor` was cloned from that
assurance source, retained 1017 accepted QA IDs, passed toolchain
readiness, and excludes input media, real Project data and prior `.loop`
state. The [full source-clone receipt](sd5b1-first-blocked-source-clone.json)
and [role-visible handoff index](sd5b1-first-blocked-handoff-index.json)
bind both source maps, role artifacts and QA copies by SHA-256. The
[current Main owner freeze](sd5b1-successor-owner-freeze.json) maps all
other source paths and its outer receipt records the full-source
fingerprint. The
successor requirement narrows new writable ownership to the cancellation
race, true Worker restart evidence, and one full-MyPy defect. Successor
preflight Loop Doctor returned READY, while direct `make lint` failed on
`delivery_repository.py:128` for the missing return annotation. This is
new Coder work, not a passed gate. Earlier failure stays preserved.
