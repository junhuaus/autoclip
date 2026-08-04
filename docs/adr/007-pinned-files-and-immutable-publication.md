# ADR-007: Pin exact bytes through validation and immutable publication

- Status: Accepted
- Date: 2026-08-04

## Context

LiveClip validates media, stage dependencies and delivery packages before it records success. A pathname is not a stable identity: another local process can replace a file or one of its path components after validation but before FFmpeg, ZIP creation, publication or database commit. Checking only a directory inode is also insufficient because a member inside that directory can be replaced independently.

The correctness contract is stronger than path confinement. The bytes validated by ffprobe/full decode/hash must be the bytes published, served and committed as an Asset. A Delivery ZIP must contain the exact approved video, subtitle and manifest bytes, and the published directory must contain that exact complete file tree.

## Decision

Security-sensitive local files are opened component by component with no-follow semantics and retained as pinned regular-file descriptors. Evidence contains the open descriptor, regular-file identity, size and SHA-256. Long media is hashed and copied in bounded blocks; it is never loaded wholly into memory.

The following boundaries use pinned evidence:

1. Render quality verification passes one pinned descriptor to ffprobe, full decode and representative-frame extraction. Publication receives the verified SHA-256 and database Asset commit independently checks it.
2. A succeeded upstream stage is usable only when its typed database checkpoint resolves to committed Assets whose project/run/generation/task ownership, canonical path, size and SHA-256 all match. Providers and FFmpeg receive the already-verified or independently re-pinned bytes.
3. Delivery members are copied or written immutably, pinned, and streamed into ZIP from descriptors with `os.pread`; `ZipFile.write(path)` is forbidden. The ZIP output is itself exclusively created and pinned, sealed with `fsync`, hashed, then reopened through a duplicated descriptor to verify every member name, size and hash.
4. Delivery publication enumerates an exact regular-file tree before and after an atomic no-replace directory rename. Every video, subtitle, manifest and ZIP endpoint must still bind to its pinned evidence and match its hash. A failed post-rename check withdraws the canonical directory or fails closed without deleting unrelated bytes.
5. Manifest and ZIP Asset commits receive an expected SHA-256. Crash recovery repeats the same exact-tree, member and archive checks; file existence alone is never recovery evidence.

Diagnostic paths and exceptions remain bounded and redacted. Temporary cleanup is inode-bound and never follows a replacement symlink.

## Consequences

- Path replacement, symlink escape and member replacement races fail closed rather than publishing unverified bytes.
- Large videos and ZIP members remain streaming operations with bounded memory.
- More descriptors remain open during validation/publication, and full hashes add deliberate I/O. The single-heavy-worker default bounds pressure.
- Native atomic no-replace directory rename uses `renameatx_np(RENAME_EXCL)` on macOS and `renameat2(RENAME_NOREPLACE)` on Linux. If the primitive is unavailable, publication fails rather than emulating a racy check-then-rename.
- A same-UID actor can still alter local files after a successful commit, but the committed Asset SHA makes later reads or recovery reject the changed bytes; LiveClip does not silently reinterpret them as the original artifact.

## Verification

Unit and integration tests cover source/member symlink replacement, directory and ZIP endpoint replacement, committed Asset tampering, crash-recovery tampering, exact ZIP member hashes, renderer validation/publication binding and safe cleanup. An independent M5 reviewer replayed both Delivery endpoint races and observed `DeliveryError`, no canonical `v001`, no retained attempt and no external-data inclusion.
