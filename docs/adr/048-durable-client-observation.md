# ADR048: Observe durable Completion from CLI and Web

Status: accepted with SD-5 B2 final acceptance and publication.

## Context

Versioned presets (ADR-046), durable Completion goals (ADR-045), and
attempt-bound Delivery progress (ADR-047) already share application-owned
identities. The earlier high-level `auto` command ran six stages in its own
foreground process. A lost create response, terminal interruption or browser
reload could leave the user uncertain about the saved work even though an
independent Worker owns processing.

## Decision

`liveclip auto` resolves the frozen preset and selection policy through the
same application Completion service as API/Web. It prints the caller and
request key before creation, uses a caller-scoped idempotency context, saves
one Project/run/goal, and only observes the persisted goal afterward. An
independent `liveclip worker` processes it. `--no-watch` returns the saved
identities immediately; a terminal interrupt stops observation without
cancelling or claiming work. Retrying an uncertain create requires the same
key, source and options; a changed body conflicts.

`liveclip resume PROJECT_ID` first performs an authorized read-only lookup.
Ambiguous Projects require the exact goal ID. A genuine manual-selection wait
continues to wait, and exhausted coordination retries stay parked. Only an
eligible `needs_action` is explicitly resumed through the version-fenced
Completion service. Observation and Web polling never start, cancel, select,
reset retries or synthesize progress. They display active attempt counts and
lease freshness separately and expose a ZIP only after its bound Delivery
Asset commits.

Web saves the confirmed goal ID before discarding pending create identity.
On reload it GETs that same goal under current authority; failures hide old
content and signed links. The unconfirmed request key and body hash remain
available only for same-body response recovery. Source media stays a
read-only reference under an allowed root and is not stored in browser
reconnect state after confirmation.

## Consequences

The CLI no longer implies that the initiating process performed work.
Operators must run the independent Worker and retain the request key when
creation is uncertain. Default and manual selection remain distinct; only
authorized selection can release manual waiting. Fresh retry and Delivery
attempt history remain visible and cannot be reset by a watcher. The three
synthetic real-browser scenarios and separate-process Worker regression are
release gates; they do not establish real model, Chinese content/audio, cloud
or 2/4-hour performance quality.
