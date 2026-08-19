# REST API contract

The local API base path is `/api/v1`; FastAPI publishes the matching OpenAPI document at `/openapi.json`. All times are integer milliseconds (`*_ms`) and timestamps are UTC ISO 8601. Responses expose IDs, safe filenames and generated asset URLs, never arbitrary absolute paths, ORM rows, credentials, provider headers or raw exceptions.

## Authentication and browser media

The server binds to `127.0.0.1` by default. When `LIVECLIP_BOOTSTRAP_ADMIN_PASSWORD` is set, it initializes only the missing password of `LIVECLIP_WORKSPACE_USERNAME`; protected routes then require local login or a configured Bearer credential. Login returns an opaque HttpOnly SameSite=Strict cookie; only its SHA-256 digest is stored. Unsafe cookie-authenticated requests require the in-memory `X-CSRF-Token` returned by login/current session. Logout, password reset, disable or system-role change revokes existing sessions. Five failed attempts within the bounded window temporarily rate-limit that identity with a neutral response.

The v0.1 `LIVECLIP_API_TOKEN` and optional `LIVECLIP_WORKSPACE_TOKENS` JSON mapping remain a deprecated CLI/API compatibility bridge. They stay environment-only. A non-loopback bind is rejected unless the main token exists. CORS accepts only explicit loopback origins and credentials.

SQLite stores Argon2id password verifiers and session-token digests, never plaintext credentials. `GET /projects` is server-side filtered to explicit memberships plus authenticated read-only access to Projects whose visibility is `workspace`. New Projects are `private` and initially have only the creator/owner. Every run, clip, render, media and Delivery route resolves its Project and applies the same policy; a non-member receives 404 for a private resource. Workspace visibility confers only effective viewer/read access. Central policy grants owner all actions, editor Pipeline/edit/render/delivery, reviewer review, and viewer read only. Owners alone manage membership and Project operational settings. Archived Projects are read-only except for owner management/restore. Disabled users remain disabled across restart and cannot be silently reactivated by environment configuration.

An authenticated clip/delivery response may contain a relative, short-lived HMAC URL. The signature binds `GET`, the canonical path, resource purpose/ID and expiry. It lets HTML5 `<video>` seek or a download link work without putting the long-lived Bearer token in a URL. Signed URLs expire within `LIVECLIP_MEDIA_URL_TTL_SECONDS`; the API is started with access logging disabled, and the Vite development proxy redacts query strings before error logging, so signatures are not recorded.

## Routes

```text
GET    /health
POST   /auth/login
POST   /auth/logout
GET    /session

GET    /admin/users
POST   /admin/users
PATCH  /admin/users/{user_id}
DELETE /admin/users/{user_id}
POST   /admin/users/{user_id}/reset-password
GET    /admin/projects
GET    /admin/projects/{project_id}
POST   /admin/projects/{project_id}/ownership-transfer
GET    /admin/audit-events
GET    /admin/storage
POST   /admin/storage/cleanup
GET    /admin/storage/projects/{project_id}/purge-plan
POST   /admin/storage/projects/{project_id}/purge

POST   /jobs
GET    /jobs/{run_id}

GET    /projects
GET    /projects/search
GET    /project-views
POST   /project-views
PATCH  /project-views/{view_id}
DELETE /project-views/{view_id}
POST   /projects/import
GET    /projects/{project_id}
GET    /projects/{project_id}/members
POST   /projects/{project_id}/members
DELETE /projects/{project_id}/members/{user_id}
POST   /projects/{project_id}/ownership-transfer
PATCH  /projects/{project_id}/management
POST   /projects/{project_id}/lifecycle
GET    /projects/{project_id}/activity
POST   /projects/{project_id}/runs
GET    /runs/{run_id}
POST   /runs/{run_id}/cancel
POST   /runs/{run_id}/retry

GET    /projects/{project_id}/transcript
GET    /projects/{project_id}/clips
GET    /clips/{clip_id}
GET    /clips/{clip_id}/comment-threads
POST   /clips/{clip_id}/comment-threads
GET    /comment-threads/{thread_id}
POST   /comment-threads/{thread_id}/replies
POST   /comment-threads/{thread_id}/status
PATCH  /clips/{clip_id}
POST   /clips/{clip_id}/review
POST   /projects/{project_id}/reviews/batch
POST   /clips/{clip_id}/render
GET    /renders/{render_id}

GET    /clips/{clip_id}/download/video
GET    /clips/{clip_id}/download/subtitle
POST   /projects/{project_id}/edit-packages
GET    /projects/{project_id}/edit-packages
GET    /edit-packages/{edit_package_id}
GET    /edit-packages/{edit_package_id}/download

GET    /release-presets
GET    /projects/{project_id}/releases
POST   /projects/{project_id}/releases
GET    /releases/{release_item_id}
PATCH  /releases/{release_item_id}
POST   /releases/{release_item_id}/approval
POST   /releases/{release_item_id}/status
POST   /releases/{release_item_id}/metrics
POST   /releases/{release_item_id}/packages
GET    /release-packages/{release_package_id}
GET    /release-packages/{release_package_id}/download

POST   /projects/{project_id}/deliveries
GET    /projects/{project_id}/deliveries
GET    /deliveries/{delivery_id}
GET    /deliveries/{delivery_id}/download

GET    /media/{asset_id}
```

`GET /health` includes a credential-free startup Provider preflight. It reports the configured combined mode, ASR and LLM adapter names, independent readiness booleans, stable blocking issue codes and explicit Mock warnings. For example, a logged-in Codex editor without OpenRouter ASR configuration reports `mode=openrouter-codex`, `asr_provider=openrouter`, `llm_provider=codex_cli`, `llm_ready=true`, `asr_ready=false`, `processing_ready=false`, and `OPENROUTER_ASR_NOT_CONFIGURED`. “Ready” means only that local configuration/executable/login preflight passed; it does not prove remote quota, model entitlement or service availability. It never returns a key, token, credential path or raw CLI output. The check is captured once at API startup so an unauthenticated health poll cannot repeatedly spawn the Codex CLI; restart `make dev` after changing `.env`/`.env.local` or Codex login.

`GET /session` returns safe user identity, credential kind, expiry and—only for a cookie session—the CSRF value. Project DTOs include safe `owner`, `members`, `visibility`, `current_user_role`, `lifecycle`, `management_version`, `assignee`, `priority`, `due_at`, `updated_at`, server-derived `allowed_actions`, and server-derived `allowed_lifecycle_transitions`. The Web consumes these capabilities instead of maintaining another role/transition matrix. Administrator user responses expose status and password-configured boolean but never hashes. `DELETE /admin/users/{id}` is a recoverable soft disable. The service refuses to disable/demote the last active administrator. `GET/POST/PATCH/DELETE /admin/users...` never trusts only the request-start actor snapshot: every repository operation rechecks the current enabled administrator row inside the same short `BEGIN IMMEDIATE`; create/update/reset returns the post-mutation user list from that transaction, so a concurrent or self role change cannot commit successfully and then produce a misleading forbidden response.

The `/admin/projects` routes are the only explicit cross-Project governance context. They require a currently enabled administrator and return a separate DTO with safe source filename, lifecycle/Pipeline facts, active-state-marked membership and only `view|transfer_ownership` governance capabilities. They do not create Project membership, expose local paths, sign media URLs or grant ordinary edit/export actions; the same administrator still receives 404 from a private Project's normal route when not assigned. The list retains an inactive recorded owner so a disabled-owner Project can be recovered. `POST .../ownership-transfer` accepts any active account ID, rechecks current administrator authority in the same `BEGIN IMMEDIATE`, atomically demotes the old owner to editor, creates/promotes the new unique owner, advances `management_version`, and writes a distinct administrator-actor audit event. `GET /admin/audit-events?project_id=...&limit=1..200` exposes newest-first sanitized structure without secrets or transcript payloads. Cookie-authenticated transfer requires CSRF.

The four `/admin/storage` routes require a currently enabled administrator; unsafe cookie requests also require CSRF. The report performs a no-follow local metadata scan and distinguishes live SQLite/WAL files, migration/operator backups, known Project directories, tracked/stale/pending/orphan/untracked Assets, unknown Project directories, unsafe entries and completed-purge quarantine awaiting retry. Because filesystem traversal can be long and deliberately holds no SQLite writer lock, report and purge-plan operations check current administrator authority before scanning and again immediately before returning; a mid-scan demotion therefore discloses no result. Safe cleanup accepts only `{"confirmation":"CLEANUP_TERMINAL_ATTEMPTS"}` and can remove terminal task worktrees plus quarantine whose exact operation/device/inode is present in completed purge audit evidence; it never deletes committed Project assets or SourceMedia. Cleanup rechecks authority/source/identity and atomically quarantines an attempt in a short SQLite transaction, then recursively deletes outside the writer lock so Worker heartbeats are not blocked. If a process exits after the deterministic hidden cleanup rename, a later pass resumes only when that endpoint matches the persisted device/inode; an original-plus-hidden collision is rejected. Terminal-attempt cleanup is also run at startup, while completed-purge cleanup remains an explicit administrator safe-cleanup operation.

Permanent purge is a two-request workflow. `GET .../purge-plan` returns Project name/lifecycle, generated byte/file counts, active run/task counts, blockers, a snapshot fingerprint and exact `PURGE PROJECT_ID` phrase; filesystem identities used by the server fence are not exposed. `POST .../purge` must repeat that fingerprint, exact Project name, current administrator username and phrase. The Project must still be archived, have no active task/run and have no Project/SourceMedia reference inside its generated directory. LiveClip first creates a validated no-clobber database backup and writes purge intent. A short transaction rechecks authority/state/source scope and atomically quarantines the exact generated-directory inode; full tree verification occurs outside the writer lock; a second short transaction repeats the fences, deletes the Project graph and records completion; recursive cleanup follows after commit. The response returns only the backup filename/hash and whether filesystem cleanup remains pending—never the source path. A stale preview or changed authority/state returns 409; the external source file is never touched. Startup restores an exact started-only quarantine if the Project row still exists.

`POST /projects/{id}/members` accepts an existing active `username`, compatibility `display_name`, and role `editor|reviewer|viewer`; it never creates or reactivates an account. Adding an existing member updates its Project role. `DELETE` removes only a non-owner, non-assigned member; removing the current assignee returns 409 until the owner reassigns the Project. `POST /projects/{id}/ownership-transfer` accepts an active member ID, atomically makes that member the unique owner and demotes the former owner to editor. All three operations require the current owner and write correlation-linked audit events.

`PATCH /projects/{id}/management` is owner-only and requires the current `expected_management_version`. It replaces the complete management tuple `visibility`, `assignee_user_id`, `priority`, and timezone-aware `due_at`; the assignee must be an active Project member. A stale version or unchanged request returns 409. `POST /projects/{id}/lifecycle` accepts `expected_management_version`, one server-advertised target, and a required bounded reason. It rejects skipped/illegal transitions, stale clients, and archiving while a current Pipeline run is queued/running. Archive stores the exact previous lifecycle, blocks ordinary writes, and can restore only to that recorded state. `GET /projects/{id}/activity?limit=1..200` returns newest-first sanitized audit events visible to any caller who can read the Project.

`GET /projects/search` is the dashboard query. It accepts `q`, repeated `lifecycle`, `priority`, `role`, `visibility`, and `platform` parameters; `assignee=any|me|unassigned|user` plus a validated `assignee_user_id`; `due=any|overdue|today|next_7_days|unscheduled`; `sort=updated_desc|due_asc|priority_desc|name_asc`; `limit=1..100`; and an opaque `cursor`. Search is always scoped to current authorization, current Pipeline run, selected current clip revisions and current release revisions. Results include canonical criteria, SHA-256 query fingerprint, fixed `evaluated_at`/timezone, authorized dashboard summary, exact filtered count, bounded match evidence and `next_cursor`. A cursor is actor/filter/time/sort bound and is never an authorization token. Concurrent visibility, membership, run/revision or result changes return safe 409 instead of stale private counts/evidence; callers retry the first page.

`GET /project-views` returns only the current user's valid saved filters. `POST /project-views` requires a 1–80 character normalized unique name, strict criteria and supports `Idempotency-Key`; replay returns the same resource and conflicting key reuse returns 409. `PATCH /project-views/{id}` replaces name and criteria with `expected_version`; `DELETE` takes `expected_version` as a query parameter. Both use exact CAS and return 409 after another tab changes the view. Other users and unknown IDs receive 404. The physical limit is 50 views per user, criteria schema version is currently `1`, and deletion never deletes a Project.

`POST /jobs` and `POST /projects/{id}/runs` return safe `503 PROVIDER_NOT_READY` before creating new work when the configured full processing chain is unavailable. A completed identical `Idempotency-Key` replay is resolved first and still returns its original 202 resource after readiness changes; conflicting reuse remains 409. The Web uses the same health contract to disable its start button. The ingest-only import route remains available as a separate operation and does not execute an LLM readiness/version probe; explicit Mock modes are runnable but health labels them with `MOCK_ASR_SELECTED` and/or `MOCK_LLM_SELECTED`.

`POST /jobs` creates a project and a full run from an allowed absolute source path. `POST /projects/import` creates an ingest-only run; its other five visible stages become `skipped`, after which `/projects/{id}/runs` can start a full generation. Even if an allowed root contains local application data, any resolved path below `LIVECLIP_DATA_DIR` is rejected at ingress and again by the shared PipelineService; generated/project/quarantine files can never become a new SourceMedia reference. Example job body:

```json
{
  "input_path": "/absolute/allowed/live.mp4",
  "top_n": 15,
  "minimum_clip_seconds": 30,
  "maximum_clip_seconds": 90
}
```

The accepted response is immediately pollable:

```json
{
  "schema_version": "1",
  "project_id": "…",
  "run_id": "…",
  "status": "queued",
  "status_url": "/api/v1/runs/…"
}
```

`GET /runs/{run_id}` returns the run status, aggregate progress, cancellation flag, safe error fields, and all six ordered stages. Every stage has an independent status, progress, retry count and safe error fields; for example:

```json
{
  "run_id": "…",
  "project_id": "…",
  "status": "running",
  "progress": 33,
  "cancellation_requested": false,
  "error_code": null,
  "safe_error_message": null,
  "stages": [
    {"stage":"ingest","status":"succeeded","progress":100,"retry_count":0,"error_code":null,"safe_error_message":null},
    {"stage":"preprocess","status":"running","progress":100,"retry_count":0,"error_code":null,"safe_error_message":null}
  ]
}
```

Resource states are deliberately separate:

```text
PipelineRun: queued | running | completed | failed | cancelled
StageRun:    queued | running | succeeded | failed | skipped | cancelled
Project:     imported | processing | pending_review | ready_for_delivery | delivered | failed
Lifecycle:   draft | processing | needs_attention | editorial_review | changes_requested | approval | ready_to_publish | published | archived
ClipReview:  pending_review | approved | rejected
Render:      queued | running | succeeded | failed | stale
Delivery:    queued | creating | succeeded | failed
EditPackage: queued | creating | succeeded | failed
ReleaseItem: draft | ready | scheduled_external | published | failed | withdrawn
ReleaseApproval: draft | pending_review | approved | changes_requested
ReleasePackage: queued | creating | succeeded | failed
```

`Project` above is computed technical readiness; `Lifecycle` is owner-controlled production intent plus deterministic Pipeline signals. A successful Delivery can therefore coexist with `editorial_review`. Only an explicit legal transition records `published`.

`GET /clips/{id}` returns the current plan/revision, separate title/Hook/reason/risk/caption metadata, grounded keyword ranges, review/render states and an `asset_urls` map containing only signed generated-media URLs. The clip-list response also includes the current-revision `hook`, bounded captions, keywords, allowed actions and—only for a current succeeded clean master—short-lived individual MP4/SRT download URLs. The Web labels `hook` as “高光语句”; it labels timed `keywords` as editor-only navigation. A keyword includes clip-relative and source-absolute integer milliseconds plus `word` or `segment` precision; `segment` is an honest persisted ASR range, not an invented word time or proportional subtitle-display interval. The compatibility render kind `proxy` identifies the clean no-LiveClip-text review/delivery master; `final` identifies an optional approved burned derivative. `GET /renders/{id}` exposes its current revision, kind and status. `GET /deliveries/{id}` wraps the Delivery snapshot and an optional signed `download_url`; it includes version, clip count, manifest/ZIP asset IDs and safe errors. Transcript, clip-list, EditPackage-list and delivery-list endpoints expose their respective artifacts without exposing the source absolute path.

Clip comment threads are collaboration metadata, not an edit or review decision. `POST /clips/{id}/comment-threads` accepts `expected_revision`, exact current-clip `clip_time_ms`, a 1–2000 character `body`, and up to 20 unique `mentioned_user_ids`. The server binds the thread to that immutable `EditPlanRevision`, derives canonical source time, and rejects stale revisions or out-of-range anchors with 409. Only active explicit Project members may be mentioned. Owner, editor and reviewer can create/reply/resolve/reopen; viewers and workspace-visible non-members can read, while private non-members receive 404 and archived Projects are read-only. `POST /comment-threads/{id}/replies` is append-only and intentionally has no client version field, so independently submitted replies serialize without overwriting each other. `POST /comment-threads/{id}/status` requires `expected_thread_version` and applies optimistic conflict detection. Every POST accepts `Idempotency-Key`.

`GET /clips/{id}/comment-threads` supports `revision=current|all`, `status=open|resolved|all`, `limit=1..100`, and non-negative `offset`; its response includes `total_count` and `next_offset`. Historical threads retain their original revision-relative time, canonical source time and identity snapshots. `current_clip_time_ms` is derived only when the current revision still contains that source instant, and thread `allowed_actions` is server-derived from live membership and lifecycle state. Comment bodies are returned only through Project-authorized comment endpoints and are excluded from audit-event payloads; audit records retain resource/time/version/mention-count metadata plus safe status-actor identity snapshots instead.

`POST /projects/{id}/edit-packages` is owner/editor-only, accepts `Idempotency-Key`, and snapshots 1–100 ordered unique items shaped as `{"clip_id":"...","expected_revision":2}`. `preset` is currently `clean_editing`; `content` is `full` or `metadata_only`; `include_zip` controls archive creation. Every selected item must still have its exact current clean proxy and quality/producer evidence. The accepted response identifies an `edit_package`; polling returns its immutable `vNNN` state and a signed ZIP URL only after success. A full package contains H.264/AAC MP4, basename-matched UTF-8 no-BOM SRT, JSON/CSV descriptions and keyword times, thumbnails, Chinese import guidance, checksums and manifest. Revision, generation, Asset, authority or lease change before publication fails the active package without mutating an older succeeded version. EditPackage creation does not approve clips, render final text, alter lifecycle, create a formal Delivery or call an AI Provider.

`GET /release-presets` returns the append-only preset history plus an explicit `current_versions` map for new tasks. Each immutable dated preset contains primary-source links, separately identified hard limits, recommendations, conservative safe-zone values and account-policy warnings. These values are editorial preflight configuration, not a claim that LiveClip has authenticated to a social account. `POST /projects/{id}/releases` is owner/editor-only, accepts `Idempotency-Key`, and binds one current, non-rejected clip revision to a target platform/account; its preflight remains blocked until content review is approved. Release mutations require `expected_management_version`; content changes reset prior approval and stale run/revision/render evidence blocks progress. Editors may submit or withdraw an approval request, while only owners/reviewers may approve, revoke approval or request changes. Queue state remains separate from approval.

`PATCH /releases/{id}` replaces editable title variants, description, hashtags, CTA, caption mode, cover time, assignee, planned time and the complete nine-item human checklist. `POST /releases/{id}/status` applies the central state machine. Recording `published` requires an HTTPS external URL or platform content ID, UTC publication time, and `release_package_id` naming the exact current successful platform ZIP. The server atomically stores immutable publication evidence containing package/item/preset versions plus video, manifest and ZIP hashes; queued, failed, cross-item, stale-content or altered-Asset packages are rejected. `failed` requires result notes. `scheduled_external` records only an operator's external plan. Publishing one item reconciles the Project lifecycle through the central lifecycle transition but never performs an upload. `POST /releases/{id}/metrics` appends a manually observed, idempotent performance snapshot.

`POST /releases/{id}/packages` is owner/editor-only and returns 202 for a leased delivery-class Task. The body requires `include_zip=true`; `false` is rejected with 422 because a platform handoff is always a complete downloadable ZIP. Only one queued/creating package may exist per task. It snapshots requester authority and display identity, Project name/generation/epoch, current clip revision and selection, full enqueue-time preflight advisory, preset/item version, render specification, producer Task/Attempt and all media/subtitle/quality/contact Asset hashes. The Worker re-probes and fully decodes the exact MP4, extracts the selected cover frame, writes editable copy/checklist/preflight/manifest/checksums and atomically publishes `release-packages/ITEM_ID/vNNN`. The manifest remains a committed internal Asset and a ZIP member; the download endpoint returns only the signed ZIP. Successful package rows retain the manifest/ZIP hashes captured at completion. Crash recovery revalidates the source-video identity and bytes, decoded media contract, decoded cover pixels, every deterministic member, canonical manifest/checksums and ZIP before adoption; dynamic duplicate-content evidence cannot change recovery bytes. A release-item version change, clip review/revision change or new Project run atomically fails active packages and cancels/fences their durable Tasks, while succeeded versions remain immutable history. Cancellation, retry exhaustion, lease recovery, authority loss or fence mismatch synchronizes the package resource to a safe terminal/retry state without overwriting an older version.

Clip changes use optimistic `expected_revision`. `PATCH /clips/{id}` creates a pending human revision. A boundary change with no `captions` field rebuilds cue-relative milliseconds from the absolute transcript; clients should send `captions` only when the user actually edited them. The optional migration field `layout` accepts only `center_crop`, allowing a historical blur-layout revision to be replaced without changing its editorial text. Every revision must retain at least one cue. `POST /clips/{id}/review` accepts `approved` or `rejected`; when the same body includes title, boundary, layout or caption changes, the new revision and decision commit atomically. The standard clean-master render body is `{"expected_revision":2,"kind":"proxy"}` and does not require approval; `kind:"final"` is the optional approved burned derivative. A delivery body is `{"include_zip":true}` and reuses approved current master assets.

`POST /projects/{project_id}/reviews/batch` accepts 1–100 unique items shaped as `{"clip_id":"...","expected_revision":2,"status":"approved"}` or a rejected item with its required `reason`. The repository validates that every clip is selected in the current Project generation, every revision matches and every decision is permitted before writing any row. One conflict rolls back the whole batch. The endpoint accepts `Idempotency-Key`; replay of the canonical same batch does not repeat effects, while reuse with a different batch returns 409.

Revision and review-decision changes atomically fail active Delivery snapshots with `DELIVERY_SNAPSHOT_STALE`; a new delivery request creates the next immutable version. Already succeeded versions are never overwritten or invalidated.

Long-running creation routes return `202 Accepted`, `Location`, `Retry-After: 1`, a resource/task ID and polling URL. `POST /jobs`, imports, runs, renders, EditPackages, deliveries and batch review accept `Idempotency-Key`. The same key plus canonical body returns the same resource/current snapshots; reuse with a different body returns 409. Only the key SHA-256 is persisted.

## Errors

Every handled failure uses this stable envelope, including request validation and Range errors:

```json
{
  "error": {
    "schema_version": "1",
    "code": "STABLE_MACHINE_CODE",
    "message": "Safe user-facing message",
    "retryable": false,
    "resource_id": null,
    "correlation_id": "...",
    "details": []
  }
}
```

Expected classes are 401 authentication, 403 owner-only membership administration, 404 unknown or inaccessible resource, 409 state/idempotency/asset-integrity conflict, 416 unsatisfiable Range and 422 request/domain validation. `X-Request-ID` carries the correlation ID. Validation details contain only field locations and error types—never submitted values.

## Generated asset serving

`GET /media/{asset_id}` serves only committed allowlisted generated kinds: review/final videos, contact sheets and clip SRTs. EditPackage, ReleasePackage and Delivery artifacts are resolved only through their owning successful resource download routes. SourceMedia and audio chunks are never public assets.

The resolver validates the database project-relative path under the configured data root, every symbolic component, regular-file type, size and SHA-256. The streamer reopens with no-follow semantics and rechecks device/inode/size/mtime before and after bounded reads, closing the validation/open race.

One `bytes` Range is supported (`start-end`, `start-`, or `-suffix`). A valid partial request returns 206 with `Content-Range`; malformed, multiple or unsatisfiable ranges return 416 with `Content-Range: bytes */SIZE`. Both full and partial responses advertise `Accept-Ranges: bytes`, exact `Content-Length`, ETag and `nosniff`.
