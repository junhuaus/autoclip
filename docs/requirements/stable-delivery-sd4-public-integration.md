# SD-4 bounded implementation C2: public goal API and acceptance

Start from accepted C1. Before coding, trusted Main records a `C2_BASELINE` PASS
receipt with a full accepted-C1 per-path hash manifest in the new isolated
candidate. It names the exact C1 DONE run/fingerprint, inherited and Main-modified
paths, matching HEAD/toolchain and no copied source media. Freeze the public
request/response DTO and owner-vs-Coder file boundary before the sole Coder edits.
Main owns `src/liveclip/bootstrap.py`, `src/liveclip/api/schemas.py`, shared
Completion DTO and transactional fresh-create guard changes in the completion
service/repository, any migrations, and final integration. The isolated Coder
owns bounded API route/exception wiring and its focused tests after those owner
files are sealed; a second writer does not modify them during the formal run.
The Coder's source boundary is `src/liveclip/api/app.py` plus focused API and
browser test files it adds or changes. It must use the frozen DTO names from
`src/liveclip/api/schemas.py` and `LiveClipRuntime.completion_service`, and
pass the already assessed `provider_readiness` to the required
`readiness_guard` callback for new-project creation. It must not call
`resolve_allowed_source` or `ensure_processing_ready` before service replay;
the callback runs only for a genuinely new create. Add safe 409 handling for
CompletionConflict and keep inaccessible goals at 404.
Freeze candidate STATUS/ExecPlan with this run ID before formal review, leaving
future results pending. Preserved root QA journals are excluded from read-only
assurance source snapshots; Reviewer checks root history before Tester requests
the fixed Runner, and Gateway checks actual receipts afterward.
Expose versioned authorized API commands to create a durable
goal for a new project/run or an existing current run, read by intent ID, resume with
expected version, submit manual selection and explicitly cancel. Use CompletionService
and current caller identity; entry points do not implement selection, permission or
delivery rules. New-project source paths use configured allowed-root validation and
fresh-run provider readiness, with no credential in a response or log. A valid
idempotent replay or resume checks current authority and canonical identity but does
not require unrelated fresh-run provider capability when no new model work is created.
Freeze the v1 route set as `POST /api/v1/completion-goals` for a new project/run,
`POST /api/v1/runs/{run_id}/completion-goals` for an existing current run,
`GET /api/v1/completion-goals/{intent_id}` for read-only observation, and
`POST /api/v1/completion-goals/{intent_id}/{resume|selection|cancel}` for explicit
versioned commands. New-project create nests the existing `JobCreateRequest`
configuration with `CompletionOptions`; existing-run create takes only options.
Main freezes strict request DTOs for those two bodies, a one-field
`expected_version` body for resume/cancel, the existing
`CompletionSelectionSubmission` body for selection, and a response containing
the authorized goal snapshot plus nullable signed download URL. Unknown body
fields fail validation; callers cannot submit project/run/actor/delivery IDs as
trusted state in the new-project body.
Freeze the JSON names as new-project `{"job": JobCreateRequest,
"options": CompletionOptions}`, existing-run `{"options": CompletionOptions}`,
versioned resume/cancel `{"expected_version": integer}`, and response
`{"goal": CompletionSnapshot, "download_url": string|null}`. The nested
`job.input_path` is the caller's request spelling for idempotency; only a
genuinely new create persists the strictly resolved allowed-root source.
Create requires `Idempotency-Key`, returns `202`, `Location` and `Retry-After: 1`;
read returns `200`. Each response projects the authorized `CompletionSnapshot`
and exposes a delivery download URL only after the bound Delivery succeeds,
through the existing authorized Delivery route that resolves its ZIP asset ID.
Idempotency-Key replay binds the canonical request and same caller; a changed request
conflicts. Fresh create and existing-goal replay must not generate a duplicate
project/run/intent.
For a new-project goal, decide canonical replay under current authority before
fresh-run source existence/provider readiness checks. A lost successful response
must replay the same intent even if the original media is temporarily unavailable
or provider capability has since changed; a genuinely new request still validates
the configured allowed root, readable source and provider readiness before commit.
Do not use an API-level precheck followed by an unrelated write transaction as the
only protection against duplicate project creation or changed authority.
Freeze an application-level fresh-create guard as needed: the repository's
`BEGIN IMMEDIATE` path resolves same-key replay and current authority first,
then invokes the guard before inserting a genuinely new project/run/intent.
The guard performs only bounded local source/readiness checks; it does not
execute an AI provider, copy source media, or accept model-supplied commands.
The API supplies its already assessed provider-readiness snapshot as a cheap
callback to CompletionService. The service invokes that callback only after
the repository rules out replay under `BEGIN IMMEDIATE`; no Codex login probe
or other subprocess runs while the write transaction is held.
Bind the idempotency digest to the caller's canonical request spelling before
strict filesystem resolution, so a formerly valid source that is now absent
or whose symlink target changed can still replay the saved intent under current
authority. Reject relative paths and parent traversal as request syntax before
the transaction. For a genuinely new create, the guard resolves and checks the
regular source under the configured allowed roots and returns that validated
path for persistence in the same transaction. Existing direct repository tests
and commands retain their historical behavior.

Return the durable intent and safe outcome, blocker and bound delivery identity.
Reads and watch/polling never claim a task. Client disconnect or Ctrl-C exits
observation only; explicit cancel is a separate versioned command and never delegates
to processing cancellation. Preserve current low-level API/CLI behavior and asset-ID
downloads. Do not claim a completed pipeline is a delivered ZIP.

Exercise a real local API/Worker/SQLite/FFmpeg synthetic flow: request goal, disconnect,
let all six stages finish without the client, restart Worker around selection and
packaging, recover a lost create/select/enqueue response with the same identities,
and inspect current MP4/SRT, manifest, ZIP, Asset hashes and DB checkpoints. Test
manual waiting and explicit empty selection, zero candidates, stale generation,
revoked/downgraded actors, read-only watch, cancellation, archived project and
unavailable source/provider. Browser inspect the authorized download flow.

Require final current lint/test and fresh independent review, fixed sandbox Runner,
Gateway, actual artifact inspection, migration recovery instructions, ExecPlan/STATUS
updates and trusted CAS publication to the original worktree. Only then mark SD-4
engineering accepted. Real model/content/audio/hardware claims remain for SD-6.
