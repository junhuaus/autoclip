# ADR-016: Storage retention, Project purge, and SQLite recovery

Status: accepted 2026-08-15

## Context

LiveClip keeps multi-hour source references and many generated local artifacts on one Mac. A professional workspace needs capacity visibility and a real destructive-retention path, but ordinary archive/cleanup must not erase source media, successful deliveries or another user's files. SQLite WAL state also makes a raw copy of only `liveclip.sqlite3` an unreliable operational backup.

## Decision

Archive remains reversible and non-destructive. The administrator storage report scans metadata without following symbolic links and classifies database/backups, known Project content, stale/pending/orphan/untracked content, unknown Project directories, unsafe entries and pending purge quarantine.

Routine safe cleanup is a narrow allowlist: terminal Task attempt worktrees and a completed purge's exact audited quarantine identity. It never deletes committed Project artifacts or SourceMedia. A filesystem lock serializes janitors. A short SQLite writer transaction rechecks authority, terminal state, source references and exact device/inode, then performs only an atomic rename into `.attempt-cleanup-quarantine`. Recursive deletion is outside the transaction. If diagnostics are referenced, the quarantined tree is reduced to `diagnostics` and the same inode is atomically restored. Recursive deletion first renames the exact tree to deterministic `.<name>.cleanup`; if the process terminates at that boundary, a later pass discovers only that hidden endpoint, requires the persisted device/inode, repeats the source fence and resumes. Both original and hidden endpoints existing is a fail-closed conflict. Terminal-attempt cleanup resumes at startup; completed-purge cleanup resumes through the explicit administrator safe-cleanup action.

Permanent Project purge is a distinct administrator-only workflow:

1. Require an archived Project with no active run/task.
2. Return a dry-run scope fingerprint, Project name and exact confirmation phrase.
3. Require both name and phrase from a fresh authenticated/CSRF-protected request.
4. Refuse every current Project/SourceMedia reference inside the generated Project directory, and prohibit all new source paths below `LIVECLIP_DATA_DIR` at API/CLI ingress and again in the shared PipelineService.
5. Create and validate an immutable SQLite backup before purge intent.
6. In a short `BEGIN IMMEDIATE`, recheck current administrator authority, database version, active work and source references, then rename only the exact Project directory inode into private quarantine.
7. Release the SQLite writer lock and perform the potentially long no-follow tree verification in quarantine; restore the exact inode if scope differs from the confirmed preview.
8. In a second short `BEGIN IMMEDIATE`, repeat authority/state/source/identity fences, delete terminal Tasks and the Project graph with deferred foreign-key validation, and append completion evidence.
9. After commit, remove the exact quarantined inode no-follow. If this last step fails, expose it for identity-bound safe cleanup. A started-only quarantine is restored automatically on startup.

Database backup uses SQLite's online backup API so committed WAL data is included. Backup and restore require `quick_check=ok`, zero foreign-key violations, one Alembic revision and SHA-256 evidence. Publication is native atomic/no-clobber and withdraws the exact output if a post-rename durability check fails. Restore rejects a raw main database with a nonempty WAL/journal sidecar, writes only a new path and never overwrites a live database automatically.

The same short-transaction quarantine rule protects immutable EditPackage and ReleasePackage compensation. An exact retry may adopt committed Assets only after transferring their producer attempt. A current failed/cancelled attempt can withdraw only by proving its active lease and ownership of every package Asset while atomically moving the expected directory inode into its private attempt quarantine. A lost attempt does nothing; recursive deletion follows the transaction. This prevents an old runner's cleanup from deleting a successor's completed package.

## Alternatives rejected

- Treating archive as deletion: rejected because archive is a normal reversible production lifecycle state.
- Deleting all stale/untracked files automatically: rejected because an Asset status or absent row alone is insufficient ownership evidence.
- Recursively deleting a Project path after a string-prefix check: rejected because symbolic links, endpoint replacement and source-inside-project layouts can cross the intended boundary.
- Copying only the SQLite main file: rejected because committed WAL pages may be omitted.
- Restoring over the configured live database: rejected because active processes and an operator typo could make recovery destructive.
- Holding SQLite's global writer lock while scanning or recursively deleting: rejected because a large generated tree can exceed the busy timeout, block Task heartbeats and invalidate otherwise healthy leases.
- Keeping a purged Project tombstone with source/transcript metadata: rejected because append-only audit plus a backup provides governance evidence without retaining the full private Project graph.

## Consequences

Purge is intentionally slower because it first creates a full database recovery point. Backups consume disk and appear separately in storage inventory; operators decide when to move or retain them. The current backup implementation temporarily holds one serialized database snapshot in memory, so very large SQLite installations need an operator capacity check. Source media remains the user's responsibility, must live outside `LIVECLIP_DATA_DIR`, and survives Project purge. Append-only audit may retain safe Project identifiers/name and backup evidence after the Project graph is removed. A restored database must be brought online through a separate data directory after services are stopped and validation evidence is reviewed.
