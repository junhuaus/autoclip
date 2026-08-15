# Database backup and recovery

These commands operate only on local SQLite files. They never call ASR/LLM Providers and never copy or delete SourceMedia.

## Create a recovery point

`db-backup` can read a running WAL database consistently, but for a planned migration or ownership/purge operation first stop new jobs and preferably stop `make dev` so the recovery point has an obvious operational boundary.

```bash
liveclip db-backup
```

The default destination is a new random filename under `LIVECLIP_DATA_DIR/database-backups/`. To place it elsewhere, name a nonexistent file:

```bash
liveclip db-backup --output /Volumes/Backup/liveclip-before-migration.sqlite3
```

Success prints the absolute path, SHA-256 and Alembic revision. It also proves `PRAGMA quick_check` is `ok` and `PRAGMA foreign_key_check` is empty. Save those lines with the change ticket. Existing destinations, symbolic-link endpoints, invalid databases or failed checks stop without replacement.

The current implementation creates one transactionally consistent SQLite snapshot in memory before writing through a pinned private file descriptor. Video and generated media are never loaded this way, but an unusually large SQLite metadata database needs enough free memory for one serialized copy. Check the database size and host memory before a major maintenance window.

## Restore for verification

Stop API, Worker and Web first. Restore to a new directory/file; never choose the current `LIVECLIP_DATA_DIR/liveclip.sqlite3`:

```bash
liveclip db-restore \
  --backup /Volumes/Backup/liveclip-before-migration.sqlite3 \
  --output /absolute/recovery-check/liveclip.sqlite3
```

Compare the printed SHA-256 and revision with the backup evidence. A restore is an exact validated byte copy and refuses an existing output.

Do not pass a raw, running `liveclip.sqlite3` to `db-restore`: a nonempty adjacent `-wal` or `-journal` makes it unsafe and is rejected. Use `liveclip db-backup` first so committed WAL state is captured in one closed recovery file.

## Bring the restored database online

Keep the original data directory unchanged. The database contains generated Asset paths relative to its data root, so a complete disaster recovery also needs the corresponding Project directories restored under the new root. Then start against that separate root:

```bash
LIVECLIP_DATA_DIR=/absolute/recovery-check make doctor
LIVECLIP_DATA_DIR=/absolute/recovery-check make dev
```

Check `/api/v1/health`, the expected Project count and several generated downloads before deciding whether to keep the recovered root. Starting Runtime may apply migrations newer than the backup's recorded revision; the restored input file remains your immutable fallback only if you first make another no-clobber copy or start from a duplicate recovery directory.

## Failed migration

LiveClip uses explicit SQLite transactions for DDL/data migrations. A raised migration rolls back its transaction, but the service must remain stopped until the cause is understood. Preserve the failed database and logs, restore the last verified backup to a new root as above, and never use `git reset`, raw file overwrite or a downgrade against the only copy of production data.

## Project purge recovery

Every confirmed permanent Project purge creates a validated backup before filesystem quarantine or database deletion. The administrator storage response reports only its safe filename and hash; the file is under `LIVECLIP_DATA_DIR/database-backups/`. A crash after the exact Project inode is quarantined but before the database graph is deleted is recovered automatically on next startup; a post-commit cleanup failure remains listed for administrator safe cleanup. To recover an already committed purge, restore that database into a separate root and restore/copy the matching generated Project directory from filesystem backup if the purge already removed it. LiveClip intentionally does not delete or back up the external SourceMedia file, which must live outside `LIVECLIP_DATA_DIR`.
