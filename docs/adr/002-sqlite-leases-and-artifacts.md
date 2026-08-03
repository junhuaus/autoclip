# ADR-002: Fenced SQLite leases and immutable artifacts

Status: accepted, 2026-08-03

## Context

Foreground CLI and an independent Worker can race, processes can crash, and SQLite/filesystem operations cannot share one transaction.

## Decision

Use a separate Task queue table claimed under `BEGIN IMMEDIATE` and `UPDATE … RETURNING`. Every claim receives a random lease token; heartbeat and completion require task, worker and token. Use short transactions, WAL/FK/busy timeout, one heavy task by default, generation/revision fencing, verified temp artifacts and atomic rename into immutable paths.

## Consequences

Expired work can be safely requeued and an old worker cannot publish current output. Stage caches require database success, fingerprints, hashes and validation—not file existence. Orphan diagnostics may require cleanup, but current data is not overwritten. External I/O never holds a database write lock.
