# ADR046: Versioned high-level completion presets

Status: accepted and published for SD-5 A local engineering on 2026-09-14;
both presets remain experimental pending SD-6 real acceptance. See
[accepted evidence](../verification/stable-delivery-sd5a-accepted-2026-09-14.md).
Date: 2026-09-14. Baseline is published SD-4 source.

## Decision

The first high-level release presets are immutable IDs
`short_highlight_v1` and `mini_lesson_v1`. Their user labels are “短高光”
and “完整小课”; both remain explicitly experimental until SD-6 real
model/content/audio acceptance. A preset ID includes its version, so a
future changed recommendation receives a new ID rather than silently
changing an existing run's configuration. The two IDs resolve through one
application registry, using the existing `clip_profile_spec` durations:
45/60/90 seconds for short highlights and 90/180/300 seconds for mini
lessons. Both pin `semantic_windowed`, `general`, top 15, score threshold
75, full-context ratio 0.58 and model context 128000. The requested
selection policy may be `default` or `manual`; target is Delivery and ZIP is
true. Normal settings still supply model/ASR/provider-specific runtime
configuration. The resulting immutable PipelineRunConfig plus saved
CompletionOptions carries the exact contract. The registry never upgrades
an existing run or replaces a preset behind an old ID.

Expose authenticated `GET /api/v1/completion-presets` as a small safe list
of IDs, labels, durations, default selection and experimental status.
Expose authenticated `POST /api/v1/completion-goals/from-preset` with strict
`input_path`, preset ID and optional selection policy, and a required
`Idempotency-Key`. The API resolves the preset server-side, then calls the
existing CompletionService create transaction. Return the same 202
Location/Retry-After/CompletionGoalResponse contract as the lower-level
goal create route. Same caller/key/canonical high-level request replays the
original goal even after source or Provider readiness changes; changed body
with that key conflicts. Existing lower-level `/completion-goals` and
`/jobs` wire shapes and defaults remain compatible. A low-level caller's
optional `preset_id` is metadata; the high-level route is the source of a
server-resolved preset guarantee.

Web presents the two user choices and manual/default selection without
exposing schema versions, model context settings or developer vocabulary.
It sends the high-level request and owns one stable idempotency key for the
same pending canonical submission. On transport failure it reuses that key;
an intentional change or completed create gets a new key. Persist the
pending key with a hash of the canonical form in tab-scoped storage so a
reload after a lost response can retry safely, without storing credentials
or source media. The page reads the returned goal ID; it does not pretend
that 202 means processing or Delivery completed.

The CLI `auto VIDEO` and `resume PROJECT_ID` will consume the same registry
and CompletionService in SD-5 B, rather than duplicating preset values or
selection rules in Typer handlers. Their Worker lifecycle and terminal
observation contract are frozen separately before implementation. SD-5 A
does not add synthetic progress percentages. Complete copy/hash/ZIP counters
require fenced producer instrumentation and persistence in SD-5 B; a
heartbeat or elapsed time is not business progress.

## Boundaries and evidence

Preset resolution is pure and contains no credentials, local source paths,
model instructions or executable commands. Source validation, authority,
idempotency and transactional effect checks remain in existing SD-4
services/repositories. The API never accepts a client-resolved model
configuration for its high-level preset route. Web remains a client and
cannot claim a package before the bound Delivery ZIP Asset succeeds.

Acceptance requires fresh isolated Planner/Coder/Reviewer/Tester/Gateway,
fixed deny-default Runner lint/test, concrete lost-response replay and
conflicting-key cases, Web user-flow tests and current browser evidence.
Synthetic engineering acceptance cannot promote either preset out of
experimental status or establish real content quality. Main owns shared
DTO/schema/contracts, ADR, plan, source CAS and publication; the sole
isolated Coder owns the scoped implementation. No second writer shares a
file during a formal run.
