# ADR-017: Revision-bound timecode collaboration comments

Status: accepted 2026-08-15

## Context

Several editors and reviewers need to discuss an exact moment without turning a comment into an edit, approval or render command. Clip boundaries and captions can later create a new immutable EditPlan revision, so storing only a floating player offset would silently move old feedback. Concurrent replies must not overwrite each other, while concurrent resolve/reopen actions do need conflict detection. Account display names and membership may also change after a production discussion becomes audit history.

## Decision

A thread belongs to one immutable `EditPlanRevision`. It stores the original clip-relative integer millisecond and the equivalent canonical source-video millisecond. Creation is allowed only against the exact current saved revision and only inside its interval. When another revision becomes current, LiveClip preserves the original anchor and derives a current-player offset from canonical source time when that instant is still inside the new boundary; otherwise the UI marks it outside the current clip.

Messages are ordered append-only child rows. Replies intentionally omit an expected-version input: one short `BEGIN IMMEDIATE` serializes writers, allocates the next unique sequence, increments the thread version and retains both valid concurrent replies. Resolve/reopen replaces shared thread state and requires the caller's exact `expected_thread_version`. All create/reply/status POST operations support caller-and-operation-scoped idempotency keys.

The central Project capability grants comment mutation to owner, editor and reviewer. Viewer and workspace-visible non-member access is read-only, private outsiders receive not-found, and archive freezes comments. Every mutation rechecks the live active account, explicit membership and Project lifecycle inside its writer transaction. Mentions can name only active explicit Project members.

Creator, author and mention username/display-name values are immutable snapshots alongside nullable user foreign keys. The thread row carries the current resolver snapshot; every append-only resolve/reopen audit also preserves that transition actor's user ID, username and display name, so reopening or a later resolution cannot erase earlier attribution. Account rename, disable or later deletion therefore does not erase history. Comment bodies remain Project-authorized content and never enter audit-event payloads; audits retain only safe identity/resource IDs, anchor/revision, thread version and mention count. Comment operations have no ReviewDecision, RenderJob, Delivery, Provider or lifecycle side effect.

## Alternatives rejected

- Bind only to the current clip-relative offset: rejected because a boundary edit would move historical feedback to different source content.
- Copy comments to each new revision: rejected because it invents editorial intent and duplicates unresolved work.
- Require optimistic version on replies: rejected because two independent valid messages should append rather than make the second author retype or retry against a new version.
- Let workspace-visible viewers or administrators comment implicitly: rejected because visibility/governance is not editorial membership.
- Store only live user joins: rejected because later rename/removal would rewrite or blank historical attribution.
- Put comment text in the general audit timeline: rejected because the timeline has a broader governance purpose and should not duplicate private transcript-like content.

## Consequences

Historical threads remain queryable with explicit current/history badges and may no longer have a seekable current-player position. Thread status conflicts return 409 and require refresh. Replies still advance the thread version, so a resolver must act on the discussion state they actually saw. Storage purge must include thread and message IDs when removing Project-scoped idempotency records; normal Project foreign-key cascade removes thread/message/mention rows without touching source media.
