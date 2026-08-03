# SQLite concurrency and migration verification

Verified: 2026-08-03

## Runtime findings

LiveClip's project runtime is CPython 3.12.13 arm64 with SQLite 3.53.1, SQLAlchemy 2.0.51 and Alembic 1.18.5. SQLite reports `threadsafety=3`; real `WAL`, foreign-key, `busy_timeout`, explicit `BEGIN`, `BEGIN IMMEDIATE` and `UPDATE ... RETURNING` Spikes pass.

The macOS Command Line Tools Python is 3.9.6 with SQLite 3.51.0. It is both outside LiveClip's Python requirement and inside an affected SQLite WAL range, so neither setup nor doctor may treat the system `sqlite3` CLI version as the application runtime.

## Official evidence and conclusions

- SQLite disclosed a rare WAL-reset race affecting WAL databases with multiple connections in 3.7.0 through 3.51.2. It is fixed in 3.51.3+, with official fixes on the 3.50 branch at 3.50.7 and 3.44 branch at 3.44.6. LiveClip blocks affected runtime versions before opening its WAL database. [SQLite WAL-reset bug](https://www.sqlite.org/wal.html#the_wal_reset_bug)
- WAL allows readers and a writer to overlap, but SQLite still has only one writer. It requires a local filesystem and can return `BUSY`; LiveClip uses short write transactions and treats lock contention as transient. [SQLite WAL](https://www.sqlite.org/wal.html), [SQLite isolation](https://www.sqlite.org/isolation.html)
- `BEGIN IMMEDIATE` acquires the write transaction at the start. LiveClip uses it only for bounded queue claim/recovery transactions. [SQLite transactions](https://www.sqlite.org/lang_transaction.html)
- Python's sqlite3 legacy transaction behavior does not consistently begin transactions for every DDL/SELECT/SAVEPOINT case. SQLAlchemy documents a cross-Python approach using `isolation_level=None` and an explicit begin event; LiveClip uses that approach for Python 3.11+. [SQLAlchemy SQLite transaction control](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html#transactions-with-sqlite-and-the-sqlite3-driver)
- SQLite foreign keys must be enabled on every connection before a transaction. LiveClip's connect event sets them and tests a real orphan insert failure. [SQLite foreign keys](https://www.sqlite.org/foreignkeys.html), [SQLAlchemy foreign-key support](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html#foreign-key-support)
- `UPDATE ... RETURNING` is supported by SQLite 3.35+; ordering of returned rows is not a queue guarantee, so LiveClip selects one deterministically and uses a conditional update under the immediate transaction. [SQLite RETURNING](https://www.sqlite.org/lang_returning.html), [SQLAlchemy RETURNING](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html#insert-update-delete-returning)
- `synchronous=FULL` with WAL provides the stronger durability choice. LiveClip chooses FULL because losing acknowledged review/task/delivery state on an OS crash is a worse trade than modest latency in short local transactions. [SQLite synchronous](https://www.sqlite.org/pragma.html#pragma_synchronous)
- Alembic autogenerate output requires review, stable naming conventions and batch mode for later SQLite table rewrites. [Alembic autogenerate](https://alembic.sqlalchemy.org/en/latest/autogenerate.html), [Alembic batch migrations](https://alembic.sqlalchemy.org/en/latest/batch.html)

## Semantics

SQLite serialization does not make external media work exactly once. LiveClip guarantees at most one unexpired valid lease at a time, while crash recovery deliberately permits another attempt. The execution contract is therefore at-least-once with idempotent stages, append-only attempts, immutable pending Asset reservations and lease/generation/revision fencing.

Running cancellation is a request until the owning worker acknowledges a safe subprocess boundary, or a reaper observes lease expiry. A queued task can become cancelled immediately. This prevents status from claiming work has safely stopped while FFmpeg or a provider request is still active.

## Actual M2 evidence

- Two concurrent SQLAlchemy connections proved `BEGIN IMMEDIATE` writer exclusion without sleeps.
- Two simultaneous queue claimers returned exactly one lease for one ready Task.
- Exact `lease_expires_at <= now` recovery, stale-token heartbeat/completion rejection, bounded crash retries, deterministic/transient failure handling, dependency readiness, heavy singleton and cancellation acknowledgement are covered with injected UTC times.
- Initial Alembic migration upgraded an empty database, reported no autogenerate drift, passed `integrity_check` and `foreign_key_check`, downgraded to base and upgraded to head again.
