# ADR-002: Fenced SQLite leases and immutable artifacts

Status: accepted, 2026-08-03

## Context

Foreground CLI and an independent Worker can race, processes can crash, and SQLite/filesystem operations cannot share one transaction.

## Decision

Use a separate Task queue table claimed under `BEGIN IMMEDIATE` and `UPDATE … RETURNING`. Every claim receives a random lease token; heartbeat and completion require task, worker and token. Use short transactions, WAL/FK/busy timeout, one heavy task by default, generation/revision fencing and a pending Asset reservation before external I/O. Derive reservation and commit authority from TaskAttempt → Task → PipelineRun → Project in the active transaction; caller scope is only an assertion. A pending reservation can be recovered only by a later failed/lost attempt of the same logical Task. Publish a verified attempt with a same-directory hard link that fails if the immutable path exists; never replace a revision artifact.

Stage success requires a typed checkpoint with both committed Assets and the stage's required domain rows. Proxy RenderJobs are persisted as queued/running before external I/O and receive durable failed states for execution error, cancellation or lease expiry; they become succeeded only after all required Assets commit.

## Consequences

Expired work can be safely requeued and an old worker cannot publish current output. Stage caches require database success, typed domain checkpoints, fingerprints, hashes and validation—not file existence. Cross-project, cross-generation, cross-candidate, cross-revision and cross-logical-Task publication is rejected transactionally. A replacement attempt of the same Task may adopt an exact pending reservation only when path, fingerprint, hash and validation match; otherwise the file is quarantined as an orphan. External I/O never holds a database write lock.
