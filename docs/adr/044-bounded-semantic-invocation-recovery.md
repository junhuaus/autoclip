# ADR044: Bounded semantic invocations and truthful recovery

Status: accepted and integrated; formal 20260913T180522Z-532b2b05 DONE. See the [SD-3 evidence](../verification/stable-delivery-sd3-accepted-2026-09-13.md).
Date: 2026-09-13. Bound to accepted SD-2 source c45b84519000a940f8b8474fd95f6fe73197e18096021d6c628b6b377328118e, formal20260913T093544Z-4aa6346f DONE, publication81e0/postc3dc PASS.

## Version and scope

New non-mini and mini configurations will use V12 and V13, respectively, extending the
exact V10/V11 models. Add `semantic_execution_contract = "semantic-bounded-units-v1"`.
Preserve all historical wire fieldsets, fingerprints and execution dispatch. The new
identity participates in every affected request/cache identity. Response schemas, prompt
resources, transport identity, quality rules and lineage contracts remain unchanged.

One shared bounded executor handles all new-profile semantic units, including short
Discovery windows, bridge Discovery, dynamic-schema V3 Boundary requests, single Global
Review and mini's five stages. Each unit owns its response model, immutable request and
validator. Generate, complete validation and at most one schema-or-domain repair execute
inside that unit. Worker threads return evidence; the owner performs durable mutations.

At most K futures are submitted. Process every completion in a wait batch, persist valid
successes and failures, observe permanent global errors, and only then fill free slots.
An observed global failure prevents replacement submissions. Authentication, permission,
quota and configuration classification comes from trusted provider status metadata, never
response text. Cancellation stops unstarted work and preserves evidence for actual calls.

## Durable invocation authority

Use a small `semantic_unit_invocations` journal rather than treating a cache filename or
an adoptable Asset producer link as permission to call a model. Each row binds the exact
run, stage run, semantic stage, subject, complete request key, execution contract, monotonic
invocation number and immutable producing TaskAttempt. Reserve it under the active mutation
fence before submission. No transcript, credential or model response belongs in this table.

A completed invocation binds a committed outcome Asset ID and its independently retained
expected hash. The Asset contains complete validated output or failure/repair evidence,
actual calls and all request/config/provider/model/prompt/schema identities. Recovery checks
the journal, attempt/task/run relationships, asset status/ownership/bindings, expected bytes
and schema/domain validation. Rehashed JSON or a changed Asset hash cannot rewrite the
journal's expected hash. New successes are reusable only through this authenticated binding.
Success from a prior generation may be reused only after exact compatible request identity
and source authority checks. Failure/repair exhaustion is scoped to its original run.

| Journal observation | Recovery action |
| --- | --- |
| No prior invocation and no valid reusable success | Reserve one invocation, then submit |
| Authenticated success | Revalidate and reuse, with no new provider call |
| Complete transient failure before semantic repair | Permit the next bounded invocation only after validating the entire prior history |
| Deterministic invalid output or any spent semantic repair | Preserve exhaustion; no new initial or repair call |
| Reserved invocation without authenticated completion | Report uncertain remote execution and stop |
| Stale, foreign, malformed, missing or conflicting evidence | Fail closed with a concrete recovery diagnostic |

The conservative uncertain state covers crashes before initial receipt, around repair and
between Asset commit and journal association. It does not claim exactly-once remote execution
or infer that missing local evidence means zero calls. A new explicit run can use changed
input/configuration; retrying the same run cannot clear this history. Network retries retain
their separate existing bounds and cannot replenish a spent semantic repair.

Artifact and journal publication must obey the current lease, cancellation and generation
fence. An expired worker cannot publish a recoverable cache, terminal outcome or business
row. Existing narrowly fenced accounting of calls already executed remains available after
cancellation. Complete diagnostics are redacted using the established credential rules.

## Capability readiness

Expose stored configuration and actual remaining actions through an application port.
One shared check is used by CLI/API retry before queue mutation and by the execution boundary.
Completed provider checkpoints allow local render/package recovery without unused ASR/LLM
credentials. Remaining paid processing checks its needed capabilities before ASR expense.
When a provider call remains, enforce the persisted provider identity and relevant installed
contracts. Login/version probes are configuration evidence, not inference success.

## Verification and consequences

Use event-controlled concurrency tests and actual SQLite leases to prove bounded start counts,
prompt sibling persistence, full completed-batch handling, cancellation and lease expiry.
Inject crashes at reservation/receipt/repair/Asset/journal boundaries and tamper with retained
evidence. Repeat recovery to prove no new calls after exhaustion or ambiguity. Exercise both
profiles, legacy dispatch and local-only remaining actions with absent provider credentials.

The additive migration is tested only on disposable databases and backup copies. It neither
upgrades old run identities nor starts processing. Fresh unchanged Coder/Runner/Reviewer/
Gateway gates and current artifacts are still required. SD-6 real-model, content, audio and
hardware evidence remains separate.

Implementation decision, 2026-09-13: semantic-bounded-units-v1 permits at most three logical invocations per exact run/unit, and only after fully authenticated transient failure before any semantic repair. This fixed policy is part of the versioned contract. Independent journal expected hashes remain authoritative; Asset.commit verifies supplied expected bytes but persists its ordinary sha256 field. Outcome files use runs/gNNN/semantic-units/<immutable-attempt-id>/<invocation-id>.json so temp cleanup cannot erase recovery authority. No real-project migration has run.

Pre-acceptance correction: compatible prior-generation success authenticates the complete originating invocation history and all predecessor outcome bytes, including transient evidence. The product subprocess helper reports successful Popen through an optional trusted callback; new Codex accounting distinguishes startup failure from later pipe I/O. Legacy callers omit this callback. No deterministic development Runner or sandbox policy is changed.
