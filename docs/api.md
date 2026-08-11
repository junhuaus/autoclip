# REST API contract

The local API base path is `/api/v1`; FastAPI publishes the matching OpenAPI document at `/openapi.json`. All times are integer milliseconds (`*_ms`) and timestamps are UTC ISO 8601. Responses expose IDs, safe filenames and generated asset URLs, never arbitrary absolute paths, ORM rows, credentials, provider headers or raw exceptions.

## Authentication and browser media

The server binds to `127.0.0.1` by default. If `LIVECLIP_API_TOKEN` is configured, protected JSON routes require `Authorization: Bearer …`; a non-loopback bind is rejected unless a token exists. CORS accepts only explicitly configured loopback HTTP origins. The Web console keeps a user-entered API token in memory only.

An authenticated clip/delivery response may contain a relative, short-lived HMAC URL. The signature binds `GET`, the canonical path, resource purpose/ID and expiry. It lets HTML5 `<video>` seek or a download link work without putting the long-lived Bearer token in a URL. Signed URLs expire within `LIVECLIP_MEDIA_URL_TTL_SECONDS`; the API is started with access logging disabled, and the Vite development proxy redacts query strings before error logging, so signatures are not recorded.

## Routes

```text
GET    /health

POST   /jobs
GET    /jobs/{run_id}

GET    /projects
POST   /projects/import
GET    /projects/{project_id}
POST   /projects/{project_id}/runs
GET    /runs/{run_id}
POST   /runs/{run_id}/cancel
POST   /runs/{run_id}/retry

GET    /projects/{project_id}/transcript
GET    /projects/{project_id}/clips
GET    /clips/{clip_id}
PATCH  /clips/{clip_id}
POST   /clips/{clip_id}/review
POST   /projects/{project_id}/reviews/batch
POST   /clips/{clip_id}/render
GET    /renders/{render_id}

POST   /projects/{project_id}/deliveries
GET    /projects/{project_id}/deliveries
GET    /deliveries/{delivery_id}
GET    /deliveries/{delivery_id}/download

GET    /media/{asset_id}
```

`GET /health` includes a credential-free startup Provider preflight. It reports the configured combined mode, ASR and LLM adapter names, independent readiness booleans, stable blocking issue codes and explicit Mock warnings. For example, a logged-in Codex editor without OpenRouter ASR configuration reports `mode=openrouter-codex`, `asr_provider=openrouter`, `llm_provider=codex_cli`, `llm_ready=true`, `asr_ready=false`, `processing_ready=false`, and `OPENROUTER_ASR_NOT_CONFIGURED`. “Ready” means only that local configuration/executable/login preflight passed; it does not prove remote quota, model entitlement or service availability. It never returns a key, token, credential path or raw CLI output. The check is captured once at API startup so an unauthenticated health poll cannot repeatedly spawn the Codex CLI; restart `make dev` after changing `.env`/`.env.local` or Codex login.

`POST /jobs` and `POST /projects/{id}/runs` return safe `503 PROVIDER_NOT_READY` before creating new work when the configured full processing chain is unavailable. A completed identical `Idempotency-Key` replay is resolved first and still returns its original 202 resource after readiness changes; conflicting reuse remains 409. The Web uses the same health contract to disable its start button. The ingest-only import route remains available as a separate operation and does not execute an LLM readiness/version probe; explicit Mock modes are runnable but health labels them with `MOCK_ASR_SELECTED` and/or `MOCK_LLM_SELECTED`.

`POST /jobs` creates a project and a full run from an allowed absolute source path. `POST /projects/import` creates an ingest-only run; its other five visible stages become `skipped`, after which `/projects/{id}/runs` can start a full generation. Example job body:

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
ClipReview:  pending_review | approved | rejected
Render:      queued | running | succeeded | failed | stale
Delivery:    queued | creating | succeeded | failed
```

`GET /clips/{id}` returns the current plan/revision, separate title/Hook/reason/risk/caption metadata, grounded keyword ranges, review/render states and an `asset_urls` map containing only signed generated-media URLs. The clip-list response also includes bounded current-revision captions, keywords and allowed actions so the review board does not need an N+1 detail fan-out. A keyword includes clip-relative and source-absolute integer milliseconds plus `word` or `segment` precision; `segment` is an honest persisted ASR range, not an invented word time or proportional subtitle-display interval. A proxy URL always references the clean no-LiveClip-text review video; final media may contain the approved overlays. `GET /renders/{id}` exposes its current revision, kind and status. `GET /deliveries/{id}` wraps the Delivery snapshot and an optional signed `download_url`; it includes version, clip count, manifest/ZIP asset IDs and safe errors. Transcript, clip-list and delivery-list endpoints expose their respective artifacts without exposing the source absolute path.

Clip changes use optimistic `expected_revision`. `PATCH /clips/{id}` creates a pending human revision. A boundary change with no `captions` field rebuilds cue-relative milliseconds from the absolute transcript; clients should send `captions` only when the user actually edited them. The optional migration field `layout` accepts only `center_crop`, allowing a historical blur-layout revision to be replaced without changing its editorial text. Every revision must retain at least one cue. `POST /clips/{id}/review` accepts `approved` or `rejected`; when the same body includes title, boundary, layout or caption changes, the new revision and decision commit atomically. A render body is `{"expected_revision":2,"kind":"final"}`. A delivery body is `{"include_zip":true}`.

`POST /projects/{project_id}/reviews/batch` accepts 1–100 unique items shaped as `{"clip_id":"...","expected_revision":2,"status":"approved"}` or a rejected item with its required `reason`. The repository validates that every clip is selected in the current Project generation, every revision matches and every decision is permitted before writing any row. One conflict rolls back the whole batch. The endpoint accepts `Idempotency-Key`; replay of the canonical same batch does not repeat effects, while reuse with a different batch returns 409.

Revision and review-decision changes atomically fail active Delivery snapshots with `DELIVERY_SNAPSHOT_STALE`; a new delivery request creates the next immutable version. Already succeeded versions are never overwritten or invalidated.

Long-running creation routes return `202 Accepted`, `Location`, `Retry-After: 1`, a resource/task ID and polling URL. `POST /jobs`, imports, runs, renders, deliveries and batch review accept `Idempotency-Key`. The same key plus canonical body returns the same resource/current snapshots; reuse with a different body returns 409. Only the key SHA-256 is persisted.

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

Expected classes are 401 authentication, 404 unknown resource, 409 state/idempotency/asset-integrity conflict, 416 unsatisfiable Range and 422 request/domain validation. `X-Request-ID` carries the correlation ID. Validation details contain only field locations and error types—never submitted values.

## Generated asset serving

`GET /media/{asset_id}` serves only committed allowlisted generated kinds: review/final videos, contact sheets and clip SRTs; delivery ZIP is resolved from the owning successful Delivery download route. SourceMedia and audio chunks are never public assets.

The resolver validates the database project-relative path under the configured data root, every symbolic component, regular-file type, size and SHA-256. The streamer reopens with no-follow semantics and rechecks device/inode/size/mtime before and after bounded reads, closing the validation/open race.

One `bytes` Range is supported (`start-end`, `start-`, or `-suffix`). A valid partial request returns 206 with `Content-Range`; malformed, multiple or unsatisfiable ranges return 416 with `Content-Range: bytes */SIZE`. Both full and partial responses advertise `Accept-Ranges: bytes`, exact `Content-Length`, ETag and `nosniff`.
