# ADR-015: Release planning and platform-package boundary

Status: accepted for V2-M4 implementation

Date: 2026-08-15

## Context

An editor handoff, an approved LiveClip Delivery and a social-platform release
answer different questions.  An editor handoff contains material for continued
editing; a Delivery proves the approved current render set; a platform release
adds channel copy, cover choice, policy checks, scheduling and a human-recorded
publication outcome.  Social-platform limits also change over time and may vary
by account.  Treating them as one status or one permanent set of hard-coded
numbers would make the audit trail misleading.

## Decision

V2-M4 introduces a Project-scoped `ReleaseItem` for one exact current,
non-rejected clip, platform and account label. It may be drafted before content
approval, while preflight keeps publication blocked. It stores editable release copy, caption mode,
clip-relative cover time, assignee, planned publication time, approval state,
an explicit human checklist, optimistic version, external publication result
and manual metric snapshots.  Release state has one centralized transition
table: `draft | ready | scheduled_external | published | failed | withdrawn`.
The Project lifecycle remains separate; recording a publication is allowed only
from `ready_to_publish|published`, and the first publication advances the
Project lifecycle to `published` with an audit event.

Platform rules live in a versioned, read-only preset registry.  Every preset
inherits the verified general MP4/H.264/AAC/progressive/yuv420p/fast-start
contract and a conservative LiveClip editorial safe-zone.  Only limits backed
by current primary vendor documentation are hard blockers.  Account-dependent
or unverified policy is exposed as a manual confirmation and warning; the UI
must never label it as universally passed.

Each release package is a separate immutable version fenced to the current
Project generation/revision epoch, ReleaseItem version, EditPlan revision,
render, committed Asset hashes, requester authority and preset version.  A
`clean_separate` package copies the current clean proxy and includes an editable
UTF-8 SRT.  A `burned` package requires the approved current final render.  The
Worker validates the actual video bytes, extracts the selected cover frame,
emits editable copy/checklist/preflight metadata, checksums, manifest and ZIP,
then publishes atomically without replacement.  It does not upload a browser
form, store a platform credential or claim that scheduling in LiveClip schedules
the external platform.

A platform package is always a complete ZIP; a caller cannot request a
manifest-only handoff.  The successful package row retains the manifest and ZIP
hashes captured at completion.  Crash recovery must independently revalidate
the pinned source video, decoded cover pixels, deterministic metadata, canonical
manifest/checksums and exact ZIP rather than trusting hashes rewritten inside an
existing directory.  Recording `published` requires an operator-supplied actual
time and external URL or content ID plus the exact current successful package.
One immutable publication-evidence row binds that package/item/preset/caption
version and its video, manifest and ZIP hashes.

Preset history is append-only.  One explicit registry entry selects the current
version for each platform, while old records continue to resolve their original
version.  Release assignees are limited to the Project owner or an editor, and
an externally scheduled item cannot discard its planned time without first
leaving the scheduled state.

Duplicate-content detection is advisory: source-time overlap and normalized
text similarity compare immutable succeeded ReleasePackage snapshots,
EditPackages and Deliveries, but never block intentional cross-platform reuse.
The enqueue-time full preflight, Project display name and requester username are
frozen as artifact context. Dynamic duplicate evidence is excluded from the
material current-content fingerprint, so later exports cannot change an
existing package's bytes or crash-recovery result. A package excludes its own
ReleaseItem history from the advisory to avoid warning about itself.

Every ReleaseItem management-version change atomically fails its queued or
creating package and cancels/fences the durable Task. Clip revision raises the
Project revision epoch, so it invalidates all active release packages for that
Project rather than only packages for the edited clip. Starting a new
PipelineRun applies the same Project-wide invalidation. Successful packages are
never overwritten or failed; they remain immutable history but stop being
current when their generation/revision/item evidence no longer matches.

## Consequences

Editors get a truthful release queue/calendar and portable package while local
privacy and recoverability stay intact.  A 540×960 clean proxy can pass the
minimum technical contract but receives a visible 1080×1920 recommendation;
teams wanting a burned 1080×1920 master must first produce the current approved
final render.  Presets need dated maintenance, and external publication success
and performance remain human-entered evidence until an approved API integration
is separately authorized and reviewed.
