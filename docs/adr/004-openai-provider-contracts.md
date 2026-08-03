# ADR-004: Timestamp-capable ASR and strict stateless Responses

Status: accepted, 2026-08-03

## Context

Official OpenAI guidance recommends `gpt-transcribe` for general file transcription, but documents word/segment timestamps only for `whisper-1` with `verbose_json` and `timestamp_granularities`. LiveClip needs evidence-backed source timing. LLM output is untrusted and must fit a closed EditPlan schema.

## Decision

Default `OPENAI_TRANSCRIPTION_MODEL=whisper-1` for v1's timestamp contract while documenting the official general recommendation and keeping the provider configurable. Unsupported word timing is explicitly unavailable; no time is fabricated. Use `client.responses.parse` with a Pydantic wire model, no tools, `store=false`, refusal/incomplete handling, local validation, at most one repair, then deterministic degradation. Use a configurable GPT-5.6-family example for LLM editing and never hardcode pricing.

## Consequences

The ASR default prioritizes editability over the newest general model and should be revisited when a recommended model exposes reliable timestamps or an approved aligner exists. Cloud behavior remains unverified without a key. Schema restrictions and provider response variants require contract tests after locking the SDK.
