# LiveClip status snapshot

Updated: 2026-08-05 20:05 CST
Current milestone: M7 local implementation complete; external OpenRouter cloud acceptance is `not_run`
Branch: `master`
Baseline commits: `60283ba` (M6 implementation), `65b327e` (delivered documentation)

## Current outcome

The user-selected real chain is implemented as OpenRouter `openai/whisper-large-v3` timestamped Chinese ASR followed by the installed Codex CLI for editorial scoring. ASR converts speech to timestamped text; Codex only receives bounded transcript/context and cannot listen to video. Neither Provider executes model-generated commands or silently substitutes Mock evidence.

The prior 2.19 GB `input/7.28.mp4` run used Mock ASR and Mock LLM. It proves read-only ingest, chunking, leases, persistence and proxy mechanics—not content understanding. The file has not been uploaded to OpenRouter.

## Completed in M7

- Added strict `openrouter-codex`, retained explicit `openai`, `openai-codex`, `mock` and development-only `mock-codex` modes.
- Implemented OpenRouter JSON `input_audio` with fixed official Base URL/model, Chinese segment/word timestamps, documented best-effort `provider.options.groq.prompt`, bounded retry/cache/resume and no Mock fallback.
- Required exact `X-Generation-Id`; ordinary, missing, invalid or overlong request IDs cannot become success evidence. Root duration and usage seconds/cost must be numeric, finite and nonnegative.
- Hardened Codex CLI 0.146.0 with 41 disabled tool features, real feature probe, read-only/no-approval execution, ignored user config/rules, credential/proxy-stripped child environment, executable/profile fingerprint and per-call identity fence.
- Rejects Codex tool items, oversized JSONL and truncated stdout; repair cancellation retains every prior call record. Real Codex smoke requires a thread/correlation ID and positive token usage.
- Added Provider readiness to Doctor/API/Web, readiness-safe Idempotency-Key replay, OpenRouter integration/smoke commands, privacy documentation, ADRs and regression coverage.
- Preserved the user-owned `OPENROUTER_SETUP.md`; its old-Key-compromised warning is enforced and it is excluded from the M7 commit.

## Verified

- `make doctor`: READY; Python 3.12.13 arm64, Node 22.11 LTS, FFmpeg/ffprobe 8.1.2, SQLite 3.53.1, data root and Codex pass. Expected warnings: raster text fallback, missing regenerated OpenRouter Key, VideoToolbox failure with successful libx264 fallback.
- `make lint`: PASS; Ruff, 167-file format check, mypy over 104 source files, EditPlan schema drift check and TypeScript all pass.
- `make test`: PASS after the final generation-ID boundary fix; 498 Python tests in 134.75 seconds, 13 Vitest tests, one controlled Mock Chrome E2E and one real API + leased Worker + SQLite + FFmpeg Chrome E2E.
- Real hardened `make smoke-codex`: PASS with provider `codex_cli`, model `gpt-5.6-terra`, thread `019fd196-1428-7b10-a814-422f64f4f030`, input 8,899/output 105 tokens and a non-degraded validated plan. This proves the editor only, not ASR.
- `make smoke-openrouter INPUT="/Users/junhuaxu/Workspace/AGI/liveclip-ai/input/7.28.mp4"`: correctly stopped `not_run` before paid work because no new safe Key exists; no Mock fallback.
- Fresh `make demo`: project `demo_20260805T120045_8bc01ec3`, three candidates, status `delivered`, immutable v001 ZIP. Final is 1080×1920 H.264/AAC, 12.000 seconds; ffprobe/full decode/automatic quality/ZIP integrity pass.
- The fresh final contact sheet was actually viewed: Chinese title/captions stay in the portrait safe area; no black/blank frame, wrong orientation or severe crop. Its quality report records `viewed_passed`.
- Latest service health returns `mode=openrouter-codex`, `asr_provider=openrouter`, `llm_provider=codex_cli`, `llm_ready=true`, `asr_ready=false` and `OPENROUTER_ASR_NOT_CONFIGURED`; Web returns HTTP 200 at `http://127.0.0.1:5173/`.
- The Browser plugin exposed no attached browser instance, so no MCP visual claim is made. The checked host-Chrome E2E suites did launch and pass.
- Independent M7 Reviewer: PASS, P0/P1/P2 all zero after 102 focused tests plus the full static gate.

## External verification still pending

- Real `OpenRouter ASR → Codex → proxies` smoke and actual upstream/usage shape.
- Whether the Groq-specific vocabulary hint affects a target term; ordinary smoke only proves the chain.
- Authorized real-content run on `input/7.28.mp4`; run only after a short smoke and budget check.
- Representative 2–4 hour Apple M3 peak memory/runtime/disk measurements. The available host is Apple M2 and the fixture is 46:20.

## Blocking safety boundary

There is no safe OpenRouter Key in `.env` or `.env.local`. `OPENROUTER_SETUP.md` says the original Key appeared in chat and must be revoked. Do not recover, print or use it. The user must create a new limited Key and place it only in ignored `.env.local`; never request it in chat. This blocks paid cloud evidence, not the implementation, Demo, tests, Web or real Codex editor smoke.

## Worktree and service state

- M7 changes are ready for a scoped local checkpoint; no remote exists and nothing is pushed.
- `.env` is ignored, mode 600, selects `openrouter-codex`, allows repository `input/`, and contains an empty OpenRouter Key.
- User `input/`, generated data, databases, deliveries and browser evidence remain ignored. No source video was changed.
- `OPENROUTER_SETUP.md` remains an untracked user file and must not be staged.
- Local API, Worker and Web are intended to remain running after the final restart.

## Next concrete task

After the user revokes the exposed Key and creates a new limited Key, place it locally in ignored `.env.local`, restart `make dev`, run Doctor, then use a short allowed Chinese sample with `make smoke-openrouter`. Only after that succeeds should `input/7.28.mp4` be processed with `liveclip run --input ... --wait`.

## Resume instructions

Read `AGENTS.md`, `docs/PRODUCT_SPEC.md`, `docs/SOLUTION.md`, `.agent/PLANS.md`, `docs/exec-plans/liveclip-v1.md` and this file. Run `git status --short --branch`, inspect the latest commits and verify API health. Never use or expose the compromised OpenRouter Key, and never describe a Mock long-file run as AI content validation.
