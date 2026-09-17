# ADR-008: Tool-disabled Codex CLI as an editorial LLM provider

Status: accepted, 2026-08-04

## Context

The original v1 provider used the OpenAI Responses API through the official Python SDK. The user explicitly requested that LiveClip also use the Codex already installed and authenticated on this Mac as its editorial LLM. Codex CLI can consume text through non-interactive `codex exec`, but its documented first-message attachment is images, not audio. It therefore cannot replace the timestamped ASR stage: a real video still needs audio transcription before Codex can judge its content.

“Local Codex” means the CLI process and its saved authentication run locally. Model inference is still an OpenAI cloud operation through the user's ChatGPT/Codex entitlement; no model weights run on this Mac.

## Decision

Add explicit combined modes while retaining the existing adapters. ADR-009 later changes the user-selected default ASR but not this editorial boundary:

- `openrouter-codex`: OpenRouter Whisper timestamp ASR plus Codex CLI editorial editing; this is now the normal default.
- `openai-codex`: direct OpenAI timestamp ASR plus Codex CLI editorial editing.
- `mock-codex`: Mock ASR plus real Codex CLI editing; this is development-only and never proves that video speech was understood.
- `openai`: OpenAI timestamp ASR plus OpenAI Responses editing.
- `mock`: Mock ASR plus Mock editing for deterministic Demo/tests.

The Codex adapter uses `codex exec` non-interactively with the saved CLI login. It sends the bounded, explicitly untrusted candidate payload only through stdin; transcript text never appears in argv. Each run is ephemeral, ignores user configuration/rules, uses a private temporary working directory, `read-only` sandbox and approval policy `never`. Codex CLI 0.154.0 is pinned to reviewed profile `tool-free-v3`: the complete installed inventory has 140 features, only the required local `code_mode_host` transport is enabled, and 88 known authority-bearing surfaces are explicitly disabled. Version output is captured as bytes and validated exactly; any JSONL item other than agent message/reasoning is rejected. The adapter passes a strict editorial-only JSON Schema, captures bounded JSONL thread/usage evidence, performs local Pydantic/EditPlan validation, allows one repair, then degrades deterministically without claiming success. ADR049 records the formal acceptance and publication evidence; earlier 0.146/0.147 profiles are historical contract identities and are rejected by the current adapter.

Only an allowlist of non-secret, non-proxy environment variables reaches the child. `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `CODEX_API_KEY`, the LiveClip API token, credential-bearing proxy URLs, prompts, raw stderr and transcript text are not persisted. Resolved executable path, executable bytes/size, exact CLI version and security-profile version are hashed into the immutable Pipeline contract and rechecked before each call.

Provider readiness is observable through Doctor and `GET /api/v1/health`. Full-run creation fails before a Project is created when a required real provider is not configured. The Web displays ASR and editorial providers separately and disables processing when either is unavailable. Explicit Mock modes remain runnable but are visibly labelled.

## Consequences

Every Codex combination needs two independent prerequisites: a local ASR credential for the selected OpenRouter/OpenAI adapter and a logged-in Codex CLI for editorial calls. A ChatGPT login can satisfy Codex editing but does not authorize ASR. Conversely, an ASR key cannot prove Codex subscription/model entitlement.

The existing pure Responses provider and `make smoke-cloud` remain supported. `make smoke-codex` makes one real structured editorial call and requires a Codex thread ID, positive token usage and non-degraded non-Mock evidence. A full real-content validation still requires ASR; `make smoke-openrouter` proves the default combined chain, while a Codex-only smoke is not a video-content test.

Rejected alternatives are treating Codex as an audio transcriber, granting the model executable tools, inheriting arbitrary user Codex configuration/MCPs, passing transcript text in argv, or silently switching to Mock after failure.

Official and local verification evidence is recorded in `docs/research/codex-cli-editor.md`.
The accepted 0.154 profile and bounded real-source verification are recorded in
`docs/adr/049-codex-cli-0154-editorial-profile.md` and
`docs/verification/sd6-codex-cli-0154-accepted-2026-09-15.md`.
