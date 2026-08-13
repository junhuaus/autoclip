# LiveClip v0.2 Product Specification

Status: proposed implementation contract

Created: 2026-08-13

Baseline: LiveClip `0.1.0` at Git checkpoint `0f34e2b`. The v0.1 media Pipeline, clean no-blur proxies, current `7.28` Project, immutable revisions and formal Delivery remain compatible unless an explicit migration below says otherwise.

## Product outcome

LiveClip v0.2 turns the local v0.1 clipping engine into a professional team workspace for a small video operation. Administrators manage local accounts and system authority; creators own private Projects by default; editors and reviewers receive explicit Project assignments; Projects move through an auditable production lifecycle; and users can select generated clips for an editor-friendly handoff or a platform-ready release.

The target operator remains a local Apple Silicon Mac. v0.2 does not require a cloud identity provider, external database, SaaS storage or automatic social-platform publishing.

## Users and authority

### System roles

- `administrator`: sign in to the administration console; create, edit, disable and reactivate users; reset a user's password; grant/revoke system roles; view all Projects for support and governance; transfer Project ownership; inspect security/audit events. At least one enabled administrator must always remain.
- `member`: sign in to the editing workspace; create private Projects; see only owned or explicitly assigned Projects; act only within assigned Project permissions.

System administration and Project collaboration are separate. Being an administrator does not silently change the recorded Project owner or Project-member role.

### Project roles

- `owner`: full Project control, member management, lifecycle transitions, export and ownership transfer.
- `editor`: edit title/bounds/subtitles, request rerenders, prepare editor handoffs and release metadata.
- `reviewer`: preview, comment, approve or reject current revisions; cannot change Project membership or ownership.
- `viewer`: read-only access to Project state, clips and deliveries.

The server owns this authorization matrix. CLI/API/Web never maintain competing permission logic.

### Authentication

- A signed-out Web user sees a login page, not Project data or Provider diagnostics.
- Username and password authenticate against local SQLite credentials.
- Passwords are never reversible and use a memory-hard password hashing scheme with a per-password salt.
- Successful login creates an opaque, random, revocable server-side session. The browser receives only a `Secure`-when-applicable, `HttpOnly`, `SameSite=Strict` cookie.
- Login errors do not disclose whether the username exists. Repeated failures receive bounded rate limiting and an audit event.
- Logout revokes the current session. Disabling a user or resetting their password revokes all sessions for that user.
- CLI/API automation may retain separately generated, hashed, scoped personal access tokens. The v0.1 environment-token bridge is accepted only as a migration/bootstrap mechanism and is deprecated for ordinary Web use.
- A bootstrap administrator is created only when the database has no administrator. Bootstrap material comes from local environment/one-time setup output and is never committed or logged as plaintext.

## Project visibility

- New Projects are `private` by default and initially visible only to their creator/owner plus system administrators acting in an explicit administrative context.
- Allowed visibility values are `private` and `workspace`. `private` requires membership; `workspace` permits any enabled member to view but not mutate unless assigned a Project role.
- There is no public/anonymous visibility in v0.2.
- Project listing, counts, search, descendant resources, media URLs, export and Delivery all enforce visibility on the server.
- A non-member cannot infer a private Project's existence, filename, processing status, clip count or generated asset IDs.
- Visibility, membership, ownership and role changes create audit events.

## Professional Project lifecycle

Business lifecycle is separate from Pipeline/Render/Delivery technical state:

```text
draft → processing → editorial_review → approval → ready_to_publish → published → archived
          ↘ needs_attention ↗       ↘ changes_requested ↗
```

- `draft`: source/configuration assembled; processing may be started.
- `processing`: one current Pipeline or required render/export job is active.
- `needs_attention`: current work failed or was cancelled and needs an operator.
- `editorial_review`: clean proxies and metadata are ready for editing/review.
- `changes_requested`: at least one reviewer returned current work for revision.
- `approval`: editorial work is complete and waiting for designated approval.
- `ready_to_publish`: approved current revisions and required release assets are complete.
- `published`: an operator records at least one platform publication result or marks the release published.
- `archived`: read-only normal workflow; retained artifacts remain governed by retention rules. Owner/admin can restore it.

Lifecycle changes have an actor, UTC time, reason and before/after state. Illegal transitions fail centrally. The Project dashboard shows lifecycle, current assignee, due date, priority, last activity, blocking reason and counts requiring attention. Technical status remains available but does not masquerade as the whole Project lifecycle.

## Editor handoff and selective download

Users can select one or more current clips and choose an export preset:

### Clean editing package

For continued work in Jianying/CapCut Desktop/Web and other nonlinear editors:

```text
liveclip-edit-package-vNNN/
├── media/
│   ├── 01-readable-title.mp4
│   └── ...
├── subtitles/
│   ├── 01-readable-title.srt
│   └── ...
├── metadata/
│   ├── clips.csv
│   ├── clips.json
│   └── README-导入剪映.txt
├── thumbnails/
├── checksums.sha256
└── liveclip-edit-package-vNNN.zip
```

- MP4 is H.264/AAC, progressive, 4:2:0, fast-start, with no burned LiveClip text in the clean preset.
- SRT is plain UTF-8 without BOM and uses clip-relative timing; each basename matches its MP4.
- Filenames are stable, readable, path-safe and portable. A conservative ASCII alias is available for editors that have path/encoding problems.
- Metadata contains title, high-impact sentence, recommendation, risks, keywords/times, source range, revision, owner and export provenance.
- A selection may be downloaded as individual MP4, individual SRT, selected ZIP or metadata-only package.
- Export is immutable/versioned, snapshot-fenced to exact current revisions/assets and cannot mix stale renders.

CapCut/Jianying project files are not generated in the first v0.2 release because no stable public Jianying draft interchange contract has been established. The supported workflow is clean MP4 plus matching SRT into CapCut/Jianying Desktop/Web. Mobile direct SRT import is not claimed.

### Platform-ready package

The user chooses a platform preset (`douyin`, `xiaohongshu`, `bilibili_vertical`, `youtube_shorts`, `tiktok`, or `generic_vertical`) and whether captions are clean/separate or burned. A release package contains platform-valid MP4, SRT where useful, thumbnail/cover, title variants, description, hashtags, CTA, rights/risk checklist and a release manifest. Presets are versioned configuration, not hardcoded marketing claims.

## Release workflow

Each selected clip can have a `ReleaseItem` per target platform with:

- platform and account/channel label (no platform credential in v0.2);
- title, description, hashtags, cover frame and caption mode;
- planned publish time, assignee and approval state;
- exported artifact/version/hash;
- status `draft | ready | scheduled_external | published | failed | withdrawn`;
- external URL/ID entered after publication;
- published time, result notes and basic performance snapshots entered manually.

Direct platform publishing is deferred until a platform provides an approved API, user authorization and privacy review. v0.2 never automates a browser upload or stores social credentials under the guise of export.

## Additional professional requirements

### Production workflow

- Assignment, due date, priority and saved Project filters.
- Review comments tied to an exact clip revision/timecode; threaded resolution and mention-ready identity, without email delivery in the local release.
- Activity/audit timeline for user, permission, lifecycle, edit, review, render, export and publication changes.
- Bulk assign/review/export with optimistic revision fences.
- Compare revision metadata and boundaries; media A/B generation remains out of scope unless explicitly requested later.
- Search by Project/source/title/Hook/keyword/assignee/lifecycle/platform.

### Editorial and release quality

- Platform-specific duration/aspect/codec/size preflight before marking a release ready.
- Safe-zone overlays for platform UI, selectable cover frame and first-frame/Hook check.
- Subtitle readability checks: cue duration, characters per line, line count and overlap warnings.
- Rights/risk checklist for music, likeness, personal data, claims, sponsorship and platform policy; AI flags remain advisory and require human confirmation.
- Duplicate-content warning using source interval and text similarity across exported/published clips.
- Title/description/hashtag variants are editable metadata, never silently published.
- Record publication outcome and basic metrics to support later feedback into candidate ranking; no automatic model training in v0.2.

### Operations

- Soft-delete/archive for users and Projects; destructive purge is a separate administrator-only, confirmation-heavy retention operation.
- Storage usage and orphan/stale-artifact visibility; explicit cleanup policy never deletes source media.
- Database backup/restore guidance before migrations or ownership transfer.
- Audit log is append-only through application services and omits secrets, password material and transcript payloads.

## Staged delivery

### V2-M0 — v0.1 freeze and v0.2 Solution

Version baseline, evidence research, user/permission matrix, lifecycle and export contracts, ADRs and Living ExecPlan.

### V2-M1 — Accounts, administrator console and authorization

Local login/logout/session, password hashing, bootstrap administrator, user CRUD/disable/reset, system roles, personal token support, Project role matrix, audit log and admin Web UI. Existing `local-admin` and `7.28` migrate safely.

### V2-M2 — Project lifecycle and production operations

Private/workspace visibility, lifecycle transitions, assignment/due date/priority, activity timeline, timecoded review comments, dashboard saved views and archive/restore.

### V2-M3 — Selective editor handoff

Clip selection, individual MP4/SRT download, immutable edit-package ZIP, CapCut/Jianying import guide, UTF-8/portable naming/fast-start validation and export history.

### V2-M4 — Release planning and platform-ready packages

Versioned platform presets, cover/safe-zone/preflight, release metadata/items, approval checklist, platform package generation and manually recorded publication outcome.

### V2-M5 — Hardening and acceptance

Migration/backup recovery, concurrent permission revocation, session security, audit integrity, storage/retention, full Mock and real-media regression, browser E2E and operator documentation.

## Acceptance boundary

v0.2 is not complete until two isolated users can log in, see only permitted Projects, exercise their actual role restrictions, move a Project through tested lifecycle transitions, select current clips, download a verified editor package, and record a platform release without any credential or inaccessible asset disclosure. Existing v0.1 projects/media remain readable and the real `7.28` Project is not reprocessed merely to validate account or export metadata.
