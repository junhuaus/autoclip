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
6. (Added 2026-11-07, Stage 19a reviewer P2-2.) `.venv/bin/python -m liveclip
   dual-profile-eval --help` exits 0 (the frozen CLI entry still imports and
   wires).

Clarifications (appended 2026-11-07 after the Stage 19a review; the items
above are unchanged): item 3 — the Settings fingerprint is computed with exactly two environment overrides, `LIVECLIP_STRUCTURED_PROVIDER=claude-cli` and `LIVECLIP_CLAUDE_EXECUTABLE=<repo>/.cache/claude-cli/2.1.308/claude` (key names and path only; no `.env` value is read or recorded), the same as the counted cold-35/cold-36 runs. Item 1 — of the CLI only the
three files `src/liveclip/__main__.py`, `src/liveclip/cli/__init__.py` and
`src/liveclip/cli/app.py` are frozen; the rest of `cli/app.py`'s import graph
(application, db, delivery, api, …) is not frozen.

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
- [x] 2026-11-07 Stage 19a implemented (pending independent tester and
  reviewer): code commits `cb13bb69098f26cafd9f7ec752ccd2d4ebef64b6` (freeze pin test;
  `load_verified_dual_profile_render_set()` refactor) and
  `096a7ca1884ce1ff6d5b1b8daa3010e37a61881b` (eligibility domain, migration `d5e8a1c3f907`,
  models, repository, import service, `CustomerClipView`, tests), plus test-only
  follow-ups `437f5f015e2f0f43b51c4c42f9905834973733e8` (concurrent duplicate import) and
  `49f8f661e5542eac593052a1d4d662c43b20f995` (schema inventory test). Evidence in
  "Stage 19a results" below.
- [x] 2026-11-07 Stage 19a ACCEPTED at `ba1e8b0` (tester: lint rc 0,
  backend 3353, vitest 80, e2e 4; reviewer ACCEPT-WITH-NITS, five freeze
  evidence items reproduced, five deviations accepted). Reviewer nits fixed
  in `29dd574cdaa8587173fb555daa2d26fe81b7819c` (see Decision Log).
- [x] 2026-11-07 Stage 19b implemented (pending independent tester and
  reviewer): code `cf11aefd513f9b26a87a8e7ceae7ecd9fec8fa56`. Evidence in "Stage 19b results".
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

## Stage 19a results (2026-11-07)

Files: `tests/unit/test_dual_profile_freeze_pins.py` (new),
`src/liveclip/services/dual_profile_delivery.py` (refactor),
`src/liveclip/domain/customer_delivery.py` (new),
`src/liveclip/db/models.py` (six new row classes),
`migrations/versions/d5e8a1c3f907_add_dual_profile_customer_delivery.py`
(new), `src/liveclip/db/dual_profile_repository.py` (new),
`src/liveclip/application/dual_profile_imports.py` (new),
`src/liveclip/application/media_assets.py` (`_PUBLIC_ASSET_KINDS` gains
`dual_profile_video`, `dual_profile_subtitle`),
`tests/unit/test_customer_delivery_domain.py`,
`tests/integration/test_dual_profile_imports.py`,
`tests/integration/test_dual_profile_migration.py` (new), and the
`HEAD` constant in `tests/integration/test_completion_migrations.py`
(now `d5e8a1c3f907`; those tests upgrade to `HEAD` and then run
`alembic check`, which requires the true head) and the expected table
set in `tests/unit/test_db_models.py`.
`tests/unit/test_dual_profile_delivery.py` is unchanged
(`git diff a79deaf -- tests/unit/test_dual_profile_delivery.py` empty).

- **Pins:** the 17 prompt identities computed by the real loaders equal
  the Stage 18b "after" column (21 tests: table size, aggregate, one per
  identity, routing `quality-gate-risk-routing-v9`, algorithm
  `dual-profile-direct-v1`). The pin table also equals the operator file
  `data/evaluations/dual-profile-strict-eval-20261106-claude-cold-36/evidence/stage18b-expected.txt`
  and the cold-36 `tree_ph.py` recompute reports 17/17, 0 mismatches.
- **Refactor byte preservation (freeze evidence item 5):** the stored
  cold-36 render manifest cannot be exported by the `a79deaf` CLI (see
  Surprises), so an APFS clone of the cold-36 `renders/` with an
  absolutised render manifest lives in the session scratchpad
  (`stage19a/renders-abs/`). (1) CLI `dual-profile-review-package` before
  (at `a79deaf`) and after the refactor: 136 files and ZIP members
  identical after normalising only `manifest.json` `created_at` (and the
  manifest hash in `checksums.sha256`); a second before-run shows the
  same single-field difference, so `created_at` is the only
  nondeterminism. (2) With the wall clock fixed (harness
  `stage19a/harness/fixed_clock_export.py`, `a79deaf` module source vs
  working-tree module), the whole 69-file package is byte-identical:
  `manifest.json` sha256
  `a7a5a6f13f3cb651b494a0ed9784c3048092161eee71c859215544c20b0e2590`, ZIP sha256
  `4b7b35c64eda612f8dfde9e966abbba1d75d54c7eba7a5155c0198fc07847149` before, after and again at
  `096a7ca`.
- **Import:** verification reuses the extracted loader (run manifest vs
  final, algorithm/Profiles, transcript hash, selected ∪ manual_review
  membership, interval/status binding, confinement, file hashes, SRT vs
  transcript captions, quality report passed) and adds routing v9. Run
  dir and transcript must resolve inside allowed roots; evidence files must
  not be reached through a symbolic link; relative render paths are joined
  to the repository base and then confined to the render directory. Media
  is copied with `copy_immutable_member` into
  `data/projects/<pid>/imports/<iid>/<profile>/<candidate_id>.{mp4,srt}`;
  one transaction inserts the project (`editorial_review`,
  `dual-profile-import:<fp20>`, owner = importer), owner membership,
  import, committed Assets, immutable clips and an audit event (no paths).
  Failure before commit removes the new project directory; a lost race on
  the unique (importer, snapshot) constraint returns the winner.
- **Real-data smoke (read-only):** importing the stored cold-36 run
  (`data/evaluations/dual-profile-benchmark-20261106-claude-cold-36`,
  transcript `tests/fixtures/8-30-full-transcript.srt`) into a scratch data
  directory yields 12 clips (7 short, 5 mini), all `manual_review`, 0
  deliverable before approval, snapshot prefix `744f55f73e45152c4f54`; a
  re-import returns the same project (`created` false). The cold-36
  `final-validated.json` and `run-manifest.json` still match
  `evidence/inputs-after-render.sha256`.
- **Freeze evidence at `096a7ca`:** (1) `git diff --exit-code f525338 --
  <closure>` rc 0, porcelain empty; (2) pins pass, independent recompute
  17/17; (3) Settings fingerprint recompute (cold-36 `settings_fp.py`, same
  env as the counted runs)
  `c81f0ece91debb4f1637ba5eecc3af64a91da256f586917408de458317d170d1`; (4) `scripts/evaluate_benchmark.py` re-run
  on stored cold-35 and cold-36 inputs: `benchmark-result.json` and
  `benchmark-report.md` byte-identical (cold-35 result sha256
  `a9f58fb8aade3fbadc9601d79745165b7d5c53ef4b80207d46b98abb9dcf86dd`, cold-36
  `d7067d2f57867c56e8e86149dce176cb824a88ae07b1c0029bfd476c915c7ad2`); (5) above.
- **Validation:** `make lint` rc 0; targeted pytest (pins, domain,
  imports, migration, delivery, flag contract, dual-profile evaluation
  integration, migration suites) 364 passed; full `make test` at `49f8f661e5542eac593052a1d4d662c43b20f995` rc 0: backend pytest 3353 passed (15 deprecation warnings), vitest 14 files / 80 tests passed, e2e 4 passed. (A first full run at `437f5f0` had 2 failures: `tests/unit/test_db_models.py` schema inventory, fixed in `49f8f66` by listing the six new tables, and `tests/unit/test_b2_synthetic_worker.py::test_canonical_independent_worker_commits_two_real_pauses` (`needs_action` instead of `succeeded`), which passed 3/3 in isolation and in the second full run; the first run overlapped an unrelated pytest process on the host, so it is classified transient and timing-related, recorded, not hidden).
  Deterministic validation only; no real model call, no render.

Reviewer notes on 19a (recorded 2026-11-07): commit `cb13bb6` is not a
*pure* refactor — besides extracting `load_verified_dual_profile_render_set()`
it adds the opt-in `relative_render_path_base` parameter (default `None`,
unused by `export_dual_profile_review_package`, so export behaviour is
byte-identical). Reviewer P2-6 is a pre-existing condition outside Stage 19's
change and is recorded as a known residual, not fixed here.

## Stage 19b results (2026-11-07)

Backend: `src/liveclip/customer_delivery_settings.py` (new,
`DualProfileImportSettings`, env-only), `src/liveclip/application/dual_profile_review.py`
(new: review views, `DualProfileReviewService`, `decision_permission`),
`src/liveclip/application/dual_profile_imports.py` (review records,
`DualProfileDecisionConflict`), `src/liveclip/db/dual_profile_repository.py`
(`load_review`, transactional `require_deliverable`),
`src/liveclip/bootstrap.py` (wiring), `src/liveclip/api/app.py` and
`src/liveclip/api/schemas.py` (three routes, three error handlers),
`src/liveclip/application/pipeline.py` (`ProjectSnapshot.source_kind`,
`generation` ≥ 0), `src/liveclip/db/pipeline_repository.py` (run-less
imported snapshot), `src/liveclip/db/project_discovery_repository.py`
(search includes imported projects). Web: `apps/web/src/DualProfileReview.tsx`
(new: `DualProfileReviewSection`, `ImportedClipCard`, approval form,
`DualProfileImportDialog`), `App.tsx` ("导入双轨结果"), `ProjectWorkspace.tsx`
(imported branch; no run/clip queries), `api.ts`, `types.ts`, `styles.css`.
Tests: `tests/integration/test_dual_profile_review_api.py`,
`tests/unit/test_customer_delivery_settings.py`, `tests/dual_profile_fixtures.py`
(shared synthetic run builder), `apps/web/tests/dual-profile-review.test.tsx`,
`apps/web/e2e/dual-profile-review.spec.ts`.

- API: `POST /api/v1/dual-profile-imports` (201 new, 200 idempotent
  replay; any authenticated workspace user, who becomes owner, as for
  `POST /jobs`); `GET /api/v1/projects/{id}/dual-profile-import` (`read`);
  `POST /api/v1/projects/{id}/dual-profile-import/clips/{clip}/decisions`
  (approve/reject need `review_clip`; select/deselect need `deliver`).
  Matrix tested: viewer read-only (403 on all four actions), reviewer
  approve/reject only, editor select/deselect only, owner all, non-member
  404, cross-project clip 404. Select on a non-deliverable clip is 409
  (checked inside the write transaction). Invalid overrides and overrides
  on non-approve actions are 422. Import errors are 422
  `DUAL_PROFILE_IMPORT_INVALID` with messages that contain no path (tested
  against the tmp base, `/etc`, `/definitely`, `../outside`, relative input).
- Imported projects: `GET /projects`, `/projects/search` and
  `/projects/{id}` work; the snapshot has `source_kind`
  `dual_profile_import`, `current_run_id` "" and `generation` 0, status
  `pending_review`. **Pipeline actions are refused** on imported projects
  (corrected after the 19b review, P1): `allowed_actions` is limited to
  `read`, `manage_members`, `manage_project`, `review_clip`, `comment`,
  `deliver`; `_require_project_access` returns 409 for every non-read action
  unless the endpoint opts in (members, ownership transfer, management,
  lifecycle, dual-profile decisions); `create_run` also refuses inside its
  write transaction. Tested with valid bodies for runs, batch review, legacy
  deliveries, edit packages and releases.
- UI: the imported workspace never requests `/runs/*` or `/clips` (vitest
  and e2e assert it); 批准 opens a form prefilled with the effective text and
  sends only fields that differ from the model original, so re-approval
  keeps earlier overrides; 选入交付 is disabled with a reason until the clip
  is deliverable.
- Freeze evidence at `cf11aef`: (1) closure diff to `f525338` rc 0, porcelain
  empty; (2) pins pass (in the full run) and the cold-36 `tree_ph.py`
  recompute is 17/17; (3) Settings fingerprint
  `c81f0ece91debb4f1637ba5eecc3af64a91da256f586917408de458317d170d1` with the two documented env overrides; (4)
  evaluator re-run on stored cold-35/cold-36 byte-identical; (5)
  `services/dual_profile_delivery.py` unchanged since `cb13bb6`; (6)
  `.venv/bin/python -m liveclip dual-profile-eval --help` rc 0.
- Validation: `make lint` rc 0; targeted API/import/migration/settings pytest and vitest green; full `make test` at `cf11aefd513f9b26a87a8e7ceae7ecd9fec8fa56` rc 0: backend pytest 3424 passed (15 deprecation warnings), vitest 15 files / 87 tests passed, e2e 5 passed (mock: `review-delivery.spec.ts` and the new `dual-profile-review.spec.ts`; real-browser: 3 scenario runs). Unrelated pytest processes from other host repositories were running during the suite; they were not touched. Deterministic only; no model call.

## Stage 19b review fix (2026-11-07)

Reviewer REJECT on one P1 at `68e6edb`: `POST /api/v1/projects/{imported}/runs`
with an Idempotency-Key returned 202, queued a run, flipped the project to
`source_kind` "pipeline" and lost the dual-profile branch, because the
imported snapshot exposed every role action and `create_run` had no import
guard. Fixed in `248082c7fbb4a9b2a5a3dbc903acb4263eb13179`:

- `create_run` raises `PipelineConflict` (409) when a `dual_profile_imports`
  row exists, inside the same `BEGIN IMMEDIATE` transaction.
- `imported_project_actions()` (`src/liveclip/application/authorization.py`)
  restricts the snapshot; `_require_project_access(..., allow_imported=False)`
  enforces it server-side. Audit of project-scoped mutating endpoints: runs,
  reviews/batch, deliveries, edit-packages and releases go through it and
  now 409; members, ownership transfer, management, lifecycle and
  dual-profile decisions opt in; clip-, run-, render-, delivery-, package-
  and release-item-scoped endpoints address entities an imported project
  never has (404), and completion goals either create a new project from a
  source or address a run.
- `ProjectSnapshot` validator ties `source_kind` "pipeline" to a non-empty
  `current_run_id` and generation ≥ 1, and "dual_profile_import" to "" and 0.
- P2: the import never reads from the managed data directory — the same
  rule as `POST /jobs`, which calls `resolve_allowed_source(...,
  forbidden_roots=(configured_data_dir,))` with `configured_data_dir` =
  `settings.resolved_data_dir()` (`data/projects`). `data/evaluations` stays
  allowed; anything under `data/projects` is refused even when a configured
  root contains it. Containment is checked lexically before existence (and
  again after strict resolution), so paths outside the roots, existing or
  not, get one message. Root lists strip each item; empty, whitespace-only
  or separator-only values fall back to the defaults. Customer links must
  use the folder of their profile (`clips/short` ↔ short, `clips/lesson` ↔
  mini lesson). Web wording is consistently 不通过. The e2e records
  forbidden `/runs` and `/clips` requests and asserts there were none.
- New tests: refused pipeline actions (5, valid bodies) with the project
  still `dual_profile_import` and no pipeline/task rows; allowed actions per
  role; repository-level `create_run` refusal; archived imported project
  blocks decisions (403); real `StorageAdministrationService.purge_project`
  of an imported project; data-dir exclusion; no existence oracle; settings
  parsing; `ProjectSnapshot` validator.
- Known limitation: the import hashes, verifies and copies media
  synchronously inside the HTTP request (cold-36: about 1 GB). A future
  stage should move it to a worker Task with progress, like deliveries.
- Residual (Stage 19a reviewer P2-6; pre-existing, not changed by Stage 19): `load_verified_dual_profile_render_set()` in `src/liveclip/services/dual_profile_delivery.py` parses `final-validated.json`, `run-manifest.json` and `renders/render-manifest.json` from one no-follow read but computes their recorded SHA-256 (`_hash_file`) from a second, separate read; likewise the transcript is hashed and then re-read by `load_srt_transcript`. A process able to write inside the allowed import root between the two reads could make the stored hashes and snapshot fingerprint describe bytes other than the parsed content. Rendered media are not affected: `copy_immutable_member` re-hashes exactly the bytes it copies against the manifest hash. Exploiting it requires local write access to the operator-controlled import root; accepted for Stage 19. A future fix hashes and parses the same in-memory bytes.
- Validation: `make lint` rc 0; full `make test` at `248082c7fbb4a9b2a5a3dbc903acb4263eb13179` rc 0: backend pytest 3447 passed (15 deprecation warnings), vitest 15 files / 87 tests passed, e2e 5 passed (2 mock specs, 3 real-browser scenario runs).

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

- 2026-11-07 (coder, 19a; for Controller confirmation): **stricter
  eligibility** — an explicit later reject also removes an automatically
  `selected` clip (the design's literal rule makes `selected` always
  deliverable). It only narrows eligibility; the customer can never
  receive a clip a reviewer rejected. cold-36 has 0 `selected`, so the
  real run is unaffected.
- 2026-11-07 (coder, 19a): one import per project (`UNIQUE(project_id)`)
  and idempotency by `UNIQUE(imported_by, snapshot_fingerprint)` instead of
  "fingerprint unique per project", because each import creates its own
  project; another user importing the same run gets a separate project.
- 2026-11-07 (coder, 19a): relative render paths are resolved against the
  repository base (the CLI working directory), not the import root,
  because cold-36 records `data/evaluations/...`; the result must still lie
  in the render directory, which must lie inside the allowed import root.
- 2026-11-07 (coder, 19a): the transcript has its own allowed roots
  (`allowed_transcript_roots`), because the cold-36 transcript is
  `tests/fixtures/8-30-full-transcript.srt`, outside `data/evaluations`.
  19b chooses the wired default.
- 2026-11-07 (coder, 19a): decisions carry a per-clip `sequence`
  (`UNIQUE(import_clip_id, sequence)`) so "latest" is deterministic; each
  approval states the complete customer text (a field it does not override
  falls back to the model original). SQLite BEFORE UPDATE triggers make
  imports, imported clips, decisions and customer-delivery clips
  immutable; their FKs never use SET NULL. Customer deliveries and share
  links are created in the same migration (19c/19d may add a later
  migration if they need changes). Imported SRTs are copied byte-for-byte.

- 2026-11-07 (Controller, 19a reviewer nits): P2-4 — a `select` counts
  only when it was made after the clip's latest review decision (a later
  reject, or reject then approve, voids earlier selects); the 19b service
  refuses `select` on a clip that is not currently deliverable (HTTP 409).
  P2-3 — customer links accept only the emitted shapes
  `clips/short|lesson/NN-<safe title>.mp4|.srt` and
  `/s/<token>/clips/<ordinal>/video|subtitle`; every URL scheme,
  protocol-relative link, backslash, dot segment, query and fragment is
  rejected. P2-5 — migration `e4b2c7d9a1f3` adds BEFORE DELETE guards on
  imports, imported clips, decisions, customer deliveries and
  customer-delivery clips that abort while the owning project exists; the
  project-purge cascade still removes them.

- 2026-11-07 (coder, 19b): imported projects keep `ProjectSnapshot.current_run_id`
  a string (`""`) instead of becoming optional, because the frozen
  `src/liveclip/cli/app.py` passes it to `get_run(str)` and an optional type
  would fail mypy in a file Stage 19 may not edit; `source_kind` tells
  clients there is no run, and `generation` is 0 (no invented ids).
- 2026-11-07 (coder, 19b): transcript roots default to
  `<repo>/data/evaluations` and `<repo>/input`; repository code/test
  directories are never allowed by default. The stored cold-36 transcript
  (`tests/fixtures/8-30-full-transcript.srt`) therefore needs
  `LIVECLIP_DUAL_PROFILE_TRANSCRIPT_ROOTS` or a copy under `input/`.
  Settings are read from the process environment only, never `.env`.
- 2026-11-07 (coder, 19b): the mock e2e follows the existing Playwright
  `page.context().route` pattern (MSW is used only by vitest in this repo).
  `deselect` is allowed regardless of eligibility (it can only narrow a
  delivery). The customer-delivery panel is a placeholder until 19c.

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

2026-11-07 (Stage 19b, after review): P1 fixed at `248082c`; pending
re-review. (Earlier:) implemented at `cf11aef` plus this docs commit;
pending independent tester and reviewer (re-check the six freeze-evidence
items). First next task after acceptance: Stage 19c (offline customer
package from `CustomerClipView`, immutable `customer_deliveries` v001…).

(Historical) 2026-11-07 (Stage 19a): implemented at `096a7ca` (code) plus a test
follow-up and this docs commit; pending independent tester and reviewer,
who must re-check the five freeze-evidence items. First next task after
acceptance: Stage 19b (API and internal review UI); wire
`DualProfileImportService` in `src/liveclip/bootstrap.py` (data dir,
`default_dual_profile_import_root(project_root)`, transcript roots), and
verify that project list/workspace endpoints tolerate an imported project
with no pipeline run (`current_generation` 0). Recovery: reverting the 19a
commits and downgrading to `c84f5d1a702e` drops only the six new tables;
copied media under `data/projects/<pid>/imports/` belongs to the project
and is purged with it.

(Historical) 2026-11-07: Checkpoint 1 (docs only) is committed on
`claude/liveclip-stage19-customer-delivery` (from `origin/main` `a79deaf`).
First next task: Stage 19a, starting with
`tests/unit/test_dual_profile_freeze_pins.py`, then the
`load_verified_dual_profile_render_set()` refactor with the before/after
review-package comparison. Nothing is pushed or merged; push/merge need
explicit user consent.

## Outcomes and Retrospective

(Filled when a sub-stage closes.)
