# SD-5 A: shared named presets and high-level Web/API creation

This is a bounded isolated successor to published SD-4. The outcome is a
short-highlights or complete-mini-lesson choice in the Web that creates one
durable Completion goal from a server-resolved versioned preset, and the
matching authenticated API for other clients. It does not claim SD-5's CLI,
packaging progress or TUI are finished. Real model/content/audio/hardware
acceptance remains SD-6.

Trusted Main cloned the accepted original SD-4 source into `a_candidate`,
excluding `input`, real Project data and earlier `.loop` runs. The clone
receipt records exact source paths, file hashes, HEAD and QA history. Main
then froze shared contracts in
`src/liveclip/application/completion_preset_contract.py`,
`src/liveclip/api/schemas.py` and `apps/web/src/types.ts`, plus three
contract tests. These files, ADR046, ExecPlan, STATUS, dependency locks,
control-plane configuration and QA history are Main-owned. The sole Coder
must not edit them. Planner/Reviewer/Tester/Gateway are fresh read-only
sessions; only the exact recorded Coder session may resume, never `--last`.

Implement a pure application preset registry in new
`src/liveclip/application/completion_presets.py`. The immutable IDs are
`short_highlight_v1` and `mini_lesson_v1`; use `clip_profile_spec` for their
45/60/90 and 90/180/300 second durations. Both pin
`semantic_windowed/general`, top 15, threshold 75, full-context ratio 0.58,
context 128000, default selection, Delivery target and ZIP true. Return the
frozen `CompletionPresetValues` and a safe `CompletionPresetSummary` with
Chinese labels “短高光” and “完整小课”; both are `experimental`. Unknown IDs
fail before mutation. Do not copy numeric choices into API or Web. Runtime
settings still choose the configured Provider; no secret or model prompt may
enter the preset DTO. Existing low-level job/goal routes retain their wire
shapes and defaults.

Add protected `GET /api/v1/completion-presets` returning
`CompletionPresetsResponse`, and protected
`POST /api/v1/completion-goals/from-preset` accepting the frozen strict
`CompletionPresetCreateRequest` and required `Idempotency-Key`. The API
translates registry values into the existing PipelineConfig builder and
CompletionService create transaction; it never trusts client-resolved model
settings. Return the existing 202 Location/Retry-After and
CompletionGoalResponse. Preserve current-authority and source root checks.
The same caller/key/canonical high-level body must recover the same goal
after a lost response even if the source vanishes or readiness changes;
same-key changed body must 409 before a second Project is made. Explicit
Mock processing in disposable tests is allowed; do not call cloud models.

Web loads both summaries, shows simple Chinese labels and experimental
status, selects default or manual review, and creates via the high-level
route. Store one pending request key with a hash of the canonical form in
tab-scoped storage, without credentials or media. A transport failure and
retry of the same form reuses that exact key, including after reload; a form
change or successful create generates a new identity. A 202 response shows
the saved goal/Project and its truthful queued/waiting state, not a finished
ZIP. Preserve low-level existing create flow and accessibility; keep schema
versions, context tokens and control-plane details out of user controls.

The sole Coder may change only
`src/liveclip/application/completion_presets.py`,
`src/liveclip/api/app.py`, `apps/web/src/api.ts`, `apps/web/src/App.tsx`,
`apps/web/src/styles.css`, a new
`apps/web/src/CompletionCreate.tsx`,
`tests/unit/test_completion_presets.py`,
`tests/integration/test_completion_presets_api.py`,
`apps/web/tests/completion-presets.test.tsx`, and existing
`apps/web/tests/app-states.test.tsx` or `apps/web/tests/api.test.ts` only
where new UI/API setup requires it. No other file ownership is granted.
Main integrates shared contracts and handles any protected-file need by a
new frozen candidate, rather than permitting ad hoc edits.

Tests must cover both exact preset configurations, unknown ID, strict body,
auth, new/replay/conflicting-key behavior, changed source/readiness replay,
manual/default selection binding and no premature Delivery URL. Web tests
must prove both profiles render, stable key on lost response/reload, new key
on changed form, and truthful post-202 state. Fresh Reviewer must find no
unresolved P0/P1. Tester selects only checked-in argv allowlist IDs; fixed
Runner lint/full test runs in the unchanged deny-default macOS sandbox and
appends correlated QA. Gateway PASS cannot override a failed/mutated/stale
Runner result. Main independently compares accepted source and current
artifacts before exact original CAS publication. Do not read, copy or mutate
`input/8-30.ts` or real Project databases.

Keep role tool results bounded and complete: size-check long docs, read
small sections, use hash/count/samples for status and manifests; never print
a full status, large manifest or transcript into one result. A truncated
result is not evidence.
