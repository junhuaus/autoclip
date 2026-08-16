# LiveClip status snapshot

Updated: 2026-08-16 08:40 CST

Current package baseline: `0.1.0`

Current milestone: V2-M6 exact-revision/timecode collaboration comments are
implemented and reviewed; checkpoint publication is in progress. The next
slice is server-authorized Project search plus per-user saved views.

Branch: `main` tracking `origin/main`. Current checked-in head is `10b443f`;
the comment implementation is still in the working tree until the next local
milestone commit.

## Current user-visible result

V2-M0 through V2-M5 remain checkpointed. LiveClip provides administrator
login and user/role management, default-private Project membership, ownership
recovery, professional editorial/release lifecycle, selective clean MP4/SRT
editor handoff, immutable Delivery, platform release planning and storage
governance without storing social credentials or claiming external uploads.

The first V2-M6 collaboration slice adds a “协作批注” panel to each high-point
editor row:

- owner/editor/reviewer can capture the exact current player time, create a
  thread, mention active explicit Project members, reply, resolve and reopen;
- viewer/workspace-visible users can read but not mutate; archived Projects are
  read-only and a private outsider still receives 404;
- a thread is bound to one exact EditPlan revision and stores immutable
  original clip-relative milliseconds plus canonical source milliseconds;
- historical threads remain truthful after an edit and seek into the current
  revision only when that source instant still exists;
- concurrent replies append independently, while resolve/reopen uses an exact
  optimistic thread version;
- all POST operations support idempotent retry, list queries are bounded and
  paginated, and comment text is excluded from audit metadata;
- comment activity does not approve/reject a clip, change Project lifecycle,
  create an EditPlan revision, queue rendering or stale existing media.

The three existing real Projects remain intact and were not reprocessed:

- `8.15-1`: `67e827b4c0c8493b9804241e517cc5fe`, completed generation 2,
  15 successful clean proxies, `pending_review`.
- `8.15-2`: `4e3bf22ebf2f4b6a81f5ae5a0e552a46`, completed generation 2,
  15 successful clean proxies, `pending_review`.
- `7.28`: `f91cb996f7534a6682aa5e5f01374b7b`, unchanged.

At the user's request, immutable offline-review v001 packages were generated
for `8.15-1` and `8.15-2`. Each contains 15 clean MP4s, 15 SRTs, 15 per-clip
descriptions, combined descriptions, manifest/checksums and a file-only HTML
viewer. Both ZIPs passed archive and per-member SHA-256 validation. They are
ignored generated data and must never enter Git.

## Current implementation

- Domain/application: `src/liveclip/application/comments.py` defines strict
  thread/message/mention/status commands and DTOs; centralized authorization
  exposes the `comment` Project capability.
- Persistence: migration `e92b7c4d1a60` adds append-only comment threads,
  messages and mentions with exact revision/source anchors, identity snapshots,
  constraints and indexes. `SqlAlchemyClipCommentRepository` performs every
  read/write authorization check against live database state.
- API: authorized list/create/get/reply/status routes use stable 201/200/403/
  404/409/422 behavior, bounded filters/pagination and `Idempotency-Key` on all
  POSTs.
- Web: `ClipComments.tsx` provides time capture/seek, member mentions,
  reply/resolve/reopen, current/history/resolved filters, paging and exact-key
  retries. A clip/revision change clears relative-time drafts with an explicit
  warning so an unsaved anchor cannot silently rebind.
- Purge: Project purge includes comment rows and Project-scoped comment
  idempotency records while preserving unrelated idempotency evidence.
- Documentation: Solution/API/architecture and ADR-017 describe the safety,
  concurrency and time-coordinate boundary.

## Real database evidence

- Before migration, `data/projects/liveclip.sqlite3` reported d8,
  `quick_check=ok`, no foreign-key violations and no active run/task.
- WAL-safe backup:
  `data/projects/database-backups/liveclip-pre-comments-bb77061a92444e399100a4fab9160c34.sqlite3`
- Backup SHA-256:
  `90dd7356f09d4a1057cedd6bcc1d931389fe536fe5fd704d5a5915a1a082b84d`
- The live database now reports `e92b7c4d1a60 (head)` and `alembic check`
  reports no pending operation.
- Post-migration integrity remains `quick_check=ok`, foreign keys are clean and
  protected counts remain 3 Projects, 3 SourceMedia, 5 PipelineRuns,
  131 candidates, 60 renders and 353 API-usage rows. The three comment tables
  began empty.

## Latest actual validation

- `make lint`: passed Ruff/format over 219 files, mypy over 134 source files,
  EditPlan schema verification and TypeScript typecheck.
- `make test`: passed 714 Python tests, 52 Web component tests, Mock Google
  Chrome E2E 1/1 and isolated real FastAPI/SQLite/leased-Worker/FFmpeg Google
  Chrome E2E 1/1.
- Independent comment reviewer: final P0=0/P1=0/P2=0 after draft-rebinding,
  resolver-history, pagination and concurrency/idempotency/purge evidence gaps
  were fixed and retested.
- Actual host Chrome viewed the real `8.15-1` editor: the collaboration panel is
  visible, the subtitle section remains last, and a representative proxy is
  direct-source 540×960 with no blurred background. The in-app Browser exposed
  no controllable instance, so MCP-Browser success is not claimed and no
  extension was installed.
- `8.15-1` offline-review ZIP: 289 MB,
  SHA-256 `38c444df0b1ab49c800646bda8debee5b774a2e4c8a1f4040e27ee0bfe2926c8`.
- `8.15-2` offline-review ZIP: 288 MB,
  SHA-256 `83ee259de0651c056cb0c4c800e64c19428dde2a36c404b34d5dfbd718262238`.

## Unverified and remaining scope

- Reusable personal saved views and full server-authorized Project/clip/release
  search are next; cross-Project optimistic bulk assignment remains after that.
- External Jianying/CapCut Desktop import is unverified. LiveClip truthfully
  provides standards-based H.264/AAC MP4 plus UTF-8 SRT and does not claim an
  undocumented native draft format.
- Scoped hashed PAT lifecycle remains deferred until an actual automation
  consumer needs more than the bounded v0.1 Bearer-token migration bridge.
- Immediate stage/render cleanup still has the documented P2 task of carrying
  persisted `TaskAttempt.temp_identity` through every synchronous cleanup call.

## Security and worktree

- Never stage `.env`, `.env.local`, `OPENROUTER_SETUP.md`, `input/`, `data/`,
  SQLite/WAL, media, offline-review packages, browser artifacts or credentials.
- No paid Provider call or long-video reprocessing occurred in this slice.
- `git diff --check`, live `alembic current/check` and health checks pass.
- The working tree intentionally contains the reviewed collaboration code,
  tests and documentation until its exact staged-set audit and commit.

## Next concrete task

Audit the exact collaboration staged set, create and push its milestone commit,
record the resulting hash here, then implement a server-owned Project search
query and user-scoped saved-view schema/API before changing dashboard UI.

## Resume instructions

Read `AGENTS.md`, both Product Specs, `docs/SOLUTION.md`, `.agent/PLANS.md`,
`docs/exec-plans/liveclip-v0.2.md` and this file. Run `git status --short
--branch`, `git diff --check`, `git log -5 --oneline`, `.venv/bin/alembic
current` and `.venv/bin/alembic check`. Preserve all three real Projects, the
pre-comments database backup and both offline-review packages. Do not reprocess
real inputs or invoke paid Providers. Finish the collaboration checkpoint, then
begin the saved-view/search contract from the server authorization boundary.
