# ADR052: Prompt-first Agent Runtime with a deterministic Python Harness

Status: accepted for an experimental parallel v2 path.
Date: 2026-09-26 PDT; amended 2026-09-28 PDT. Owner: Main.

## Context

The accepted dual-profile implementation is a fixed structured workflow. Python
schedules Discovery, linking, boundary review, Global Review, validation,
Top-N, rendering and publication. That path has real benchmark evidence and
must remain replayable, but changing editorial behavior often requires both a
Prompt change and a Python change. It also carries historical publication-risk,
approval and score-threshold semantics that the current clipping product no
longer wants.

The requested direction is an Agent architecture: Python supplies a reusable,
bounded Harness and safe capabilities, while versioned Skills, Prompts and
Context define discovery, semantic boundaries, merging, scoring, subtitle
calibration and titles. Editorial optimization should normally be a Prompt or
Skill revision. Deterministic code still owns facts that a model must not
invent, including cue identity, source time, configured duration bounds,
filesystem safety and FFmpeg execution.

## Decision

Add `agent_clipping_v2` as a parallel, non-default path. Keep the accepted v1
dual-profile path unchanged until v2 has real-provider and real-media parity.

The generic runtime exposes only a bounded action/observation loop, typed tools,
immutable artifacts, Context limits, cancellation, repetition/turn limits and
audit evidence. It has no hard-coded Profile names, risk taxonomy, approval
status, semantic duplicate rule, score threshold, review-stage graph or Top-N
policy. A Skill manifest supplies complete versioned instructions, ordered
Prompt resources and configuration. The exact bytes, order and configuration
are hashed into run identity.

The model receives the registered capabilities as native OpenAI Responses
function tools. It returns exactly one provider-native `function_call`; the
application executes that named tool and sends one `function_call_output`
correlated by the exact provider `call_id`. Completion is itself a strict
native `finish` function whose arguments contain stored Artifact IDs. Every
function object has `strict: true`; all object schemas forbid additional
properties and require every declared field. The internal `AgentTurn` form is
audit normalization only, not a simulated provider action protocol. Unknown
tools, malformed arguments, reused call IDs, repeated actions, excessive
Context and exhausted turn budgets fail closed.

The Harness owns orchestration and safe dispatch, but it does not contain the
application functions. Generic loop/limits live in `agent_runtime`; typed
capability implementations live in `agent_tools`; editorial decisions live in
the Skill. The LLM chooses which exposed function to call and supplies its
arguments, while Python executes it because a model cannot and must not execute
local code directly.

The first clipping Skill defines `short_highlight`, `mini_lesson` and optional
`full_lesson` Profiles in configuration, not Python enums. It asks the Agent to
score every technically valid candidate and leaves selection to the user. It
does not apply content-risk review, automatic approval/blocking or a minimum
editorial score. Cross-Profile variants may coexist. Subtitle calibration and
title generation are separate Skill responsibilities exercised through safe
tools: subtitle corrections must cite audio-grounded evidence and preserve the
original/corrected diff; titles must be novice-readable, attractive and
source-grounded, with alternatives rather than fabricated trend claims.

Python clipping tools may validate only executable facts: known cues, one
continuous interval, exact source timestamps and Profile duration membership.
They may expose literal search observations, but they do not infer topic
identity from timestamps, overlap, gaps, keywords or punctuation.

Each run has a durable, hash-bound identity over source Context, Skill,
provider/model, limits and native tool definitions. The Harness commits a
post-turn checkpoint containing exact events and Artifacts and seals a separate
completed result. The stateless Responses adapter commits full provider
input/output history, opaque encrypted reasoning and a pending native call
before local execution. A restart may replay a recorded response, but may not
repeat that provider request or change its call ID.

Agent rendering consumes only a completed result whose Skill hash, transcript
hash and Artifacts still validate. A verified subtitle revision takes
precedence over source text without changing timing; grounded title options
remain alternatives rather than approval. Rendering inventories and pins the
complete output tree, then atomically publishes one no-replace directory. The
offline-review exporter revalidates all hashes and evidence before publishing
its own page, media, audit inputs, checksums and verified ZIP.

For a full-transcript run, Global Review is an explicit Agent-authored Artifact
rather than a Python stage implementation. The model must submit one review row
for every saved candidate, including its semantic disposition, replacement and
cross-Profile links, opening/ending/padding checks and rationale. The clipping
tool can verify only conservation, references and requested-Profile presence;
after it accepts the ledger, candidate creation is frozen and titles may target
only final reviewed candidates. This makes an incomplete review observable
without moving semantic deduplication or boundary judgment into the Harness.
The review itself is included in `finish` and remains auditable alongside raw
tool events.

Offline review includes combined Markdown/JSON script exports in the verified
package. These files are derived from the effective SRT/candidate/title
Artifacts, labelled as untrusted transcript data and protected by the same
member hashes as the media. They support external model review without treating
model-facing transcript text as instructions.

## Consequences

Most future editorial improvements can change checked-in Skill/Prompt resources
without changing the Harness. Adding a genuinely new capability, such as
audio-grounded retranscription, still requires one safe typed tool or adapter;
the decision policy that uses that capability remains in the Skill.

The v2 transport can use direct OpenAI Responses or Codex App Server. App
Server reuses only the local Codex ChatGPT OAuth login and exposes LiveClip
capabilities through its native experimental dynamic-tool protocol; it does
not turn model text into synthetic tool calls. LiveClip disables all available
built-in execution/search/file/MCP/plugin/subagent capabilities, supplies an
empty private working directory and no network, and fails closed if an
unexpected built-in item appears. Python remains the sole executor of
registered LiveClip functions. The OAuth token is owned by Codex and is never
read into or copied through LiveClip state.

App Server dynamic tools and their resume surface are experimental. Therefore
the adapter pins and records the observed CLI contract, exact model settings,
tool-schema hash and disabled-feature fingerprint. A CLI/schema drift fails
before an existing run can resume. This limitation does not alter the accepted
v1 Codex path or make v2 the default. Real subtitle correction, title quality
and benchmark parity still require their own actual artifacts.
