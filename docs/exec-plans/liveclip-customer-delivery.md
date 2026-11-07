# LiveClip customer delivery of dual-profile results — Living ExecPlan

Prepared 2026-11-07 (Stage 19). This plan follows `.agent/PLANS.md`. It
extends the accepted dual-profile benchmark flow
(`docs/exec-plans/liveclip-dual-profile-benchmark-v1.md`, strict acceptance
2/2 on frozen `f525338ed9427b0fcac9925bac6075d60af13e69`) and the dual-profile
offline-review package (`docs/exec-plans/liveclip-dual-profile-review-delivery.md`)
without changing any semantic selection result, prompt, routing policy,
algorithm version, evaluator, threshold or benchmark file.

## Purpose / Big Picture

An operator imports one finished dual-profile CLI run (validated final
result, run manifest, render manifest, rendered MP4/SRT, quality reports) into
the review console as a project. Internal reviewers see the clips in two
groups, 短片 (short highlight) and 小课 (mini lesson), approve or reject each
`manual_review` clip, may override the customer-facing title, hook and
summary at approval, and select clips for delivery. The operator then
publishes an immutable, versioned customer delivery (v001, v002, …) and gives
the end customer (a teacher or streamer) either:

- an offline package: a ZIP with a self-contained `index.html`, clean MP4s and
  separate SRTs; or
- an expiring, revocable, read-only share link served on the local network
  (explicit opt-in) by a separate small web process.

The customer can only watch, read the title/hook/summary and download. The
customer never sees scores, flags, routing status, review reasons, prompt
hashes or local paths.

## User decisions (2026-11-07, recorded verbatim in substance)

1. Audience is the END CUSTOMER (teacher/streamer). Read-only: watch, read
   title/hook/summary, download. Never sees scores, flags, routing status,
   review reasons, prompt hashes or paths.
2. Channels: BOTH an offline package (ZIP, self-contained `index.html`) AND
   an expiring read-only share link.
3. Pipeline integration: IMPORT existing dual-profile CLI results first.
   Running dual-profile from the console is out of scope.
4. Freeze rule amended: the benchmark freeze now covers only the
   dual-profile benchmark closure (section "Freeze closure" below). Changes
   outside it do not reset the 2/2 count and need no cold re-run, provided
   the reviewer's freeze evidence is clean at every checkpoint.
5. Customer text overrides are ALLOWED: at approval a reviewer may override
   title/hook/summary. Model originals stay immutable; overrides are stored
   as decision fields with actor and time; the customer sees the effective
   (overridden) text.
6. Clean MP4 plus separate SRT (no burned captions) for v1.
7. Share link: LAN only (explicit opt-in), no internet exposure or tunnels,
   no TLS; document "do not use on public Wi-Fi"; the offline package serves
   customers off the LAN.

## Context and Orientation

- Dual-profile evaluation (`src/liveclip/services/dual_profile_evaluation.py`,
  `src/liveclip/pipeline/dual_profile.py`) is a standalone CLI flow
  (`python -m liveclip dual-profile-eval`, `dual-profile-render`,
  `dual-profile-review-package` in `src/liveclip/cli/app.py`). It writes a
  run directory: `final-validated.json` (semantic authority; routing policy
  `quality-gate-risk-routing-v9`, algorithm `dual-profile-direct-v1`;
  `source_hash` is the sha256 of the transcript SRT), `run-manifest.json`
  (provider, model, `prompt_hashes`, call counts), and
  `renders/render-manifest.json` plus per-clip MP4, SRT, quality report and
  contact sheet.
- The internal pending-review package is built by
  `export_dual_profile_review_package` in
  `src/liveclip/services/dual_profile_delivery.py`, which joins and verifies
  final/run/render/transcript evidence (run manifest vs final, algorithm and
  Profiles, transcript hash, render candidate in selected ∪ manual_review,
  interval/status binding, path confinement, file hashes, SRT equals
  transcript-derived captions, quality report `automatic_status`/`full_decode`
  passed) and hands a `DualProfileReviewPackageInput` to
  `src/liveclip/delivery/dual_profile_review.py`.
- The existing formal Delivery (`src/liveclip/db/delivery_snapshot.py`
  `load_eligible_delivery_set`, `src/liveclip/delivery/package.py` gallery
  and manifest) is bound to single-profile `candidate_clips`/`render_jobs`
  lineage and its manifest and gallery expose `risk_flags` and
  `review_status`. Dual-profile output has no DB lineage, and
  `docs/exec-plans/liveclip-dual-profile-review-delivery.md` forbids
  inventing it. Therefore Stage 19 adds new tables and reuses projects,
  project members, assets, audit events and the `package.py` file/ZIP
  helpers (`safe_filename_component`, `normalize_srt`, `copy_immutable_member`,
  `delivery_checksums_text`, `create_verified_zip`, lock/temp/no-replace
  publication). It never fakes `candidate_clips` or `render_jobs` rows.
- Authorization lives in `src/liveclip/application/authorization.py`
  (`review_clip`, `deliver` permissions by project role). Assets are served
  by ID through `/api/v1/media/{id}` (`src/liveclip/api/app.py`,
  `src/liveclip/api/media.py`); public asset kinds are enumerated by
  `_PUBLIC_ASSET_KINDS` in `src/liveclip/application/media_assets.py`.
- Database: SQLite via SQLAlchemy models in `src/liveclip/db/models.py`,
  repository functions in `src/liveclip/db/`, Alembic migrations in
  `migrations/versions/` (head before Stage 19: `c84f5d1a702e`).

## Freeze closure (user decision 4, 2026-11-07)

The benchmark freeze, previously the whole code tree
(`src tests scripts config tools apps migrations pyproject.toml uv.lock
alembic.ini Makefile .gitignore` plus the two benchmark files, see
`STATUS.md` "Acceptance policy from Stage 17"), now covers only the
dual-profile benchmark closure below. The closure is the transitive in-repo
Python import closure of `src/liveclip/services/dual_profile_evaluation.py`
and `src/liveclip/pipeline/dual_profile.py` (computed with an AST walk over
every `import`/`from … import`, including function-local imports, plus every
parent package `__init__.py`), the package resources those modules load
(`importlib.resources` prompt Markdown), the CLI entry of
`dual-profile-eval`, the evaluator and its imports, the two benchmark files,
and the dependency lock:

```
src/liveclip/__init__.py
src/liveclip/__main__.py
src/liveclip/limits.py
src/liveclip/cli/__init__.py
src/liveclip/cli/app.py
src/liveclip/clipping_skills
src/liveclip/config
src/liveclip/domain/__init__.py
src/liveclip/domain/candidate.py
src/liveclip/domain/clip_profile.py
src/liveclip/domain/edit_plan.py
src/liveclip/domain/review.py
src/liveclip/domain/semantic_validation.py
src/liveclip/domain/state_transitions.py
src/liveclip/domain/time.py
src/liveclip/domain/transcript.py
src/liveclip/media/__init__.py
src/liveclip/media/ingest.py
src/liveclip/media/models.py
src/liveclip/media/process.py
src/liveclip/media/secure_files.py
src/liveclip/observability
src/liveclip/pipeline/__init__.py
src/liveclip/pipeline/dual_profile.py
src/liveclip/pipeline/semantic_global.py
src/liveclip/pipeline/semantic_lineage.py
src/liveclip/pipeline/semantic_profiles.py
src/liveclip/pipeline/semantic_transport.py
src/liveclip/pipeline/srt.py
src/liveclip/prompts
src/liveclip/providers
src/liveclip/renderer
src/liveclip/services/__init__.py
src/liveclip/services/captions.py
src/liveclip/services/dual_profile_evaluation.py
src/liveclip/services/structured_editorial_provider.py
scripts/__init__.py
scripts/evaluate_benchmark.py
scripts/benchmark_gates.py
liveclip_dual_profile_benchmark_v1.json
liveclip_dual_profile_benchmark_v1.md
pyproject.toml
uv.lock
```

Additions to the Controller's draft list (draft: `clipping_skills/dual_profile_v1`,
`pipeline/{dual_profile,semantic_global,srt}.py`,
`services/{dual_profile_evaluation,structured_editorial_provider,captions}.py`,
`providers/`, `renderer/`, `config/settings.py`,
`scripts/{evaluate_benchmark,benchmark_gates}.py`, the two benchmark files),
each found by the AST closure walk at `a79deaf`:

- Imported modules missing from the draft: `domain/{candidate,clip_profile,edit_plan,review,semantic_validation,state_transitions,time,transcript}.py`,
  `media/{ingest,models,process,secure_files}.py`,
  `pipeline/{semantic_lineage,semantic_profiles,semantic_transport}.py`,
  `limits.py`, `config/fonts.py`, `observability/__init__.py`,
  `prompts/__init__.py`.
- Package `__init__.py` files executed on import: `src/liveclip/__init__.py`,
  `clipping_skills/__init__.py` (which imports `semantic_continuous_v1`,
  `semantic_window_v1`, `semantic_window_v2`), `config/__init__.py`
  (provides `get_settings`), `domain/__init__.py`, `media/__init__.py`,
  `pipeline/__init__.py`, `services/__init__.py`, `scripts/__init__.py`
  (the evaluator imports `scripts.benchmark_gates`).
- `dual_profile_v1` imports `semantic_global_v1.SemanticGlobalPromptBundle`;
  the whole `clipping_skills/`, `prompts/`, `config/` and `observability/`
  directories are frozen (directories, so their Markdown resources are
  covered too; this is a conservative superset).
- CLI entry: `src/liveclip/__main__.py`, `cli/__init__.py`, `cli/app.py`. The
  `dual-profile-eval` command is not pure argument wiring: it owns the
  defaults `--short-top-n 15` and `--mini-lesson-top-n 15` that the counted
  runs relied on (their argv passes only `--discovery-concurrency 3`), builds
  the provider factory from `get_settings()`, and maps errors. Therefore
  `cli/app.py` is in the closure and **Stage 19 must not edit it**. A future
  CLI command for import/export needs either a separate entry module or a
  new user decision. The rest of the CLI's import graph (application, db,
  delivery, …) is imported for side-effect-free definitions only and is not
  on the `dual-profile-eval` call path; it is not frozen.
- `pyproject.toml` and `uv.lock`: not Python imports, but they pin the
  third-party runtime (pydantic, etc.) of the closure and the evaluator.
  Stage 19 plans no dependency change; any later need is a new decision.

Not in the closure (may change in Stage 19, behaviour-preserving where noted):
`src/liveclip/services/dual_profile_delivery.py` (the evaluation does not
import it; its 19a refactor must be byte-preserving, evidence item 5),
`src/liveclip/delivery/`, `src/liveclip/db/`, `src/liveclip/application/`,
`src/liveclip/api/`, `apps/`, `migrations/`, `tests/`, `Makefile`,
`alembic.ini`, `.gitignore`.

### Reviewer freeze evidence (required at every Stage 19 checkpoint)

1. `git diff --exit-code f525338ed9427b0fcac9925bac6075d60af13e69 -- <closure paths above>`
   exits 0 (and `git status --porcelain -- <closure paths>` is empty).
2. `tests/unit/test_dual_profile_freeze_pins.py` passes and an independent
   recompute of the 17 prompt identities (via `load_dual_profile_prompt` /
   `load_dual_profile_variant_link_prompt`) matches the Stage 18b "after"
   column in `STATUS.md`.
3. The Settings fingerprint recompute equals
   `c81f0ece91debb4f1637ba5eecc3af64a91da256f586917408de458317d170d1` (same
   script and inputs as the cold-35/cold-36
   `evidence/step1-settings-fingerprint.txt`).
4. Re-running `scripts/evaluate_benchmark.py` on the stored cold-35 and
   cold-36 inputs yields byte-identical `benchmark-result.json`.
5. When `src/liveclip/services/dual_profile_delivery.py` changes: the cold-36
   review-package `manifest.json` regenerated before/after is identical
   (see 19a for the exact procedure and the one normalised field).

## Scope and explicit non-goals

In scope (Stage 19a–19e): import of finished dual-profile run directories;
internal review UI with approve/reject, customer text overrides and
selection; immutable versioned customer deliveries; offline customer package;
LAN-only expiring share links in a separate process; ADR and Product Spec
amendment.

Non-goals (deferred, not deleted): running dual-profile from the console;
rendering additional candidates from the console ("render more"; only
rendered candidates are deliverable — cold-36 rendered 12 of 64 eligible);
burned captions; internet exposure, tunnels or TLS; any change to the
benchmark closure, prompts, routing, algorithm, evaluator, thresholds or
benchmark files.

## Design

### A. Import (19a)

- Inputs: the run directory (`final-validated.json`, `run-manifest.json`,
  `renders/render-manifest.json` plus per-clip MP4, SRT, quality report and
  contact sheet) and the transcript SRT.
- Pure refactor: extract the join/verification of
  `export_dual_profile_review_package` into a public
  `load_verified_dual_profile_render_set()` in
  `src/liveclip/services/dual_profile_delivery.py`; export calls it.
  `tests/unit/test_dual_profile_delivery.py` stays unchanged and passing.
- Import adds: `routing_policy_version ==
  DUAL_PROFILE_ROUTING_POLICY_VERSION` (v9); records the run-manifest
  `prompt_hashes` internally.
- Paths: render-manifest paths may be repo-relative (cold-36 video/subtitle
  paths are `data/evaluations/...`; the existing `_confined_file` rejects
  non-absolute paths). Import resolves relative paths against an allowed
  import root (default `<repo>/data/evaluations`), rejects anything that
  resolves outside the root or outside the render directory, and rejects
  symlink escapes.
- Storage: copy media into `data/projects/<pid>/imports/<iid>/{short_highlight,mini_lesson}/`
  via `copy_immutable_member`; `AssetRow`s with new kinds
  `dual_profile_video` / `dual_profile_subtitle` (added to
  `_PUBLIC_ASSET_KINDS`); internal playback via `/api/v1/media/{id}`.
- Import creates the Project with lifecycle `editorial_review` and
  `source_request_path="dual-profile-import:<fp20>"` (no absolute path
  stored). Re-import of the same snapshot fingerprint into the same project
  is idempotent. An audit event records the import.
- One migration (down_revision `c84f5d1a702e`):
  - `dual_profile_imports`: project, source/final/run/render/transcript
    sha256, algorithm, routing, `snapshot_fingerprint` (unique per project),
    `prompt_hashes_json`, `imported_by`, `created_at`.
  - `dual_profile_import_clips` (immutable): profile, `routed_status` CHECK
    in (selected, manual_review), ms bounds, title/hook/summary (model
    originals), internal score/review_reason/flags/risks, asset ids.
  - `dual_profile_clip_decisions` (append-only): action
    approve/reject/select/deselect, optional title/hook/summary overrides
    (approve only), actor, time.
  - `customer_deliveries` + `customer_delivery_clips` (immutable snapshot,
    versioned v001, v002, …) and `customer_share_links` (used in 19d).
- Eligibility (pure domain function): a clip is deliverable iff it is
  `selected`, or it is `manual_review` and its latest approve/reject decision
  is approve. `blocked` and rejected candidates are never imported. cold-36
  has 0 selected, so every clip needs approval. Effective customer text =
  the latest approve decision's override per field, else the model original.
- Customer-safe allowlist: profile (短片/小课), effective title, hook,
  summary, duration, MP4, SRT. Enforced by `CustomerClipView`
  (pydantic, `extra="forbid"`).

### B. Internal review UX (19b)

- "导入双轨结果" next to project creation: server-local run-dir path and
  transcript path.
- `ProjectWorkspace`: if `GET /projects/{id}/dual-profile-import` returns an
  import, render `DualProfileReviewSection` instead of RunPanel/clip list,
  grouped 短片 (n) / 小课 (n). Sibling `ImportedClipCard` (do not generalise
  `ClipCard`); reuse clip-card/highlight-list CSS and `StatusBadge`.
  Internal view shows 自动入选 / 需人工审核, score, risks, reason.
- 批准 / 不通过 need `review_clip`; the approve form allows title/hook/summary
  overrides. 选入交付 needs `deliver` and is disabled until eligible.
- `CustomerDeliveryPanel` modelled on `DeliveryPanel`: create version
  (customer-facing title), list versions and ZIPs, create/revoke share links.

### C. Offline package (19c)

- `src/liveclip/delivery/customer_package.py` reusing the `package.py`
  helpers; Worker Task like current deliveries.
- Layout: `index.html`, `manifest.json` (schema
  `liveclip.customer-delivery.v1`, allowlisted keys), `checksums.sha256`,
  `clips/short/NN-<title>.mp4|.srt`, `clips/lesson/...`.
- `customer_index_html(manifest, href=…)`: sections 短片 then 小课, ordered by
  profile, start_ms, id. Card: `<video controls preload=metadata>`, title,
  hook, summary, 时长 mm:ss, MP4/SRT download links. CSP `default-src 'none';
  style-src 'unsafe-inline'; media-src 'self' file:`; no script, no CDN, no
  `<track>`.

### D. Share link (19d)

- Token `secrets.token_urlsafe(32)`; store sha256 only (unique); shown once;
  expiry required (default 7 days, max 30); revocable; scoped to one
  immutable customer delivery.
- Separate process: `create_share_app()` in `src/liveclip/api/share.py`,
  `make share` on its own port (e.g. 8766). Only `/s/{token}`,
  `/s/{token}/clips/{ordinal:int}/video|subtitle`, `/s/{token}/download`.
  No cookies/Authorization read, no CORS; internal routes absent; the main
  app's protected router and `security.py` unchanged.
- LAN bind needs explicit `LIVECLIP_SHARE_ALLOW_LAN=true` plus a base URL in
  a new `ShareSettings` class (NOT `config/settings.py`, which is in the
  freeze closure and the benchmark Settings fingerprint).
- Unknown/expired/revoked → identical 404. Video via `stream_asset_response`
  (Range/206/416). Headers: `Cache-Control: no-store`,
  `Referrer-Policy: no-referrer`, `X-Robots-Tag: noindex`,
  `X-Frame-Options: DENY`, CSP, RFC 5987 `filename*`.
- In-process rate limit (429 + Retry-After). Audit created/revoked/page
  view/download, never the token. Uvicorn access log disabled; log
  `/s/<redacted>`.

## Milestones and progress

- [x] 2026-11-07 Stage 18 merged to `main` as `a79deaf0a62e4a506b8ea2c3221e9388d12dd286`
  (merge commit of PR #2, tree identical to `d386981`). Branch
  `claude/liveclip-stage19-customer-delivery` created from it.
- [x] 2026-11-07 Checkpoint 1 (docs only): this ExecPlan; freeze rule
  amendment recorded in `STATUS.md`,
  `docs/exec-plans/liveclip-dual-profile-benchmark-v1.md` and
  `docs/exec-plans/liveclip-agent-runtime-v2.md`; closure verified by AST
  walk (`git diff --exit-code f525338 -- <closure>` rc 0 at `a79deaf`).
- [ ] Stage 19a: freeze pin test; `load_verified_dual_profile_render_set()`
  refactor (byte-preservation evidence); eligibility domain function;
  migration, models, repository; `application/dual_profile_imports.py`;
  `CustomerClipView`; tests (eligibility truth table incl. overrides, tamper
  matrix, idempotent re-import, migration up/down).
- [ ] Stage 19b: API and internal review UI (authz matrix, project
  isolation 404, overrides; vitest; Playwright `e2e/dual-profile-review.spec.ts`
  with the mock provider).
- [ ] Stage 19c: offline customer package (golden key set; recursive
  forbidden-token scan of manifest/HTML/member names for `score`, `risk`,
  `manual_review`, `review_reason`, `prompt`, `/Users`, `data/`;
  byte-identical ZIP for the same inputs; XSS escaping; overrides shown;
  non-eligible → 409; later decisions do not change v001 (→ v002);
  Playwright `file://` with network blocked).
- [ ] Stage 19d: share links (no raw token in DB; expired/revoked 404; other
  deliveries unreachable; traversal 404/422; Range 206/416; no Set-Cookie;
  internal session cookie gains nothing; internal paths 404 on the share
  app; headers; 429; redacted logs; LAN opt-in validation; vitest URL shown
  once).
- [ ] Stage 19e: ADR, Product Spec amendment, STATUS, operator LAN phone test
  (user).

## Work breakdown and file ownership

Single writer (the coder); the main agent owns schemas, migrations, ExecPlan
and STATUS. 19a files: `tests/unit/test_dual_profile_freeze_pins.py`,
`src/liveclip/services/dual_profile_delivery.py` (refactor only),
`src/liveclip/domain/customer_delivery.py` (new), `src/liveclip/db/models.py`,
a new `src/liveclip/db/` repository module, one new migration,
`src/liveclip/application/dual_profile_imports.py` (new),
`src/liveclip/application/media_assets.py` (`_PUBLIC_ASSET_KINDS` only), new
unit/integration tests. 19b depends on 19a's schema; 19c on 19a/19b; 19d on
19c's delivery snapshot.

## Commands (from the repository root)

- Freeze evidence item 1:
  `git diff --exit-code f525338ed9427b0fcac9925bac6075d60af13e69 -- <closure paths>`
  (rc 0 expected; any output is a freeze break that needs a user decision).
- Pins: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q tests/unit/test_dual_profile_freeze_pins.py`.
- Lint: `PYTHONDONTWRITEBYTECODE=1 NODE_LTS_BIN=/opt/homebrew/opt/node@22/bin make lint`.
- Existing dual-profile guards: `tests/unit/test_dual_profile_delivery.py`,
  `tests/unit/test_dual_profile_flag_contract.py`,
  `tests/integration/test_dual_profile_evaluation.py`.

## Validation and acceptance

Each sub-stage is accepted by an independent tester and reviewer with the
five freeze-evidence items clean. Deterministic validation proves only its
gates; the customer-facing experience additionally needs a human check of a
real package and a real phone on the LAN (19e). No real model call is part
of Stage 19.

## Idempotency, retry and recovery

- Import is idempotent per (project, snapshot fingerprint); copying uses
  no-replace immutable publication, so a crashed import is re-run safely
  (partial directories are not referenced by any committed row).
- Decisions are append-only; deliveries are immutable snapshots; a new
  decision after v001 produces v002, never mutates v001.
- Rollback: each sub-stage is a separate commit series; reverting 19a removes
  the migration (downgrade drops only the new tables).

## Surprises and Discoveries

- 2026-11-07: the existing `dual-profile-review-package` CLI cannot export
  the cold-36 run as stored: its render manifest records repo-relative
  `video_path`/`subtitle_path` (contact sheet and quality report paths are
  absolute), and `_confined_file` rejects non-absolute paths ("video path is
  not an absolute system path"). This confirms the import's need for
  root-relative resolution. The refactor's before/after evidence therefore
  uses an APFS-clone copy of the cold-36 renders with an absolutised render
  manifest in the session scratchpad.
- 2026-11-07: the review package `manifest.json` carries `created_at`
  (wall clock), so two exports of identical inputs at identical code differ
  in that one field; byte identity is structurally impossible and the
  comparison normalises only `created_at` (and the derived manifest hash in
  `checksums.sha256` and in the ZIP).

## Decision Log

- 2026-11-07 (user): decisions 1–7 above.
- 2026-11-07 (coder, closure verification): `cli/app.py`, `__main__.py`,
  the package `__init__` files, the missing domain/media/pipeline modules,
  `limits.py`, `prompts/`, `observability/`, `scripts/__init__.py`,
  `pyproject.toml` and `uv.lock` are added to the closure (reasons in
  "Freeze closure"). Alternative considered: freezing only the
  `dual_profile_eval` function inside `cli/app.py`; rejected for 19a because
  `git diff --exit-code` cannot express a function-level freeze and Stage 19
  needs no CLI change.

## Risks and Mitigations

- Leaking internal fields to the customer: allowlist model with
  `extra="forbid"`, forbidden-token scans (19c/19d).
- Path traversal or symlink escape during import: resolution against an
  allowed root, `resolve(strict=True)` confinement and no-follow hashing.
- Freeze break by accident: freeze evidence at every checkpoint; the pin test
  fails on any prompt identity drift.
- LAN HTTP without TLS: explicit opt-in, documented "do not use on public
  Wi-Fi"; internet exposure out of scope.
- Only rendered candidates are deliverable (cold-36: 12 renders of 64
  eligible); "render more" is deferred.

## Recovery Notes

2026-11-07: Checkpoint 1 (docs only) is committed on
`claude/liveclip-stage19-customer-delivery` (from `origin/main` `a79deaf`).
First next task: Stage 19a, starting with
`tests/unit/test_dual_profile_freeze_pins.py`, then the
`load_verified_dual_profile_render_set()` refactor with the before/after
review-package comparison. Nothing is pushed or merged; push/merge need
explicit user consent.

## Outcomes and Retrospective

(Filled when a sub-stage closes.)
