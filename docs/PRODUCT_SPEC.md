# LiveClip v1 Product Specification

Status: authoritative product contract
Captured: 2026-08-03
Target completion state: `delivered`

Amendment, 2026-08-04: at the user's explicit request, the installed Codex CLI is an additional real editorial LLM adapter and the normal combined mode is OpenAI ASR plus Codex editing. Codex runs locally as a CLI but uses OpenAI cloud inference through saved ChatGPT authentication; it is not a local model and cannot replace timestamped ASR. This amendment adds capability and does not remove the official-SDK Responses adapter.

Amendment, 2026-08-05: the user explicitly selected OpenRouter `openai/whisper-large-v3` as the default real ASR paired with Codex. `openrouter-codex` therefore becomes the normal combined mode; direct OpenAI ASR/Responses and `openai-codex` remain supported alternatives. Only preprocessed audio chunks cross the OpenRouter boundary and may be routed to its upstream ASR host. The Key previously exposed in chat is invalid for acceptance and must be revoked; only a newly generated Key stored in ignored local environment is permitted.

Amendment, 2026-08-05: the user explicitly requires review proxies to be clean video clips without LiveClip-generated title or caption overlays. Editorial title, Hook, reason, risk flags and editable caption cues are separate metadata shown by CLI/API/Web. Only the post-review final render may burn the approved current revision's title and captions. This changes proxy presentation, not revision fencing, quality validation or final delivery requirements.

Amendment, 2026-08-12: the user requires a portable package of generated review clips and their descriptions before final approval/rendering. LiveClip therefore supports a separate versioned offline-review export containing current clean proxy MP4s, SRTs, titles, high-impact sentences, recommendation reasons, risks, editor keywords with evidence timing, an offline HTML viewer, JSON/Markdown metadata, hashes and ZIP. This export is explicitly not a formal Delivery, does not approve clips, does not burn text into video and does not change Project/review/Delivery state.

Amendment, 2026-08-13: the Web home page is a video-editor project workspace rather than a processing diagnostic page. Every authenticated workspace member sees only Projects to which they belong, with searchable status views, personal workload counts and explicit owner/editor/reviewer membership. The Project owner manages membership; access isolation is enforced by the API for Project, run, clip, render and Delivery resources rather than copied into the browser. Local installations may assign one distinct Bearer token per username; no token is stored in SQLite or returned to the Web client.

Amendment, 2026-08-18: the user rejects approval-before-render as the standard workflow. Immediately after candidate selection, LiveClip must render one clean delivery-quality current-revision master with a matching SRT and quality evidence. Review then decides only whether that exact master is kept (`approved`) or discarded from Delivery (`pending_review` or `rejected`). Formal Delivery reuses the approved master bytes and must not require a second post-approval render. An edit creates a new revision and therefore requires rerendering only that changed clip. A text-bearing `title_and_captions` render remains an explicit optional derivative for release use, not a prerequisite for ordinary review or Delivery. The persisted/API kind `proxy` remains a compatibility name for the clean master.

Amendment, 2026-08-18: the ordinary Web clipping flow is selection, not an approval ceremony. Each rendered current-revision master has one user-facing “选入交付” control; selected items map to the compatible persisted `approved` state and unselected items map to a non-deliverable state, but the Web does not ask for approval/rejection reasons. The candidate score is human-editable as part of the versioned EditPlan. Formal Delivery exports the currently selected set in one batch and its ZIP includes a file-only `index.html` gallery so the package is directly browsable after extraction. Separate release approval, collaboration comments and advanced editor handoff remain distinct optional workflows.

Amendment, 2026-08-18: candidate discovery is explicitly A/B-testable per new PipelineRun. Algorithm A is the unchanged v1 path: deterministic rule windows followed by one AI edit per rough candidate and forced Top-N. Algorithm B is a separate Agent + versioned Skill path. Its first frozen version uses requested maximum clip length `L` (Web default 60 seconds), timestamped `2L` transcript windows at stride `L`, and a strong-overlap rejection rule. Historical Algorithm B v1 runs and Skills remain immutable and reproducible.

Amendment, 2026-08-19: the time-clustered two-pass B v2 design remains available only as `b_v2_experimental`. Its target/maximum controls and continuous-output safety rules are preserved for experimentation, but it is not the recommended default.

Amendment, 2026-08-19: `semantic_global` is the recommended new-run algorithm. It is Full-first: use the configured model tokenizer and context size to place the complete timestamped transcript in one Discovery request whenever prompt, transcript, output reserve and safety margin stay within the configured budget ratio (default 0.58), then give complete transcript, topic map and all candidates to one Global Review. Discovery returns zero or more continuous cue-ID candidates without final scores. Global Review alone performs semantic duplicate/containment decisions, boundary revision and comparable six-part scoring. If full context is unsafe, token-bounded 10–20 minute transport windows overlap by `maximum clip duration + context guard`; every window may return multiple candidates and all enter one review. Python never treats overlap or five-second adjacency as semantic identity. It validates schema/cue IDs/45–90 second continuous time bounds, recomputes score, requires strictly `>75`, applies risk gates, treats Top-N only as a ceiling and lets FFmpeg consume only validated intervals. Exact historical v2/v3/v4 run snapshots remain reproducible.

Amendment, 2026-08-22: `semantic_windowed` supersedes Full-first as the recommended new-run algorithm; `semantic_global` remains an explicit comparison mode. Discovery scans 120-second logical windows at a 60-second step, batching four logical windows into one deduplicated 300-second request with a half-open 240-second candidate-ownership interval. Each batch may return zero or many candidates and structured open-topic evidence. Either adjacent side reporting an unfinished outer-edge topic triggers a 180-second union review across that boundary. Global Review receives candidate source text, local context and boundary results rather than rereading the whole livestream. Discovery does not score or finally reject; Python does not infer semantic identity from overlap, adjacency, keywords or punctuation. It only schedules/caches calls and enforces Schema, cue/time, one continuous 45–90 second range, strict `score > 75`, risk gates, Top-N ceiling and FFmpeg safety. Base batches use bounded concurrency and independent cache keys so local reruns are faster and failures are isolated.

Amendment, 2026-09-02: the existing single bounded structure/domain repair must receive the complete deterministic validation result before it is spent. For Discovery this includes the exact stage-domain rules for immutable source identity/range, chronological non-overlapping topic coverage, batch candidate ownership, boundary-bridge crossing and continuous referencing-topic spans in addition to JSON Schema and generic cue checks. A repaired result is not entitled to a second repair; repeated invalidity fails explicitly as provider output invalid while retaining call evidence and valid independent caches.

Amendment, 2026-09-02: at the user's explicit request, accuracy and repeatability take priority over ASR speed. LiveClip adds an opt-in `mlx-codex` mode using one pinned, unquantized MLX Whisper `large-v3` FP16 snapshot on Apple Silicon, temperature-zero deterministic greedy decoding and one inference worker. Previous-window text conditioning and the generic product vocabulary prompt are disabled after full-input evidence showed that they caused long repetition loops at chunk/window boundaries. Decode windows rejected by the pinned runtime's compression-ratio or average-log-probability thresholds are omitted and counted instead of being published as transcript. Audio remains local; the resulting bounded transcript still goes to the existing Codex editorial provider. The exact package version, model revision, model bytes, thresholds and decode contract are frozen into the PipelineRun ASR contract. There is no implicit model download or cloud/Mock fallback. `openrouter-codex` remains the default until real labelled Chinese accuracy and repeated-run evidence justify a separate default decision.

Amendment, 2026-09-03: Windowed Global Review must remain inside the immutable configured token budget even when a local ASR emits unusually fine-grained cues. It first retains the existing object transport and adapts only the extra candidate context guard from 30 to 15 seconds. If that still does not fit, it losslessly encodes repeated candidates, topics, input units, boundary reports, semantic contexts and cue fields as rows with explicit columns, omits normalization columns only when every value is absent, and may reduce only the extra guard from 15 to zero in five-second steps. Every Discovery candidate, complete linked topic, boundary-bridge report, source cue and deterministic calculated fact remains present; Python does not rank, merge or discard semantic evidence to fit. The request fails closed if the compact zero-extra-context form still exceeds budget. Provider preflight, repair and dynamic response Schema must rehydrate either representation identically.

Amendment, 2026-09-04: a Global Review `manual_review` decision is advisory risk provenance, not candidate deletion or a default-delivery block. Every deterministically valid `keep` result—automatic or manual-review—must have final score strictly greater than 75, become an EditPlan revision and clean review render, and enter default selection. Manual-review provenance remains visible as the system-owned `manual_review` risk flag in review and Delivery metadata. Explicit manual selection may still exclude any clip. Deterministic `rejected` results never become renderable revisions or enter Delivery.

Amendment, 2026-09-04: current Global Review uses the versioned accuracy-first v2 contract. It must return exactly one independent six-dimension scorecard for every Discovery candidate before consolidation; rejection groups remain audit records and cannot stand in for those scores. An advancing candidate and every duplicate representative map back to a retained `keep` clip whose deterministically recomputed score is strictly above the configured threshold. A `no_general_value` rejection whose own score is above that threshold is invalid and receives the one bounded repair. To keep output bounded, full clip records are emitted only for retained results. Historical v1 Global Review Prompt/Schema loading remains installed for immutable run and cache replay. New-run editorial defaults use `gpt-5.6-sol`; Codex Discovery stays at medium reasoning and only the final v2 Global Review uses high reasoning. The accepted 13-clip `8-30.ts` portfolio is a checked-in regression reference for later consistency evaluation, not a forced output count or source-specific production rule.

Amendment, 2026-09-09: new recommended `semantic_windowed` runs use high-recall
`semantic_windowed_v2` Discovery, separately cached candidate Boundary Review and candidate-level
`semantic_global_v3` review. Discovery never receives the score threshold or Top-N and keeps risky
topics discoverable. Boundary Review sees each proposed interval plus at most 180 seconds of local
source, must judge the actual continuous opening, ending and internal content, and either keep it,
return one concrete 45--90-second repair, or drop it. Global Review sees every candidate, the boundary
result, Discovery cue evidence and candidate-local context—not the whole livestream—and returns one
content decision, independent publication status, fixed six-dimension scorecard, quality flags, risk
flags and duplicate audit row per candidate. Python recomputes totals and counts and treats every
unresolved quality flag as a non-compensable gate: title/source mismatch and ASR meaning reversal
block publication, while unresolved boundary, cleanliness, padding, mixed-topic and weaker-duplicate
flags drop the candidate. Automatic materialization requires score strictly above 75, one actual
continuous 45--90-second interval, no quality flag and `publish_status=auto`; manual and
blocked rows remain auditable but do not enter an automatic Delivery. Top-N is applied once to this
final eligible automatic set, never used to limit Discovery or fill a quota. Pipeline config v6
records all three Prompt versions and hashes; v1/v2 review and config v2--v5 remain installed for
immutable replay.

Amendment, 2026-09-11: LiveClip adds an explicit `mini_lesson` Clip Profile alongside the
default-compatible `short_highlight`. `short_highlight` remains one 45--90-second micro-point with a
60-second target. `mini_lesson` is one 90--300-second central teaching objective with a 180-second
target and may contain tightly related definitions, steps, explanation, demonstration, practice and
conclusion. Mini-lesson Discovery keeps the existing 120-second logical windows, 60-second step,
four-window batches and deterministic ownership, but emits boundary Topic Fragments. Either open side
schedules a local 180-second Link Review; only its Agent decision can connect two Fragments, and an
open confirmed link iteratively schedules the next boundary. Python assembles these explicit links
into auditable Topic Chains without using time distance, text similarity, keywords or punctuation as
semantic evidence. A separate Agent reviews each complete Chain, and a Chain above 300 seconds may
produce only Agent-identified natural teaching subunits; otherwise it is rejected as
`topic_too_long_without_natural_split`. Boundary and Global Review then run independently for the
requested Profile. Mini-lesson scores are recomputed from 20/20/15/15/10/10/10 dimensions, 75 is
insufficient, Top-N is only a post-gate ceiling, and only `auto` results enter automatic FFmpeg.
Manual, blocked, rejected, weaker duplicate and cross-Profile variant records remain in Schema v4
audit data. The first release permits exactly one continuous source interval and no jump cuts.

Amendment, 2026-09-14: the high-level `auto VIDEO` path now persists a
versioned-preset Completion goal and returns or observes that saved identity;
an independent Worker performs the six stages and default selection, then
builds immutable Delivery when eligible. Manual selection remains an
authorized user action. The CLI prints the caller-scoped request
key before creation so the same source and options can recover a lost
response. `--no-watch` returns saved IDs; Ctrl-C stops only observation.
`resume PROJECT_ID` authorizes goal lookup, requires an exact goal ID when
ambiguous, observes a manual-selection wait or exhausted coordination budget
without changing it, and explicitly wakes only eligible `needs_action` through
the version-fenced application service. Web saves a confirmed goal ID before
clearing pending-create identity, polls under current authority after reload,
and hides stale state or signed links when access fails. Read-only watchers
never claim Worker tasks, reset retries, select clips or publish a ZIP before
the bound Asset commits. Both presets remain experimental until real
content/audio and long-input acceptance.

## Product outcome

LiveClip is a local-first Chinese livestream video clipping system for Apple Silicon macOS. A user supplies an absolute path to a 2–4 hour local video and chooses compatibility Algorithm A/B v1, experimental B v2, Full-first comparison mode, or recommended `semantic_windowed`. LiveClip imports and analyzes it, uses the explicitly configured local or cloud ASR plus OpenAI/Codex editorial understanding, produces up to a configurable number of highlights, renders their clean vertical masters, supports default or manual user selection and revision, and creates an immutable versioned delivery package from the selected subset.

The complete flow is:

```text
Ingest → Preprocess → Transcribe → Generate Candidates → AI Editing
→ Validate EditPlan → Render Clean Review/Delivery Masters → Select Keepers
→ Export Selected Set → Browsable Delivery
```

At minimum a successful delivery contains:

```text
delivery/
├── clips/
├── subtitles/
├── index.html
├── checksums.sha256
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
liveclip auto /absolute/path/live.mp4
liveclip run --input /absolute/path/live.mp4 --top-n 15 --wait
liveclip status PROJECT_ID
liveclip status PROJECT_ID --watch
liveclip stage RUN_ID transcribe
liveclip stage RUN_ID candidates
liveclip clips PROJECT_ID
liveclip select PROJECT_ID
liveclip select PROJECT_ID --mode manual --clips 1,3,5
liveclip review CLIP_ID --approve
liveclip review CLIP_ID --start 125.5 --end 183.2 --title 修改后的标题 --approve
liveclip review CLIP_ID --reject --reason 内容不完整
liveclip rerender CLIP_ID --wait
liveclip package PROJECT_ID --zip
```

`auto VIDEO` is the high-level default path. It uses the versioned short-highlight `semantic_windowed` preset: Top 15, a 45–90-second range, a 60-second target and threshold 75. It saves a durable goal so an independent Worker can process all six stages, apply default selection and create the immutable ZIP Delivery without Project-ID shell plumbing in the initiating command. The caller may instead request the versioned `mini_lesson` profile or manual selection. `run --wait` remains the configurable lower-level path: it processes through successful clean masters and leaves every new candidate ready for selection unless `--finish` is explicitly supplied. `select` is the ordinary selection surface: default mode selects all newly generated candidates without overriding an existing manual exclusion; manual mode atomically selects the named IDs/list numbers and excludes the rest. Selection creates the formal package by default and `--no-package` separates the two operations. `package` and the compatibility alias `deliver` use the same immutable Delivery service. `stage` accepts each of the six fixed stage names, runs unmet dependencies, stops immediately after the requested stage and never duplicates stage business rules in the CLI. On an interactive terminal, foreground lower-level commands redraw one fixed eight-step Text UI every two seconds rather than scrolling. `auto` and `resume` watch saved Completion state without owning work. The observation includes current-stage elapsed time, ASR progress, active Delivery attempt counts, cancellation state, Worker lease freshness and the latest refresh time. Non-TTY output remains bounded plain text suitable for logs.

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

The React/TypeScript/Vite UI opens on “我的项目”, a project-management workspace for video editors. It shows only the signed-in member's Projects, searchable and filterable by workflow state, with “需要我处理”, processing and delivered counts. Project cards identify owner, member count, the current user's role and the next meaningful action. Creating a Project makes the current user its owner; an owner can add editor/reviewer members or remove non-owners from the Project workspace.

The workspace supports project creation from a local path, run configuration, stage/progress/error display, candidate video preview, title/boundary/subtitle editing, approve/reject, rerender, delivery creation/version listing, and ZIP download. The review section is named “高光时刻” and is a single-column list. Each item is one full-width horizontal row with video and editorial metadata side by side; the complete subtitle block is the last section in that row. The EditPlan Hook is shown to the user as “高光语句”, meaning concise AI-authored candidate-grounded copy suitable for consideration as on-screen text. Grounded timed terms are labelled “编辑关键词” and explicitly treated as editor-only navigation rather than audience-facing copy. The review workspace deliberately does not show a separate full-livestream transcript panel, while the transcript remains available through the REST API and backend application services. It must represent loading, empty, error, stale, disabled, retrying, and cancelled states. It does not copy backend state transitions, access-control decisions or EditPlan validation.

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
- Stream SHA-256 without loading a large file into memory; persist source stat identity and metadata. Treat the persisted device ID as audit evidence rather than a cross-launch rejection key because macOS can renumber a mounted volume after reboot/remount; cross-launch acceptance still requires the same strict real path, regular-file type, size, nanosecond mtime, inode when available, and full pinned SHA-256.
- Give every Project an isolated generated-data directory.
- Recognize duplicate fingerprints for information/cache purposes without merging explicitly separate Projects.
- Recheck the referenced source for mutation before dependent processing and publication.

### Audio preprocessing and ASR

- Extract compressed mono speech audio with FFmpeg and stream file operations.
- Split by configurable duration with configurable overlap and a conservative size below the selected Provider upload limit.
- Persist a chunk manifest with absolute source offsets, duration, bytes, hash, and cache key.
- Persist `silencedetect` signals and resume from verified successful chunks.
- Cancellation stops subprocesses safely; partial files never count as success.
- Provide `ASRProvider` with local MLX, OpenRouter, OpenAI and Mock implementations.
- Local accuracy mode accepts only the pinned full-precision Whisper `large-v3` snapshot, validates exact regular-file bytes before processing, uses fixed deterministic decode settings and never downloads a model during a Pipeline run.
- Preserve Chinese text; support configured domain vocabulary hints through each Provider's documented parameter. For OpenRouter, use JSON `provider.options.groq.prompt`; never claim its ignored multipart `prompt` was applied.
- Save real segment times and, only when supported, real word times. Unsupported word timing is explicitly `unavailable`.
- Convert local chunk times to the canonical source timebase and deduplicate overlap using time and text evidence.
- Retry timeouts, genuine 429 rate limits, retryable 5xx, and malformed successful ASR responses with bounded exponential backoff and jitter. A response retry must reuse verified successful chunk caches and must not switch to Mock. Do not blindly retry authentication, quota, invalid model, or deterministic parameter errors.
- Cloud ASR concurrency defaults to four and is configurable from one through eight. Local MLX ASR always freezes concurrency at one. Submit only one bounded batch at a time; cache each successful chunk before propagating a peer failure, and persist request count, retries, latency, audio seconds, request ID, and usage.
- Produce `transcript.json`, `transcript.srt`, and durable segments.
- Mock is allowed only for tests, development, and no-key Demo. Cloud smoke never falls back to Mock.

Current official API findings and URLs are recorded in `docs/research/openai-audio.md` before the real provider is implemented.

### Candidate generation and AI editing

Algorithm A candidate generation must work without an LLM. It uses punctuation/sentence closure, pauses, speech density, volume/silence signals, topical continuity, context, duration constraints, hook signals, and expression closure. It first produces approximately 30–50 rough candidates for normal long input, records boundaries/text/context/rule score/reasons, then deduplicates by time overlap, text n-grams, and Jaccard similarity. A rule-ranked fallback selects top-N when cloud editing fails. Algorithm B instead requires the configured discovery Agent and, for current runs, the configured continuous-consolidation Agent. Provider failure or invalid output is discarded and must never silently invoke A. Consolidation is limited to one continuous source interval in phase one; discontinuous montage remains out of scope.

For new `semantic_windowed` runs, Discovery is high recall and does no final scoring or risk-based
suppression. A separately cached Boundary Review evaluates each real continuous source interval before
candidate-level Global Review. Global Review independently scores every Discovery candidate exactly
once and records content decision, publication decision, semantic duplicate relationships and
structured rejection evidence. Python validates complete candidate-ID coverage, cue/time facts,
continuous boundaries, duration, exact score arithmetic, enumerated gates and the final Top-N ceiling.
It never invents semantic quality, upgrades a model rejection, materializes manual/blocked content or
forces a reference clip count. Historical `semantic_global_v1/v2` behavior remains replayable.

`LLMProvider` has OpenAI Responses, Codex CLI and Mock implementations. Both real implementations use strict structured output, send only one bounded candidate plus small context and quality signals, enable no tools, and treat transcript content as untrusted data rather than instructions. Codex uses controlled non-interactive execution and saved local authentication; it receives text only after ASR. They return value, hook and completeness judgment, boundary suggestions, score/rank, concise Chinese title, reason, risks, and whitelisted caption/effect selections. Layout is system-owned and absent from the model wire schema. Prompt files are versioned. Calls persist model, prompt version/hash, time, request ID, usage, and result status. Model and optional prices are configuration; prices are never hardcoded.

Current Responses API findings are recorded in `docs/research/openai-responses.md`.

### EditPlan and revisions

EditPlan is a strict Pydantic v2 model with exported JSON Schema. Its minimum fields are candidate ID, source start/end, score, title, hook, reason, layout, caption template, effect, risk flags, prompt version, model, and degraded flag. Allowed v1 enums are:

- layout: `center_crop` for every active plan. The historical `vertical_blur_background` value remains readable only so old audit rows do not become corrupt; active validation and rendering reject it.
- caption template: `clean_zh_v1`
- effect: `none`, `fade_in_out`

Times are nonnegative, ordered, within source and configured clip limits, and model adjustments stay inside allowed context. Text fields have bounds. Extra fields and any paths, commands, code, script, SQL, or filter string are rejected. A structurally invalid model result gets at most one repair request, then a deterministic plan marked degraded. Every human change creates an immutable revision, including structured caption cues.

### Rendering and quality

`Renderer` has a deterministic FFmpeg implementation. New pipeline and manual clean masters default to 1080×1920. Historical 540×960 review proxies remain readable but are not the new production default. Every render uses one source-video layer with deterministic center crop; blurred-background fill, duplicated/shrunken foreground composition and model-selected layout are prohibited. It supports basic fades and loudness normalization and outputs H.264/AAC MP4. The clean master contains only the selected source video/audio—no LiveClip-generated title or caption overlay—and is accompanied by an independent clip-relative SRT. Title, Hook, reason, risks and editable caption cues remain separate metadata. An optional derivative may burn an approved title and Chinese captions over the same single-layer video. All cuts re-encode; captions use clip-relative time.

FFmpeg is invoked as argv with `shell=False`. Paths are system generated. No model output becomes executable syntax. Logs redact sensitive/local details. A validated temp artifact is atomically published. VideoToolbox failure automatically retries with libx264. Paths are revision-specific and never overwrite a different successful revision. Any title, caption, or boundary revision marks older renders stale.

Every clean master and optional burned derivative receives ffprobe stream/container validation, audio+video presence checks, resolution/orientation checks, duration tolerance, size floor, full decode to null, representative beginning/middle/end frames, a contact sheet, and heuristics for black/blank/wrong-aspect/severe-crop problems. Renderer-owned safe-area checks apply to burned overlays; a clean master records them as not applicable. When an image viewer is available, Demo contact sheets are actually viewed and the observation is recorded; otherwise the report explicitly says manual visual inspection is pending.

### Selection and delivery

CLI and Web show the candidate, clean master, source interval, score/title/reason/risks and support score/title/boundary/caption edits, keep/discard selection, and rerender. Every edit records the before/after revision, score, title, bounds and captions; the compatibility review record retains the selection transition and timestamp. Only a selected current revision with its validated current clean master is deliverable; selection never initiates or requires the standard render.

The Web review board supports selecting and reviewing several existing candidates in one atomic action. It does not create per-candidate A/B variants inside one board; A/B comparison occurs through separate immutable PipelineRuns. Each full-width horizontal row presents the clean review/delivery master beside title, reason, high-impact sentence and editor keywords; the clip-relative subtitle cues form the row's final full-width section. Subtitle and editor-keyword controls seek only that row's video. The high-impact sentence is the persisted current-revision EditPlan Hook and is distinct from keyword metadata. Keyword text may be selected deterministically or semantically, but every displayed time must be derived from persisted ASR evidence: word intervals when available, otherwise an explicitly labelled transcript-segment interval. LiveClip never invents a precise word timestamp or presents proportional subtitle-display timing as ASR timing. This review metadata is derived from the existing current transcript and must not trigger another ASR request.

Deliveries are immutable `v001`, `v002`, … directories. They contain only selected (`approved` in the compatibility schema) current revisions, silently exclude unselected clips, and fail if none qualify or any selected clip's required clean master is stale, failed, or missing. Creation snapshots and copies the already-rendered master/SRT inputs, builds and validates a temp tree, then atomically publishes without overwriting an existing version. Filenames are safe, stable, and readable; ZIP entries are path-safe. The package includes a CSP-constrained file-only `index.html` video gallery, `checksums.sha256`, manifest, MP4/SRT members and optional ZIP. The manifest includes schema/project/delivery/version/timestamps/source name+fingerprint and, for every ordered clip, IDs, revision, title, filenames, source times, duration, score, review status, and SHA-256. A successful current snapshot makes Project state `delivered`; later edits do not mutate old deliveries and move the computed Project state back appropriately.

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

Transitions are centralized and tested. Required durable concepts include WorkspaceUser, ProjectMember, Project, SourceMedia, PipelineRun, StageRun/attempt, Task, Asset, AudioChunk, Transcript/Segment, CandidateClip, EditPlanRevision/captions, RenderJob, ReviewDecision, Delivery/DeliveryClip, ApiUsage, and idempotency records. Every Project has exactly one owner membership; Project listings and resource reads are server-side membership-scoped.

SQLite uses WAL, foreign keys, busy timeout, Alembic migrations, short explicit transactions, atomic task claims, default single heavy-task concurrency, leases, heartbeat, expiry, worker ID and fencing token, retry counts, crash recovery, safe cancellation, stage idempotency, artifact/input/dependency fingerprints, and persisted failure classification. An explicit retry may resume an unambiguous terminal cancelled Stage while preserving verified succeeded Stages; ambiguous cancelled task graphs fail closed. External I/O never holds a write transaction.

## Security and privacy invariants

- Source video and all image/video/database/generated artifacts remain local.
- Cloud ASR uploads only prepared audio chunks. `mlx-codex` uploads no audio; it reads verified chunks locally.
- LLM receives only candidate transcript/context and necessary metadata.
- The ASR/API key comes only from local environment and never enters DB, logs, UI, errors, Git, or conversation requirements. Codex CLI authentication stays in the CLI credential store and is never copied into LiveClip state.
- Authorization headers/tokens/credentials are redacted.
- Workspace Bearer tokens remain environment-only. SQLite stores user identity and Project membership, never credentials.
- Every Project/run/clip/render/Delivery API operation resolves the owning Project and requires current membership. A non-member receives the same not-found shape as an unknown Project.
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
