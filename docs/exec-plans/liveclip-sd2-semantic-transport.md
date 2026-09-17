# SD-2: Lossless cue transport and complete request budgets

Accepted and integrated, 2026-09-13: formal `20260913T093544Z-4aa6346f` DONE; all fresh roles, current lint/test, artifact inspection and trusted publication pass.
See the [accepted evidence](../verification/stable-delivery-sd2-accepted-2026-09-13.md). Six findings are resolved; 16 paths are published. Continue SD-3 without a milestone pause.
The [pre-acceptance plan](../verification/history/sd2-exec-plan-before-acceptance-2026-09-13.md) preserves all failed runs and diagnostics. Historical implementation checkpoints below remain historical.

## User outcome

Long semantic requests transmit repeated transcript cues once while retaining every source,
unit, route, boundary and risk. Every new initial/repair request is measured before model I/O,
including its actual instructions, serialized body, output schema, reserve and safety margin.
If it cannot fit, report an explicit budget error with zero attempted model calls; never
truncate authority, errors, candidate lists or final-boundary evidence to make it fit.

## Current code findings

The V4 Global builder repeats cue objects in candidate_contexts. Discovery, Link, Chain and
Boundary builders use local cue lists; the V5 wrappers add full source/risk authority.
Structured providers retain an immutable original request for validation and sole repair.
The existing _guard_current_repair_budget checks current-contract repairs only. It estimates
a Codex-shaped response schema even for OpenAI and does not gate initial requests. Codex
writes the actual prompt plus its strict schema; OpenAI Responses.parse converts the Pydantic
model through the locally installed SDK type_to_text_format_param before serializing the body.
Keep the current raw-response/SDK-error diagnostics, safety precedence and sole-repair behavior.

## Bounded implementation

1. Add pure pipeline/semantic_transport.py with explicit transport identity, reversible cue
   table encoding/decoding, deterministic serialization and immutable budget measurements.
   Preserve cue IDs, timestamps, text, order, duplicate occurrences and all non-cue fields.
   Reference indices are data; no model paths or commands are interpreted. Reject malformed,
   dangling, conflicting or ambiguous reference envelopes. Literal reference-like user data
   must roundtrip unchanged. Do not infer semantic equivalence from equal text or cue ID alone.
2. Encode recognized cue lists into one table; preserve the authoritative object payload in
   memory for local validation and repair. Supply explicit static transport-reading instructions
   to the model. The same decoder supports mock/object/compact/repair paths. Use the smaller
   lossless representation; retain all required evidence when compression yields no saving.
3. In structured.py construct the exact outgoing instruction/input/schema once, measure that
   representation, then submit those same objects. OpenAI measurement must match its installed
   SDK strict schema conversion; prove parity with actual captured HTTP request bytes through
   an in-process fake transport. Codex must measure the exact prompt and exact schema file bytes
   before creating/spawning the inference process. Include max(actual OpenAI output cap,
   configured reserve) and safety margin. Existing Codex argv has no enforced output-token
   cap; report its reserve honestly and preserve the validated argv. Do not claim token-exact
   server accounting beyond the configured tokenizer estimate.
4. Gate every semantic stage and both initial and sole repair before I/O. Preserve multipart
   safety rejection without automatic repair; explicitly supplied repair payloads still measure
   all indexed parts, immutable request and complete errors. Budget rejection
   preserves the initial call/audit, records a deterministic local failure and invents no second
   call. Keep network retries, structured repair and stage retries separate.
5. Main gives new runs an explicit versioned transport identity in immutable config and all
   affected cache/model settings. Exact V2–V9 snapshots, fingerprints, loaders, prompts and
   saved artifacts remain unchanged. Extend the discriminated config union and StageWork/import
   roundtrips; select new transport only for new runs. ADR043 freezes V10 (non-mini, V8 base)
   and V11 (mini, V9 base), both with semantic-cue-table-v1. The V5 lineage/quality output schemas
   need no change. No old cache entry can acquire new semantics by default injection.

Primary Coder paths: pipeline/semantic_transport.py, providers/llm/structured.py and focused
transport/provider tests. Payload-builder integration is allowed only when the generic lossless
boundary cannot retain the existing shape. Main owns config/domain identity/bootstrap, schema resources, ADR/this plan/STATUS and final integration.
The recorded formal Coder owns the listed planner/Stage/transport/provider/test paths exclusively.
Freeze the exact final scope before formal handoff; no control-plane, dependency or model changes.

## Evidence and acceptance

- Reproduce the recorded ten 270-second candidate/one-cue-per-second roughly145k-token sample.
  Record object/compact input, actual schema and reserve totals. Reconstruct exact object data.
  It must fit the configured budget or return an explicit zero-call budget error.
- Roundtrip all five mini semantic stages, legacy object representation and sole repair with
  noncontiguous/local IDs, overlapping contexts, altered boundaries, full V5 risk authority,
  Unicode/escaping, repeated cues and reference-like untrusted strings. No source graph loss.
- Captured actual OpenAI HTTP body and Codex prompt/schema bytes match the measured request.
  Cover initial/repair exact threshold, long instructions, large schemas, enormous Chain,
  >200 indexed errors and caller nested mutation. Overbudget means no HTTP/process call.
- Preserve V2–V9 config/StageWork/import/cache/history identities and all SD-1A/B acceptance.
  A new-generation synthetic flow exercises cache identity separation and recovery.
- One fresh formal plan/coder/reviewer/tester, unchanged allowlisted sandbox lint/test and
  Gateway; same frozen source/toolchain, full logs, current artifacts and original CAS.
  Do not replace deterministic evidence with token estimates or a semantic PASS.

## Progress

- [x] Inspect actual builder/provider/schema serialization and cache injection boundaries.
- [x] Bind accepted SD-1B source and create isolated candidate.
- [x] Freeze new immutable config/transport identity and implement one complete package.
- [x] Run focused wire-budget/roundtrip/recovery diagnostics.
- [x] Complete formal acceptance, inspect actual artifacts and publish.
- [x] Update recovery docs and hand off accepted source to SD-3 bounded queues and timely cache writes.

No paid/real-model batch is needed for this engineering package. Real model context behavior,
content quality, audio and hardware performance remain SD-6 and require actual evidence.

## Concrete integration notes from current V9 candidate inspection

All structured semantic paths share StageHandlers._structured_provider, including V3
Discovery/Global and _call_semantic_global, as well as the five V4/V5 mini stages. Inject
new transport identity at this factory and _semantic_model_settings, preserving the exact
old dictionary when no new config field exists. New cache settings also bind the full
context budget ratio. Mock must receive the same new budget/transport settings instead of
returning before their construction. Keep semantic evaluation constructors explicit.

SemanticCue fields are cue_id, segment_id, start_ms, end_ms, original_text, normalized_text
and normalization_note. Detect these actual complete cue objects; a codec looking only for
a text field would miss current payloads. Preserve all extra JSON fields and repeated list
occurrences without treating cue IDs as table indices. V5 rough/final artifacts bind the
full pipeline config fingerprint and have a separate profile-only artifact config, so new
transport identity does not require changing any of the six frozen V5 response/artifact schemas.

OpenAI currently submits max_output_tokens=16000. Codex currently has no output-token-cap
argument; preserve its strict read-only/no-tools argv and describe reserve accounting as
an estimate. The new initial budget error must retain a local initial_budget diagnostic
without inventing ApiUsage or a second Provider attempt, mirroring the accepted repair gate.

## 2026-09-13 implementation checkpoint (not accepted)

Isolated candidate `.loop/development/sd2-semantic-transport-20260913/candidate` inherits
accepted SD-1B source39405cbd and current main docs; setupf95f PASS. Implemented reversible
cue-table envelopes, strict malformed-reference rejection, immutable request snapshots,
actual OpenAI SDK strict schema/HTTP byte measurement, exact Codex prompt/schema measurement,
initial/repair zero-call budget gate, V10/V11 config/loader/bootstrap and stage-cache identity.
No V2–V9 schema or six V5 response/artifact schema resource changed. Legacy semantic-evaluation
constructors retain their existing object transport because their historical checkpoints do
not carry the new config identity; the product factory explicitly selects transport for V10/V11.

First codec/config/repair diagnostic4d39:66PASS. Wire fixture145988 object input tokens;
OpenAI complete estimate37861 and Codex37454 including16000reserve+1000margin (budget74240),
using a synthetic 270cue/ten-context fixture and small Answer schema. These are tokenizer
estimates, not server usage or real-model quality evidence. Actual SDK HTTP bytes and Codex
prompt/schema parity passed. Subsequent diagnostic failures were test-fixture expectations
(retry-policy field, multipart safety precedence and insufficient synthetic repair size),
retained in append-only QA; final focused/full/formal acceptance is still pending.

Focused216d209PASS; complete unit536a1750PASS; three-version mini b1873PASS68.02s;
lint773cPASS; follow-upcabd23PASS includes V9/V11 zero candidates and V11 rehashed recovery.
Historical V9 six-fault matrixdd17:6PASS26.13s; final freeze lint33c4PASS. New
transport budgets use configured values even when V10 selects the legacy validator. At that historical checkpoint main
protected config/bootstrap/Stage and seven integration/config test paths; formal
Coder owned codec/provider and their two focused unit-test files. That historical13-path scope,
full inherited hash map, immutable schema proof and fresh gate evidence are mandatory.

Pre-handoff inspection found old Stage repair entry points truncated errors/selected partial
repair authority before the new provider could measure them. Preliminary freeze17d08fbe
was archived with its unchanged nested source/toolchain snapshots BEFORE any formal run
was created; no role state, budget or gate was reset. Main corrected the three V3 Stage
repair entrances and V4 complete-audit dispatch for V10/V11, preserving exact V2–V9 behavior.
New actual shared-stage tests retain225large errors and all immutable authority; legacy
repair shape is byte-equivalent. Diagnostic8813:162PASS, final lint6992PASS. Fresh complete
baseline proof supersedes the archived preliminary proof;13-path publication scope unchanged.

Formal1551beb1 terminated BLOCKED after PlannerREADY and exact CoderIMPLEMENTED/no edits,
before any Runner. Outerd409 proved initial-budget errors were classified transient by the
main-owned Stage wrapper; only owned Reviewer groups were stopped (f157), preserving state,
source, captures and budgets. New isolated correction candidate9e6d inherits2086hashes and
local dependencies without setup/network. Fix adds deterministic initial-budget Stage code,
no automatic/manual unchanged retry, semantic-stage diagnostic identity and a fenced,
redacted, attempt-owned committed budget audit for V10 paths. V11 keeps its existing full
semantic failure audit. Actual V10/V11 Worker/SQLite tests and wire regressions7b42:26PASS.
Publication scope is now14paths; formal Coder owns11nonshared codec/provider/Stage/test paths,
main retains config/domain/bootstrap and integration. This is a verified prerequisite fix,
not a budget reset or prior-evidence substitution. Full fresh acceptance remains required.

Correction candidate final lint077bPASS; read-only loop doctor456dPASS with per-command
PYTHONDONTWRITEBYTECODE=1. No original setup or global environment change. That14-path baseline was frozen for now-terminal12065ad2. The current16-path scope above
supersedes it; prior gates and diagnostics do not establish current acceptance.
