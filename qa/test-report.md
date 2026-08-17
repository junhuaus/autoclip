# LiveClip QA test report

### 20260817T060348Z-ba78
- ts: 2026-08-17T06:04:23Z
- command: npm --prefix apps/web run e2e:real
- cwd: /Users/junhuaxu/Workspace/AGI/liveclip-ai
- status: ERROR
- duration_seconds: 6
- summary: Managed sandbox aborted the Google Chrome process before the E2E test body started.
- details:
  Playwright reported `browserType.launch: Target page, context or browser has been closed`; Chrome exited with SIGABRT and process cleanup reported EPERM. FastAPI, Worker, SQLite migrations and Vite all started normally. No product assertion ran, so this is not evidence of an approval-flow failure.

### 20260817T060423Z-7cdd
- ts: 2026-08-17T06:20:53Z
- command: npm --prefix apps/web run e2e:real
- cwd: /Users/junhuaxu/Workspace/AGI/liveclip-ai
- status: PASS
- duration_seconds: 22
- summary: Real Google Chrome completed the isolated content-review and release-approval flow through immutable delivery.
- details:
  One Playwright test passed against real FastAPI, a leased Worker, SQLite and FFmpeg. It created a Project, completed the Pipeline, edited a clip to revision 2, approved that revision, rendered the current final video, created and downloaded delivery v001, submitted a platform release for approval, approved it, generated its platform package and recorded publication evidence. Fixture verification reported 10 attempts, 6 stages and 10 tasks.

### 20260817T062300Z-ffc4
- ts: 2026-08-17T06:23:31Z
- command: npm --prefix apps/web run test:run -- tests/review-flow.test.tsx tests/review-board.test.tsx
- cwd: /Users/junhuaxu/Workspace/AGI/liveclip-ai
- status: PASS
- duration_seconds: 3
- summary: All 15 focused Web review tests passed.
- details:
  Two single-clip tests and thirteen review-board tests passed, covering revision edits, stale media, approval, atomic batch approval, retry reconciliation, unsaved-draft exclusion and in-flight editor locking.

### 20260817T062300Z-5358
- ts: 2026-08-17T06:23:31Z
- command: .venv/bin/pytest -q tests/integration/test_review_atomic.py tests/unit/test_authorization.py
- cwd: /Users/junhuaxu/Workspace/AGI/liveclip-ai
- status: PASS
- duration_seconds: 2
- summary: All 14 atomic-review and centralized authorization tests passed.
- details:
  Revision fencing, transaction rollback, idempotent batch decisions, stale-render/delivery invalidation and the static owner/editor/reviewer/viewer capability matrix passed. These tests do not persist or display a content-review actor because the current schema has no such field.
