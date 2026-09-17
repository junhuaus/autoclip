# SD-3: Bounded semantic work and action-specific readiness

Living ExecPlan prepared during SD-1B acceptance, 2026-09-13. Implementation follows
accepted SD-2 publication. No second product Coder or active candidate mutation is allowed.

## Outcome

A permanent provider failure starts at most the configured number of in-flight units.
Successful siblings become recoverable promptly even while another unit repairs slowly.
Restarting the same deterministic failed unit does not purchase another sole-repair budget.
Recovery checks only the capabilities needed by the remaining durable actions; a completed
ASR/semantic checkpoint does not require those providers merely to render or package.

## Verified current behavior

PipelineStageHandlers._run_v4_requests submits every uncached unit through a comprehension,
then consumes as_completed. Provider generation runs in workers, but domain validation and
provider.repair run inside the result-consumer loop. A slow repair therefore delays recording
other finished outputs and writing their valid cache entries. Provider calls are recorded
through StageStateStore with a mutation fence; cache files are written separately. The new
implementation must preserve or strengthen lease/cancellation fencing for both kinds of write.

The current immutable semantic failure audit already binds project/run/stage/generation,
request_fingerprint, provider/model/prompt, complete diagnostics and actual call IDs. It is
committed through the asset store and referenced by a task-attempt-owned manifest. Use this
existing authority when designing durable terminal-unit recovery; do not trust arbitrary JSON
with a matching filename or introduce a second unauthenticated negative-cache authority.

providers/readiness.py currently returns whole-mode readiness. CLI retry calls that whole
check, and API initially assesses the configured provider at startup. Stage providers are
constructed lazily from StageWork; bootstrap passes credentials according to the configured
runtime provider. Remaining-action readiness must agree with the immutable stored run and
existing runtime/provider compatibility checks, without silently changing a failed run's mode.

## Bounded implementation

1. Extract an internal unit executor covering generate, complete validation and at most one
   repair. It returns a typed result containing validated output or structured failure,
   actual call records, validation events and retained provider diagnostics. It performs no
   SQLite mutations or cache publication from worker threads. Keep schema repair versus
   domain repair mutually exclusive, and preserve all indexed evidence from SD-1A/B/2.
2. Keep at most K futures in flight. Process all completions from a wait batch, classify
   failures and record/cache completed successes before filling free slots. A global
   permanent error stops further submissions. Use typed failure codes/statuses, not model
   text, to classify global configuration/auth/permission failures. Per-unit deterministic
   invalid output is distinct from transient network failure and cancellation.
3. Publish success/cache and failure evidence on the owning thread under current lease and
   cancellation checks. An expired lease cannot publish a late result. A slow repair must
   not hold up sibling commits. Stop unstarted work on cancellation/global failure; join
   owned work using existing bounded provider timeouts and cancellable process handling.
   Preserve legitimate calls already executed, including existing after-cancel usage rules.
4. Persist terminal unit disposition using committed, run-scoped asset/task evidence and
   the exact request/provider/model/settings/prompt/schema/validation/transport identity.
   On retry, verify bytes, binding and complete previous attempt/repair accounting before
   deciding that a deterministic unit is exhausted. Rehashed, stale, foreign or incomplete
   evidence must fail closed. A partial initial-call/repair crash needs an explicit checkpoint
   policy; do not infer that no remote call occurred merely because no local result exists.
   No automatic stage retry may reset the semantic repair allowance. New configuration
   means a new explicit run identity; retain old evidence and never silently clear caches.
5. Add application-level remaining-action capability analysis from persisted stage/artifact/
   render/delivery state. New processing checks the needed ASR and semantic capabilities
   before paid ASR. Recovery with only rendering/packaging remaining checks local media,
   storage and requested packaging requirements, without unrelated ASR/LLM credentials.
   Keep legacy doctor/health representation meaningful; action readiness should explicitly
   name what was required, satisfied and blocked. Recheck at actual execution boundaries.
6. Local CLI version/login checks remain configuration evidence. Known deterministic
   permission/nested-execution restrictions are reported before expensive processing;
   do not remove sandbox restrictions or claim inference smoke without a real inference.

Main owns shared DTOs/ports, bootstrap, StageStateStore/asset integration, cache identity,
config/execution-contract decisions and any necessary migration. One isolated Coder owns
the bounded executor/provider/readiness implementation and its tests under an exact scope.
Before coding, freeze how execution policy identity affects old runs and all checkpoint
schemas. No new external queue, scheduler, dependency or provider is needed.

## Acceptance

- 28 pending requests, K concurrency, first global permanent error: started work is bounded
  by K; no full upfront submission, no new work after the error is observed.
- Block one repair on an event while another unit succeeds: inspect actual persisted cache
  and usage before releasing the slow repair. Restart uses the successful cache unchanged.
- Cover simultaneous success/failure batches, all-cache and zero-work cases, ordering,
  caller mutation, provider exceptions, network retry versus semantic repair and cancellation.
- Expire/revoke the lease before a late result: no late asset/cache or business-row commit.
  Preserve already valid sibling outcomes and real usage according to existing fences.
- Repeat recovery after deterministic schema/domain failure: no fresh initial/repair calls
  for an exhausted identical unit. Exercise crashes around initial receipt, repair start,
  failure commit and manifest association; uncertain remote execution is reported honestly.
- Rehash malformed or foreign durable failure evidence, change relevant identities, and
  verify rejection or explicit new-run behavior without bypassing the sole-repair contract.
- Stored processing checkpoint with only render/package pending and unavailable providers
  still completes the local remaining action. Needed missing credentials block before paid
  ASR. Changed runtime mode does not silently replace the stored run configuration.
- Existing SD-1A/B/2 checks and current synthetic artifacts remain required, followed by
  fresh read-only roles, allowlisted sandbox Runner lint/test, Gateway and trusted CAS publish.

## Progress

- [x] Inspect current request queue, repair consumer, failure audit and readiness boundaries.
- [x] 2026-09-13 Bind accepted SD-2 source and freeze execution/checkpoint/capability contracts.
- [x] 2026-09-13 Implement and run event-controlled concurrency plus persistent recovery diagnostics (9676/0bf6/5a39 PASS).
- [ ] Complete formal acceptance and inspect current media/SQLite/browser artifacts.
- [ ] Publish and update recovery documentation, then continue SD-4 durable completion.

2026-09-13 15:50 UTC: formal20260913T121731Z-09cfe619 stopped at code_cycle=1
on an external Codex usage limit; terminal state SHA256
a1be690ffe8d3c609c113d94839060d3e4ff479eac2f1892f595eafa76ad0287.
Only `tests/integration/test_semantic_unit_recovery.py` changed in its sealed coding
snapshot. The added migrated-journal test failed in a local disposable diagnostic
(receipt20260913154858Z-38e1). A bounded trace of the synthetic mock
(receipt20260913160253Z-1bc2) identified `AttributeError` at its assertion on the
nonexistent `StageWork.attempt_id`, before any Provider call. This is a test defect,
not evidence of a migration defect; migration constraints still need a corrected formal
test. The run configuration was V12, so an earlier old-config hypothesis was wrong.
No Runner or publication occurred. Credits are
available again; create a new isolated run without resuming that terminal session.

A separate disposable clone corrected only that test's attempt-ID lookup and reran
the real upgrade, constraints, FK deletion behavior, downgrade and re-upgrade:
QA20260913160353Z-ec63 PASS (1 test). This is useful migration evidence, but
it is outside the current formal candidate and cannot substitute for its Runner
test or publication gates.

Fresh isolated successor `.loop/development/sd3-quota-recovery-20260913` froze
2105 source paths at d20e19b8d2414c73970c8c2e140e22961038227ded99cd9bfecee39cf76a233b.
The 31-path patch reconstructed from all 60 review chunks; seven proof-authority
mutations rejected before proof emission, exact nested read-only Codex access verified
the full source and ten support files, and prepared acceptance scripts passed.
Formal20260913T155905Z-ef82ea7c is terminal BLOCKED at plan1/code2;
state SHA256 57973252d73596cdacc3d459e8e190e01a20a3983af92c255587fd76377d838d.
The independent proof observer PASS receipt20260913155916Z-b962 and formal
exit2 receipt20260913155924Z-bf83 are retained. No Runner, Tester, Gateway or
publication occurred. Coder code2 made no edits.
The six prior terminal runs and their evidence remain sealed; this is not yet SD-3 acceptance.

Reviewer cycle1 found a new P1 in cross-generation reuse: the outcome envelope is checked
against the requesting run's compatible config but not independently against the originating
PipelineRun config fingerprint and StageRun input fingerprint. Valid predecessor reuse must
remain possible when different generations legitimately have different stage-input hashes.
Both origin mutations need disposable SQLite regressions with zero new calls on rejection.
The exact-session Coder entered code_cycle2 under archived authenticated proof1-2,
read the complete Reviewer artifact and correctly reported BLOCKED. The protected
SemanticInvocationStore port exposes no authenticated originating config or stage-input
identity. Main must add this narrow contract in a fresh isolated successor, keeping the
Coder's 22-path scope and the original product unchanged. The corrected migrated-journal
test passed on a separate disposable clone (QA20260913161249Z-9e59), but still needs
formal Runner evidence. Preserve all seven terminal runs, captures and budgets.

No real/paid provider call is required for this engineering package. Real inference
permission, content quality, hardware behavior and performance remain SD-6 evidence.

## Implementation preparation during SD-2 formal acceptance

2026-09-13: read-only inspection confirms two additional integration requirements.
SqlAlchemyAssetStore.reserve may transfer a prior attempt's pending or committed Asset
ownership to a retry. Therefore a mutable Asset producer link alone cannot be the durable
authority for whether a logical semantic unit already consumed its repair allowance.
OpenAI's retry helper already classifies authentication, quota and other deterministic
HTTP failures, but StructuredLLMProvider currently wraps them all as PROVIDER_ERROR.
Preserve the trusted classification explicitly through the new executor. The structured
OpenAI cancellation branch also currently discards the helper's executed request counts;
the new path must retain actual call evidence without inventing server usage.

Proposed contract in [ADR044](../adr/044-bounded-semantic-invocation-recovery.md), to freeze
against accepted SD-2 before implementation:

- Add a versioned bounded-execution identity to new configurations only (successors of
  V10 and V11: V12/V13 with semantic-bounded-units-v1). Historical config loaders,
  fingerprints and dispatch remain unchanged.
  Bind this identity into every affected cache and durable unit key.
- Add a small run-scoped unit invocation journal with immutable task-attempt ownership,
  exact request identity and monotonic invocation number. Reserve before submission under
  the existing mutation fence. Its completion references a committed outcome Asset and
  exact expected bytes/hash; do not store transcript or model output in the journal.
- Treat a reserved invocation without an authenticated completion as uncertain remote
  execution. Recovery must stop with an explicit diagnostic; absence of a receipt does
  not authorize another initial call or repair. This conservative crash policy also
  covers a crash after initial output, immediately before repair, and after repair.
- A fully recorded transient failure may permit another bounded network attempt only
  when trusted phase evidence proves no semantic repair was started. Exhausted schema or
  domain repair, including a failed transport attempt during repair, cannot be reset by
  automatic or manual stage retry. Configuration changes create a new explicit run.
- Keep worker threads free of database and cache mutations. Each complete unit returns
  all initial/repair outputs, diagnostics, validation events and actual calls. The owner
  processes every completed future in a batch, persists successes and terminal evidence,
  observes global failures, then submits replacements up to K.
  Apply the shared executor to every new-profile path: mini's five-stage request batches,
  short-highlight Discovery windows, boundary-bridge Discovery and per-output V3 Boundary
  reviews. The last path uses a different dynamic response model per request, so the unit
  descriptor must carry its response model and validator rather than assuming one model
  for the entire batch. Single Global Review calls also need durable repair accounting.
- Success reuse must require the authenticated journal/Asset binding as well as response
  and domain validation. Pending files or independently rehashed JSON are not successful
  caches. Keep immutable outcome files under attempt ownership until fenced publication;
  a lost lease cannot create a recoverable success or update business state.
- Preserve budget-failure precedence across every completed batch. SD-2 Reviewer cycle1
  proved that a transient result arriving first can otherwise mask a deterministic budget
  rejection. The new executor must retain the corrected aggregation and all diagnostics,
  not reintroduce first-exception-wins behavior.
- Expose persisted run configuration and remaining actions through an application port.
  CLI/API retry must use one shared capability check before changing task state. Local
  render/package continuation does not require unused ASR/LLM credentials; a stage that
  actually invokes a provider still enforces the stored provider identity. Startup health
  is diagnostic, not permanent authority for later execution readiness.

This section records design preparation only. SD-2's active candidate, formal evidence and
scope remain frozen; no SD-3 source, migration or real database change has been made.

Task-brief requirement learned during SD-2: the unchanged Loop forwards only P0/P1 in its
automatic Coder rework context. Every SD-3 Coder invocation must also read the complete latest
Reviewer artifact named in that run's state, including P2/P3 and required acceptance details,
and report any unresolved in-scope item explicitly. This is a task-context requirement,
not a control-plane change, permission expansion or retry-budget reset.


## Owner-callback and cancellation implementation notes

Read-only inspection during formal SD-2 dd22b0c2 confirms StageStateStore has no explicit
public fence assertion: record_provider_calls(()) returns early. Add an explicit assertion
port and use it before every cache/outcome publication. Journal reservation and completion
must independently assert the complete current task/attempt/run/project-generation fence
inside their write transactions; an earlier check is insufficient.

The bounded executor must drain owned work even when an owner persistence callback raises.
Stop replacement submissions, signal the shared cancellation predicate, collect actual
completed/cancelled call records through the existing historical-attempt accounting path,
then propagate the original fence/persistence error. Do not commit later outcomes or caches
with a lost lease. Keep provider workers free of SQLite and cache mutations. Validate the
whole wait batch before admitting replacements, so a sibling global permanent error cannot
be hidden behind the first successful completion.

Provider evidence currently tests TaskAttempt.started_at <= ProviderCallRecord.called_at
<= TaskAttempt.finished_at. Capture the actual invocation start for the new execution
contract; completion-time stamping can discard legitimate slow calls after cancellation.
Do not fabricate counts for a journal reservation that has no authenticated provider receipt.
Reserved-but-uncompleted remains uncertain, including a crash before submission.

Actual API retry is src/liveclip/api/app.py:retry_run; it currently queues directly after
authorization. CLI retry performs whole-mode readiness before loading the stored run.
Expose a small application snapshot of immutable stored config plus remaining actions rather
than expanding the public RunSnapshot or duplicating stage inference in those entry points.
Only needed ASR/semantic actions enforce provider identity; local-only recovery constructs no
unused provider. A changed runtime setting must never silently replace the persisted model.

## 2026-09-13 active implementation checkpoint

SD-2 formal4aa6346f DONE, exact16-path publication81e0 and original458-path/18ASR postc3dc PASS.
Candidate `.loop/development/sd3-bounded-execution-20260913/candidate` preparation6cb9PASS
copies all2091source files and locked dependencies without setup/network. Inherited source
328a7e09e8d440b40e669d554a8ab5fc9fab1b9eee8589f95a1b4bf4f062baf9. Earlier preparatione47e
mistakenly compared the original data-inclusive fingerprint; its source-only copy is preserved
at sd3-preparation-sourcecopy-rejected-20260913T1004. All repository hashes/modes and Git diff
were identical;75untracked user-data files were correctly excluded. No formal run existed.

Sole main isolated Coder ownership is recorded in outer ownership.json (initial28paths plus
provider evidence test). Implemented foundations: V12/V13 types/loader (default not enabled),
explicit fence port, additive invocation journal/model/migration, complete-unit executor and
owner persistence/authenticated replay. Contract fixes at most3logical invocations, each only
after verified transient pre-repair evidence; deterministic/repair-spent or uncertain history
never permits another call. Journal hash is independent of Asset metadata. Actual adapter
call-start/cancellation accounting changes are being verified; mini five-stage dispatch is
connected for explicitly constructed V13 and its real Worker/FFmpeg diagnostic is running.

Diagnostics8046PASS:8event-controlled executor cases plus disposable migration metadata
parity. First actual journal97c5 failed5cases due an incorrect assumption about Asset's
expected_sha256 field, plus one lease-expiry fixture violated the heartbeat CHECK. Corrected
without changing the journal hash requirement; c5f1PASS all9actual SQLite cases (replay,
repair exhaustion, bounded transients, rehashed tamper, three crash boundaries, late lease
with historical usage/no committed outcome). Initial lint5358/a103 failures are preserved;
format/type corrections continue. No formal acceptance or original SD-3 publication.

Next: finish all short Discovery/bridge/dynamic Boundary/single Global paths, shared remaining-
action readiness and actual adapter evidence; run targeted/new plus compatibility diagnostics,
then freeze complete scope and use fresh unchanged formal gates/current artifacts.


## SD-3 complete implementation checkpoint

V12/V13 are now enabled only in the isolated candidate. Shared bounded execution covers
short Discovery/bridges/dynamic Boundary/single Global and all five mini stages. The stored
run/config/action snapshot is checked by one application service before CLI/API retry; the
repository compares the complete snapshot again inside its write transaction. Completed
provider stages and a committed EditPlan checkpoint permit local recovery with unavailable
providers. Actual provider boundaries recheck persisted mode/contracts; ASR checks semantic
readiness before expense. Local media/source/storage validation remains at execution.

Actual V12/legacy short six-flow diagnostic80efPASS14.141s and V13 mini120sec flow2d52PASS
29.917s. Adapter/executor91f5PASS16cases; readiness/config/actual CLI/API/local rendering plus
SQLite fast-sibling persistence37cePASS22cases26.319s. During an event-blocked sole repair,
the sibling's committed Asset, independent journal hash and ApiUsage are visible in SQLite
before release; authenticated replay adds no calls. Crash2599PASS13cases3.03s additionally
covers before/after repair and exhaustion association before the Stage failure manifest.
Full implementation lint775aPASS6.037s; final new/compatibility diagnostics are in progress.

Preserve diagnostic failures: ba73 zip strictness;5758 used nonexistent StageRunStatus.COMPLETED
(corrected to SUCCEEDED/SKIPPED, import-only actions handled);2a0a had five fixture failures
(mini algorithm, Asset kind and demo minimum duration),54passed. All corrected actual flows
pass37ce. These are implementation diagnostics; no fresh formal SD-3 run or original product
publication exists yet. Formal review must inspect all complete changes, current artifacts
and every severity of findings. No gate, capture bound, sandbox or retry budget is relaxed.

Next: finish the active compatibility run, retain current semantic journal fixture artifacts,
freeze the complete candidate/source/toolchain/scope and launch fresh formal roles and fixed
Runner gates. Source data, credentials, original dependencies and accepted SD-1A/B/2 remain
untouched. Continue SD-4 after acceptance and trusted publication.


Budget compatibility closeout:4fdd timed out240s after21lineage cases reached completion
markers because old budget fixtures still used current default configs, old as_completed
events and incomplete call metadata. Isolationa90e proved the first mismatch was the new
per-subject failure manifest shape. Preserve old V10/V11 cases explicitly and add V12/V13
cases with real journal completion events and exact phase/provider metadata. Fixture syntax
6a33 and zero-padded subject77b7 failures are retained. New-profile8d68 passed22cases and
exposed a missing explicit config fingerprint in the new per-subject failure audit. Main
SD3-MAIN-001 adds config/input/execution binding only for new profiles. Final0bf6PASS all48
old/new budget cases59.68s proves budget precedence, zero forbidden repair/model calls,
complete225errors and independent journal evidence for prior successful bridge calls.

Current29-path review support archives exact accepted SD-2 baseline files;22nonshared
Coder paths and seven main-owned DTO/contract/bootstrap/model/migration paths are explicit.
Thirteen journal fixtures now emit terminal SQLite backups plus hash-bound outcome manifests
for current formal retention. Final integration diagnostic and final lint are running;
formal baseline/toolchain freeze and fresh role execution have not yet started.


Final implementation diagnostic9676PASS97cases104.64s, including all21V9/V11/V13 lineage
empty/tamper paths, actual CLI/API/local recovery/mismatch,13retained SQLite journal fixtures,
repository retries and provider/executor evidence. Full lint5a39PASS5.737s; loop-doctor4f5aPASS.
The independent reading prerequisiteb783PASS reconstructs every29current file from56complete
chunks/224750UTF8bytes; context readere3b4 measures62806bytes. Index8bffPASS. No1MB capture
or2plan/3code budget changes. Main diagnostic summary hashes all receipts and logs.

Implementation is ready for formal handoff. Freeze and independently materialize exact source/
toolchain snapshots, create one fresh run, publish its current coding proof before Coder writes.
Main stops product writes while the exact scoped formal Coder owns its isolated workspace.
Keep current mini/browser/13journal-fixture observers bound to actual Runner QA and execution.
One main finding SD3-MAIN-001 is implemented/diagnostically verified; current formal gates and
independent final evidence must close it before trusted29-path publication.


Formal handoff:5c52PASS32.593s verifies2104source/29publication/22Coder paths and seven
protected shared paths. Frozen source5de3cd5d13285f8cc18b630c7dd7ffa064ec71d0bd3b142f12fecbb429485612;
sealed toolchainc16e68cc8df231df744d52ddb07c9046de21e314f4f00273882064815ef277e2
under cache939102d2abf4a0da. Fresh creatione548PASS creates20260913T104834Z-a6d6e678.
Formal loop and first-coding proof observer have started. Main performs no candidate or
coding product writes; record the exact Coder session from state before any resumption.
Current mini/browser/journal observers, final gate/evidence closeout and trusted CAS remain.

Formal cycle1/code1 Coder01a09a66-4958-7b53-bf82-c080b3467c54 completed two authorized corrections: cancel before Codex process entry, and retain initial evidence when schema repair cannot start. Three regression cases added. Current assurance46557ca4c32c87f655eadba4ee008dbeed4d0cb294309bbc706724f8dd8533bc, six unchanged V5 schemas cf26PASS. Fresh Reviewer is active; no SD-3 original publication. Outer fixture observers now reject pytest alias directories; stopped pre-test observer receipts remain separate from formal gates.

Formal a6d6e678 terminal BLOCKED, cycle1/code2: Reviewer found cross-generation history P1, post-launch process OSError accounting P2, and scheduling-dependent28-request test P2. Coder correctly refused stale5de3proof against46557source; no second-cycle writes or Runner gates. Outer proof refresh747c failed because the run was already terminal. Do not reset it. Isolationa5aePASS creates sd3-history-and-process-evidence-20260913/candidate with31explicit main-owned correction paths; no formal run starts until concrete fixes and persistent proof correlation pass.

Correction prerequisite ready:20SQLite casesaa02PASS, reviewed46557source counterexample0b98 reproduces six expected failures/one validPASS; corrected50case272dPASS7.16s, linte9c2PASS. Optional product process-start callback distinguishes actual post-launch I/O and cleans callback failure; no development Runner change. Bounded concurrency tests separate failure-first/full-batch/success-before-failure schedules. CurrentV13full Worker/FFmpeg plus20journal b12bPASS21cases31.13s; actual120s contact sheet viewed. Independentf7e0 validates20fixtures/27runs and exactlyeight intentional damage sets. Persistent per-cycle proof106cPASS verifies actual first/reviewed source maps and prepares rework proof during readonly review, not after repair starts. Formal31publication/22Coder/9protected scope will be frozen after full packet/source verification. Five findings remain pending fresh formal gates; old a6d6e678 stays terminal.

Fresh formal handoff: freeze6967PASS32.896s, source dd7f72609aef6536a8180a15027fa11824f32404bc644467f26cec909c746ed5,2105source/31publication/22Coder/9protected paths. Toolchain410f91584171d3a5a48f43d01e50cf5fe2fb82e29d6c015500c4c494904ed994. Complete60chunks/241329byte patch0854PASS; createc70bPASS creates20260913T111951Z-58ee94e9. Persistent observe_all_cycles started before formal loop and will refresh rework proof during readonly review. No candidate/main product writes while formal owns the workspace. Prior a6d6e678 and all non-PASS receipts remain unchanged.


### 2026-09-13 11:28 UTC — first-session handoff correction

Formal58ee94e9 is terminal BLOCKED, cycle1/code1, exactCoder01a09a83-ce59-73b1-8e2e-c6a2f5f65706;
no edits, no Runner commands, QA4f58exit2 duration359.995s. Persistent observerf8f5 correctly
published first proofdd7f7260,2105paths. Coder required its own ID in state before return.
Read actual workflow.py:74–78 and codex.py:126–143: first session ID is captured by the
trusted process and persisted after Agents.run returns. Waiting for it inside that first
call is impossible. This additional outer instruction defect is SD3-OUTER-002.

Successor distinguishes first launch from resume; first proof may carry null ID, every
resume must match the already-recorded exact ID. Source/workspace/toolchain/cycle proof,
22pathCoder/9protected scope, fresh roles, Runner sandbox and2plan/3code budgets remain.
No product corrections or duplicate product diagnostics are needed for this wording fix.
All31product/test bytes remain frozen from dd7f7260; preserve both prior terminal states.
SD-4 remains design preparation only; original product still accepted SD-2.


### 2026-09-13 11:31 UTC — corrected first-session formal started

Fresh formal20260913T113034Z-ff1afbdf is active from frozen91afa8b3 (2105paths).
Isolationa8fdPASS10.606s preserves terminal58ee94e9 SHA22edbf4a. Lifecycleb19ePASS
verifies actual null initial proof, returned exact session and control-plane assignment
ordering;469nondocument paths unchanged. Scope383aPASS31/22/9; completepatchccb8PASS
241329bytes SHA119d8290. Freeze c219PASS34.893s validates six schemas and independent
coding/assurance probes using sealed toolchain2c3b87b5. Create2229PASS6.435s.

Persistent first-launch/resume-aware proof observer begins before formal execution.
Allsix findings remain pending current gates. Prepared publication/closure syntax and
13actual document anchors9bb8PASS;95ff failed because that diagnostic was scheduled before
its formal manifest existed, and its receipt remains. No productcode changed or tests
relabelled; prior product diagnostic bytes remain exactly matched. Continue current formal
and current artifact inspection, then trusted publication before SD-4 implementation.


### 2026-09-13 11:37 UTC — explicit outer-path handoff prerequisite

Formalff1afbdf terminal BLOCKED cycle1/code1; exactCoder01a09a8c-797f-7523-92cb-3c879b210dbb,
noedits/noRunner. QA1a28exit2 duration300.701s; observer8e02 correctly archived first
proof91afa8b3. Full Coder log16541bytes shows searches only in cache parents and no read
of the workspace role index containing the actual outer path. PlannerT1 listed ../support
and local.loop paths that do not exist inside the materialized coding snapshot. This is an
additional concrete SD3-OUTER-002 handoff defect. TerminalSHA7bbc16aa remains immutable.

Successor sd3-explicit-handoff-paths-20260913 supplies every exact absolute support location
at the top of both task and index, requires Planner to preserve it, and allows context reads
before the pre-WRITE proof. Before formal, a read-only actual Codex session in the nested
probe workspace must prove support and current-source access. No model output supplies
Runner commands; source scopes/sandbox/budgets unchanged. Product469paths identical; no
repeat product implementation or original migration/publication. Preserve all three failures.


### 2026-09-13 11:44 UTC — actual nested access verified

Successor isolationbb91PASS10.267s preserves thirdterminalff1afbdf and unchangedproduct.
Scopea042PASS31/22/9; completepatchaba4PASS241329bytes SHA119d8290; context759ePASS62511bytes.
Freeze9376PASS33.272s source69474e9d,2105paths, sixunchangedschemas; independentprobes
20260913T114100Z-26ae466e in cache6ed0f96e33ae70ba. Sealedtoolchain0b0b70ae.

Actual ephemeral read-only Codex in coding-probe executed three successful read commands,
read both task/index with exactabsoluteouterpaths, hashed all10supportfiles and all2105source
paths withzero mismatches. Full36019bytecapture andfinalstructuredPASS are retained.
InitialouterQAbc85exit1 after87.449s because project minimal schema helper does not support
integer JSONSchema fields; the real process had completed and passed return/capture checks.
No control-plane change or repeat model session: independent5bd1PASS0.812s strictly checks
resulttypes/keys, everyfilebyte, allsource, threeactualcommandexits andcomplete turn.
Originalbc85failure retained. Accessproof records both currentresult/capturesha; formal
creation now requires this exact actual-access PASS and frozenprobe identity.

This is a handoff diagnostic, not product/formal acceptance. Allsix findings await current
gates and media/SQLite/browser inspection. Original product remains SD-2.


### 2026-09-13 11:52 UTC — compact metadata prerequisite

Formal5ca3725d BLOCKEDplan1/code0, noCoder/noRunner. Planner capture hit exact1000000bytes
after cat of baseline-summary plus oldformalmanifest produced436570bytes, dominated by
duplicate source/CAS maps. TerminalstateSHA c438e665b0d40a1c05a515373bb6fe97bd28091edf298b6380bf2003021168f8;
QA1b08exit2 duration249.847s. Observer6576endedwithzeroproofs, notacceptance.

SD3-OUTER-003: makeformalmetadata small with exactbaseline path/SHA reference; verify
full source/CAS maps through one trusted outerloader. Largeverifiedbaseline remains
programmaticinput with compact validationresults. Full31path/60chunk review and1MB
capture cap stay. No product/control-plane/scope changes; allfourterminalstates preserved.
Successor sd3-compact-handoff-metadata-20260913 needs exact-source nestedaccess and
metadata-loader verification before fresh formal. This is a concrete metadata correction,
not a reset of any old run or a product acceptance claim.


### 2026-09-13 11:57 UTC — compact handoff and current access PASS

Isolation7d1dPASS10.904s preserves fourterminalstates. Scope0a96PASS31/22/9; unchanged
completepatchdd77PASS241329bytes/60chunks SHA119d8290; contexta0c8PASS63258bytes.
Compactloader28dePASS usesactual2105source/458originalCAS maps; representative metadata
is3031bytes versusold432675bytes. Five negativecases reject foreignbaseline path, wrong
fingerprint, scopeexpansion, duplicate maps and baselinebyte mutation. Consumer scripts
forpublication/schema/postintegration now load complete maps only after SHAreferencecheck.

Freeze78f0PASS33.99s sourceedfcc5cb,2105paths, sixschemas unchanged; probe2075dbd9 in
cache510527ab150cfed9; sealedtoolchaine0b49820. Actualcurrentnestedreadonlycf4bPASS97.447s
verifies10supportfiles/all2105sourcepaths withoutmutations, complete37680bytecapture.
The outerdiagnostic now validates strictinteger fields directly and retains processmetadata;
previousbc85schema-helperfailure remains in its oldworkspace. Sevenfindings remain pending
currentformal productgates and artifactinspection. No originalcodepublication.


### 2026-09-13 11:58 UTC — formal4829347c active

Formal20260913T115737Z-4829347c started fromedfcc5cb aftercf4bactualnestedaccessPASS.
Createba70PASS6.313s writes3318byteformalmetadata and checks complete source/CAS map
roundtrip through the handoff loader. Preparedacceptancece13PASS verifies consumer syntax
and13actualdocumentanchors. Persistent firstlaunch/exact-resume proof observer starts
before formal. Full31pathreview/22Coder/9protected/sevenfindings/1MBcap andunchanged
Runnerconstraints remain; allfourpriorterminalstates/captures/budgets preserved.


### 2026-09-13 12:13 UTC — observer authority correction after formal4829347c

Formal4829347c BLOCKED, plan1/code2, Coder01a09aa5-ae90-78a2-bb2b-dc1d82e57814.
No source edits or Runner; QA6fa4 exit2/700.09s; terminalSHA5f95354e934d2fcc7d591981a59357c5aeacfad789877a8a3ee0880a723e7290.
Reviewer supports all product corrections but found one P1: observe_all_cycles.py consumed
unverified baseline maps/scopes. Coder correctly refused this Main-owned support change.
Observer0c42 completed; four artifact observers exited because no Runner began, with all
receipts retained. V5 schema check3dff passed on this now-unaccepted assurance.

Successor sd3-authenticated-proof-authority-20260913 isolated with4612PASS10.663s.
Product469paths unchanged. Observer authenticates exact baseline and toolchain receipt
references before reading them and at every publication, and embeds digests in each proof.
QAfcaaPASS7.086s rejects seven authority mutations before proof emission, including unchanged
fingerprint maps/scopes and post-load changes; full2105real paths verified. Both old proof
bytes were retrospectively authenticated, without changing the old BLOCKED verdict.
Initial diagnosticfc83 used an obsolete wrapper cwd and failed; preserved and corrected.
All five prior terminal runs remain intact. Seven findings still need current formal gates.


### 2026-09-13 12:18 UTC — formal09cfe619 active

Freezecc3fPASS32.961s binds source902952a07d4f60d01d5d3d5d58dc1697c92b3ea0d425c0b928542bbfea78fedd
and2105paths. Toolchainf444b2f5957712862c36042f35ee9f596f8eb0553df1172210e654d93f6c0995,
actual coding/assurance probes verified. Actual nested access71c1PASS87.174s,10files/2105paths
and42352bytecomplete capture. Create6e9dPASS6.632s creates20260913T121731Z-09cfe619.
Metadata3863bytes binds exact baseline and toolchain receipt SHA references. Prepared scripts
10c7PASS checks six acceptance/publication scripts and13current documentation anchors.
Authenticated persistent observer started before formal. Original product remains accepted
SD-2; seven findings pending current gates. No source edits, publication or SD-4 code.
The fresh eighth isolated successor `.loop/development/sd3-origin-identity-20260913`
adds only the Main-owned `SemanticInvocationOrigin`/`load_origin_identity` port to
the protected code paths before source freeze. Its source fingerprint is
411a328f1056a66d090d1acb512e274a3192d6e545927b5dffd2f4890a41cc65
over 2105 paths; original 458 non-document code paths remain unchanged. The
carried migration test passed locally (QA20260913162219Z-e8b8), 31-path packet
roundtrip db97 PASS, observer tamper0629 PASS, exact nested read-only Codex access
ef60 PASS and prepared acceptance1681 PASS. Formal20260913T162600Z-1276f1a3
is active with an independent proof observer, initially in read-only planning.
None of these prerequisites is a formal Runner/Gateway acceptance or publication.

Formal20260913T162600Z-1276f1a3 ended BLOCKED at plan1/code2; state SHA256
3286af0f8513d1b30f86f0506b9f51dbff1f7fc00f512598f7a5c54c500d738b.
First Coder changed only three authorized paths, adding transactional origin lookup,
per-envelope origin comparison and ten separately marked SQLite regressions. Reviewer
PASS/no findings reviewed31paths/65chunks. Local exact-source diagnostic a57b passed
all ten origin cases; f627 passed all31 recovery cases; ef7b passed lint. Formal
Runner lint029e and testb077 failed before mypy/pytest started because copied venv
entrypoints still referred to a historical long interpreter path, producing macOS
bad-interpreter/Operation-not-permitted errors. No tested artifacts, Gateway or
publication. Coder2 reported BLOCKED without edits; observerd632 PASS authenticated
both proof cycles. Formal7ac2 exit2 and all retainer failure receipts are preserved.
Do not resume/reset this terminal run. Main must stage an isolated trusted-toolchain
repair, prove sealed entrypoints execute under the unchanged deny-default Runner,
then start a fresh formal run with all current gates and artifact inspection.

Ninth isolated successor `.loop/development/sd3-entrypoint-recovery-20260913`
carries exact Reviewer-PASS source ca065, including the Main-protected port and three
authorized Coder files. Main rewrote only 28 ignored project-local venv Python
entrypoints to shell trampolines that the existing trusted toolchain relocator
recognizes; no Runner argv, sandbox or control-plane code changed. New sealed
toolchain fingerprint35e2e3f050404d5804fa20c8226e2e5d845f87e8c361b3cce729c0adfe0aac5d
passes actual pytest/mypy/alembic/uvicorn version probes (QA5921). The fixed
allowlisted Runner must still pass lint/test inside its deny-default sandbox before
new formal creation. This local diagnostic is not SD-3 acceptance.

Ninth preformal fixed-Runner lint passed (QAd68a); its first complete sandbox
test executed 2038 cases, with 2015 PASS and 23 FAIL (QA6835). The failures
exposed two historical test contracts: the exact persistence table inventory
omitted `semantic_unit_invocations`, and 22 V4 cache-failure parameter cases
used the latest V13 config rather than the legacy V11 execution path they
assert. Main corrected only `tests/unit/test_db_models.py` and
`tests/unit/test_semantic_profiles.py` in the isolated candidate. Targeted
23-case recheck be38 PASS. Both paths are Main-protected, bringing the proposed
package to 33 paths/22 Coder/11 protected. Regenerate the packet and handoff,
then rerun fixed Runner lint/test before freezing; retain the failed diagnostic
and all QA receipts. No formal ninth run or original publication exists yet.

The corrected fixed-Runner preflight completed PASS (QA2e24) against source
0efdb4bd84d1d06d1f60ec913c74fb233f0a55704a437090faf8f5794e085f2f
and sealed toolchain35e2e3f050404d5804fa20c8226e2e5d845f87e8c361b3cce729c0adfe0aac5d.
Its lint1691 PASS and test44fb PASS included2038 Python,58 Web unit, mock-browser
and real API/Worker/FFmpeg E2E. The 33-path packet roundtrip cbb1 PASS.
These are complete preformal checks, not formal SD-3 acceptance. Freeze the
same source next, verify nested read-only access, then start a fresh formal run.
Freeze b78f PASS authenticated2105 source paths,33 publication paths and the
unchanged sealed toolchain against exact source0efdb4. A fresh read-only nested
handoff check remains before formal creation. No ninth Coder has started.
Fresh nested read-only Codex access5653 PASS checked all2105 source paths and10
support files. Create378f PASS instantiated formal20260913T171927Z-7344e2b7
on source0efdb4; prepared acceptance7caf PASS checked all13 original document
anchors and compiled trusted scripts. The proof observer began before formal
execution; Planner is now running. Retain and inspect only this run's evidence.
Planner1 READY authenticated2105paths, source/toolchain and33/22/11 ownership.
Coder1 exact session01a09bcc-449e-7e21-8a8b-12bb3ecaa5f9 returned
IMPLEMENTED with zero changes after full33path/67chunk reading. State moved to
fresh read-only Reviewer at17:28:28 UTC. Five run-correlated retainers are
waiting for formal Runner output. No formal lint/test or Gateway PASS yet.
Reviewer1 PASS/no findings after independently reading33paths/67chunks,
authenticating2105source paths and the sealed toolchain. State test_planning
began17:32:30 UTC; Tester and current Runner/Gateway evidence remain pending.
Tester READY. Formal lint2c8d PASS; test5729 began17:34:09 UTC in the exact
assurance-1-1 source. Five current-run retention observers match its QA request.
No current test/Gateway PASS or publication yet.
Test5729 finished PASS with2038 Python,58 Web unit and both browser E2E.
Gateway FAIL/BLOCKED on missing formal-artifacts/retention.json: the outer
legacy observer and mini observer launched during planning, froze code_cycle0,
and never matched assurance-1-1. Legacy 22 SQLite/66 redacted JSON files were
removed with Runner scratch, so cannot be attributed to that QA afterward.
Ninth terminal state SHA256 c2057f4ea3fc3a9a45bff8c1a4bd28108b18ac35f326907d0cbbb30232892843;
formal969b exit2, observer3b8c PASS, failed retention0547 and mini d11c
receipts preserved. Current journal20/27/eight intentional faults inspection
6edb PASS, origin10/five expected faults inspection0493 PASS; mini inspection
7a38 PASS from persistent test artifacts. These do not override missing legacy
evidence. Tenth `.loop/development/sd3-retention-cycle-recovery-20260913`
isolates byte-identical469 product/test paths, repairs only outer cycle lookup,
and will start observers after current Coder ownership is known. Repeat exact
toolchain, Runner, formal roles, full retention and trusted publication.
Tenth preformal correction: shared `current_runner_request.matching_test_request`
reads fresh state inside both legacy and mini observer loops. Actual ninth
QA regression9647 PASS rejects planning cycle0 and foreign/later cycles, matches
only the recorded assurance-1-1 test. Both observers will start after Coder
cycle1 is established. Entry-point/toolchain7b47 PASS; packet6868 PASS has
exact same33-path patch SHA as ninth; authority4ce3 PASS rejects seven tamper
cases. Fixed Runner preflight78d8 PASS on source9e6e4b07: lint73c4 PASS,
test7c3a PASS with2038 Python,58 Web unit and both browser E2E. Not formal
acceptance. Fresh source freeze and formal gates follow.
Freeze8beb PASS bound source9e6e4b,2105paths,33publication/22Coder/11protected
and toolchain326d1723. Nested read-only accessb4fc PASS verified ten support
files and all source paths. Create0e0e PASS made formal
20260913T180522Z-532b2b05; prepared scripts50ab PASS checks dynamic matcher,
recovery draft and13 original document anchors. Authenticated observer began
before Planner. Do not start the legacy/mini observers until code_cycle1 is
recorded, then verify both read current assurance test QA while it runs.
Formal tenth reached coding/1/1 with authenticated pre-write proof PASS. Five
retainers started after that transition; corrected legacy and mini observers
read current state each poll and were confirmed alive before Reviewer/Runner.
Verify their exact QA binding as soon as Runner test starts.
