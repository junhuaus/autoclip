# ADR043: Versioned lossless semantic transport and request budgets

Status: accepted and integrated; formal 20260913T093544Z-4aa6346f DONE. See the [SD-2 evidence](../verification/stable-delivery-sd2-accepted-2026-09-13.md).
Date: 2026-09-13. Built on accepted and published SD-1B runtime.

## Decision

Keep the exact V8 and V9 configuration models, persisted field sets, fingerprints and
historical request/cache behavior. New non-mini configurations use V10, derived from V8;
new mini configurations use V11, derived from V9. Both add the immutable
`semantic_transport_contract = "semantic-cue-table-v1"` field. The discriminated config
union and exact persisted loader accept all four current wire models. Historical V2–V7
adaptation still ends at V8. V11 retains the existing V9 lineage dispatch through inheritance.
Neither a database migration nor an upgrade of an existing run is part of this change.

Transport identity enters every affected semantic cache key and actual request boundary.
It is independent of CLI/provider identity, prompt resource identity, response schema,
quality validation and lineage contracts. Those existing identities retain their meanings.
New configurations and their actual transport/budget behavior publish as one package.

The pure transport codec accepts an authoritative JSON object and can replace recognized
cue-list occurrences with references to a single table of complete cue objects. Deduplication
uses exact canonical object equality, including all fields; IDs or text alone are insufficient.
Repeated occurrences and order survive. An explicit versioned outer envelope distinguishes
the encoded representation, and reference locations are explicit structural paths recorded
by the encoder rather than inferred from user strings or arbitrary object keys. Decoding
rejects malformed, duplicate, conflicting, non-cue or dangling reference locations and
reconstructs the exact original JSON object. Paths are in-memory data only.

Retain an immutable copy of that original authority for validation and sole repair. Choose
the smaller measured lossless wire form, accounting for its static decoding instructions.
Mock and validation paths reconstruct the same original object; model output never becomes
executable code, commands, SQL, filesystem paths or filtergraphs. Compression never removes
risks, routes, candidates, boundary evidence, invalid response parts or indexed errors.

## Budget boundary

Build each provider's actual outgoing representation once and measure it before I/O. OpenAI
uses the installed SDK strict response-schema conversion and the same instruction/input/
schema objects submitted to the SDK. Codex measures the exact prompt and strict schema file
bytes before spawning. Budget accounting includes instructions, the complete serialized input,
schema, output allocation and safety margin. The OpenAI allocation is the greater of its
actual 16,000-token request cap and the configured output reserve. The current Codex argv
does not enforce an output-token cap, so its configured reserve is explicitly an estimate;
do not invent a CLI option or describe that reserve as an enforced maximum. Token counts
are estimates from the configured tokenizer; they are not claims about exact server usage.

The gate applies to all new semantic initial calls and sole repairs. An oversized initial
request makes zero provider calls. An oversized repair preserves the real initial-call audit
and complete diagnostics but records no fabricated second provider attempt or usage. Network
retry, semantic repair and durable Stage retry budgets remain distinct. Historical object
requests retain their recorded behavior; no missing field silently opts an old run into V1.

Trusted planner guards may reject a request before wire construction. New profiles opt into
explicit SemanticPlanningBudgetError with the measured planner payload hash/bytes, prompt
and payload counts, configured reserve/margin and budget. Its measurement_basis is
semantic_planning_estimate; it does not claim actual wire/schema or provider allocation.
Stage persists the deterministic attempt-owned budget diagnostic before provider construction.
Legacy planners default to their exact ordinary ValueError behavior. Domain repair rejection
binds the executed initial call and full outputs/errors without double usage; mixed failures
prioritize deterministic budget rejection and scope no-call wording to the rejected request.

## Validation and consequences

Prove lossless roundtrips for all five mini stages and repair, including Unicode, extra cue
fields, overlapping contexts, repeated occurrences and literal reference-like data. Capture
the actual OpenAI HTTP body with an in-process fake transport and actual Codex prompt/schema
bytes to check measurement parity. Cover exact budget thresholds, huge instructions/schema/
Chain input, more than 200 indexed repair errors, caller mutation and zero-call rejection.

The ten-candidate, 270-second-context fixture must fit the configured budget after compaction
or fail explicitly before I/O. It is an engineering fixture, not a real model context or
quality benchmark. Preserve historical config/StageWork/cache identities and exercise new-run
identity separation in actual synthetic recovery. No dependency, model, response-schema or
control-plane change is needed. Formal gates, current artifacts and trusted publication
remain required; real model/content/audio/hardware evidence remains SD-6.
