# ADR-005: SQLite runtime gate, explicit transactions and FULL durability

Status: accepted, 2026-08-03

## Context

LiveClip depends on WAL plus multiple local connections because foreground CLI and Worker execution can compete. SQLite's official 2026 WAL-reset disclosure makes version selection part of data safety. Python 3.11 and 3.12 sqlite3 transaction defaults also differ from the explicit transaction behavior required by migrations and lease claims.

## Decision

Use the SQLite library embedded in LiveClip's active Python runtime, never the standalone CLI version. Require SQLite 3.35+ and a WAL-reset-safe release: 3.51.3+, 3.50.7 on the 3.50 branch, or 3.44.6 on the 3.44 branch. Reject a runtime compiled without thread safety or required foreign-key capabilities.

Set the DBAPI connection to explicit transaction control, emit `BEGIN` for normal work and `BEGIN IMMEDIATE` for bounded queue claim/recovery. Enable WAL once and verify its returned mode; enable foreign keys and the configured busy timeout per connection. Use `synchronous=FULL` because preserving acknowledged local state across OS crash/power loss outweighs the latency difference for short transactions.

## Consequences

The project-local CPython 3.12.13/SQLite 3.53.1 runtime passes. The development host's system Python/SQLite 3.51.0 is rejected. Setup, doctor and application startup must all evaluate the application runtime. Database files must stay on a local filesystem. Queue semantics remain at-least-once rather than exactly-once, so leases, idempotent stages, pending Asset reservations and immutable publication remain mandatory.
