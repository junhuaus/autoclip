# LiveClip v1 Solution

Status: accepted implementation baseline; living document
Decision date: 2026-08-03

## User scenarios and success boundary

LiveClip turns a local Chinese livestream into reviewable vertical highlights and an immutable delivery archive. A CLI user can run the whole pipeline in the foreground; API and Web users enqueue the identical work for one independent Worker. Users first review clean vertical video clips alongside separate editorial title/Hook/reason/risk/caption metadata, then choose whether the approved final revision burns title and captions. Users can recover failed stages, change a proposed clip without mutating history, see stale media, rerender the exact current revision, and download a versioned ZIP.

The system controls execution. Cloud models may interpret content and propose a whitelisted EditPlan, but they cannot choose local paths, commands, filtergraphs, SQL, or code. Source video frames never leave the Mac; prepared audio is sent to the selected ASR Provider, and bounded transcript text plus metadata is sent separately to the editor model.

## Architecture

We use a modular monolith with ports and adapters, plus one Worker process and a separately built Web client.

```text
Typer CLI ─┐
FastAPI ───┼──> application commands/queries + UnitOfWork + TaskRunner
Worker ────┘                      │
                                 v
                     domain models/invariants/state
                                 ^
                                 │ ports
       SQLAlchemy/SQLite | filesystem | FFmpeg | OpenRouter | OpenAI | Codex CLI | Mock

React/Vite ──HTTP──> FastAPI only
```

Import direction is enforced:

- `liveclip.domain`: pure values, entities, EditPlan, caption cues, transition tables, errors. It imports no framework or adapter.
- `liveclip.application`: use cases, DTOs, repository/UoW/provider/renderer/asset ports, fixed pipeline orchestration.
- `liveclip.config`: environment parsing and safe public configuration views.
- `liveclip.db`: SQLAlchemy models, Alembic, repositories, SQLite queue and UoW.
- `liveclip.media`: allowed-root checks, streaming hashes, ffprobe, audio extraction/chunk manifests, silence signals.
- `liveclip.providers`: OpenRouter, OpenAI and Mock ASR adapters plus OpenAI Responses, Codex CLI and Mock LLM adapters.
- `liveclip.renderer`: deterministic layout mapping, raster text assets, FFmpeg execution, validation/contact sheets.
- `liveclip.review`: revision/review application helpers where they do not belong in generic commands.
- `liveclip.delivery`: immutable snapshot, manifest, filenames, ZIP validation and atomic publish.
- `liveclip.observability`: structured logging, redaction, usage and subprocess diagnostics.
- `liveclip.bootstrap`: the single composition root.
- `apps/api`, `apps/worker`, and `liveclip.cli`: thin entry adapters.
- `apps/web`: API client and review UI; no domain transition implementation.

The fixed six automated stages are `ingest`, `preprocess`, `transcribe`, `candidates`, `edit`, and `proxy_render`. We deliberately do not introduce a general workflow engine, broker, microservices, event sourcing, local vector database, or local ML runtime.

## Shared application-service boundary

Commands such as ImportProject, StartPipelineRun, CancelRun, RetryRun, ReviseClip, ReviewClip, RenderClip, and CreateDelivery live once in application services. Queries return sanitized DTOs. CLI commands either enqueue and return, or enqueue then run/poll through the same TaskRunner. They never directly call a private “CLI implementation” of a stage. API returns 202 for enqueued commands. Worker only claims Tasks and dispatches application handlers.

## Canonical time and identifiers

UUID4 strings identify resources. All stored and domain media times are integer milliseconds measured from the beginning of the original source. Field names use `_ms`. This avoids binary floating drift across revisions, SQLite, JSON, captions, and manifests. CLI/API decimal seconds are converted exactly at ingress; FFmpeg seconds and SRT timestamps are formatted only at adapter egress. UTC aware timestamps use ISO 8601.

The public EditPlan representation exposes both clearly named millisecond fields and computed decimal-second fields only where API ergonomics require them; there is never an ambiguous numeric `start` with undocumented units.

## Data model

The initial relational model is:

- Project: user-created workspace, current successful generation/run, current processing run, revision epoch.
- SourceMedia: one read-only resolved reference per Project, filename, fingerprint, stat identity, ffprobe metadata.
- PipelineRun: immutable configuration snapshot, generation, run state, progress and error.
- StageRun: logical stage state, input/output fingerprint, checkpoint and progress.
- StageAttempt: append-only lease/attempt/error/metrics audit.
- Task: operational queue item targeting a StageRun, RenderJob, or Delivery; queue state is separate from domain state.
- Asset: generated project-relative path, kind/MIME/size/hash/producer/input fingerprint and validation metadata. SourceMedia is not a downloadable Asset by default.
- AudioChunk: source absolute interval, overlap, generated audio Asset, size/hash/cache key/provider state.
- Transcript: versioned run output; TranscriptSegment and optional TranscriptWord hold real absolute times and timing availability.
- CandidateClip: rough bounds, transcript/context, rule score/reasons, dedup evidence, current EditPlan revision.
- EditPlanRevision: immutable validated plan, parent, origin (`ai`, `deterministic`, `human`), prompt/model/degraded metadata.
- CaptionCue: immutable per-revision structured relative cue; caption edits create a revision.
- ReviewDecision: append-only decision bound to an exact revision, reason and timestamp.
- RenderJob: exact revision, kind, dimensions/spec hash, render state, Asset, quality report/contact sheet.
- Delivery: unique Project version and immutable status/snapshot metadata.
- DeliveryClip: ordered immutable snapshot of clip/revision/render/title/bounds/filenames/hash.
- ApiUsage: provider/method/model/request ID/attempts/latency/audio seconds/token or duration usage; optional configured-cost estimate.
- IdempotencyRecord: endpoint scope, caller key, canonical request hash and resulting resource.

Fingerprint is informational on SourceMedia, not globally unique, so an explicit second import creates a second Project. `current_run_id` and generation boundaries prevent transcript/candidate rows from different attempts being mixed.

## State model

Allowed transitions are defined only in `domain/state_transitions.py` and are covered by table-driven tests. Database columns use check constraints. Services request a transition; they do not assign arbitrary status strings.

- PipelineRun: `queued → running → completed|failed|cancelled`; transient failure can be explicitly requeued on the same immutable run. A deterministic failure with unchanged input/config is rejected; changed input/config creates a new run/generation.
- StageRun: `queued → running → succeeded|failed|skipped|cancelled`; expired recoverable work is requeued.
- Review is the effective decision for the current revision. A new revision has no inherited approval and therefore computes `pending_review`.
- Render: `queued → running → succeeded|failed`; queued, running, succeeded or failed renders for a non-current revision become `stale` and stale is terminal.
- Delivery: `queued → creating → succeeded|failed`; succeeded snapshots are immutable.

Project state is derived for the current generation, never manually set as a second source of truth. Active pipeline/render/delivery work yields `processing`; an unrecovered current-generation failure yields `failed`; no completed generation yields `imported`; pending/all-rejected/no-approved clips yield `pending_review`; at least one approved current revision with all required current final renders yields `ready_for_delivery`; the latest successful Delivery whose snapshot fingerprint equals the current deliverable set yields `delivered`. Editing after delivery leaves the old version downloadable and recomputes a non-delivered current state.

## Pipeline execution, lease, and recovery

SQLite connections enable WAL, `foreign_keys=ON`, a configurable busy timeout, and `synchronous=FULL`. Application startup gates on the embedded SQLite runtime: it must support RETURNING and include the official WAL-reset race fix. Python sqlite3 legacy transaction control is disabled; SQLAlchemy emits explicit `BEGIN` and queue ownership uses `BEGIN IMMEDIATE`. SQLAlchemy uses a synchronous engine and short transactions. HTTP handlers may run DB work in FastAPI's thread pool; we do not maintain parallel async and sync repository stacks. ADR-005 and `docs/research/sqlite-concurrency.md` record the evidence and exact safe versions.

A Task claim uses `BEGIN IMMEDIATE`, recovers expired eligible leases, selects one dependency-ready task whose `not_before` has passed, and atomically updates it with worker ID, random lease token, heartbeat and expiry using `UPDATE … RETURNING`. Heartbeat and completion require `(task_id, worker_id, lease_token)`. This fencing prevents an expired old worker from publishing after a replacement has claimed the task.

No FFmpeg, filesystem hash, or network call holds a database write transaction. Before external I/O, a short transaction reserves a pending Asset with producer attempt, expected path and input fingerprint. Asset authority is derived in that transaction through the active TaskAttempt → Task → PipelineRun → Project graph; caller project/generation/candidate/revision values are checked assertions, never trusted authority. Only a later failed or lost attempt of the same logical Task may adopt an exact matching pending reservation. Each attempt writes a system-owned temporary directory. The handler checks cancellation between bounded operations and terminates an owned subprocess group when necessary. Running cancellation remains a request until the owner acknowledges that safe boundary; queued work may cancel immediately. The handler validates results, verifies that it still owns the lease and relevant revision/generation, then publishes through a same-directory atomic hard link that fails if the immutable destination already exists. It never uses a replacing rename for revision artifacts. Lost-lease or outdated results become diagnostics/orphans, never current success.

Path existence or a prior hash is not a byte-identity fence. Security-sensitive inputs and outputs are opened through a component-anchored no-follow chain and held as pinned regular-file descriptors across validation, subprocess execution and publication. Evidence binds descriptor identity, size and SHA-256. Render validation sends the same pinned bytes through ffprobe, complete decode and representative-frame extraction, then publication and Asset commit require that verified SHA. Committed stage dependencies are resolved through their exact producer Task and project/run/generation scope, re-opened no-follow, and checked against committed size/hash before a Provider or FFmpeg process can consume them. ADR-007 records this byte-binding model.

One heavy task is claimed by default. `proxy_render` renders candidate proxies sequentially within the stage and checkpoints each RenderJob, avoiding parent/child queue deadlock. Before FFmpeg I/O, each proxy RenderJob is durably inserted and transitioned `queued → running`; success requires committed video/subtitle/quality Assets, while failure, cancellation and lease expiry persist a safe error code. Cheap API queries remain concurrent.

Stage completion is not inferred from arbitrary file existence or a generic Asset row. Each stage has a typed checkpoint contract covering its committed artifacts and required domain rows. The StageStateStore validates that checkpoint and the active Task/Attempt/Run/Project generation under the same `BEGIN IMMEDIATE` transaction before mutating StageRun, PipelineRun, Project or downstream Task state. A committed checkpoint is accepted only when every required Asset still resolves to its canonical project-relative endpoint, is a regular no-follow file, matches committed size and SHA-256, and belongs to the expected producer Task. A legacy SourceMedia row without verified video/audio stream indices cannot satisfy ingest recovery; a matching modern ingest must explicitly upgrade it from actual ffprobe evidence.

Stage retry uses the same PipelineRun and resumes the first failed/incomplete stage when configuration and input fingerprints are unchanged. Persisted PipelineRun configuration is a closed v2 wire snapshot: provider adapter contracts, Prompt version/hash, editorial wire schema, EditPlan schema, vocabulary, retry/timeout/concurrency and optional price inputs all participate in a canonical SHA-256. Every database load checks the exact field set, schema version and stored fingerprint before a handler or provider can run; legacy/tampered snapshots fail deterministically rather than inheriting current defaults. A different configuration creates a new PipelineRun/generation. Deterministic input/configuration failures require a corrected input/configuration and new generation. Two explicitly classified local implementation failures (`UNEXPECTED_STAGE_ERROR` and `EDIT_OUTPUT_INVALID`) may be manually requeued on the same immutable run after the installed code is repaired; the bounded retry can fail deterministically again and does not reinterpret bad media as transient. Genuine transient errors—including bounded ingest, preprocess and validation subprocess timeouts—respect retry count and `not_before` backoff.

## Idempotency, cache, and artifact graph

File existence is insufficient for success. Every stage input fingerprint includes relevant source/artifact hashes, configuration, algorithm/schema/prompt version, provider/model, and tool version. A cache hit requires either an existing succeeded database fact or a crash-recovery replay of a complete immutable cache record. Cache records are opened through a component-by-component `openat`/`O_NOFOLLOW` chain, size-bounded, strictly parsed, matched to the source/provider/model/prompt/contract identity and checked against their canonical result SHA-256. A present but unsafe, malformed or mismatched record fails before any paid call. Cache bytes are written before the database callback so a crash in that narrow window can resume without paying twice; replay promotes success only through the current TaskAttempt/generation fence and reuses the original immutable call ID.

Representative fingerprints:

- ingest: source SHA/stat and ffprobe contract version.
- preprocess: source SHA, chunk/overlap/audio/loudness settings and FFmpeg version.
- transcribe: chunk SHA, provider/model/context/timestamp mode and adapter version.
- candidates: transcript SHA, duration/top-N settings and algorithm version.
- edit: canonical candidate/context, prompt file SHA, model and EditPlan schema version.
- render: source SHA, exact revision/captions, layout/dimensions/font hash/effect/codec spec and renderer version.
- delivery: ordered approved revision+render hashes, manifest schema and ZIP setting.

Artifacts use immutable revision/generation-specific system paths. Verified ASR chunk results may be reused across later generations of the same Project only when the chunk bytes, source interval, Provider/model and complete adapter contract identity match cryptographically. The current cache identity is a versioned SHA-256 binding both the deterministic preprocessing `cache_key` and the published chunk-byte SHA-256; a real chunk with either field missing or malformed fails closed. The current generation records no new Provider call for such a hit; original paid-call evidence remains attached to the generation that made it. Cross-project global media caching remains deferred because it complicates privacy and lifecycle management.

## Ingest and source mutation protection

Allowed roots are strict existing directories resolved at configuration load. An input must be absolute, exist, be a regular file, and after `resolve(strict=True)` remain inside at least one resolved root using path-component ancestry—not string prefix. This rejects `..`, prefix tricks, and symlink escape.

We save resolved path, size, mtime nanoseconds, inode/device where available, streamed SHA-256, selected video/audio stream indices, normalized rotation/display dimensions, frame-rate evidence and ffprobe metadata. Expensive stages pin the source endpoint, validate stat identity and hash it once per stage before per-clip work; per-clip checks reuse that evidence instead of repeatedly hashing a multi-gigabyte source. A changed source fails deterministically as `SOURCE_CHANGED`. The source is passed read-only to ffprobe/FFmpeg; LiveClip never opens it for write. Stream mapping is explicit, so a non-first/default audio stream, rotation metadata and VFR timing do not silently change renderer input.

Generated Asset serving re-resolves the database project-relative path beneath the configured data root, rejects symlinks/outside paths and only serves explicitly allowed media kinds. Single-byte-range responses support 206/416, `Content-Range`, `Accept-Ranges`, auth, and bounded streaming. A short-lived HMAC URL binds GET, canonical path, purpose/asset ID and expiry so HTML5 video can seek without placing the long-lived Bearer token in query parameters; streaming reopens no-follow and rechecks file identity around the read.

## Audio and ASR decision

Preprocessing produces mono compressed `m4a` (AAC) or `mp3` chunks, both in the common documented format set, with time overlap and a conservative byte ceiling below 25 MB. Chunk length is additionally capped by configuration. FFmpeg emits to a temp file; a manifest stores absolute millisecond bounds, overlap, bytes, SHA and cache key. `silencedetect` output is parsed into structured source-time intervals.

The user-selected default real path is `openrouter-codex`. OpenRouter receives fixed-model `openai/whisper-large-v3` JSON `input_audio` M4A chunks and returns `verbose_json` with required segment and requested word timestamps. The official STT documentation records that multipart `prompt` is ignored, so configured vocabulary is sent only through `provider.options.groq.prompt`. This is best effort: only a matched Groq upstream receives that option, and ordinary smoke success proves the request chain—not that a vocabulary term was applied; a target-specific transcript must be inspected separately. Each request base64-encodes one already verified chunk bounded to 24 MB, never the multi-hour source. The upstream processing timeout is 60 seconds, so LiveClip now defaults to conservative 90-second chunks and retains configurable duration/size limits. The adapter requires an exact `X-Generation-Id`, rejects an ordinary request ID as proof, validates finite nonnegative usage/cost and the SDK's other permissive response fields, and never switches to Mock. ADR-009 and `docs/research/openrouter-audio.md` record the dated evidence and privacy boundary.

The direct OpenAI alternative remains available. OpenAI's 2026-08-03 general recommendation is `gpt-transcribe`, but official documentation states real word/segment timestamps are currently provided by `whisper-1` with `verbose_json` and `timestamp_granularities`. The `openai`/`openai-codex` modes therefore use `whisper-1` for their required time-aligned contract. This capability-driven exception is recorded in ADR-004. No Provider is allowed to synthesize unavailable word times, and a response without usable segment alignment fails deterministically.

Overlap merging converts all results to source milliseconds, first filters segment overlap by time ownership, then removes duplicated leading text using normalized Chinese character n-grams/longest suffix-prefix similarity. Empty, malformed, sentence-mirror or unaligned optional word arrays make word timing `unavailable` while preserving an otherwise valid timestamped segment transcript; impossible or invalid segment timing still rejects the response. Timing is never fabricated. Original text and merge evidence remain available for audit.

## Candidate and LLM editing design

Candidate generation first forms sentence/turn units from transcript punctuation and gaps. It scores sliding units for duration fit, boundary closure, speech density, pause strength, simple volume/silence signals, hook lexicon/question/list cues, and topic continuity. It keeps context, adjusts to legal sentence boundaries, and deduplicates by interval-overlap ratio plus normalized n-gram/Jaccard similarity. On typical long input it retains 30–50 rough candidates, then deterministic score is always available as a fallback.

The editor sends one candidate per call, bounded pre/post context, rule score and necessary quality signals. The prompt labels transcript fields as untrusted quoted data and explicitly disallows following instructions found inside them. The request exposes no tools. The OpenAI adapter uses `client.responses.parse(..., text_format=WireModel)` or the equivalent strict `text.format` JSON schema. It separately handles `incomplete`, refusal, provider errors, SDK/Pydantic parsing, missing parsed output and local domain validation. Only a normal parsed result reaches EditPlan validation. One repair call is allowed for repairable structure/domain errors; refusal/auth/quota are not “repaired.” Then a deterministic EditPlan is stored with `degraded=true`.

Application-owned retry disables SDK retries, honors bounded `Retry-After`/exponential jitter for timeout, connection, rate-limit and retryable 5xx failures, and never retries deterministic auth/parameter/quota failures blindly. Cancellation exceptions carry every call already made for that candidate, including an initial invalid response followed by a cancelled repair. An append-only evidence fence binds each record to the exact historical TaskAttempt lease token and may persist it after cancellation/lease loss, but cannot mutate transcript, candidate or render state.

At the user's request, ADR-008 adds a second real editorial adapter through the installed Codex CLI. `openrouter-codex` combines OpenRouter timestamp ASR with non-interactive Codex editing; `openai-codex` is the direct OpenAI ASR alternative, while `mock-codex` is explicitly development-only. Codex consumes the same bounded editorial payload via stdin and a strict model-owned JSON Schema. Version 0.146.0 is pinned to a reviewed tool-free security profile: every known apps/browser/computer/shell/MCP/plugin/multi-agent/search/tool feature is disabled, execution is read-only/no-approval, user config/rules are ignored, and proxy URLs plus all Provider/API credentials are removed from the child environment. Any JSONL tool item, oversized JSONL line or bounded-capture truncation causes failure. The resolved executable path, bytes, size, CLI version and profile are hashed into the immutable Pipeline contract and rechecked before every call. A real smoke must include a Codex thread/correlation ID and positive token usage. Codex never receives LiveClip audio or replaces ASR; its local process reuses saved ChatGPT authentication while inference remains cloud-based.

The `.env.example` LLM model is a configurable cost/quality-balanced example, not a claim of a LiveClip-specific official recommendation. Alias behavior must be evaluated before release; production can pin a snapshot when offered. We set `store=false` because independent clip scoring requires no server-side conversation state and minimizes retention beyond configured OpenAI policy.

## EditPlan trust boundary

Pydantic models use `extra='forbid'`, strict enums and constrained text/list fields. The wire model contains content decisions only. It has no generic metadata dictionary or optional executable extension point. Local validation confirms source duration, configured clip bounds, candidate adjustment window and canonical milliseconds. Layout is not model-owned: the application always chooses the single-layer center-crop template. Effect values map through a local dictionary to deterministic renderer templates.

The renderer never interpolates title or caption text into FFmpeg expressions. Text is normalized for control characters and rendered by Pillow using an approved local font into system-generated RGBA images. FFmpeg receives those image paths as distinct argv input values. This also addresses the current host FFmpeg build, which lacks `subtitles`, `ass`, and `drawtext`.

## Rendering compatibility decision

Discovery found FFmpeg 8.1.2 arm64 with scale/crop/boxblur/overlay/fade/afade/loudnorm/silencedetect, AAC, libx264 and h264_videotoolbox, but without libass/freetype-based text filters. Rather than remove captions or require a nonstandard FFmpeg distribution, v1 has a deterministic raster-overlay backend:

1. Pillow lays out a bounded Chinese title and each bounded caption cue inside known safe areas using an allowlisted detected font.
2. It writes transparent full-frame RGBA assets in a revision temp directory.
3. The deterministic FFmpeg builder supplies these assets as inputs and adds only system-generated numeric enable windows and fixed overlay templates.
4. Assets and filter templates are bounded; user/model text never becomes filter syntax.

Doctor still reports the exact absence of `subtitles`/`drawtext`. If they exist on another machine they are capability information, not a different trust path in v1. The raster path is tested for performance on 30–90 second clips; it avoids generating a frame for every video frame.

The layout graph has exactly one source-video branch: scale-to-fill followed by deterministic center crop. It contains no `boxblur`, background copy or shrunken foreground overlay. The removed blur value remains decodable only for historical rows and is rejected before FFmpeg argv construction. Effects and loudness are fixed enum mappings. Every cut re-encodes. The renderer exposes two system-owned text modes: `none` for clean review proxies and `title_and_captions` for final delivery media. The render-spec fingerprint includes the text mode and no-blur renderer contract, so an older composited proxy cannot be adopted. In final mode, a raster overlay is supplied as one finite PNG frame; the fixed `overlay` template explicitly repeats that last secondary frame instead of starting an unbounded looping image demuxer. Complex-filter workers are capped at two and normal libx264 workers at four. A libx264 launch/timeout failure gets exactly one conservative retry with one filter and one encoder thread; completed invalid output is not blindly retried. Partial timeout stderr is retained through process-group termination and bounded before diagnostics. We attempt VideoToolbox first when selected and validated, then fall back to libx264 after any runtime failure. Actual discovery showed VideoToolbox succeeds on the host but fails inside the Codex sandbox with OSStatus -12903, so doctor reports the environment context and fallback honestly. ADR-010 records clean proxies; ADR-011 records the single-layer no-blur decision.

## Render invalidation and review consistency

A visual change transaction inserts a new immutable EditPlanRevision and caption snapshot, increments the Project revision epoch, points CandidateClip to it, makes the effective review pending, and marks queued/running/succeeded/failed RenderJobs for older revisions stale. Boundary-only Web edits omit unchanged relative captions so the repository regenerates them from absolute TranscriptSegment time. A worker that finishes an old render fails revision/lease fencing before publication.

Any current-revision or review-decision change also fails queued/creating Delivery snapshots and cancels or requests cancellation of their durable Tasks in the same SQLite transaction. Successful Delivery versions remain immutable and downloadable. This keeps stale work observable even when the Worker is offline and prevents a late task from publishing an obsolete approved-clip set.

Approval and rejection are append-only decisions on an exact revision. Delivery eligibility requires the current revision, its current approval, and a succeeded validated final RenderJob with the same revision and render-spec hash. Editing after approval never inherits approval.

## Quality verification

Validation is a first-class output. A single pinned output descriptor feeds ffprobe, full decode and frame extraction, so validation cannot silently move to replacement bytes. ffprobe confirms MP4, H.264/AAC, both streams, expected dimensions/orientation and duration tolerance. File size has a conservative floor. FFmpeg performs a full decode to null. The validator extracts start/middle/end samples, calculates simple luminance/variance/edge/aspect heuristics, checks renderer-owned title/caption bounds against safe areas in final mode (and records `not_applicable` for clean proxies), and builds a contact sheet. Heuristics are labeled automatic; only an actual image-viewer observation sets visual status to viewed, with notes and timestamp. Diagnostic argv/stderr is bounded, path-safe and secret-redacted; failure to persist optional diagnostics emits a path-free structured warning rather than disappearing.

## Immutable delivery

The service allocates a unique version and snapshots ordered eligible revisions/render assets before I/O. It copies only validated final media into a same-filesystem private attempt directory, emits relative SRT and a canonical manifest, and pins every resulting video, subtitle and manifest with exact size/SHA evidence. ZIP creation streams from those descriptors, never from ordinary member paths; the exclusively-created ZIP is fsynced, pinned, hashed and reopened from the descriptor to verify its complete canonical member list, member sizes, every member SHA and manifest object.

Publication scans the exact regular-file tree and then performs a native atomic no-replace directory rename. After rename, every canonical endpoint is rebound to the original pinned descriptor and rehashed; failure withdraws the canonical version and fails closed. Before the task records success, it rechecks Project revision epoch/current eligibility and repeats manifest, disk member, ZIP member and committed Asset hash validation. An existing version is never removed or overwritten. Crash recovery adopts only a directory that passes the same exact validation; mere presence of `manifest.json` or `delivery.zip` is insufficient.

## API, errors, and idempotency

API schemas are DTOs, never ORM serialization. Internal absolute paths are omitted unless a CLI-only command explicitly needs them; Web receives asset IDs and source filenames/ranges. The stable error envelope contains version, code, message, retryable, resource ID, and optional safe field details/correlation ID. Exception mapping strips headers, tokens, provider request content, raw SQL and stack traces.

An Idempotency-Key is scoped by authenticated caller and endpoint. The canonical request hash is stored with the created resource. Reuse with the same hash returns that resource even if Provider readiness later changes; reuse with a different payload is a stable 409. API create handlers replay a completed record before readiness gating, while new work is still rejected when the selected chain is unavailable. Creation and record insert occur in one transaction.

Batch review is a short synchronous application transaction, not a background task. The request carries a unique clip ID, expected EditPlan revision, decision and optional rejection reason for each selected candidate. The repository first checks the canonical `Idempotency-Key` record, validates every item belongs to the requested current Project generation and every expected revision still matches, then records every decision, invalidates active Delivery snapshots and persists the idempotency result under the same `BEGIN IMMEDIATE`; any conflict rolls back the entire batch. A same-key/same-payload replay returns current snapshots without repeating effects, while same-key/different-payload fails with 409. The Web never approximates this with concurrent single-clip requests. A failed Web request retains the exact body/key for explicit retry, reconciles Project/clip state first, and disables that retry if any included candidate is missing, has a changed revision or has an unsaved editor draft. Batch work in flight locks editor writes so a response cannot overwrite local draft state.

Review-board keywords are read-only grounded navigation metadata, not LLM-authored execution data and not an EditPlan field. A deterministic extractor ranks phrases from trusted editorial metadata but returns them only when the exact normalized phrase occurs in a persisted ASR segment fully contained by the current clip. It binds the phrase to persisted transcript word intervals when present or to the entire containing ASR segment otherwise. Responses include clip-relative and source-absolute integer milliseconds plus `word` or `segment` precision. Proportional caption display intervals never become keyword evidence. Keywords are recomputed from the current revision and current transcript, so no migration, render invalidation or repeat ASR is required. Human caption/boundary edits continue to create a new revision; the next query derives keyword occurrences inside that exact boundary.

The Web review workspace does not fetch or render the complete livestream transcript. That large panel duplicated the information needed during candidate review and separated it from the video being judged. The current-revision caption cues and grounded keyword ranges are the candidate-level presentation surface. The persisted transcript and `GET /projects/{project_id}/transcript` remain application/API capabilities for processing, diagnostics and external consumers; removing the Web panel does not remove ASR or transcript data.

## Configuration and secrets

Pydantic Settings reads environment variables and optional ignored `.env`/`.env.local` files. Settings validation never includes secret values in exceptions or dumps. The composition root reads `OPENROUTER_API_KEY` only for `openrouter-codex` and `OPENAI_API_KEY` only for `openai`/`openai-codex`; a runtime/provider mismatch fails deterministically before any stage handler. OpenRouter's Base URL and v1 model are exact allowlisted values, preventing configuration-based credential exfiltration. Mock-only startup retains neither key and instantiates no cloud client. Codex receives no ASR key, API token or credential-bearing proxy URL. API health exposes only safe Provider names, readiness booleans and stable issue codes.

## Observability

Structured JSON logs include timestamp, level, event, correlation/project/run/stage/task/clip IDs, attempt, duration and stable error code. A centralized processor redacts authorization, API keys, bearer tokens, cookies, common secret fields and matching secret substrings. Uvicorn request access logging is disabled and the Vite proxy removes query strings before its offline error logger runs, because short-lived media signatures are credentials. FFmpeg logs store a sanitized logical argv using asset IDs/relative paths plus a bounded stderr tail in a diagnostic file. ApiUsage captures provider metrics but no prompts containing transcript text unless an explicit local debug mode is later designed.

## Testing strategy

- Unit tests own pure domain, security paths, fingerprints, timestamp conversion/merge, candidates, EditPlan/schema, prompt boundary, subtitles, argv, fallback, states, leases, stale rules, delivery/ZIP and redaction.
- Integration tests use actual generated H.264/AAC media and FFmpeg/ffprobe, a temp data root and SQLite database, Mock providers, interruption/failure injection, and full artifact validation.
- API tests use a real application composition with temp resources and verify 202/idempotency/error/auth/Range/user-visible flows.
- Web unit/component tests cover all critical states and actions. One Playwright flow uses a controlled API double for UI-state determinism; a second isolated flow starts real FastAPI, a leased Worker, SQLite, Vite and FFmpeg with Mock AI, then proves Range, revision stale, final render, ZIP and `delivered` through both UI and persisted evidence.
- `make demo` is a deterministic real-media acceptance, not a unit-test alias.
- `make smoke-cloud` is opt-in, calls both real providers, and cannot construct Mock providers.
- `make smoke-codex` is opt-in, makes one real tool-disabled structured Codex editorial call through saved CLI authentication, and rejects missing thread/token, degraded or Mock evidence. It is not an ASR/video smoke.
- `make smoke-openrouter INPUT=...` is the default real-chain acceptance: it requires OpenRouter generation IDs, Codex thread/token evidence and non-degraded selected plans, with no Mock evidence.
- Milestones receive an independent read-only review; M6 receives a Product Spec verification matrix.

## Technical alternatives and deliberate exclusions

- A full FFmpeg build with libass/drawtext would work but adds a system-level installation prerequisite. Raster overlays work on the inspected stock Homebrew build and create a safer data/execution separation.
- `gpt-transcribe` is more current for general ASR, but lacks the timestamp contract needed for v1. We retain a provider path and research it rather than invent timing.
- PostgreSQL/external queues improve high concurrency but violate local prerequisites. Fenced SQLite leases are sufficient for one heavy Worker.
- Async SQLAlchemy would add a second concurrency model with little local benefit; sync UoW plus short transactions is simpler.
- Copying source video would improve immutability but doubles large storage. We keep a read-only reference plus mutation checks.
- Whole-transcript LLM editing, local embeddings and local model weights are excluded by privacy/resource/product constraints.
- Treating Codex CLI as ASR is excluded: its documented attachment surface is images, while LiveClip requires timestamped audio segments. See ADR-008.

## Known risks and uncertainties

- Current development hardware is Apple M2, not M3; M3 throughput remains unmeasured.
- A project-local native arm64 Python 3.12 must be installed because PATH Python is 3.9 and the existing 3.12 is x86_64.
- Default PATH Node 26 is not LTS; Node 22 LTS exists at `/usr/local/bin` and setup/doctor must choose/report it.
- Current Vite 8 requires Node 22.12 while the native LTS installation is 22.11. ADR-006 pins the latest compatible Vite 6/Vitest 3 toolchain without reducing UI capability.
- Raster overlays and Chinese glyph fallback passed real M1/M5 rendering, full-decode and viewed contact-sheet inspection; overlay/input/thread budgets are enforced. Representative 2–4 hour/M3 throughput remains unmeasured.
- VideoToolbox is inaccessible inside the current sandbox but proved available in a host process; ordinary-terminal final verification remains distinct.
- A regenerated OpenRouter Key is configured only in ignored local environment. On 2026-08-05 the 46:20 source completed 33/33 real Whisper calls (2,942.016 overlap-inclusive audio seconds, USD 0.0735504 reported Provider cost), 233 timestamped segments and no fabricated word timing. Provider/upstream behavior beyond this sample remains external.
- Generation 2 historically reused all 33 cache files under the then-current key-first identity and made no new OpenRouter call. A post-run canonical comparison confirmed all 33 generation-1/generation-2 tuples of chunk ID, interval, preprocessing key and byte SHA-256 were identical. The subsequently hardened dual-hash identity is covered by same/different-byte regressions but has intentionally not been proven by another paid cross-generation long run; its new filenames make earlier cache files miss safely.
- Codex CLI 0.146.0 saved-login structured editing is verified both by isolated smoke and by 39/39 real long-run candidate calls; 15 selected plans are non-degraded. A restricted Codex sandbox could not initialize its nested app-server, so the successful long edit was intentionally run by the host Worker.
- Official audio guide and API reference differ on `flac`/`ogg`; v1 emits common `m4a`/`mp3` and does not depend on those formats.
- The repository's available long sample is 46:20 and 2.19 GB, shorter than the typical 2–4 hour product target. It completed a five-chunk streaming Mock run in 28.83 seconds with about 18 MB generated project data, but 2–4 hour runtime/peak-memory and Apple M3 throughput remain unmeasured.
- VFR with 90°/270° display rotation and explicit non-first/default audio selection is covered by generated real-FFmpeg integration media. Broader codec/container/device diversity still depends on user samples.
- Automated severe-crop and subtitle-quality checks are heuristic and cannot replace the explicitly recorded visual inspection.

## Decision index

- ADR-001: modular monolith, inward dependencies and millisecond timebase.
- ADR-002: SQLite fenced task leases and immutable artifact publication.
- ADR-003: deterministic Pillow text rasterization plus FFmpeg overlay.
- ADR-004: timestamp-capable ASR default and strict Responses integration.
- ADR-005: WAL-safe SQLite runtime, explicit transaction control and FULL durability.
- ADR-006: Node 22.11-compatible locked Web toolchain until the local LTS runtime is upgraded.
- ADR-007: pinned file evidence and exact immutable publication from validation through Asset commit.
- ADR-008: tool-disabled Codex CLI editorial provider, explicit ASR boundary and readiness gates.
- ADR-009: OpenRouter Whisper Large V3 default ASR, strict endpoint/model and dual-cloud privacy boundary.
- ADR-010: clean review proxies with separate editorial metadata; text overlays only in final mode.
- ADR-011: one direct center-crop source layer; blurred backgrounds and duplicated foregrounds are prohibited.
- ADR-012: grounded review metadata and atomic, revision-fenced batch decisions without A/B variants.
