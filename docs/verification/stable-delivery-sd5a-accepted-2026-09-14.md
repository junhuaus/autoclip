# SD-5 A versioned Completion presets: accepted engineering evidence

Status: accepted and published in the delivery worktree on 2026-09-14.
This is local synthetic engineering acceptance; both presets remain
experimental pending SD-6 real content, audio and performance evidence.

`short_highlight_v1` (“短高光”) and `mini_lesson_v1` (“完整小课”) are
immutable application presets. Authenticated
`GET /api/v1/completion-presets` lists safe descriptors;
`POST /api/v1/completion-goals/from-preset` strictly resolves one preset
server-side and creates a Project, PipelineRun and durable Completion goal
with one idempotency key. The Web retains a pending key per tab, replays
the same goal after a lost response and reload, and shows the new Project
without a dashboard refresh. A ZIP URL appears only after a bound
Delivery Asset succeeds. The existing low-level Completion routes remain
compatible. SD-5 B's actual packaging progress and CLI/TUI watch are
separate work.

The accepted formal run is `20260914T091046Z-d9794226` at HEAD
`6009b23859564b2bfdc193eee366afd990b9ef5d`. Its 2250-path frozen
source fingerprint is
`27399c19c3f2ba79f6f2708b9e9cd4580024c245ae42fa42948fcaea8e261d09`.
Fresh Planner READY; sole Coder
`01a09f32-ec65-7161-9253-0e2c65839eeb` IMPLEMENTED with zero edits;
read-only Reviewer PASS with no findings; Tester READY selected only
fixed allowlist IDs `lint` and `test`; fresh semantic Gateway PASS/DONE.
The outer deterministic Gateway also verified current source, toolchain,
QA requests/reports, immutable Runner logs, retained execution and
read-only Gateway evidence-bundle integrity. Earlier blocked formals
remain failures and were not counted as approvals.

Fixed Runner lint QA `20260914T092125Z-ac45` PASS in 41.166s. Full test
QA `20260914T092206Z-b541` PASS in 1154.64s: 2351 Python, 70 Web,
one Mock Chrome and two real API/Worker/FFmpeg Chrome cases. The current
test's post-cleanup verifier recorded 16 committed Assets, 21 retained
files, eight Tasks, 11 attempts including three deferred, fixture
removal and full MP4 decode PASS. Independent source audit matched all
2250 candidate and assurance paths and rechecked the current Gateway
bundle. Independent retained-artifact audit checked SQLite lineage,
each file hash, ZIP/page/Asset byte equality, ZIP members/checksums,
SRT structure, safe text and complete MP4 decode. Its ZIP SHA-256 is
`e6608b2595403aac8fc02f5195b445f9d560ce1184f7a8b4a08743dd3681d3fa`.
The earlier disposable real Chrome lost-response probe is preserved in
[its receipt](stable-delivery-sd5a-successor-browser-receipt.json) and
[screenshot](stable-delivery-sd5a-successor-browser.png): same key and
goal after reload, exactly one Project visible/openable without refresh,
no premature download URL, and fixture cleanup.

Trusted CAS publication receipt:
`.loop/development/sd5-presets-20260914/original-sd5a-publication-20260914T094413Z/receipt.json`.
It changed exactly 20 code paths, eight new, from the accepted 491-path
SD-4 code baseline to 499 candidate code paths. The published code map
was rechecked byte-for-byte. Formal QA IDs were appended to the original
append-only history. Original postpublication lint QA
`20260914094429Z-c507` PASS; focused Python QA
`20260914094546Z-940f` PASS with 107 tests; focused Web QA
`20260914094821Z-e6f5` PASS with 21 tests. All 1017 original QA request
IDs have unique matching report headings. The prior exposed OpenRouter
key was not used; no paid inference, source-media mutation or real
Project-data mutation was part of this acceptance.

The 110m34s read-only `input/8-30.ts` remains available for SD-6, but
does not cover distinct two-hour or four-hour performance cases. Real
Chinese semantic quality, listened-to audio, provider readiness/cost and
hardware throughput remain unverified; no preset is promoted out of
experimental status by these synthetic gates.
