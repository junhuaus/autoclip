# SD-5: Shared presets and complete progress observation

Living ExecPlan prepared 2026-09-13. SD-4 and all bounded SD-5 A/B1/B2
slices were accepted and published on 2026-09-14. Versioned preset create,
durable producer-side Delivery progress and high-level CLI/Web observation
now exist. SD-6 real-content acceptance remains open. Main froze shared
contracts before one isolated Coder changed application entry points or
frontend components.

Accepted SD-4 handoff: formal `20260914T052758Z-fb55229f` DONE on source
`a32107ca88c7ff8ea38ba9f03e2f8d802e03e333a744bcc03035382fafac49bd`;
exact 47-path original CAS publication and postpublication lint/43 targeted
tests PASS. The source exposes authenticated idempotent completion-goal create,
read, select, resume and cancel, with persistent Worker and signed successful
ZIP download. Current `CompletionSnapshot` has durable status/outcome/version
but no real packaging progress, and existing `auto` still coordinates selection
and packaging in its initiating process. Freeze versioned preset resolution,
progress storage/DTO, Worker startup requirement and CLI/API/Web request-key
ownership before modifying user entry points. Keep SD-6 real-content claims
separate from SD-5 synthetic acceptance.

Accepted SD-5 A handoff: formal `20260914T091046Z-d9794226` DONE,
2250 exact source paths, fixed Runner 2351 Python/70 Web/three browser
cases PASS, independent source and ZIP/media audits PASS, trusted 20-path
code CAS publication and postpublication lint/107 Python/21 Web PASS.
[Accepted evidence](../verification/stable-delivery-sd5a-accepted-2026-09-14.md).
The immutable preset/API/Web request-key contract is frozen and published;
B1 subsequently published producer progress DTO/migration and counters,
then B2 published Worker/CLI/Web observation. `auto` now persists a goal
and watches an independent Worker. See [B2 accepted evidence](../verification/stable-delivery-sd5b2-accepted-2026-09-14.md).

## Outcome and entry points

`auto VIDEO` creates an idempotent durable goal using a named preset; `resume PROJECT_ID`
continues the existing intent and never creates another project or generation. Existing
run/retry/stage/select/package commands remain available with their old defaults. Multiple
eligible intents require an explicit intent selection, not an arbitrary latest record.

CLI, API and Web call one application preset resolver and completion service. Presets bind
profile, duration/quality contracts, model/runtime settings, selection policy and delivery
options through versioned explicit data. Freeze IDs and canonical resolved configuration
before implementing callers. Web offers short highlights and mini lessons with honest
experimental/acceptance labels. No default is promoted on synthetic tests alone.

The high-level create flow reuses existing project/run idempotency and then durably binds
the completion intent. Lost responses can be retried with the same canonical request key.
Manual selection is submitted explicitly and retains human exclusions. User-facing forms
contain meaningful choices, not schema versions, internal cache keys or control-plane jargon.

## Shared progress contract

CompletionSnapshot is the source for both terminal and browser displays. Represent phase,
durable goal outcome, actual work counters when known, current action, elapsed time, last
business progress time, Worker heartbeat/lease state, blocking reason and final delivery ID.
Expose processing, waiting for selection, rendering, combined copy-and-hash,
ZIP creation, archive verification and Asset commit. The current immutable
member copier hashes bytes in the same read/write loop, so it cannot report
two independently measured copy and hash phases.
Heartbeat freshness and business advancement are separate; neither implies the other.

Existing PipelineRun/Stage progress covers only processing. Current DeliverySnapshot does
not supply complete copy/hash/ZIP progress, so add real producer instrumentation and fenced
persistence before drawing those bars. Reuse owned Task/Completion storage; freeze any needed
progress DTO/schema with Main. Counters identify units such as clips, files or bytes, and
totals can change when the actual work set becomes known. Unknown work is shown as activity
without a fabricated percentage. Do not stretch six Stage weights into a delivery ETA.

The final success view shows the real absolute local package path from the authorized
delivery artifact resolver and its delivery identity. The browser downloads by asset ID.
Zero eligible clips, explicit zero selection, waiting, blocked and cancelled states show
their own outcome; none renders a nonexistent successful ZIP path.

## CLI and Web implementation

- Extend the existing foreground auto command and add durable resume over shared services; keep configuration resolution,
  authorization, selection and recovery rules out of the command handlers.
- Use a terminal live display only for TTY output. Refresh around two seconds and react to
  resize, narrow widths and Chinese display width. Long errors wrap/crop once without endless
  scrolling. Non-TTY output uses stable concise state transitions or an explicit JSON mode.
- Watch/inspect performs reads only, including while packaging. Ctrl-C exits observation
  without cancelling the durable goal. Explicit cancellation is a separate application action
  using SD-4 lease/atomic-publication rules. Client disconnect behaves like watch exit.
- Web uses the same preset identifiers and CompletionSnapshot. Poll or stream authorized
  state without starting work on refresh. Display waiting/manual/empty/error states and actual
  package progress; refresh after selection/revision conflicts using current CAS.

Main owns preset definitions, Python/TypeScript DTO correspondence, API schema, migrations,
bootstrap and shared integration. Serialize changes to shared CLI/API files. Frontend work
stays within assigned components/client tests; read-only reviewers do not write.

## Acceptance

Equivalent CLI/API/Web preset requests resolve to the same canonical configuration and
goal options. Historical low-level defaults and exact persisted run identities stay intact.
Test lost create/resume responses, ambiguous intents, manual wait/submission, human exclusions,
zero candidates, cancelled/failed work, new generation, stale revision and permission changes.

Exercise an actual synthetic API/Worker/SQLite/FFmpeg run through selection, rendering and ZIP,
with client disconnect and Worker restart. Inspect the current media, subtitles, database
checkpoints and package. Verify watch keeps showing packaging until its real terminal outcome.

Render narrow/wide terminal snapshots with Chinese long lines, resize, non-TTY and long errors;
verify bounded output and that watch interruption creates no cancellation/state mutation.
In a real local browser, inspect both profiles' forms, changing progress counters, manual wait,
zero/no-package state and the final successful authorized download. No mocked screenshot alone
establishes the local flow, and no synthetic flow establishes real model/content quality.

Require fresh code review, allowlisted sandbox Runner lint/test, Gateway, current artifacts
and trusted original CAS publication. Document exact working commands with their current
output, then continue SD-6 real acceptance and SD-7 reproducible recovery.

## Progress

- [x] Bind the intended UI to existing durable services and identify missing packaging progress.
- [x] Freeze and publish the SD-5 A preset/API/Web contract with full formal gates.
- [x] Freeze and publish the B1 durable producer-progress DTO, migration and lease-fenced sink contract.
- [x] Implement and accept B1 actual copy/hash, metadata, ZIP, verification and Asset counters.
- [x] Implement and accept B2 durable CLI/TUI/Web observation and resume flow (2026-09-14).
- [x] Complete current terminal/browser/synthetic media inspection, publish SD-5 B and update operator commands (2026-09-14).
- [ ] Continue SD-6 real acceptance and SD-7 recovery/release documentation.

2026-09-14 historical B2 recovery: formal successor-11
`20260914T212259Z-6956bd70` is terminal BLOCKED. Its fixed lint and early
E2E passed; full test passed 2425 Python, 78 Web, Mock Chrome and legacy
real Chrome, then B2 real Chrome lost a `page.evaluate` execution context
while navigating at terminal wait. The failure snapshot showed login, so
the next test must also verify the final authorized UI, not merely retry
the API read. No Gateway or original publication occurred. Trusted Main
cloned the exact frozen 2299-path source into isolated successor-12 with
accepted QA1021; owner freeze sealed 2309 paths. Only the browser E2E test
file was in the successor's sole Coder scope. The failed Runner QA remains
in its old candidate and was not published.

Successor-12 `20260914T224719Z-804eeb92` then reached DONE: sole Coder
changed only the browser test to use navigation-independent, cookie-backed
goal reads and require the final authorized UI/download; Reviewer PASS with
zero findings, Tester READY, fixed Runner lint/e2e/full test PASS (2425
Python, 78 Web, three browser scenarios), Gateway PASS. Independent
2309-path source/Gateway/QA and four current retained fixture audits PASS.
Trusted CAS published 22 declared code/test paths (7 new) from the exact
503-path B1 baseline to a 510-path accepted map; three QA IDs and seven
operator/contract documents were separately appended/published. Original
postpublication lint, 133 focused Python, 18 Web, product Doctor, Demo and
loop Doctor PASS/READY with 1030 matched QA IDs. The [bounded acceptance
report](../verification/stable-delivery-sd5b2-accepted-2026-09-14.md)
has exact evidence and synthetic-only limits. SD-5 engineering work is
closed; SD-6 and SD-7 remain.

First B1 formal `20260914T100238Z-15c257d5` ended terminal BLOCKED at
Tester, with no Runner/Gateway or original publication. Reviewer confirmed
the persisted cancellation acknowledgement race and missing independent
Worker-process restart observation. Trusted Main cloned its exact 2186-path
Coder/Reviewer source into a new isolated successor and preserved a
role-visible eight-file source/QA handoff. The bounded successor requirement
permits only the runner cancellation repair, process restart fault test,
the `delivery_repository.py:128` return annotation found by full MyPy,
and any proven temporary-package cleanup repair; no shared contract or
control-plane edit is delegated. Repeat fresh formal gates before B1
acceptance. The first failure remains preserved and visible.

The fresh B1 successor later reached DONE and was accepted. Its sole Coder
closed the cancellation race and added a real independent-process Worker
interruption/restart test. Formal Runner lint and full tests, Reviewer,
Tester and Gateway all passed; Main verified current source/QA/Gateway and
retained package/media evidence, then CAS-published 17 declared code/test
paths. Original postpublication lint and 29 focused tests passed. See the
[bounded B1 acceptance report](../verification/stable-delivery-sd5b1-accepted-2026-09-14.md).


## 2026-09-13 source findings for the entry-point handoff

Existing auto already calls run_pipeline with semantic_windowed/general, top_n15, score75,
context128000 and budgetratio0.58; short durations45/60/90seconds and mini90/180/300seconds
come from domain.clip_profile. It performs selection/packaging only in the initiating process.
Replace that high-level coordination with the accepted durable completion contract while
preserving low-level run defaults. The preset resolver should bind these meaningful values
without reusing unrelated platform-release presets already present in Web types.

Web createJob currently generates a fresh Idempotency-Key inside every invocation. A lost
response followed by another invocation therefore has a new identity. The new durable-create
client must own a stable key for the same pending canonical submission and pass it explicitly;
renew it only for an intentional new request. Test a server commit followed by transport
response loss and retry, including interrupted observation. Do not claim server idempotency
alone prevents duplicate creation when the client changes its key. Existing API request shape
and low-level defaults remain compatible.

Do not implement watch-only Ctrl-C by leaving a worker thread tied to the exiting CLI.
Persistent Worker must drive queued completion independently, as established in SD-4. Freeze
the high-level CLI's supported Worker lifecycle/startup contract before claiming auto survives
client exit; the current foreground run/--finish path does not provide that behavior.
This was read-only preparation while SD-3 formal `ff1afbdf` was active;
SD-3 has since been accepted. No SD-5 code exists yet, and its shared
contracts remain dependent on full SD-4 acceptance.


Packaging instrumentation must follow actual operations: current create_delivery copies
and hashes video in the same bounded read loop, then creates the ZIP and verifies/commits
its Assets. Model a combined copy/hash phase where that is what occurs; ZIP input bytes are
known but final compressed output size is not. Throttle fenced progress writes and use real
phase changes, retaining truthful recovery after an already-published directory. Do not
derive fake file/byte counts from elapsed time or reuse processing stage percentages.

## 2026-09-14 SD-5 A bounded handoff

Main froze [ADR046](../adr/046-versioned-completion-presets.md) and
[the SD-5 A requirement](../requirements/stable-delivery-sd5a-presets.md).
The isolated `a_candidate` cloned all 2161 accepted original source paths
with exact file hashes and HEAD, preserving QA1012 while excluding input,
real Project data and previous Loop state. Its shared Python preset values,
strict API request/list response and matching TypeScript types are Main-owned;
three contract tests and local lint/typecheck PASS. The sole Coder is next to
implement one application registry, high-level API route and Web create flow
within the frozen allowlist. No SD-5 A formal acceptance or original
publication is claimed. The broader progress/CLI/TUI contract is SD-5 B.

## 2026-09-14 SD-5 A first formal and successor

Formal `20260914T062211Z-a588ff44` is terminal BLOCKED before Runner. Its
sole Coder `01a09e9a-b57d-7c82-9ce7-312e198e2d81` implemented 11
authorized paths, with 10 focused Python and 20 Web tests locally passing.
Fresh Reviewer found a P1: a late success from request A could erase
request B's stored idempotency key after dialog remount. The exact Coder
repaired that race, prevented dialog dismissal while submitting and added
deferred-response regressions. Second review found no P0/P1, but its P2
identified a real user-visible gap: successful preset creation did not
refresh the dashboard list. Fresh Tester blocked the run; there are no
correlated Runner or Gateway results to reinterpret as a pass.

Trusted Main cloned all 2171 second-Coder assurance source paths byte-for-byte
to `a_successor`, with exact terminal fingerprint
`bbf2bf97216073c64e3da2eea48c8296dd99bad2c8f6a938af128de15d09889f`.
The blocked candidate and artifacts remain retained. Before any new formal
roles, Main integrated a success callback to invalidate Project search,
kept the queued-goal confirmation visible and provided direct Project
navigation; a new App test closes the dialog and finds the Project without
refreshing. Focused Web 21/21, TypeScript and full lint checks pass. The
disposable real Chrome/API/SQLite replay also passed: manual mini-lesson
server 202 followed by lost browser response, same key and goal after reload,
one Project visible/open without another refresh and no premature ZIP URL.
Its synthetic media, database and temporary credentials were removed;
the isolated successor retains a hashed screenshot/receipt that Main viewed.
The per-file owner freeze and full fresh Runner/Gateway gates still must
pass. Keep SD-5 B's true progress/CLI/TUI work separate from this bounded
successor.

## 2026-09-14 SD-5 A second formal provenance block

Formal `20260914T065553Z-87aaf774` stopped terminal BLOCKED at its fresh
Coder before Reviewer/Runner/Gateway. Exact session
`01a09eb8-3779-7c81-ae31-c783c3f8d64c` changed zero files: the product
fix and real Chrome proof looked sufficient, but the full clone/frozen/code
maps lived outside its role workspace, so it declined to claim it had
verified them. The resulting 2176-path frozen source still has fingerprint
`54516b630e3709d660bb13482d44a68cf3421216ffa00883736781679be20901`.
Trusted Main cloned it byte-for-byte to `a_successor2`, preserving both
blocked runs. The successor now contains the exact source maps, clone
receipts, browser code-file map, current screenshot and a small SHA-indexed
provenance guide in `docs/verification/`. Its task book clarifies that a
fresh Coder session ID and Runner QA IDs are future outer-process records,
not evidence available before those roles run. Main has not altered product
code since the real browser PASS. Fresh full gates and original CAS
publication are still required.

## 2026-09-14 SD-5 A third formal QA-evidence block

Formal `20260914T070824Z-3f443545` froze 2188 source paths at
`68e5d77cf101060fc7e66b9e61ebb6fb58785074ac7e95b8908cf6fb977ebf3e`.
Fresh Planner READY validated the role-visible provenance index, browser
code map and selected source hashes. Fresh sole Coder
`01a09ec5-3855-70e1-b716-ece7f1737d75` reported BLOCKED with zero edits:
the role workspace omits the preserved `qa/pipeline.jsonl` and
`qa/test-report.md` control files, so QA1012 was not directly inspectable
there. It also found two missing direct same-key conflict test cases for
changed preset ID and selection policy. No Reviewer, Runner or Gateway ran.
Preserve the terminal failure. Trusted Main cloned all 2188 frozen paths to
`a_successor3` with the same source fingerprint. Hash-checked read-only
copies of both accepted QA files and the third blocked artifact are now
role-visible under `docs/verification/`. The two direct route assertions
pass in focused API 7/7; full local lint/typecheck PASS. The explicit
browser-code addendum names the sole changed path, a test file, and proves
all non-test runtime code remains byte-identical to the retained real
Chrome replay. Fresh formal gates and trusted CAS publication remain
required.

## SD-5 B proposed execution split after A publication

Treat this as a plan, not an acceptance claim. B1 freezes the versioned
Completion observation DTO, migration and fenced per-Delivery-attempt
projection, then instruments real package copy/hash, metadata, ZIP,
verification and Asset commit events. It adds authorized API reads and
synthetic fault tests across retry, lease loss, cancel and existing-package
recovery. B2 binds `auto`, `resume`, read-only TTY/non-TTY watch and Web
polling to that same DTO, with an explicit independently running Worker
startup contract. Both slices need fresh isolated Coder/review/test/Runner/
Gateway evidence and trusted code-only publication. A browser showing a
moving number is not B1 acceptance without producer-side counters; a
successful B1 API alone is not the requested SD-5 operator flow.
Every new B1/B2 formal candidate must bind its accepted append-only QA
baseline to a direct role-visible SHA-256 index before freeze, because
the Coder/Reviewer/Tester source snapshots intentionally omit canonical
`qa/` control files. Fresh current Runner/Gateway evidence remains separate.

## 2026-09-14 SD-5 A fourth formal Mock E2E block

Formal `20260914T072351Z-e2c8da4b` froze 2199 paths at
`63161707533b794eb1cad41c59f10a0fd988b4add87129d0a2bde37bd4bf9ba2`.
Planner READY, sole Coder `01a09ed1-6db0-79b3-b34f-302b3dbd53db`
IMPLEMENTED with zero edits, Reviewer PASS with zero findings and Tester
READY. Fixed Runner lint QA `20260914T073725Z-16a9` PASS. Fixed test QA
`20260914T073806Z-8de5` FAIL after 2349 Python and 70 Web unit tests
PASS: the legacy Mock Chrome fixture rejected the new protected
`GET /api/v1/completion-presets` request. No real Chrome case ran. The
Coder's exact same-session repair cycle correctly returned BLOCKED with
zero edits because the role workspace did not contain the correlated
Runner failure log; its scoped write list also excluded the legacy E2E
fixture. The formal is terminal BLOCKED, with no Gateway or original
publication. Preserve all failed QA/result logs. A new isolated successor
must inherit the exact terminal source, restore only accepted QA1012 as
its baseline, copy the bounded Runner failure evidence into role-visible
verification docs and add the missing Mock E2E response before fresh
Planner/Reviewer/Tester/Runner/Gateway gates.

Trusted Main has now done that preformal integration in `a_successor4`:
exact 2199-path blocked source clone, accepted QA1012 restored, 21 KB
Runner failure log and correlated QA/role artifacts copied under a
role-visible SHA index. Only the Mock E2E fixture changed. Its new
498-path binding proves all 349 non-test runtime paths remain unchanged.
Diagnostic Mock Chrome 1/1, both real browser cases 1/1 including actual
ZIP SHA equality and fixture cleanup, and lint/typecheck PASS. These
diagnostics do not replace fresh formal fixed Runner/Gateway evidence.

## 2026-09-14 SD-5 A fifth formal Gateway evidence block

Formal `20260914T080446Z-bced5e5c` froze 2212 source paths at
`5ab9b154bdabbeb075649e09ad4698aa0d038dafee7222a833bbc07c62f5a88a`.
Fresh Planner READY, sole Coder `01a09ef6-cd30-77d2-aa2c-4fcfd800fa51`
IMPLEMENTED with zero edits, Reviewer PASS with no findings and Tester
READY. Fixed Runner lint QA `20260914T081403Z-ddbe` PASS; test QA
`20260914T081443Z-661e` PASS after 2349 Python, 70 Web, one Mock Chrome
and both real Chrome cases. The current Completion browser downloaded the
same SHA-256 ZIP committed by the Delivery; fixture cleanup passed.
Semantic Gateway returned FAIL because its read-only assurance snapshot
did not expose the current `.loop`/QA logs. The formal is terminal BLOCKED,
not DONE, and no original code was published. Independent forensic checks
verified canonical Runner/QA/log/toolchain correlation, all 2212 source
paths byte-for-byte against the sealed assurance snapshot, the 21 retained
browser files, ZIP members, full MP4 decode and safe text. Those checks do
not override the semantic FAIL.

Trusted Main cloned that unchanged source into `a_successor5` with accepted
QA1012 only. The previous PASS logs, QA/report, Gateway finding, sealed
source and retained media audits are role-visible under a hash index. A
control-plane-only bridge now makes *new current* Runner evidence
inspectable to the fresh Gateway after canonical deterministic precheck;
the ignored read-only bundle is tamper-checked after the role and does not
change the source fingerprint. Fixed Runner argv/sandbox, sole Coder and
outer deterministic Gateway remain intact. The 499-path code map shows
only four control-plane/test changes; 319 product runtime paths retain the
real-browser-tested bytes. Diagnostic control-plane 64/64 and full lint
PASS. Fresh formal roles, Runner/Gateway, independent accepted-source and
artifact audit, then trusted CAS publication remain required.

## 2026-09-14 SD-5 A sixth formal control-policy block

Formal successor 5 `20260914T084649Z-30c94bf7` reached Planner READY,
then terminal BLOCKED at its sole Coder. The Coder found that the new
Gateway inspection-bundle tamper map covered files but missed an added
empty directory. It wrote a fix in its isolated coding snapshot; the
trusted outer policy immediately rejected mutation of frozen
`tools/loop_engineering/gateway_evidence.py`. No Coder artifact,
Reviewer, Runner, Gateway or original publication was accepted. Main
cloned all 2231 frozen source paths, accepted QA1012 and exact HEAD to
`a_successor6`, leaving the attempted coding snapshot behind. Main
reviewed the proposed fix and wrote a corrected standalone regression:
the attempted test tried to create a directory inside the production
read-only bundle and failed with `PermissionError`; the accepted test
uses a separate writable fixture. Control-plane 65/65 and Ruff/format
PASS. The 499-path code map has only bridge/test changes from the prior
freeze; all 319 product runtime paths retain the real-browser-tested
bytes. The new requirement explicitly tells Coder to inspect frozen
control-plane policy without writing; another defect must be reported
BLOCKED for Main's next prefreeze integration. Fresh full formal gates
remain required for SD-5 A acceptance.

Trusted Main then recorded the successor 6 baseline: 2238 source paths
before its receipt, QA1012 unchanged, exact accepted HEAD and ready
toolchain, with eleven named pre-receipt differences from the blocked
clone. The owner freeze sealed 2240 paths at fingerprint
`d00421ca89b2fb93533fbb8661c4316b16b4434fc0e9b8b34d0fe1b355ba8568`.
Formal `20260914T090014Z-4d329f03` is active. DONE requires fresh
Planner/Coder/Reviewer/Tester, current fixed lint/test Runner PASS,
current semantic Gateway PASS plus canonical deterministic correlation,
independent sealed-source and retained-browser/media audits, then trusted
code-only CAS publication. No current verdict is inferred from the
preformal diagnostics or historical browser evidence.

## 2026-09-14 SD-5 A seventh formal QA-visibility block

Formal successor 6 `20260914T090014Z-4d329f03` had Planner READY, then
sole Coder `01a09f29-d02e-76c3-82f6-8d1c9460f8e6` returned BLOCKED
with zero edits. No Reviewer, fixed Runner or Gateway ran. The Coder's
read-only source snapshot intentionally excludes the canonical
`qa/pipeline.jsonl` and `qa/test-report.md` control records. It treated
their absence as a provenance defect rather than using the inherited
role-visible QA1012 copies and hash index. The trusted delivery/candidate
QA files are present and equal, but the new successor will surface the
canonical and role-visible SHA-256s in one direct, indexed evidence
receipt and name the exclusion explicitly in its frozen requirement.
Main must clone the 2240 frozen source paths only, preserve the terminal
block and zero edits, then repeat fresh formal roles and fixed gates.
Neither the Coder's BLOCKED result nor historical synthetic browser
evidence grants acceptance or publication.

Trusted Main's successor 7 clone preserved all 2240 frozen source
paths at the same fingerprint, QA1012 and accepted HEAD, with no media,
real Project data or blocked coding snapshot. A direct role-visible
index binds both canonical QA hashes to the copied request/report files;
all 1012 unique request IDs match exactly one report heading. Preformal
full lint PASS. The 2250-path owner freeze has fingerprint
`27399c19c3f2ba79f6f2708b9e9cd4580024c245ae42fa42948fcaea8e261d09`.
Fresh formal `20260914T091046Z-d9794226` is active. Product runtime
remains byte-identical to the prior real Chrome-tested 319-path map;
current roles, fixed Runner, Gateway, independent audits and trusted
code publication are still required.

Fresh Planner READY, sole Coder IMPLEMENTED with zero source edits and
exact role-visible QA1012 correlation, and independent Reviewer PASS
with no findings. Tester/fixed Runner and Gateway are the remaining
formal gates; the current source is not yet accepted.

Tester READY selected fixed `lint` and `test`. Runner lint QA
`20260914T092125Z-ac45` PASS in 41.166s; full test QA
`20260914T092206Z-b541` PASS in 1154.64s with 2351 Python tests,
70 Web tests, Mock Chrome and two real-service Chrome cases. Its
post-cleanup verifier reports 16 committed Assets, 21 retained files,
11 Task attempts including three deferred attempts, fixture removal and
full MP4 decode PASS. Fresh Gateway, independent source/artifact audits
and trusted publication are still required.

## 2026-09-14 SD-5 A accepted publication

Fresh Gateway returned PASS/DONE; the canonical outer deterministic
Gateway accepted current QA/log/execution/source/toolchain evidence and
the read-only Gateway bundle. Independent audit matched all 2250
candidate and assurance source paths. Current retained media audit
checked SQLite/Task/Attempt/Asset lineage, 21 file hashes, ZIP contents
and checksums, SRT, safe text and full MP4 decode; ZIP SHA-256
`e6608b2595403aac8fc02f5195b445f9d560ce1184f7a8b4a08743dd3681d3fa`.
Trusted CAS published exactly 20 code paths (8 new) from the accepted
491-path SD-4 baseline. The resulting original 499-path code map is
byte-identical to the accepted candidate. The two formal QA records
were appended; original postpublication lint QA `20260914094429Z-c507`,
107 targeted Python QA `20260914094546Z-940f` and 21 focused Web QA
`20260914094821Z-e6f5` all PASS, with 1017 matched original QA IDs.
[Full acceptance and limits](../verification/stable-delivery-sd5a-accepted-2026-09-14.md).
Advance to B1 without promoting either experimental preset or claiming
true Delivery progress, real Chinese content/audio, or 2h/4h throughput.

## 2026-09-14 SD-5 B1 accepted publication and B2 handoff

First B1 formal `20260914T100238Z-15c257d5` remains terminal BLOCKED
at Tester after Reviewer found two P2 gaps. Fresh successor
`20260914T103344Z-8075efd1` reached DONE with sole isolated Coder
`01a09f7e-5bc5-7021-8563-c9399d4013d9`, Reviewer PASS/zero findings,
Tester READY, fixed Runner lint QA `20260914T110326Z-8381` PASS and
full test QA `20260914T110405Z-ce5b` PASS (2378 Python, 70 Web, Mock
Chrome and two real-service Chrome). Read-only Gateway PASS and an
independent deterministic reevaluation bound current QA, log, source,
toolchain and evidence bundle. All 2198 candidate/assurance source paths
matched; Coder changed only three scoped files.

Retained Runner media proved five independent OS processes, interruption
after an intermediate durable event, queued observation, a second attempt,
recovered ZIP/Asset lineage, unchanged source, full MP4 decode and SRT.
Trusted CAS published 17 code/test paths (4 new) from the original
499-path SD-5 A code baseline; postpublication 503-path map matched.
Two formal QA IDs were appended. Original lint QA `20260914T112732Z-c085`
PASS and targeted progress/contract/migration QA `20260914T112800Z-4840`
PASS (29 tests). Full acceptance and limits are in the
[B1 report](../verification/stable-delivery-sd5b1-accepted-2026-09-14.md).

B2 starts only from these accepted bytes. The current high-level `auto`
still uses foreground `run_pipeline(wait=True, finish=True)`, while the
independent `liveclip worker` already processes the durable Task kinds.
Freeze one idempotent `auto VIDEO` request identity and an authorized
`resume PROJECT_ID` intent lookup, then a read-only watch that survives
terminal resize, narrow Chinese text, non-TTY output and Ctrl-C without
cancelling work. Web must reconnect to the same saved goal after refresh
and display the B1 phase-local counters; only the API's bound successful
download URL may expose ZIP. Verify CLI and actual browser behavior with
an independent Worker and retained artifacts. SD-6 real content/audio
and separate 2h/4h inputs remain outside B2 synthetic engineering gates.
