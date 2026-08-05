# Codex CLI editorial-provider verification

Verified: 2026-08-05

## Official findings

Primary sources:

- [Codex non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode.md)
- [Codex developer commands](https://learn.chatgpt.com/docs/developer-commands?surface=cli#cli-codex-exec)
- [Codex authentication](https://learn.chatgpt.com/docs/auth.md)
- [Codex sandboxing](https://learn.chatgpt.com/docs/sandboxing)

The current official manual documents that:

- `codex exec` is the non-interactive interface for scripts and pipelines.
- `PROMPT=-` reads the prompt from stdin; `--ephemeral` avoids saving session rollout files.
- `--ignore-user-config` still permits authentication through `CODEX_HOME`, while preventing arbitrary user configuration from changing the controlled run.
- `--output-schema` constrains the final response to JSON Schema, `--output-last-message` writes that final response to a file, and `--json` emits JSONL lifecycle/usage events.
- `codex login status` exits successfully when saved credentials are present; Codex CLI supports ChatGPT subscription authentication as well as API-key authentication.
- `read-only` plus approval policy `never` is the documented non-interactive least-permission combination.
- The documented first-message file attachment is `--image`; there is no documented audio attachment or audio-transcription contract. This absence, together with the required timestamped transcript contract, means Codex CLI is not used as LiveClip ASR.

## Local verification

The checked host has `/opt/homebrew/bin/codex`, version `codex-cli 0.146.0`. `codex login status` returned success and reported a ChatGPT login without exposing any credential value.

An initial real strict-schema spike reached the provider and was rejected because the first schema did not mark every property required. The production adapter now supplies a smaller editorial-only strict schema whose property set exactly equals its required set.

After the first independent M7 review, the production profile was tightened to exact CLI 0.146.0, 41 explicitly disabled tool-capability features, runtime JSONL tool-event rejection, and executable/profile byte identity in the Pipeline contract. A host `features list` probe confirmed all 41 profile features were `false`. The post-hardening `make smoke-codex` completed a real non-Mock call:

```text
Codex smoke: succeeded
Provider: codex_cli
Model: gpt-5.6-terra
Codex thread ID: 019fd196-1428-7b10-a814-422f64f4f030
Usage: input=8899 output=105
Score: 86.0
Title: 直播开头三秒这样留住人
Boundary: 10000-60000 ms
```

This proves saved-login authentication, the reviewed tool-free profile, strict structured editorial output, local validation and thread/token evidence. The identifier is a Codex thread/correlation ID, not claimed to be an OpenAI HTTP request ID. It does not prove ASR or real-video content understanding. That requires `openrouter-codex` with a regenerated local OpenRouter Key and a real source video.

A second persistent `mock-codex` integration run exercised the real Pipeline/lease/database/editor/proxy path without pretending its transcript was real ASR. Project `f63068e81d3e4807bf6101be7055027e`, run `5b3efaffc1c241ed8eee78f997d35f16`, completed all six stages. Its EditPlan records provider `codex_cli`, request `019fd15c-ef7d-7911-affb-128069d85a26`, model `gpt-5.6-terra`, 11,321 input/161 output tokens, score 82 and title `3招让直播表达更完整`; `degraded=false`. The generated 270×480 H.264/AAC proxy is 32 seconds/1,497,842 bytes, passed ffprobe and full decode, and its contact sheet was actually viewed with correct 9:16 composition plus safe title/captions. This proves real Codex integration after a transcript exists. Because the run deliberately used Mock ASR, it still does **not** prove that the source video's speech was understood.

## Safety and operational conclusions

The production argv is system-owned and uses `shell=False`. Candidate transcript stays in a private stdin file and never appears in argv. The child receives an allowlisted environment that excludes OpenRouter/OpenAI/Codex API keys, LiveClip tokens and proxy URLs that may contain credentials. All known model command/file/browser/apps/plugin/MCP/tool capabilities are explicitly disabled, and an observed tool event fails the call; output can only populate the closed editorial wire fields and must pass EditPlan bounds/enum/text validation.

Failures, timeout, invalid structure and invalid bounds never become a claimed Codex success. Invalid output gets at most one repair; other failures immediately use a deterministic degraded EditPlan with explicit failure evidence. Cloud inference through the saved ChatGPT login remains subject to account entitlement, rate limits and model availability.

The API/Web `ready` fields are local startup preflight signals only: selected ASR readiness checks nonempty local key configuration, and Codex readiness checks exact executable/version/saved-login status. They do not claim live account quota, model entitlement or remote service availability. `make smoke-codex`, `make smoke-openrouter`, `make smoke-cloud` or a real task provides stronger evidence for its stated boundary.
