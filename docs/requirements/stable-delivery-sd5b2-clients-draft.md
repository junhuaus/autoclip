# SD-5 B2 draft: observable CLI, terminal and Web completion

Status: draft. Start only after SD-5 A and B1 are accepted and the shared
observation DTO plus independent Worker lifecycle contract are frozen.

`liveclip auto VIDEO` should resolve a named immutable preset through the
same application service as API/Web, durably create one Completion intent,
print its Project/Run/Goal identities, and attach a read-only watch. The
operator must be able to disconnect without cancelling work; processing
belongs to an independently running Worker, not a CLI child thread. Main
must specify how the CLI persists its pending idempotency key before a
create request, how an intentional new request differs from a lost-response
retry, and what an operator sees when no Worker is running. Never derive a
new Project merely because a terminal process exited.

`liveclip resume PROJECT_ID` resolves an existing authorized goal, never
creates a Project/run/generation, and requires an exact intent ID when
multiple eligible goals exist. Any CAS conflict or lost response is
resolved by rereading current state. Explicit selection and cancellation
remain separate application actions; Ctrl-C, non-TTY pipe closure and Web
disconnect only stop observation. Local package paths appear only in an
authorized successful terminal view. Browser download remains by Asset ID.

TTY watch reads the same Completion observation DTO about every two
seconds, handles Chinese display width, narrow/wide resize and long safe
errors without unbounded scrolling. It shows business phase/counters,
elapsed time, last advancement and Worker lease freshness separately.
Unknown totals remain indeterminate. Non-TTY watch emits bounded state
changes or explicit JSON, without ANSI repaint. Web polls authorized goal
state and displays the two named preset forms, manual wait, zero selection,
render/package progression, error/cancel and final success. Refresh does
not create work, lose a pending request key or display a premature ZIP URL.

Acceptance uses disposable Mock API/SQLite/Worker/FFmpeg to observe one
default and one manual goal through real package commit, with client
disconnect and Worker restart. Inspect exact database/Asset/MP4/SRT/ZIP
evidence. Render narrow/wide terminal captures and verify Ctrl-C leaves
Task/Goal state unchanged. In a real local browser inspect both forms,
manual selection, changing producer-backed counters, zero/no-package and
authorized final download. Fresh isolated Coder, read-only review/test,
allowlisted sandbox Runner, deterministic Gateway and independent
sealed-source audit remain required. Synthetic flow cannot establish
real content, audio, cloud-provider or Apple hardware quality.
