# LiveClip v1 Product Specification

Status: authoritative product contract
Captured: 2026-08-03
Target completion state: `delivered`

Amendment, 2026-08-04: at the user's explicit request, the installed Codex CLI is an additional real editorial LLM adapter and the normal combined mode is OpenAI ASR plus Codex editing. Codex runs locally as a CLI but uses OpenAI cloud inference through saved ChatGPT authentication; it is not a local model and cannot replace timestamped ASR. This amendment adds capability and does not remove the official-SDK Responses adapter.

Amendment, 2026-08-05: the user explicitly selected OpenRouter `openai/whisper-large-v3` as the default real ASR paired with Codex. `openrouter-codex` therefore becomes the normal combined mode; direct OpenAI ASR/Responses and `openai-codex` remain supported alternatives. Only preprocessed audio chunks cross the OpenRouter boundary and may be routed to its upstream ASR host. The Key previously exposed in chat is invalid for acceptance and must be revoked; only a newly generated Key stored in ignored local environment is permitted.

Amendment, 2026-08-05: the user explicitly requires review proxies to be clean video clips without LiveClip-generated title or caption overlays. Editorial title, Hook, reason, risk flags and editable caption cues are separate metadata shown by CLI/API/Web. Only the post-review final render may burn the approved current revision's title and captions. This changes proxy presentation, not revision fencing, quality validation or final delivery requirements.

## Product outcome

LiveClip is a local-first Chinese livestream video clipping system for Apple Silicon macOS. A user supplies an absolute path to a 2–4 hour local video. LiveClip deterministically imports and analyzes it, uses configured cloud ASR plus OpenAI/Codex editorial understanding, produces 10–20 configurable highlight candidates (default duration 30–90 seconds), supports human review and revision, re-encodes approved vertical clips, and creates an immutable versioned delivery package.

The complete flow is:

```text
Ingest → Preprocess → Transcribe → Generate Candidates → AI Editing
→ Validate EditPlan → Render Review Proxies → Human Review
→ Final Render → Delivery
```

At minimum a successful delivery contains:

```text
delivery/
├── clips/
├── subtitles/
├── manifest.json
└── delivery.zip
```

## Supported user surfaces

All entry points call the same application services and domain rules.

### CLI

The CLI must work with neither API, background Worker, nor Web running. Foreground work still uses the same durable queue, lease, fencing, retry, and idempotency protocol as a Worker.

Required commands:

```bash
liveclip doctor
liveclip run --input /absolute/path/live.mp4 --top-n 15 --wait
liveclip status PROJECT_ID
liveclip clips PROJECT_ID
liveclip review CLIP_ID --approve
liveclip review CLIP_ID --start 125.5 --end 183.2 --title 修改后的标题 --approve
liveclip review CLIP_ID --reject --reason 内容不完整
liveclip rerender CLIP_ID --wait
liveclip deliver PROJECT_ID --zip
```

`run --wait` processes through successful review proxies and leaves every candidate in `pending_review`.

### REST API

Required routes:

```text
GET    /api/v1/health
POST   /api/v1/jobs
GET    /api/v1/jobs/{run_id}
GET    /api/v1/projects
POST   /api/v1/projects/import
GET    /api/v1/projects/{project_id}
POST   /api/v1/projects/{project_id}/runs
GET    /api/v1/runs/{run_id}
POST   /api/v1/runs/{run_id}/cancel
POST   /api/v1/runs/{run_id}/retry
GET    /api/v1/projects/{project_id}/transcript
GET    /api/v1/projects/{project_id}/clips
GET    /api/v1/clips/{clip_id}
PATCH  /api/v1/clips/{clip_id}
POST   /api/v1/clips/{clip_id}/review
POST   /api/v1/clips/{clip_id}/render
POST   /api/v1/projects/{project_id}/deliveries
GET    /api/v1/deliveries/{delivery_id}
GET    /api/v1/deliveries/{delivery_id}/download
GET    /api/v1/media/{asset_id}
```

Long-running commands return HTTP 202 with a resource ID and polling URL. Creation routes honor `Idempotency-Key`. Errors use a stable redacted JSON schema. The API binds to `127.0.0.1` by default, optionally requires a Bearer token, and permits only configured local CORS origins. Generated media is served by asset ID with HTTP byte Range support; arbitrary local paths are never a read API.

### Web review console

The React/TypeScript/Vite UI supports project creation from a local path, run configuration, stage/progress/error display, transcript viewing, candidate video preview, title/boundary/subtitle editing, approve/reject, rerender, delivery creation/version listing, and ZIP download. It must represent loading, empty, error, stale, disabled, retrying, and cancelled states. It does not copy backend state transitions or EditPlan validation.

## Runtime and engineering baseline

- Apple Silicon macOS; primary performance target M3.
- Python 3.12 and compatibility with 3.11+.
- Node.js LTS, FFmpeg, ffprobe, local filesystem, SQLite, OpenRouter and OpenAI cloud APIs.
- No local AI weights, Docker, external database, or external queue prerequisite.
- Modular monolith plus one independent Worker.
- FastAPI, React/TypeScript/Vite, Typer, SQLAlchemy 2, Alembic, Pydantic v2, official OpenAI Python SDK, pytest, Ruff, and structured logs.

Material compatibility changes require evidence, an alternative, and an ADR in `docs/SOLUTION.md`; capability may not be silently removed.

## Functional requirements

### Doctor

`make doctor` and `liveclip doctor` inspect OS/CPU, Python, Node/npm/Git, FFmpeg/ffprobe, exact `subtitles`, `drawtext`, `loudnorm`, and `silencedetect` filters, Chinese fonts, SQLite WAL/FK/RETURNING behavior, writable data directories, allowed media roots, and presence (never value) of OpenRouter/OpenAI configuration. They must attempt a real tiny `h264_videotoolbox` encode. Failure reports an automatic `libx264` fallback without blocking Mock functionality.

### Ingest and local file boundary

- Accept only an absolute regular media file whose strict real path remains under a strict real configured allowed root.
- Reject traversal, nonexistent paths, and symlink escape.
- Never alter or overwrite source media and do not copy it by default.
- ffprobe media and require both audio and video streams.
- Stream SHA-256 without loading a large file into memory; persist source stat identity and metadata.
- Give every Project an isolated generated-data directory.
- Recognize duplicate fingerprints for information/cache purposes without merging explicitly separate Projects.
- Recheck the referenced source for mutation before dependent processing and publication.

### Audio preprocessing and ASR

- Extract compressed mono speech audio with FFmpeg and stream file operations.
- Split by configurable duration with configurable overlap and a conservative size below the selected Provider upload limit.
- Persist a chunk manifest with absolute source offsets, duration, bytes, hash, and cache key.
- Persist `silencedetect` signals and resume from verified successful chunks.
- Cancellation stops subprocesses safely; partial files never count as success.
- Provide `ASRProvider` with OpenRouter, OpenAI and Mock implementations.
- Preserve Chinese text; support configured domain vocabulary hints through each Provider's documented parameter. For OpenRouter, use JSON `provider.options.groq.prompt`; never claim its ignored multipart `prompt` was applied.
- Save real segment times and, only when supported, real word times. Unsupported word timing is explicitly `unavailable`.
- Convert local chunk times to the canonical source timebase and deduplicate overlap using time and text evidence.
- Retry timeouts, genuine 429 rate limits, and retryable 5xx with bounded exponential backoff and jitter. Do not blindly retry authentication, quota, invalid model, or deterministic parameter errors.
- Default concurrency is one, configurable. Cache successful results and persist request count, retries, latency, audio seconds, request ID, and usage.
- Produce `transcript.json`, `transcript.srt`, and durable segments.
- Mock is allowed only for tests, development, and no-key Demo. Cloud smoke never falls back to Mock.

Current official API findings and URLs are recorded in `docs/research/openai-audio.md` before the real provider is implemented.

### Candidate generation and AI editing

Deterministic candidate generation must work without an LLM. It uses punctuation/sentence closure, pauses, speech density, volume/silence signals, topical continuity, context, duration constraints, hook signals, and expression closure. It first produces approximately 30–50 rough candidates for normal long input, records boundaries/text/context/rule score/reasons, then deduplicates by time overlap, text n-grams, and Jaccard similarity. A rule-ranked fallback selects top-N when cloud editing fails.

`LLMProvider` has OpenAI Responses, Codex CLI and Mock implementations. Both real implementations use strict structured output, send only one bounded candidate plus small context and quality signals, enable no tools, and treat transcript content as untrusted data rather than instructions. Codex uses controlled non-interactive execution and saved local authentication; it receives text only after ASR. They return value, hook and completeness judgment, boundary suggestions, score/rank, concise Chinese title, reason, risks, and whitelisted layout/caption/effect selections. Prompt files are versioned. Calls persist model, prompt version/hash, time, request ID, usage, and result status. Model and optional prices are configuration; prices are never hardcoded.

Current Responses API findings are recorded in `docs/research/openai-responses.md`.

### EditPlan and revisions

EditPlan is a strict Pydantic v2 model with exported JSON Schema. Its minimum fields are candidate ID, source start/end, score, title, hook, reason, layout, caption template, effect, risk flags, prompt version, model, and degraded flag. Allowed v1 enums are:

- layout: `vertical_blur_background`, `center_crop`
- caption template: `clean_zh_v1`
- effect: `none`, `fade_in_out`

Times are nonnegative, ordered, within source and configured clip limits, and model adjustments stay inside allowed context. Text fields have bounds. Extra fields and any paths, commands, code, script, SQL, or filter string are rejected. A structurally invalid model result gets at most one repair request, then a deterministic plan marked degraded. Every human change creates an immutable revision, including structured caption cues.

### Rendering and quality

`Renderer` has a deterministic FFmpeg implementation. Default review proxy is 540×960; final is 1080×1920. It supports 9:16 blurred background and center crop, preserves foreground aspect ratio, supports basic fades and loudness normalization, and outputs H.264/AAC MP4. Review proxies contain only the selected source video/audio in the chosen layout—no LiveClip-generated title or caption overlay. Their title, Hook, reason, risks and editable caption cues remain separate metadata. Final renders may burn the approved title and Chinese captions. All cuts re-encode; captions use clip-relative time.

FFmpeg is invoked as argv with `shell=False`. Paths are system generated. No model output becomes executable syntax. Logs redact sensitive/local details. A validated temp artifact is atomically published. VideoToolbox failure automatically retries with libx264. Paths are revision-specific and never overwrite a different successful revision. Any title, caption, or boundary revision marks older renders stale.

Every proxy and final render receives ffprobe stream/container validation, audio+video presence checks, resolution/orientation checks, duration tolerance, size floor, full decode to null, representative beginning/middle/end frames, a contact sheet, and heuristics for black/blank/wrong-aspect/severe-crop problems. Renderer-owned safe-area checks apply to final overlays; a clean proxy records them as not applicable. When an image viewer is available, Demo contact sheets are actually viewed and the observation is recorded; otherwise the report explicitly says manual visual inspection is pending.

### Review and delivery

CLI and Web show the candidate, proxy, source interval, score/title/reason/risks and support title/boundary/caption edits, approval, rejection reason, and rerender. Every action records the before/after revision, title, bounds, captions, decision/reason, and timestamp. Only an approved current revision with a validated current final render is deliverable.

Deliveries are immutable `v001`, `v002`, … directories. They contain only approved current revisions and fail if none qualify or any required final render is stale, failed, or missing. Creation snapshots inputs, builds and validates a temp tree, then atomically publishes without overwriting an existing version. Filenames are safe, stable, and readable; ZIP entries are path-safe. The manifest includes schema/project/delivery/version/timestamps/source name+fingerprint and, for every ordered clip, IDs, revision, title, filenames, source times, duration, score, review status, and SHA-256. A successful current snapshot makes Project state `delivered`; later edits do not mutate old deliveries and move the computed Project state back appropriately.

## State, persistence, and execution

Separate state machines are mandatory:

```text
PipelineRun: queued | running | completed | failed | cancelled
PipelineStage: ingest | preprocess | transcribe | candidates | edit | proxy_render
StageRun: queued | running | succeeded | failed | skipped | cancelled
ClipReview: pending_review | approved | rejected
Render: queued | running | succeeded | failed | stale
Delivery: queued | creating | succeeded | failed
Project (derived): imported | processing | pending_review | ready_for_delivery | delivered | failed
```

Transitions are centralized and tested. Required durable concepts include Project, SourceMedia, PipelineRun, StageRun/attempt, Task, Asset, AudioChunk, Transcript/Segment, CandidateClip, EditPlanRevision/captions, RenderJob, ReviewDecision, Delivery/DeliveryClip, ApiUsage, and idempotency records.

SQLite uses WAL, foreign keys, busy timeout, Alembic migrations, short explicit transactions, atomic task claims, default single heavy-task concurrency, leases, heartbeat, expiry, worker ID and fencing token, retry counts, crash recovery, safe cancellation, stage idempotency, artifact/input/dependency fingerprints, and persisted failure classification. External I/O never holds a write transaction.

## Security and privacy invariants

- Source video and all image/video/database/generated artifacts remain local.
- ASR uploads only prepared audio chunks.
- LLM receives only candidate transcript/context and necessary metadata.
- The ASR/API key comes only from local environment and never enters DB, logs, UI, errors, Git, or conversation requirements. Codex CLI authentication stays in the CLI credential store and is never copied into LiveClip state.
- Authorization headers/tokens/credentials are redacted.
- Allowed-root enforcement governs input reads; output paths are system-owned.
- Model output is untrusted and cannot control execution.
- `.gitignore` covers `.env`, DBs, media, caches, and deliveries.

## Required project commands

```bash
make setup
make doctor
make dev
make lint
make test
make demo
make smoke-cloud INPUT=/absolute/path/short.mp4
make smoke-codex
make smoke-openrouter INPUT=/absolute/path/short.mp4
make clean-demo
```

Setup is repeatable and creates an isolated Python environment, installs frontend dependencies, and prepares local directories. Dev starts API, Worker, and Vite and cleans all children on Ctrl+C. Cloud smoke fails clearly on missing configuration and never reports a Mock call as cloud success. Clean Demo resolves and validates its target and may delete only Demo-owned content below `data/demo`, never HOME, repository root, project data, source directories, or allowed roots.

## Demo acceptance

Without an API key, `make demo` must generate copyright-free media and actually execute:

```text
test video → audio processing/chunks → Mock ASR → >=3 candidates
→ valid EditPlans + clean review proxies + separate editorial metadata → Demo-only approval
→ human-style title/boundary revision → old render stale
→ current final 9:16 render + relative SRT
→ manifest + delivery.zip → ffprobe + full decode + contact sheet
```

It prints project ID plus absolute final-video, contact-sheet, and ZIP paths. Any failed media/state/ZIP validation makes the command fail.

## Test and documentation acceptance

Automated tests cover allowed roots/traversal/symlink escape, streaming hash, ffprobe, chunk offsets, overlap deduplication, candidate boundaries/dedup/fallback, EditPlan schema/security, prompt injection boundary, SRT timing, safe FFmpeg argv and fallback, state transitions, atomic lease/recovery/idempotency, stale renders, delivery versions/manifest/hash/ZIP, and secret redaction. Integration tests exercise the complete Mock media and API flows. Frontend tests cover critical states/actions and one browser E2E. Standard tests never need a real key or livestream.

Required maintained documents are README, Product Spec, Solution, architecture diagrams, API, EditPlan, current OpenAI research, ADRs, plan rules, Living ExecPlan, STATUS, and this concise AGENTS guide.

Final acceptance requires actual successful runs of `make doctor`, `make lint`, `make test`, and `make demo`; cloud smoke is additionally required only when valid OpenAI configuration is available. A final independent read-only verifier classifies every requirement as implemented, tested, actually run, unverified, gap, or risk. Completion may be claimed only after real gaps are fixed or explicitly remain outside currently available credentials/hardware evidence.
