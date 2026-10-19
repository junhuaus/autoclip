# LiveClip Solution

Status: v0.1 accepted baseline with v0.2 production-workflow implementation; living document
Decision date: 2026-08-03; v0.2 addendum 2026-08-13

## User scenarios and success boundary

LiveClip turns a local Chinese livestream into selectable vertical highlights and an immutable delivery archive. `liveclip auto VIDEO` resolves a frozen versioned preset and saves one durable Completion goal; an independent Worker processes it while CLI `auto`/`resume` and Web observe the same authorized goal and attempt-bound progress. The configurable `run --wait`, `stage`, `select` and `package` commands preserve foreground and lower-level control. CLI creation prints a caller-scoped request key before commit for same-body recovery; `resume` performs authorized lookup and only explicitly wakes an eligible `needs_action` through the version-fenced application service. Manual selection and exhausted retry remain unchanged by observation. The CLI presentation layer polls persisted snapshots every two seconds and redraws one owned terminal region only when stdout is a TTY. It never derives business state: ASR unit progress comes from fenced persisted chunk outcomes, semantic activity comes from persisted successful provider-call evidence, and current Delivery counts come from a fenced attempt rather than Worker heartbeat. Web saves a confirmed goal ID for reload and hides stale signed links after an authority failure. The Web opens as a video-editor project workspace: each authenticated member sees only assigned Projects, while a Project owner can add editors and reviewers. Users inspect clean vertical video clips alongside separate editorial title/Hook/reason/risk/caption metadata, then keep the default AI-retained set or make one explicit manual selection. Users can recover failed stages, change a proposed clip without mutating history, see stale media, rerender the exact current revision, and package the selected set as a versioned ZIP.

The system controls execution. Models may interpret content and propose a whitelisted EditPlan, but they cannot choose local paths, commands, filtergraphs, SQL, or code. Source video frames never leave the Mac; prepared audio is either processed by the selected local ASR Provider or sent to the selected cloud ASR Provider, and bounded transcript text plus metadata is sent separately to the editor model.

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
       SQLAlchemy/SQLite | filesystem | FFmpeg | MLX | OpenRouter | OpenAI | Codex CLI | Mock

React/Vite ──HTTP──> FastAPI only
```

Import direction is enforced:

- `liveclip.domain`: pure values, entities, EditPlan, caption cues, transition tables, errors. It imports no framework or adapter.
- `liveclip.application`: use cases, DTOs, repository/UoW/provider/renderer/asset ports, fixed pipeline orchestration.
- `liveclip.config`: environment parsing and safe public configuration views.
- `liveclip.db`: SQLAlchemy models, Alembic, repositories, SQLite queue and UoW.
- `liveclip.media`: allowed-root checks, streaming hashes, ffprobe, audio extraction/chunk manifests, silence signals.
- `liveclip.providers`: local MLX, OpenRouter, OpenAI and Mock ASR adapters plus OpenAI Responses, Codex CLI and Mock LLM adapters.
- `liveclip.renderer`: deterministic layout mapping, raster text assets, FFmpeg execution, validation/contact sheets.
- `liveclip.review`: revision/review application helpers where they do not belong in generic commands.
- `liveclip.delivery`: immutable snapshot, manifest, filenames, ZIP validation and atomic publish.
- `liveclip.delivery.edit_package`: selective current-proxy handoff with clean MP4/SRT, editorial metadata, thumbnails, hashes and immutable ZIP publication.
- `liveclip.delivery.release_package`: one-platform release snapshot with an exact video/SRT source, selected cover, editable copy, preflight/checklist evidence, hashes and immutable ZIP publication.
- `liveclip.delivery.review_package`: state-preserving offline-review snapshots of current clean proxies and editorial metadata; these never substitute for formal approved Delivery.
- `liveclip.observability`: structured logging, redaction, usage and subprocess diagnostics.
- `liveclip.bootstrap`: the single composition root.
- `apps/api`, `apps/worker`, and `liveclip.cli`: thin entry adapters.
- `apps/web`: API client and review UI; no domain transition implementation.

The fixed six automated stages are `ingest`, `preprocess`, `transcribe`, `candidates`, `edit`, and `proxy_render`. We deliberately do not introduce a general workflow engine, broker, microservices, event sourcing, or local vector database. The optional MLX runtime is confined to the ASR adapter.

The Typer adapter exposes those stages through one `stage RUN_ID STAGE` command that runs the same durable TaskRunner only until the target succeeds. It also exposes the post-Pipeline steps as `select` and `package`. `SelectionService` maps product-facing default/manual selection onto the compatible atomic batch-review repository: default selection decides only new pending candidates and preserves earlier human exclusions; manual selection validates an exact current candidate set, selects named revisions and excludes all others in one transaction. The compatibility `approved|rejected|pending_review` storage vocabulary remains internal. The CLI Text UI presents the complete user flow as eight steps without pretending the six-stage Pipeline percentage includes selection or packaging.

## Accepted V9 mini-lesson lineage

SD-1B is integrated as of2026-09-13. Its V9 compatibility baseline uses fixed
90/180/300-second bounds, result schema5 and semantic-v5-lineage-v1; quality-v2 remains.
That baseline retains V8 for other algorithms; accepted SD-2 now selects V10/V11 for new requests, as described below. Historical snapshots keep exact fields/fingerprints.
V9's typed rough/final artifacts retain every original proposal, chain/unit route, source
risk and actual terminal quality outcome. Reload revalidates immutable context, graph,
slots, quality partition, persistent IDs, edit plans and captions before downstream writes.
Valid local Discovery cache is namespaced once; post-commit and new-generation recovery
preserve authority without repeating successful semantic calls. No database migration.
The V4 profile discussion below is the compatibility baseline and explicit quality projection;
current mini lineage and schemas are defined by ADR041/042 and the
[accepted report](verification/stable-delivery-sd1b-accepted-2026-09-13.md). Real-model/content acceptance remains SD-6.

## Accepted semantic transport and request budgets

SD-2 is integrated. Its V10/V11 compatibility baseline extends the exact V8/V9 contracts with
semantic-cue-table-v1. Repeated cues are represented losslessly while local validation and
the sole repair retain complete original authority. Initial and repair requests measure the
actual installed OpenAI strict-schema/body or Codex prompt/schema before model I/O. Trusted
planner estimates are identified separately from provider-wire measurements. Budget failures
are deterministic and request-scoped, preserve original calls/audits and prohibit unchanged retry.
All affected cache keys include the new transport and full context-budget settings. No database
migration, response schema, prompt or dependency change is required. See ADR043 and the
[SD-2 report](verification/stable-delivery-sd2-accepted-2026-09-13.md).
SD-3 is now integrated. New defaults V12/V13 extend exact V10/V11 with
semantic-bounded-units-v1: complete-unit bounded futures, owner-thread durable publication,
immutable attempt-owned invocation history and independently hashed outcomes. Compatible
successes are authenticated before reuse; only complete transient failures before repair
permit another logical invocation, at most three total. Uncertain, exhausted or damaged
history fails closed. Actual call evidence survives cancellation without late business
publication. Shared CLI/API retry readiness checks persisted contracts and remaining work,
then compares the recovery snapshot in the mutation transaction. Local completed-provider
recovery retains media/storage validation. See ADR044 and the
[SD-3 report](verification/stable-delivery-sd3-accepted-2026-09-13.md).

## Developer loop control plane

The autonomous development loop is deliberately outside `src/liveclip` and the product's six-stage
runtime. `tools/loop_engineering` owns a durable bounded state machine for planning, coding, review,
test design, deterministic execution, triage and final gating. Requirements and structured role
artifacts are untrusted inputs. Only the coding role receives `workspace-write`, and that authority is
limited to an external candidate workspace; Planner, Reviewer, Tester and Gateway start fresh under
`read-only` against a separate assurance snapshot. A coding repair resumes only the exact persisted
session ID, never a process-global “last” session. The delivery worktree is updated by the trusted outer
process only after deterministic and semantic gates accept the exact assurance snapshot.

The outer Runner owns execution authority. Checked-in configuration maps stable command IDs to fixed
argv arrays and invokes resolved executables with `shell=False` inside an outer deny-default macOS
sandbox; an Agent can discuss a test but cannot create the command that runs. The Runner has no external
network, uses a private HOME and can write only fixed temporary/browser-test paths, never Git, source,
policy, `.loop` or QA evidence. Before Coder, the outer process seals a project-local Python/Web
dependency snapshot in a user-private cache outside Coder authority and freezes Make/lock inputs. Runner
executes a retained source snapshot whose independently computed worktree identity equals the exact
pre-command worktree, never mutable ignored tools in the Coder workspace. Each command binds exit status
to identical before/after Git HEAD, worktree and toolchain fingerprints, while `qa/pipeline.jsonl` and
`qa/test-report.md` remain append-only. The deterministic Gateway correlates request/report/log/execution
identity and rejects missing, failed, mutated or stale evidence and unresolved P0/P1 findings even when
the semantic Gateway says PASS. Writable-role policy inputs are frozen in memory before execution.
Replan/recode budgets and explicit role/environment blocks end in `blocked`, preventing unbounded loops.
ADR-026 records the trust, memory and routing decisions.

## Shared application-service boundary

Commands such as ImportProject, StartPipelineRun, CancelRun, RetryRun, ReviseClip, ReviewClip, RenderClip, CreateEditPackage, and CreateDelivery live once in application services. Queries return sanitized DTOs. CLI commands either enqueue and return, or enqueue then run/poll through the same TaskRunner. They never directly call a private “CLI implementation” of a stage. API returns 202 for enqueued commands. Worker only claims Tasks and dispatches application handlers.

## v0.2 identity, authorization, and production workflow

The local installation has real accounts rather than treating an environment token as a person. Argon2id password verifiers, opaque session-token digests, expiry/revocation, persisted login throttling, CSRF protection, administrator changes, and append-only audit events remain inside SQLite. Provider/API credentials stay environment-only. The v0.1 Bearer-token bridge remains temporarily available for CLI/API compatibility; the Web uses HttpOnly local sessions when account login is configured.

Authority has three independent dimensions: the `administrator|member` system role governs account administration; the `owner|editor|reviewer|viewer` Project role governs work; and `private|workspace` visibility governs discovery. New Projects are private and initially visible only to their creator/owner. Workspace-visible Projects are readable by any active signed-in user as an effective viewer, but visibility never grants mutation rights. API DTOs return the server-derived actions; API, Web, CLI, media, and ZIP access all consume the same policy. An archived Project is read-only except that its owner may manage or restore it.

Professional Project discovery is also server-owned. One strict criteria contract covers free text, repeated lifecycle/priority/role/visibility/platform filters, active assignee semantics, due windows and four stable sorts. SQL starts from the authorized Project set and matches NFKC/casefolded parameterized substrings across Project/source plus only the current run/current revision clip and release evidence. The response contains authorized global facets, exact filtered count, bounded Project pages and bounded match evidence; the browser never downloads all Projects to filter them. Keyset cursors bind the actor, canonical filter fingerprint, initial timezone-aware evaluation instant and final sort tuple. A second selection read after bounded Project hydration rejects concurrent permission, current-run/revision, facet or page changes with a safe 409 rather than mixing snapshots. ADR-018 records the `instr()` Chinese-search baseline and alternatives.

Saved Project views are private user preferences, not Project resources. SQLite stores at most 50 per user with a versioned strict criteria document and per-user normalized unique name. Create is idempotent; update/delete use exact optimistic versions; account deletion cascades its views. Web retry retains a create key after a lost response, refreshes after a CAS conflict and requires explicit confirmation before deletion. No search query history or transcript payload is persisted by this feature.

Business lifecycle is persisted separately from the derived technical Project status. Its values are `draft`, `processing`, `needs_attention`, `editorial_review`, `changes_requested`, `approval`, `ready_to_publish`, `published`, and `archived`. A centralized transition table supplies the only manual next states. Pipeline completion/failure/cancellation updates the appropriate business signal through a system audit event, while successful Delivery does not silently claim publication. Project owners manage visibility, active-member assignment, priority, timezone-aware due date, archive/restore, and lifecycle reason through an optimistic `management_version` compare-and-swap transaction. Removing the current assignee is rejected until the Project is reassigned. This keeps Pipeline facts, human editorial intent, and publication evidence from overwriting one another.

Storage retention keeps archive and destruction separate. Archive is reversible and retains every artifact. Administrator inventory scans with anchored no-follow directory descriptors and reports tracked, stale, pending, orphan, untracked, unknown and unsafe local entries without reading media bytes. Routine cleanup is allowlisted to terminal Task worktrees and completed-purge quarantine whose random operation ID plus device/inode are persisted in database/audit evidence. A process-wide filesystem lock serializes janitors. Under a short `BEGIN IMMEDIATE`, cleanup rechecks current authority, terminal attempt identity and every persisted source reference, then atomically renames the exact attempt inode to a system quarantine. Recursive deletion happens after commit; diagnostic-bearing attempts are reduced in quarantine and atomically restored with only `diagnostics`. This keeps SQLite heartbeats available during large-tree deletion, and an interrupted quarantine is deterministically resumed on startup.

Permanent purge requires an archived Project, no active run/task, a fresh snapshot fingerprint, exact Project-name and `PURGE PROJECT_ID` confirmations, and a current administrator recheck. It creates a WAL-consistent validated no-clobber SQLite backup before intent. One short transaction rechecks the database/source fence and atomically renames the exact Project inode into private quarantine. The potentially long no-follow tree verification runs outside the writer transaction. A second short transaction rechecks authority/state/source references, deletes the Project graph with deferred foreign-key validation and writes completion; recursive quarantine deletion again runs after commit. A failed verification or database transaction restores the exact inode, a process crash before database deletion is recovered at startup, and a post-commit cleanup failure remains visible and safe-cleanup eligible. New Projects can never use any path below `LIVECLIP_DATA_DIR` as SourceMedia, closing the prevalidated-import/purge race; all legacy Project and SourceMedia references are still checked before cleanup. The external source path is never opened for deletion.

Operator backup/restore is implemented independently of Runtime auto-migration. `db-backup` uses `sqlite3.Connection.backup()` against an opened engine so committed WAL state is included, validates an in-memory consistent SQLite snapshot, writes it only through a pinned private descriptor, then requires `quick_check=ok`, no foreign-key violations and one Alembic revision. Publication uses native atomic no-replace rename and withdraws the exact inode if byte/identity or post-rename durability checks fail. `db-restore` pins and streams a no-follow backup into a new private temporary file, rejects a raw database with a nonempty WAL/journal sidecar, validates it, and publishes only to a nonexistent destination. It never overwrites the live database; operators stop services and switch to the separately restored data directory after inspecting revision and hash evidence. LiveClip's explicit transaction-begin hook keeps SQLite DDL/data changes rollback-safe when a migration raises. The current online backup serializes one full snapshot in memory before pinned publication; that bounded-operational simplicity is a known peak-memory limitation for unusually large SQLite databases and is not used for video bytes.

## Canonical time and identifiers

UUID4 strings identify resources. All stored and domain media times are integer milliseconds measured from the beginning of the original source. Field names use `_ms`. This avoids binary floating drift across revisions, SQLite, JSON, captions, and manifests. CLI/API decimal seconds are converted exactly at ingress; FFmpeg seconds and SRT timestamps are formatted only at adapter egress. UTC aware timestamps use ISO 8601.

The public EditPlan representation exposes both clearly named millisecond fields and computed decimal-second fields only where API ergonomics require them; there is never an ambiguous numeric `start` with undocumented units.

## Data model

The initial relational model is:

- Project: user-created workspace, current successful generation/run, current processing run, revision epoch, default-private visibility, business lifecycle, optimistic management version, assignee, priority, due time and archive/restore state.
- WorkspaceUser: local username/display identity, system role, optional Argon2id password verifier and revocable authentication version; it never stores a Provider credential or plaintext password/token.
- ProjectMember: unique user/Project membership with `owner`, `editor`, `reviewer` or `viewer` role; every Project has one owner membership matching `Project.owner_id`.
- AuthSession/AuthLoginAttempt/AuditEvent: hashed opaque browser sessions, bounded persisted login throttling and append-only security/Project activity history.
- SourceMedia: one read-only resolved reference per Project, filename, fingerprint, stat identity, ffprobe metadata.
- PipelineRun: immutable configuration snapshot, generation, run state, progress and error.
- StageRun: logical stage state, input/output fingerprint, checkpoint and progress.
- StageAttempt: append-only lease/attempt/error/metrics audit.
- Task: operational queue item targeting a StageRun, RenderJob, Delivery, or EditPackage; queue state is separate from domain state.
- Asset: generated project-relative path, kind/MIME/size/hash/producer/input fingerprint and validation metadata. SourceMedia is not a downloadable Asset by default.
- AudioChunk: source absolute interval, overlap, generated audio Asset, size/hash/cache key/provider state.
- Transcript: versioned run output; TranscriptSegment and optional TranscriptWord hold real absolute times and timing availability.
- CandidateClip: rough bounds, transcript/context, rule score/reasons, dedup evidence, current EditPlan revision.
- EditPlanRevision: immutable validated plan, parent, origin (`ai`, `deterministic`, `human`), prompt/model/degraded metadata.
- CaptionCue: immutable per-revision structured relative cue; caption edits create a revision.
- ReviewDecision: append-only decision bound to an exact revision, reason and timestamp.
- ClipCommentThread: collaboration thread bound to one immutable EditPlan revision with canonical source milliseconds, original clip-relative milliseconds, open/resolved state, optimistic version and creator/resolver identity snapshots.
- ClipComment/ClipCommentMention: append-only ordered messages and explicit active-Project-member mention snapshots; account rename or removal cannot rewrite history.
- RenderJob: exact revision, kind, dimensions/spec hash, render state, Asset, quality report/contact sheet.
- Delivery: unique Project version and immutable status/snapshot metadata.
- DeliveryClip: ordered immutable snapshot of clip/revision/render/title/bounds/filenames/hash.
- EditPackage: Project-scoped immutable export version, requester, exact generation/epoch fingerprint, content preset and durable task/result Assets.
- EditPackageClip: ordered snapshot of the selected EditPlan revision, clean proxy RenderJob/video/contact-sheet Assets, editorial metadata and published member hashes.
- ReleaseItem: one current clip/platform/account release plan with versioned preset, editable copy, caption/cover choice, assignee, schedule, approval/checklist, optimistic version and manual publication outcome.
- ReleaseMetricSnapshot: append-only manually recorded views/engagement observations for one ReleaseItem; it is evidence, not automatic analytics ingestion.
- ReleasePackage: immutable per-ReleaseItem export version fenced to Project generation/epoch, item version, EditPlan/render/Asset identity and the selected platform-preset version; successful rows retain completion-time manifest/ZIP hashes.
- ReleasePublicationEvidence: one immutable record binding a published ReleaseItem to the exact successful package/item/preset/caption versions and video/manifest/ZIP hashes used by the operator.
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
- EditPackage: `queued → creating → succeeded|failed`; deterministic/transient task failure is persisted, an eligible retry returns `failed → queued`, and succeeded versions are immutable.
- ReleaseItem: `draft → ready → scheduled_external|published|failed|withdrawn`; scheduled work can be recorded as published or failed, failed work may return to draft, a published item may be explicitly withdrawn, and withdrawn is terminal. Approval and item status are separate so an editor cannot imply human approval by changing a queue state.
- ReleasePackage: `queued → creating → succeeded|failed`; every succeeded version is immutable and a newer package never overwrites an older export.

Project state is derived for the current generation, never manually set as a second source of truth. Active pipeline/render/delivery work yields `processing`; an unrecovered current-generation failure yields `failed`; no completed generation yields `imported`; pending/all-rejected/no-approved clips yield `pending_review`; at least one approved current revision with all required current delivery masters yields `ready_for_delivery`; the latest successful Delivery whose snapshot fingerprint equals the current deliverable set yields `delivered`. Editing after delivery leaves the old version downloadable and recomputes a non-delivered current state.

That derived Project state is a technical readiness projection. The v0.2 business lifecycle above is the human workflow projection. For example, a Project can correctly show business state `editorial_review` and technical state `delivered`: an immutable technical package exists, but an owner has not asserted that publication approval or publication itself occurred. Both are returned and displayed explicitly.

## Pipeline execution, lease, and recovery

SQLite connections enable WAL, `foreign_keys=ON`, a configurable busy timeout, and `synchronous=FULL`. Application startup gates on the embedded SQLite runtime: it must support RETURNING and include the official WAL-reset race fix. Python sqlite3 legacy transaction control is disabled; SQLAlchemy emits explicit `BEGIN` and queue ownership uses `BEGIN IMMEDIATE`. SQLAlchemy uses a synchronous engine and short transactions. HTTP handlers may run DB work in FastAPI's thread pool; we do not maintain parallel async and sync repository stacks. ADR-005 and `docs/research/sqlite-concurrency.md` record the evidence and exact safe versions.

A Task claim uses `BEGIN IMMEDIATE`, recovers expired eligible leases, selects one dependency-ready task whose `not_before` has passed, and atomically updates it with worker ID, random lease token, heartbeat and expiry using `UPDATE … RETURNING`. Heartbeat and completion require `(task_id, worker_id, lease_token)`. This fencing prevents an expired old worker from publishing after a replacement has claimed the task.

No FFmpeg, filesystem hash, network call or recursive deletion holds a database write transaction. Before external I/O, a short transaction reserves a pending Asset with producer attempt, expected path and input fingerprint. Asset authority is derived in that transaction through the active TaskAttempt → Task → PipelineRun → Project graph; caller project/generation/candidate/revision values are checked assertions, never trusted authority. A later failed or lost attempt of the same logical Task may adopt an exact matching pending reservation. Immutable package recovery may also adopt exact matching committed Assets, but atomically transfers their producer-attempt ownership before reuse. Each attempt writes a system-owned temporary directory. The handler checks cancellation between bounded operations and terminates an owned subprocess group when necessary. Running cancellation remains a request until the owner acknowledges that safe boundary; queued work may cancel immediately. The handler validates results, verifies that it still owns the lease and relevant revision/generation, then publishes through a no-replace primitive. Revision files use same-directory atomic hard links; immutable package directories use native no-replace rename. Neither replaces an existing official endpoint. Lost-lease or outdated results become diagnostics/orphans, never current success.

Package withdrawal is also attempt-fenced. A runner that observes lost ownership leaves the official directory untouched. For cancellation, validation failure or a failed final completion fence, the Asset store takes a short SQLite writer transaction, proves the Task lease and every package Asset are still owned by that exact attempt, atomically renames only the expected directory inode into the attempt quarantine, and marks the Assets invalid. Recursive quarantine deletion runs after commit. A successor therefore either adopts committed Asset ownership first or observes the old directory already withdrawn; an expired runner cannot delete a package completed by its successor.

Path existence or a prior hash is not a byte-identity fence. Security-sensitive inputs and outputs are opened through a component-anchored no-follow chain and held as pinned regular-file descriptors across validation, subprocess execution and publication. Evidence binds descriptor identity, size and SHA-256. A persisted source device ID is retained for audit but is not a cross-launch equality requirement: macOS may renumber the same mounted volume after reboot or remount. Cross-launch source validation instead requires the same strict real path, regular-file mode, size, nanosecond mtime, inode when available, and full SHA-256 of the pinned descriptor. The current-open binding remains stricter and revalidates device, inode, size, mtime and ctime on that descriptor, so removing the historical-device comparison does not weaken the TOCTOU fence. Render validation sends the same pinned bytes through ffprobe, complete decode and representative-frame extraction, then publication and Asset commit require that verified SHA. Committed stage dependencies are resolved through their exact producer Task and project/run/generation scope, re-opened no-follow, and checked against committed size/hash before a Provider or FFmpeg process can consume them. ADR-007 records this byte-binding model.

One heavy task is claimed by default. `proxy_render` renders candidate proxies sequentially within the stage and checkpoints each RenderJob, avoiding parent/child queue deadlock. Before FFmpeg I/O, each proxy RenderJob is durably inserted and transitioned `queued → running`; success requires committed video/subtitle/quality Assets, while failure, cancellation and lease expiry persist a safe error code. Cheap API queries remain concurrent.

Stage completion is not inferred from arbitrary file existence or a generic Asset row. Each stage has a typed checkpoint contract covering its committed artifacts and required domain rows. The StageStateStore validates that checkpoint and the active Task/Attempt/Run/Project generation under the same `BEGIN IMMEDIATE` transaction before mutating StageRun, PipelineRun, Project or downstream Task state. A committed checkpoint is accepted only when every required Asset still resolves to its canonical project-relative endpoint, is a regular no-follow file, matches committed size and SHA-256, and belongs to the expected producer Task. A legacy SourceMedia row without verified video/audio stream indices cannot satisfy ingest recovery; a matching modern ingest must explicitly upgrade it from actual ffprobe evidence.

Stage retry uses the same PipelineRun and resumes the first failed/incomplete stage when configuration and input fingerprints are unchanged. An explicit retry may also resume a terminal cancelled run only when the first cancelled Stage has exactly one cancelled stage Task: completed Stages stay immutable, that Task is cleared of cancellation/lease state, and only cancelled downstream Stages return to queued. Ambiguous cancelled task graphs fail closed. Persisted PipelineRun configuration is a closed v2 wire snapshot: provider adapter contracts, Prompt version/hash, editorial wire schema, EditPlan schema, vocabulary, retry/timeout/concurrency and optional price inputs all participate in a canonical SHA-256. Every database load checks the exact field set, schema version and stored fingerprint before a handler or provider can run; legacy/tampered snapshots fail deterministically rather than inheriting current defaults. A different configuration creates a new PipelineRun/generation. Deterministic input/configuration failures require a corrected input/configuration and new generation. Explicitly classified local implementation failures (`UNEXPECTED_STAGE_ERROR`, `EDIT_OUTPUT_INVALID` and `PROXY_RENDER_OUTPUT_INVALID`) may be manually requeued on the same immutable run after the installed code is repaired; the bounded retry can fail deterministically again and does not reinterpret bad media as transient. Genuine transient errors—including bounded ingest, preprocess and validation subprocess timeouts—respect retry count and `not_before` backoff.

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

Allowed roots are strict existing directories resolved at configuration load. An input must be absolute, exist, be a regular file, and after `resolve(strict=True)` remain inside at least one resolved root using path-component ancestry—not string prefix. This rejects `..`, prefix tricks, and symlink escape. The resolved path must also remain outside `LIVECLIP_DATA_DIR`, even when an allowed media root contains that directory. API and CLI validate this at ingress, and the shared PipelineService repeats the data-root fence before inserting a Project, so a path validated before a concurrent purge cannot later become a committed source reference to cleanup scope.

We save resolved path, size, mtime nanoseconds, inode/device where available, streamed SHA-256, selected video/audio stream indices, normalized rotation/display dimensions, frame-rate evidence and ffprobe metadata. Expensive stages pin the source endpoint, validate stat identity and hash it once per stage before per-clip work; per-clip checks reuse that evidence instead of repeatedly hashing a multi-gigabyte source. A changed source fails deterministically as `SOURCE_CHANGED`. The source is passed read-only to ffprobe/FFmpeg; LiveClip never opens it for write. Stream mapping is explicit, so a non-first/default audio stream, rotation metadata and VFR timing do not silently change renderer input.

Generated Asset serving re-resolves the database project-relative path beneath the configured data root, rejects symlinks/outside paths and only serves explicitly allowed media kinds. Single-byte-range responses support 206/416, `Content-Range`, `Accept-Ranges`, auth, and bounded streaming. A short-lived HMAC URL binds GET, canonical path, purpose/asset ID and expiry so HTML5 video can seek without placing the long-lived Bearer token in query parameters; streaming reopens no-follow and rechecks file identity around the read.

## Audio and ASR decision

Preprocessing produces mono compressed `m4a` (AAC) or `mp3` chunks, both in the common documented format set, with time overlap and a conservative byte ceiling below 25 MB. Chunk length is additionally capped by configuration. FFmpeg emits to a temp file; a manifest stores absolute millisecond bounds, overlap, bytes, SHA and cache key. `silencedetect` output is parsed into structured source-time intervals.

The user-selected default real path is `openrouter-codex`. OpenRouter receives fixed-model `openai/whisper-large-v3` JSON `input_audio` M4A chunks and returns `verbose_json` with required segment and requested word timestamps. The official STT documentation records that multipart `prompt` is ignored, so configured vocabulary is sent only through `provider.options.groq.prompt`. This is best effort: only a matched Groq upstream receives that option, and ordinary smoke success proves the request chain—not that a vocabulary term was applied; a target-specific transcript must be inspected separately. Each request base64-encodes one already verified chunk bounded to 24 MB, never the multi-hour source. The upstream processing timeout is 60 seconds, so LiveClip defaults to conservative 90-second chunks and four concurrent requests, with both duration/size and concurrency (one through eight) configurable. Only one bounded concurrency batch is submitted at a time; each successful result is validated and cached immediately, while a peer failure stops later batches and retains the completed evidence for retry. The adapter requires an exact `X-Generation-Id`, rejects an ordinary request ID as proof, validates finite nonnegative usage/cost and the SDK's other permissive response fields, and never switches to Mock. ADR-009 and `docs/research/openrouter-audio.md` record the dated evidence and privacy boundary.

The opt-in `mlx-codex` path runs full Whisper `large-v3` locally through `mlx-whisper==0.4.3`. Installation downloads only `config.json` and `weights.npz` from exact repository commit `49e6aa286ad60c14352c404340ded53710378a11`; processing accepts only the recorded configuration hash, 3,083,520,416-byte unquantized weight hash and a local absolute directory. The Pipeline never resolves a Hub ID. A verified M4A chunk is exposed through its pinned seekable descriptor to fixed `shell=False` FFmpeg argv, decoded into a private mono 16 kHz WAV and only that private path reaches MLX. Decode is fixed to Chinese transcription, FP16, temperature-zero deterministic greedy decoding, previous-text conditioning disabled, no generic initial prompt and word timestamps enabled. Disabling prior-window prompting is intentional: the first full-video evaluation exposed long repetition loops, and the pinned runtime itself documents this option as the way to reduce that failure mode. A controlled same-chunk test also proved the generic `LiveClip、直播、高光、切片` prompt caused a 29.98-second high-compression “直播” loop that disappeared without the prompt. Segments whose decoder compression ratio exceeds 2.4 or whose average log probability is below -1.0 are therefore rejected and counted rather than cached as valid text. Pinned `mlx-whisper` does not implement beam search, so unsupported `beam_size` is forbidden rather than silently ignored. Local concurrency is frozen to one, and the complete model/decode/threshold fingerprint participates in immutable config and cache identity. Startup readiness checks Apple Silicon, the exact package, Metal importability, FFmpeg and the full model hash before Project processing. Local audio never leaves the Mac; the later Codex editor remains cloud-backed through its saved login. ADR-027 records the decision and acceptance boundary.

The direct OpenAI alternative remains available. OpenAI's 2026-08-03 general recommendation is `gpt-transcribe`, but official documentation states real word/segment timestamps are currently provided by `whisper-1` with `verbose_json` and `timestamp_granularities`. The `openai`/`openai-codex` modes therefore use `whisper-1` for their required time-aligned contract. This capability-driven exception is recorded in ADR-004. No Provider is allowed to synthesize unavailable word times, and a response without usable segment alignment fails deterministically.

Overlap merging converts all results to source milliseconds, first filters segment overlap by time ownership, then removes duplicated leading text using normalized Chinese character n-grams/longest suffix-prefix similarity. Empty, malformed, sentence-mirror or unaligned optional word arrays make word timing `unavailable` while preserving an otherwise valid timestamped segment transcript; impossible or invalid segment timing still rejects the response. Timing is never fabricated. Original text and merge evidence remain available for audit.

## Candidate and LLM editing design

### Prompt-first Agent Runtime v2

The experimental v2 path is deliberately parallel to the fixed dual-profile
pipeline described below. Its dependency flow is:

```text
versioned Skill + ordered Prompts + configuration + bounded Context
                              ↓
             OpenAI Responses native function tools
       (function_call → local execution → function_call_output)
                              ↓
                immutable evidence-backed Artifacts
                              ↓
       deterministic media validation/render/publication adapters
```

`src/liveclip/agent_runtime` owns the generic loop, OpenAI native transport,
Context budgeting, typed Tool registry, immutable Artifact store, cancellation,
limits and event evidence. `src/liveclip/agent_tools` contains the narrow safe
capability implementations; they are not embedded in the Harness.
`src/liveclip/clipping_skills/agent_clipping_v2` owns editorial behavior and
Profile configuration. `src/liveclip/services/agent_clipping.py` composes one
run without putting provider-specific or editorial rules in the Harness.

Each turn supplies registered capabilities as Responses function tools with
strict closed argument Schemas. The model chooses exactly one native function
and supplies its typed arguments. The Harness executes only that registered
function and returns its bounded observation as `function_call_output` using
the exact provider `call_id`. `finish` is also a native function and is accepted
only when its Artifact IDs exist and pass applicable technical validation. The
internal `AgentTurn` is a stable audit projection of a native call; it is not a
simulated `call_tool` wire protocol. Strict tool definitions require
`additionalProperties: false` and every declared property in `required`.

The configured v2 transport is independent of the ASR/compatibility-pipeline
provider. `openai-responses` uses the direct Responses API, while
`codex-app-server` uses the installed Codex CLI's existing ChatGPT OAuth session
and experimental `dynamicTools` JSON-RPC contract. The latter is genuine native
function calling: Codex chooses a LiveClip dynamic tool, LiveClip's Harness
executes that registered capability, and its result is returned against the
exact App Server request/call IDs. It does not require or persist an
`OPENAI_API_KEY` and it is not a structured-text `call_tool` emulation.

The OAuth adapter starts App Server in an empty private working directory with
network disabled, clears configured MCP servers, disables built-in command,
filesystem, web, plugin, skill and subagent features, and rejects any
unexpected built-in item before it can become an accepted Agent action. The
child environment contains only the minimum process/locale/Codex-login
variables and excludes API keys. Durable state contains thread/call identity,
hashes and usage, not OAuth credentials. Restart either replays a locally
recorded pending dynamic call or resumes the bound App Server thread and
supplies the exact previous tool output. The exact CLI contract, model settings
and disabled-feature fingerprint are included in run identity because dynamic
tools remain experimental.

Run recovery is local and stateful even though provider requests use
`store=false`. One Harness journal binds source Context, Skill, provider/model,
limits and native tool definitions, then persists post-turn events and
Artifacts plus an immutable terminal result. A separate provider conversation
snapshot saves full Responses input/output items, including opaque encrypted
reasoning and a pending function call, before local execution. On restart the
same recorded response is replayed without another provider request; the next
turn appends the exact `function_call_output` under its original `call_id`.

Profile names and bounds are loaded from Skill configuration. Python may prove
that cue IDs exist, an interval is continuous, timestamps are exact and the
duration satisfies the selected Profile. It may not decide semantic identity,
quality, usefulness or title appeal from keywords, punctuation, overlap or
time gaps. The v2 Skill scores all technically valid candidates and has no
automatic approval/block/rejection, content-risk gate or minimum score. User
selection remains downstream. Subtitle correction requires a successful
audio-grounded tool observation and preserves original/corrected evidence;
title generation is its own novice-facing, source-grounded Prompt module.

Completed Agent results flow through a separate v2 delivery adapter rather than
the v1 dual-profile assembler. It revalidates the exact Skill and transcript,
uses a verified subtitle-revision Artifact in preference to original cue text,
and preserves all grounded title alternatives and independent title scores.
FFmpeg writes into a private attempt tree; LiveClip hashes and pins every
regular output, including quality frame samples, and then atomically publishes
the directory without replacement. The offline-review exporter again validates
run/render/transcript identity, hashes, exact SRT and full-decode status before
publishing a browsable package and verified ZIP.

The Skill package and all ordered resources/configuration are hashed exactly
into each run. Scripted/fake-provider tests cover native calls, crash recovery,
subtitle/title precedence and tamper rejection, and a real-media fixture covers
atomic rendering/package publication. That fixture is not real LLM semantic
evidence. V2 remains non-default until real-provider audio/title quality and the
full real-video benchmark are independently accepted. ADR-052 records this
boundary.

Full-transcript runs use an Agent-authored `global_review` Artifact as the
semantic commit point. The model first saves drafts and any corrected
replacements, then submits one exhaustive review row per raw candidate through
`save_global_review`. The capability checks array conservation, existing
references and requested-Profile presence, then freezes candidate creation.
It does not infer duplicates, completeness or cross-Profile relationships.
Those judgments and the review rows remain Prompt/model output. Title tools are
unavailable for a candidate until this review exists and names that candidate
as final, preventing a partial review from silently moving into presentation.
The review Artifact remains in the completed result for raw/final audit.

The offline package includes `全部切片脚本.md` and `全部切片脚本.json` in
addition to individual SRT files. They combine exact candidate identity,
Profile, boundary, score/reason, title alternatives, calibration evidence and
the effective subtitle text. Both label transcript text as untrusted content
and are included in the same checksum/verified-ZIP boundary as the videos.

Pipeline config v6 records `a`, frozen `b`, `b_v2_experimental`, Full-first `semantic_global`, or recommended `semantic_windowed`, plus profile, duration/context budget, strict score threshold and independently hashed Discovery, Boundary Review and Global Review Prompts. Exact historical v2/v3/v4/v5 snapshots are fingerprint-checked against their original closed field sets and adapted only in memory: v2 remains A, v3 remains B v1, v4 B with consolidation maps to the experimental name, and v5 preserves its recorded v1/v2 semantic review. Algorithms never share mutable candidate state or cache namespaces, so the same SourceMedia can be processed through separate immutable runs for truthful comparison.

Algorithm A is unchanged. Candidate generation first forms sentence/turn units from transcript punctuation and gaps. It scores sliding units for duration fit, boundary closure, speech density, pause strength, simple volume/silence signals, hook lexicon/question/list cues, and topic continuity. It keeps context, adjusts to legal sentence boundaries, and deduplicates by interval-overlap ratio plus normalized n-gram/Jaccard similarity. On typical long input it retains 30–50 rough candidates, then deterministic score is always available as a fallback. The editor processes every rough candidate and the pipeline retains the forced Top-N.

Algorithm B v1 remains isolated behind `semantic_window_v1`. For maximum clip length `L`, it creates timestamped `2L` transcript windows at stride `L`, accepts at most one Agent proposal per window and rejects proposals covering at least 55% of a shorter retained interval. This historical path and the completed `8-16-3.ts` run are not rewritten.

The unfinished B v2 design is retained only as `b_v2_experimental`: `semantic_window_v2` followed by `semantic_continuous_v1`, with target `T=60s`, hard maximum `M=90s`, analysis span `T+M=150s`, and stride `T=60s`. It is not the recommended default because its transport-time overlap/adjacency clustering can hide global topic structure.

`semantic_global_v1` is the historical Full-first contract and remains installed for immutable replay. A `tiktoken` estimator for the configured target model computes prompt plus transcript tokens and reserves output and safety space. Absent optional normalization fields are omitted from model transport, while original text, global cue IDs, exact milliseconds and every actual normalized value/note remain available and auditable. If the sum fits the configurable context fraction (0.58 by default), Discovery reads every global cue once and returns a topic map plus zero or more candidates. Global Review again reads the full transcript, topic map and every candidate, may repair omissions and boundaries, compares `viewer_promise`/evidence/payoff rather than time overlap, and performs the only final score. For oversize sources, Python creates token-bounded 10–20 minute transport windows targeting 15 minutes and overlapping by `max_duration + context_guard` (120 seconds by default); it retains global cue IDs and multiple candidates per window. The review input then contains all candidates, topic maps, candidate transcripts, parent-topic ranges and mechanically coalesced nearby context. Coalescing only saves tokens and never decides semantic identity.

`semantic_windowed_v2` is now the recommended Discovery Prompt over the unchanged window transport. It uses 120-second logical windows at a 60-second step, groups four windows into one deduplicated 300-second batch context and assigns that batch a half-open 240-second candidate-start ownership interval. Uncached batches run with bounded concurrency five. Each output has a complete local topic map, zero or more candidates and structured left/right open-topic evidence. One open side is sufficient for Python to schedule a fixed 180-second union of the adjacent edge windows; only the Agent decides whether the boundary evidence is one topic and selects a continuous crossing candidate. Discovery v2 omits the score threshold and Top-N from its request and explicitly preserves valuable risky or imperfect-boundary topics for downstream review. Ownership and the boundary-crossing requirement are deterministic transport validation, not semantic deduplication.

Pipeline config v7 adds the independent `clip_profile` field. Historical config v2--v6 snapshots
upgrade in memory to `short_highlight` and retain their original Prompt hashes and behavior. New
`mini_lesson` runs require the exact 90/180/300-second contract and the versioned
`semantic_topic_chain_v1` Prompt hashes for Discovery, Link Review, Topic Chain Review, Boundary
Review and Global Review; the existing content-domain profile remains a separate orthogonal setting.

For `mini_lesson`, each Discovery logical-window record contains left/right semantic boundaries and
one or more Topic Fragments with central question, learning outcome, completeness facts, source batch,
window and cue evidence. Candidate start ownership removes duplicate transport records inside a batch;
it does not deduplicate meaning. Python schedules an approximately 180-second Link Review whenever
either adjacent side reports an open topic. The Link Agent alone returns same-topic,
same-central-objective, relationship, evidence and whether another boundary is required. Confirmed
open links therefore iterate A→B→C→D instead of stopping after one boundary call. Python's union-find
assembler joins only explicit positive Agent edges and records every edge ID on the resulting Topic
Chain; it never derives an edge from overlap, gap, time adjacency or transcript text.

Topic Chain Review receives the complete continuous Chain transcript and selects the shortest complete
Profile interval. A Chain longer than 300 seconds must either yield Agent-authored natural subunits,
each with split evidence and an independently complete objective, or the explicit
`topic_too_long_without_natural_split` rejection. Boundary Review then receives one candidate, its
Chain and link provenance, plus 30 seconds of actual source context on each side. It classifies
interruptions as none/minor/material; unresolved material interruption is structurally blocking.
Global Review is Profile-local, uses the Boundary Review interval and its local context, records
semantic duplicates and cross-Profile variants, and scores mini lessons as 20 central-objective + 20
closure + 15 teaching structure + 15 standalone understanding + 10 density + 10 cleanliness + 10
title/summary fidelity. Python validates all evidence against the cues actually supplied to that
stage, recomputes the total, applies strict `>75`, quality/risk/publication gates and Top-N, and creates
EditPlan revisions only for automatic results. Mini-lesson FFmpeg masters are isolated below
`runs/gNNN/output/mini_lessons`; manual, blocked and rejected rows remain audit-only. Each Discovery
batch, Link Review, Topic Chain, Boundary Review and Profile Global Review has an independent cache
key bound to source hash, Profile, local identity, model/settings, Prompt hash and the applicable response Schema (v4 for the legacy path), so a
local failure reuses already validated siblings.

Before Global Review, `semantic_global_v3.boundary_review` processes every candidate-bearing Discovery
batch through its own Prompt, response Schema and cache key. It receives the candidate, its exact
source opening/ending, Discovery evidence and provenance, plus at most 180 seconds of local cues. The
Agent must return one actual continuous keep/repair/drop decision per candidate. Python checks exact
cardinality, cue existence/order, literal boundary quotes and 45--90-second duration, but makes no
keyword or topic judgment. A local structure/domain error consumes only that Boundary Review's single
repair and never reruns successful Discovery batches.

Windowed `semantic_global_v3` review reads each candidate's complete linked-topic transcript, normally
15--30 seconds of extra surrounding source cues, all semantic/risk evidence, provenance and its
Boundary Review result. It performs distant semantic deduplication, shortest-complete boundary review,
title/source fidelity review and the only final score, but does not rescan the entire livestream. The
transport may reduce only the extra context guard to fit the immutable budget; candidate/topic
identities, complete linked topics, cue timing/text and calculated facts remain unchanged. A zero-guard
package that remains over budget fails closed. Full-first and historical windowed v1/v2 review remain
available for comparison and immutable replay.

An evaluation plan becomes real media only through an explicit offline-review artifact. The artifact
is SHA-bound to the exact plan, partitions every kept clip into selected or rejected, and may override
boundaries only with real transcript cue IDs. The delivery service maps those IDs back to source
milliseconds, rechecks one continuous configured duration, fingerprints and probes the read-only
source, renders through the fixed FFmpeg contract and publishes the checksum-protected `index.html`
Delivery. This adapter contains no source-specific timestamps or semantic acceptance rules; review
changes remain auditable data.

Discovery v2 makes recall auditable rather than implicit. Its topic map must cover the supplied cue range, and every medium/high-value topic either references one or more candidates or has a typed no-candidate reason. Duration reasons include the model's ideal cue boundaries; safety or rights risks remain structured annotations and cannot suppress a semantically valuable candidate. Candidate records preserve the literal source opening, opening relevance, semantic-core range, irrelevant intro/outro IDs, quality flags and typed risk objects. This lets validation reject noise padding without adding keyword-based candidate discovery.

Python enriches every Discovery candidate and topic with exact cue-derived milliseconds and duration.
`semantic_global_v3` returns exactly one candidate review with separate `content_decision` and
`publish_status`, a fixed 20/20/15/20/15/10 scorecard, proposed cue boundaries, quality/risk enums,
evidence and duplicate mapping. Python recomputes the score and every selected/manual/blocked/rejected
count from the arrays. Context-dependent opening, incomplete ending, internal irrelevant content,
minimum-duration padding and weaker duplicates deterministically drop; title/source mismatch and ASR
meaning reversal block publication; all other unresolved quality flags drop the interval. Typed
health/rights/medical/absolute/person/region risks escalate publication without suppressing Discovery.
No high aggregate score can compensate for these enums.
Historical v2 assessment/coverage validation remains active only for v2 replays.

The stage Prompt loader composes `main.md → common_rules.md → stage → profile → runtime/input`; evaluation examples are excluded from production. Discovery and each versioned Global Review use checked-in JSON Schemas plus strict Pydantic validation. New v2 response Schemas bind both eligible-topic coverage and candidate-assessment arrays to their exact input cardinalities before the call. The single repair request aggregates Schema and deterministic cross-field errors so a model does not consume its only repair fixing one field at a time. Discovery Provider preflight rehydrates the immutable `SemanticInputUnit` and runtime config and invokes the exact stage-domain validator before that repair is spent; ownership, bridge crossing, topic ordering/overlap and continuous-reference failures therefore cannot first appear only after a repaired Provider result has been accepted. Global Review preflight applies the same assessment mappings to raw invalid JSON, including the observed 30-candidate mass-rejection shape. The Stage repeats the same validation as the final enforcement boundary, and repaired repeated invalidity fails without a second model repair. Redundant summary counts are recomputed from concrete candidate dispositions without changing editorial decisions; the exact Agent response remains separate from the normalized raw review, and every correction is audited. The complete cache identity includes transcript/input hash, algorithm, stage, model/settings, stage Prompt version/hash, profile/runtime bounds, input mode/range and—at review—Discovery result hash. A Global Review Prompt change therefore reuses valid Discovery cache while a Discovery change invalidates its downstream review. Ordinary logs contain hashes, files, token estimates and mode, never the full transcript.

Agent boundaries are expressed only as existing cue IDs. Python maps them back to exact source milliseconds, rejects absent/reversed/non-continuous/out-of-range or non-45–90-second intervals, recomputes all six score dimensions, applies `score > 75` (not `>=`), and executes only the structured quality/publication gates described above. It then stably caps the eligible automatic set at Top-N without filling it and records candidates, qualified-before-Top-N, excluded-by-Top-N, manual, blocked and rejected counts. One bounded structure/domain repair is permitted per independently cached stage output; repeated invalidity fails explicitly and provider evidence is retained without replaying the entire semantic stage. The validated artifact preserves every raw Agent response, repair response, source batch/window trace, Boundary Review, duplicate relationship and final disposition. Only automatic results become EditPlan revisions and enter automatic rendering/default Delivery; manual, blocked, rejected and Top-N-excluded results remain audit-only.

All historical and new Skills live in separate versioned directories. Their content hashes are part of immutable run config, making Discovery and Global Review independently replaceable while preserving historical replay safety.

Quality-first new runs default to `gpt-5.6-sol`. Codex Discovery and Boundary Review calls use medium reasoning; only final Global Review v2/v3 uses high reasoning and the existing timeout floor. The model and effective reasoning are present in immutable configuration/cache/call evidence. Historical v1 review runs continue at their recorded medium route. See ADR-028.

The editor sends one candidate per call, bounded pre/post context, rule score and necessary quality signals. The prompt labels transcript fields as untrusted quoted data and explicitly disallows following instructions found inside them. The request exposes no tools. The OpenAI adapter uses `client.responses.parse(..., text_format=WireModel)` or the equivalent strict `text.format` JSON schema. It separately handles `incomplete`, refusal, provider errors, SDK/Pydantic parsing, missing parsed output and local domain validation. Only a normal parsed result reaches EditPlan validation. One repair call is allowed for repairable structure/domain errors; refusal/auth/quota are not “repaired.” Then a deterministic EditPlan is stored with `degraded=true`.

Application-owned retry disables SDK retries, honors bounded `Retry-After`/exponential jitter for timeout, connection, rate-limit and retryable 5xx failures, and never retries deterministic auth/parameter/quota failures blindly. Cancellation exceptions carry every call already made for that candidate, including an initial invalid response followed by a cancelled repair. An append-only evidence fence binds each record to the exact historical TaskAttempt lease token and may persist it after cancellation/lease loss, but cannot mutate transcript, candidate or render state.

At the user's request, ADR-008 adds a second real editorial adapter through the installed Codex CLI. `openrouter-codex` combines OpenRouter timestamp ASR with non-interactive Codex editing; `openai-codex` is the direct OpenAI ASR alternative, while `mock-codex` is explicitly development-only. Codex consumes the same bounded editorial payload via stdin and a strict model-owned JSON Schema. ADR049 pins exactly version 0.154.0 to reviewed profile `tool-free-v3`: only the required local `code_mode_host` transport is enabled, 88 known authority-bearing features are explicitly disabled, execution is read-only/no-approval, user config/rules are ignored, and proxy URLs plus all Provider/API credentials are removed from the child environment. Version output is captured as bytes and validated exactly. Any JSONL tool item, oversized JSONL line or bounded-capture truncation causes failure. The resolved executable path, bytes, size, CLI version and profile are hashed into the immutable Pipeline contract and rechecked before every call. A real smoke must include a Codex thread/correlation ID and positive token usage. Codex never receives LiveClip audio or replaces ASR; its local process reuses saved ChatGPT authentication while inference remains cloud-based.

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

The layout graph has exactly one source-video branch: scale-to-fill followed by deterministic center crop. It contains no `boxblur`, background copy or shrunken foreground overlay. The removed blur value remains decodable only for historical rows and is rejected before FFmpeg argv construction. Effects and loudness are fixed enum mappings. Every cut re-encodes. The renderer exposes two system-owned text modes: `none` for the clean review/delivery master and `title_and_captions` only for an explicitly requested burned derivative. New automatic and manual clean masters use the delivery resolution and publish MP4, clip-relative SRT, quality report and contact sheet before review. The persisted kind `proxy` is retained as a compatibility identifier; it no longer means a disposable low-resolution preview. The render-spec fingerprint includes the text mode and no-blur renderer contract, so an older composited proxy cannot be adopted. In burned mode, a raster overlay is supplied as one finite PNG frame; the fixed `overlay` template explicitly repeats that last secondary frame instead of starting an unbounded looping image demuxer. Complex-filter workers are capped at two and normal libx264 workers at four. A libx264 launch/timeout failure gets exactly one conservative retry with one filter and one encoder thread; completed invalid output is not blindly retried. Partial timeout stderr is retained through process-group termination and bounded before diagnostics. We attempt VideoToolbox first when selected and validated, then fall back to libx264 after any runtime failure. Actual discovery showed VideoToolbox succeeds on the host but fails inside the Codex sandbox with OSStatus -12903, so doctor reports the environment context and fallback honestly. ADR-010 records clean media, ADR-020 records its promotion to the standard delivery master, and ADR-011 records the single-layer no-blur decision.

Transport streams require an additional time boundary. A direct input-side seek may land between HEVC reference frames, so the renderer seeks up to ten seconds early, decodes that bounded preroll, and then applies an output-accurate seek. Source audio and video retain one shared PTS timeline through the filtergraph; LiveClip never rebases the two source streams independently. Trusted overlay/fade windows are shifted by the same preroll, and `ffmpeg-renderer-v4.av-sync-preroll` participates in manual-render fingerprints so corrected media is published as a new immutable artifact. ADR-019 records the evidence and trade-off.

## Render invalidation and review consistency

A visual change transaction inserts a new immutable EditPlanRevision and caption snapshot, increments the Project revision epoch, points CandidateClip to it, makes the effective review pending, and marks queued/running/succeeded/failed RenderJobs for older revisions stale. Boundary-only Web edits omit unchanged relative captions so the repository regenerates them from absolute TranscriptSegment time. A worker that finishes an old render fails revision/lease fencing before publication.

Any current-revision or review-decision change also fails queued/creating Delivery snapshots and cancels or requests cancellation of their durable Tasks in the same SQLite transaction. Successful Delivery versions remain immutable and downloadable. This keeps stale work observable even when the Worker is offline and prevents a late task from publishing an obsolete approved-clip set.

Approval and rejection are append-only decisions on an exact revision. Delivery eligibility requires the current revision, its current approval, and the succeeded validated clean delivery-master RenderJob with the same revision and render-spec hash. Pending and rejected clips are excluded. The master exists before review and its exact bytes are reused by Delivery; a legacy current final is accepted only as a compatibility fallback for projects rendered before ADR-020. Editing after approval never inherits approval and stales the prior master, so only that changed clip must be rerendered.

The ordinary highlight board deliberately presents that compatibility state as one keep/discard selection, not as an approval ceremony. Checking “选入交付” records `approved`; unchecking records the non-deliverable `rejected` state with a system-owned reason. The batch endpoint remains the atomic/idempotent write boundary, but the Web does not ask editors to author rejection reasons and it no longer exposes a second EditPackage selection model in the normal path. Score is part of the immutable EditPlan revision: a score edit advances the revision and therefore requires the clean master for that exact revision before the clip can be selected again. Release approval and historical review APIs remain separate compatibility capabilities. ADR-021 records this presentation boundary.

Timecoded collaboration is deliberately separate from ReviewDecision and Project lifecycle. Creating a thread requires the exact current saved EditPlan revision and an in-range clip-relative millisecond; the repository stores both that original coordinate and the canonical source millisecond. After a boundary revision, the historical anchor never moves. The current-player coordinate is derived from source time only when the new revision still contains it. Threads neither change review status nor stale a RenderJob.

Owner, editor and reviewer have the centralized `comment` capability; viewer and workspace-visible read access are read-only, and archived Projects allow no comment mutation. Every create/reply/status write reacquires `BEGIN IMMEDIATE` and rechecks the active user, current Project membership and lifecycle rather than trusting request-start authorization. Mentions resolve only to active explicit Project members. Replies are append-only and do not carry an optimistic version: SQLite serializes them and assigns unique sequence/thread versions so two valid replies are both retained. Resolve/reopen is state replacement and therefore requires the exact current thread version. All POST operations are idempotency-key capable. Historical author and mention display snapshots survive account rename/removal. The thread row exposes the current resolver snapshot, while each append-only resolve/reopen audit preserves that transition actor's safe identity snapshot; audit events never contain comment bodies or transcript text. ADR-017 records this boundary.

## Quality verification

Validation is a first-class output. A single pinned output descriptor feeds ffprobe, full decode and frame extraction, so validation cannot silently move to replacement bytes. ffprobe confirms MP4, H.264/AAC, both streams, expected dimensions/orientation and duration tolerance. File size has a conservative floor. FFmpeg performs a full decode to null. The validator extracts start/middle/end samples, calculates simple luminance/variance/edge/aspect heuristics, checks renderer-owned title/caption bounds against safe areas in final mode (and records `not_applicable` for clean proxies), and builds a contact sheet. Heuristics are labeled automatic; only an actual image-viewer observation sets visual status to viewed, with notes and timestamp. Diagnostic argv/stderr is bounded, path-safe and secret-redacted; failure to persist optional diagnostics emits a path-free structured warning rather than disappearing.

## Immutable delivery

The service allocates a unique version and snapshots ordered eligible revisions/render assets before I/O. It copies only validated selected clean masters into a same-filesystem private attempt directory, reuses their matching relative SRTs, emits a canonical manifest, a deterministic CSP-constrained file-only `index.html` gallery and `checksums.sha256`, and pins every resulting member with exact size/SHA evidence. It does not start a render after selection. ZIP creation streams from those descriptors, never from ordinary member paths; the exclusively-created ZIP is fsynced, pinned, hashed and reopened from the descriptor to verify its complete canonical member list, member sizes, every member SHA and manifest object.

Publication scans the exact regular-file tree and then performs a native atomic no-replace directory rename. After rename, every canonical endpoint is rebound to the original pinned descriptor and rehashed; failure withdraws the canonical version and fails closed. Before the task records success, it rechecks Project revision epoch/current eligibility and repeats manifest, disk member, ZIP member and committed Asset hash validation. An existing version is never removed or overwritten. Crash recovery adopts only a directory that passes the same exact validation; mere presence of `manifest.json` or `delivery.zip` is insufficient.

Offline review export is a separate synchronous application query/export path. It resolves only the current clean succeeded master Asset for every selected current-generation clip, verifies the committed size/hash and transactionally captures run/generation/Project epoch/current revision/review/RenderJob/producer Task/Asset lineage. It snapshots the exact EditPlan description/captions/grounded keywords and builds outside SQLite, then rechecks the captured fence immediately before and after atomic no-replace publication; a raced post-publication version is withdrawn by exact directory identity. Strictly named crash-orphan attempts are recovered under the package lock with no-follow identity checks. Each immutable `offline-review-packages/vNNN` includes a CSP-constrained file-only HTML viewer plus MP4/SRT/Markdown/v2 JSON/checksums/ZIP and requires no server after extraction. The export never writes a ReviewDecision, RenderJob, Delivery row, ApiUsage row or Project status; `pending_review` remains truthful. Formal Delivery uses the same master bytes but filters to approved current revisions.

Selective editor handoff is the durable `EditPackage` path, distinct from both offline review and formal Delivery. Owner/editor requests carry 1–100 unique clip IDs and exact revisions. One `BEGIN IMMEDIATE` transaction verifies the current completed generation, active membership, immutable EditPlan/captions/review metadata, current clean proxy, contact sheet, producer TaskAttempt lineage, committed hashes and quality evidence; pipeline-stage proxies and later manual proxy renders are both valid only through their own exact producer contract. The selection and package fingerprints are persisted before a normal leased heavy Task is queued. The Worker copies pinned bytes, validates H.264/AAC/yuv420p/progressive/fast-start/full decode, writes matching UTF-8 no-BOM relative-time SRT plus JSON/CSV/thumbnail/guide/checksum members, and publishes `edit-packages/vNNN` atomically without replacement. It rechecks requester authority, Project generation/epoch, every revision/render/Asset and the Task lease before and after publication. A changed selection fails closed; an older succeeded package remains downloadable and never changes Project review, lifecycle, Provider usage or formal Delivery state.

Release planning is a fourth, separate path. A `ReleaseItem` may be drafted from a current non-rejected high point before editorial approval, but its preflight stays blocked until the exact current revision is approved, its selected media mode has a trusted current render, all required Hook/first-frame/subtitle/rights/privacy/claims/sponsorship/platform confirmations are explicit, and hard preset checks pass. Presets are immutable code configuration with a version, check date, primary-source links and separately labelled hard rules, recommendations and account-dependent warnings. The registry exposes one explicitly selected current version per platform while keeping historical versions resolvable for old records and safe-zone previews. Safe-zone values are conservative LiveClip editorial overlays, not claims about undocumented platform coordinates. A duplicate-content check compares immutable succeeded ReleasePackage snapshots, EditPackages and Deliveries using source overlap and normalized n-gram similarity; it is an advisory warning, never a blocker on intentional cross-platform reuse. Release-item mutations use optimistic compare-and-swap and append audit events; approval is a distinct owner/reviewer operation and can be revoked with a reason. Only an owner or editor may be the release assignee; a scheduled item cannot silently lose its planned time.

A release-package request snapshots one ready or externally scheduled item in `BEGIN IMMEDIATE`, then queues an ordinary leased delivery-class Task. Platform handoff always produces a complete ZIP; an explicit false `include_zip` value is invalid. `clean_separate` selects the current trusted clean proxy and emits a basename-matched UTF-8 SRT; `burned` selects the exact current approved final render and omits a separate SRT only when the requested mode says so. The Worker re-probes and fully decodes the pinned MP4, checks the selected preset, extracts the exact clip-relative cover frame with argv-only FFmpeg, writes editable release copy, checklist/preflight JSON, manifest, checksums and ZIP, and atomically publishes `release-packages/ITEM_ID/vNNN`. Requester authority, Project/revision/item/preset/render/Asset fingerprints and task lease are checked before and after publication. Artifact-facing Project/requester names and full source preflight are frozen at enqueue; duplicate advisory state is excluded from the material current-content fingerprint, so another export cannot make an older package stale or change crash-recovery bytes. Recovery does not trust a self-reported replacement manifest: it rechecks the pinned video hash/size and decoded media, compares a freshly decoded cover by pixels, regenerates deterministic metadata, and requires canonical manifest/checksum/ZIP equality. Any release-item version change invalidates its queued/creating packages; a clip revision (which increments the Project epoch) or new PipelineRun invalidates all active Project release packages in the same SQLite transaction, cancelling queued Tasks and requesting cancellation of leased Tasks. Successful package versions remain immutable history. Recording `published` requires actual time plus external URL/ID and the exact current successful package; immutable publication evidence binds its package/item/preset/caption versions and video/manifest/ZIP hashes. Scheduling is explicitly `scheduled_external`: LiveClip neither stores social credentials nor automates an upload.

## API, errors, and idempotency

API schemas are DTOs, never ORM serialization. Internal absolute paths are omitted unless a CLI-only command explicitly needs them; Web receives asset IDs and source filenames/ranges. The stable error envelope contains version, code, message, retryable, resource ID, and optional safe field details/correlation ID. Exception mapping strips headers, tokens, provider request content, raw SQL and stack traces.

The API resolves one `AuthenticatedCaller` at the request boundary. V2-M1 adds local username/password login backed by Argon2id verifiers, opaque random sessions stored only as SHA-256 digests, HttpOnly SameSite=Strict cookies, synchronizer CSRF checks for unsafe cookie-authenticated requests, bounded login throttling and immediate session revocation after logout/disable/role/password change. `LIVECLIP_BOOTSTRAP_ADMIN_PASSWORD` is a local one-time initializer that only fills a missing verifier; it never enters Git or API output. If no password login has been enabled, the v0.1 loopback identity and configured `LIVECLIP_WORKSPACE_TOKENS` Bearer mapping remain a deprecated compatibility bridge rather than locking out the existing installation.

System role (`administrator`/`member`), Project role (`owner`/`editor`/`reviewer`/`viewer`) and Project visibility (`private`/future `workspace`) are distinct. A new Project is private and owned only by its creator. `GET /projects` joins through `ProjectMember`, and every run, clip, render, media, EditPackage and Delivery route resolves the owning Project and verifies current membership. A centralized action matrix grants owner all actions, editor Pipeline/edit/render/export/delivery, reviewer review, and viewer read only; the same matrix produces `allowed_actions` for clients. Non-members receive the same not-found response as unknown resources, including when they know a media, EditPackage or Delivery ID. Project ownership transfer is one `BEGIN IMMEDIATE` transaction that preserves one owner, demotes the former owner to editor, advances the management version and writes a correlation-linked audit event. The administrator console does not silently add Project membership or grant descendant/media access. Its separate `/admin/projects` projection explicitly lists every Project—including an inactive owner—without ordinary Project actions; an explicit CSRF-protected transfer can promote any active account under a same-transaction current-administrator fence and records a distinct administrator audit event. `/admin/audit-events` exposes sanitized global governance evidence. Request authentication supplies an actor snapshot for routing, but no administrator repository treats that snapshot as continuing authority: DB-only identity/governance reads and mutations recheck the live enabled role under a short `BEGIN IMMEDIATE`, and identity mutations return their user-list projection from that same transaction. Filesystem-backed storage reads check before traversal and again on fresh DB state before returning, so concurrent demotion is either ordered after the result or causes denial.

The Web receives the safe current-session identity plus Project owner/member/role DTOs. It never decides authorization: member-scoped queries and mutations remain backend rules. Signed-out users see a login screen; administrators see member create/edit/disable/reactivate/reset actions. Session identifiers remain HttpOnly and never enter Web storage; CSRF values are kept on the API client in memory. The optional legacy Bearer input is also retained in React memory only during the migration window.

An Idempotency-Key is scoped by authenticated caller and endpoint. The canonical request hash is stored with the created resource. Reuse with the same hash returns that resource even if Provider readiness later changes; reuse with a different payload is a stable 409. API create handlers replay a completed record before readiness gating, while new work is still rejected when the selected chain is unavailable. Creation and record insert occur in one transaction.

Batch review is a short synchronous application transaction, not a background task. The request carries a unique clip ID, expected EditPlan revision, decision and optional rejection reason for each selected candidate. The repository first checks the canonical `Idempotency-Key` record, validates every item belongs to the requested current Project generation and every expected revision still matches, then records every decision, invalidates active Delivery snapshots and persists the idempotency result under the same `BEGIN IMMEDIATE`; any conflict rolls back the entire batch. A same-key/same-payload replay returns current snapshots without repeating effects, while same-key/different-payload fails with 409. The Web never approximates this with concurrent single-clip requests. A failed Web request retains the exact body/key for explicit retry, reconciles Project/clip state first, and disables that retry if any included candidate is missing, has a changed revision or has an unsaved editor draft. Batch work in flight locks editor writes so a response cannot overwrite local draft state.

Review-board keywords are read-only grounded navigation metadata, not LLM-authored execution data and not an EditPlan field. A deterministic extractor ranks phrases from trusted editorial metadata but returns them only when the exact normalized phrase occurs in a persisted ASR segment fully contained by the current clip. It binds the phrase to persisted transcript word intervals when present or to the entire containing ASR segment otherwise. Responses include clip-relative and source-absolute integer milliseconds plus `word` or `segment` precision. Proportional caption display intervals never become keyword evidence. Keywords are recomputed from the current revision and current transcript, so no migration, render invalidation or repeat ASR is required. Human caption/boundary edits continue to create a new revision; the next query derives keyword occurrences inside that exact boundary.

The review list exposes the current EditPlan `hook` in its summary DTO and labels it “高光语句”. This is LLM-authored, bounded editorial copy associated with the exact immutable revision; it is not derived from the keyword extractor and it is never treated as executable data. “编辑关键词” remain timed internal navigation aids. The Web renders one semantic ordered-list item per full-width row: a desktop grid places video on the left and editorial fields on the right, then a sibling subtitle section spans the bottom as the row's final content. Narrow screens collapse the main grid to one column without changing semantic order.

The Web review workspace does not fetch or render the complete livestream transcript. That large panel duplicated the information needed during candidate review and separated it from the video being judged. The current-revision caption cues and grounded keyword ranges are the candidate-level presentation surface. The persisted transcript and `GET /projects/{project_id}/transcript` remain application/API capabilities for processing, diagnostics and external consumers; removing the Web panel does not remove ASR or transcript data.

## Configuration and secrets

Pydantic Settings reads environment variables and optional ignored `.env`/`.env.local` files. Settings validation never includes secret values in exceptions or dumps. `LIVECLIP_API_TOKEN` authenticates the configured default workspace user and signs browser-media URLs; optional `LIVECLIP_WORKSPACE_TOKENS` contains distinct member tokens and therefore requires that signing token. Only a safe configured-member count appears in public configuration summaries. The composition root reads `OPENROUTER_API_KEY` only for `openrouter-codex` and `OPENAI_API_KEY` only for `openai`/`openai-codex`; `mlx-codex` requires neither ASR key. A runtime/provider mismatch fails deterministically before any stage handler. OpenRouter's Base URL and v1 model are exact allowlisted values, while the MLX repository revision and content hashes are exact constants, preventing configuration-based credential or model substitution. Mock-only startup retains neither key and instantiates no cloud client. Codex receives no ASR key, API token or credential-bearing proxy URL. API health exposes only safe Provider names, readiness booleans and stable issue codes.

## Observability

Structured JSON logs include timestamp, level, event, correlation/project/run/stage/task/clip IDs, attempt, duration and stable error code. A centralized processor redacts authorization, API keys, bearer tokens, cookies, common secret fields and matching secret substrings. Uvicorn request access logging is disabled and the Vite proxy removes query strings before its offline error logger runs, because short-lived media signatures are credentials. FFmpeg logs store a sanitized logical argv using asset IDs/relative paths plus a bounded stderr tail in a diagnostic file. ApiUsage captures provider metrics but no prompts containing transcript text unless an explicit local debug mode is later designed.

## Testing strategy

- Unit tests own pure domain, security paths, fingerprints, timestamp conversion/merge, candidates, EditPlan/schema, prompt boundary, subtitles, argv, fallback, states, leases, stale rules, delivery/ZIP and redaction.
- Integration tests use actual generated H.264/AAC media and FFmpeg/ffprobe, a temp data root and SQLite database, Mock providers, interruption/failure injection, and full artifact validation.
- API tests use a real application composition with temp resources and verify 202/idempotency/error/auth/Range/user-visible flows.
- Web unit/component tests cover all critical states and actions. One Playwright flow uses a controlled API double for UI-state determinism; a second isolated flow starts real FastAPI, a leased Worker, SQLite, Vite and FFmpeg with Mock AI, then proves Range, selective EditPackage ZIP, revision stale, pre-approval master rerender, formal Delivery reuse and `delivered` through both UI and persisted evidence.
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
- ADR-027: optional pinned full-precision MLX Whisper large-v3 ASR with single-worker deterministic decoding.
- ADR-028: accuracy-first per-candidate Global Review scoring with Sol/high final-review routing.
- ADR-029: independent mini-lesson Profile with iterative Agent-linked Topic Chains.
- ADR-052: prompt-first Agent Runtime with a deterministic Python Harness.
- ADR-010: clean review proxies with separate editorial metadata; text overlays only in final mode.
- ADR-011: one direct center-crop source layer; blurred backgrounds and duplicated foregrounds are prohibited.
- ADR-012: grounded review metadata and atomic, revision-fenced batch decisions without A/B variants.
- ADR-013: environment-authenticated workspace identities with server-side Project membership isolation.
- ADR-014: local accounts, separate authority dimensions, professional business lifecycle and immutable standards-based editor handoff packages.
- ADR-015: release planning, platform preflight and immutable handoff packages without storing social-platform credentials.
- ADR-016: storage inventory, recoverable archive, fenced Project purge and WAL-correct backup/restore.
- ADR-017: exact-revision/timecode collaboration comments with append-only replies and optimistic resolution state.

## SD-1A accepted quality contract (2026-09-12)

PipelineRunConfig v8 records semantic-v4-quality-v2 while preserving exact historical
v2–v7 fingerprinted loaders and old V4 wire/Prompt/Schema bytes. Current Boundary and
Global validation checks structured quality facts and direct retained duplicate
representatives before Top-N. Current cache identities distinguish this contract.
The provider retains complete available Schema/domain and indexed multipart errors;
one eligible semantic repair shares the existing budget. Failure audit uses immutable
run-generation assets and an exact task/lease-owned diagnostic manifest,with recursive
credential redaction and successful sibling-cache recovery. ADR030 and ADR036–039
record the rules; ADR031–035 preserve the developer Runner's constrained environment.

Formal195929 accepted the exact source and synthetic mini artifacts; the report is
in docs/verification/stable-delivery-sd1a-accepted-2026-09-12.md. This does not establish
real-provider/content performance. Source-lineage closure,new transport,execution recovery
and durable completion intent remain separately bounded SD-1B through SD-5 work.

## SD-4 C1 isolated Worker coordination contract

This section preserves the isolated C1 acceptance contract that preceded
the integrated SD-4 publication. Bootstrap
constructs one CompletionRunner on the same SQLite queue as stage, render and delivery,
with the resolved generated-data directory and the configured delivery retry limit.
The persistent Worker tries stage, render, delivery and completion at most once per
bounded round. IDLE or transient claim BUSY moves to the next category; the first
handled outcome ends the round and moves the process-local starting cursor after that
category. An entirely unhandled round preserves the cursor and waits; `--once` runs
one bounded round. The Worker does not implement selection or delivery decisions.

Manual selection parks a completion Task in WAITING with no periodic attempt. Timed
deferral instead records an honest attempt and `not_before` without consuming a
failure retry. A client watch, browser refresh, disconnect or Ctrl-C only observes
persisted state and does not claim or cancel work. Restart uses the saved intent,
selection action key and immutable Delivery ID/version; it cannot retarget a newer
delivery or reset historical failed renders. The existing heavy-task lease fence
still applies across independent Workers.

During artifact inspection, lease renewal and cancellation observation run outside
the writer transaction. Shutdown must stop and join the monitor, including an
in-flight bounded SQLite lock wait, before closing inspection handles or runtime
resources. A previous owner's unfinished attempt remains truthful until lease
expiry and ordinary bounded recovery; shutdown must not fabricate success or
cancellation, and late renewal after stop is forbidden. C1 engineering evidence
requires disposable SQLite, synthetic FFmpeg artifacts and fresh fixed Runner and
independent review; it does not establish the public API or real-content acceptance.

## SD-4 C2 public goal integration contract

C1 Worker recovery was first accepted in an isolated candidate. Published C2 adds the public
goal commands over one CompletionService; API handlers translate authenticated
requests and authorized snapshots without duplicating selection, retry or Delivery
rules. The frozen routes create a new project/run goal, attach to an existing
current run, read by intent ID, and explicitly resume, select or cancel with
version checks. Creation requires an Idempotency-Key and returns a 202 Location;
observation never claims a Task. The response exposes a signed Delivery ZIP URL
only when the bound Delivery actually succeeded, through the existing asset-ID
download route.

For a new-project create, the service rejects relative or parent-traversing
request syntax before entering SQLite. The repository derives canonical identity
from that original request spelling, enters BEGIN IMMEDIATE, checks same-key
replay under current authority first, then runs a bounded fresh-source/Provider
readiness guard only if a new project/run/intent must be inserted. The guard
strictly resolves a readable regular file within configured allowed roots and
outside generated data, returning the path persisted by that same transaction.
Provider readiness is assessed before the transaction and the callback inside
it reads that result; no login probe, inference or source copy occurs while
holding the writer lock. A lost-response replay can therefore recover the
same intent after the source disappears or provider readiness changes, while a
genuinely new request still fails safely. The integrated SD-4 source was
published after fresh API/Worker/SQLite/FFmpeg and real-browser synthetic
evidence, fixed Runner lint/test, Reviewer/Gateway PASS, independent retained
ZIP/Asset/media audit and exact 47-path original CAS publication. The
completion intent remains a thin durable coordinator over existing business
services; clients never supply executable commands, a media path for download
or authority for Worker effects. The accepted engineering evidence is in
`docs/verification/stable-delivery-sd4-accepted-2026-09-14.md`.
