# ADR 033: Search-only intermediate directory descriptors

Date: 2026-09-12. Status: proposed, isolated prerequisite under review.

## Context

Actual frozen Runner test QA20260912T164243Z-d9bb cannot collect transcript tests: the secure-file
reader opens every ancestor with O_RDONLY, requiring HOME directory read/list authority even though
the final fixture lies in an authorized source root. Runner must continue denying HOME enumeration.
macOS exposes O_SEARCH, and a fixed real sandbox probe proves no-follow fd-relative traversal with
this capability succeeds while the same content/write/network restrictions remain enforced.

## Decision

Use O_SEARCH for intermediate directory descriptors when the OS provides it, retaining the existing
O_DIRECTORY, O_NOFOLLOW and O_CLOEXEC flags. Keep the final descriptor and absolute anchor O_RDONLY;
callers still receive the capability needed for listing, fsync and atomic publication. Creation,
descriptor cleanup and typed failures remain unchanged. If O_SEARCH is absent, preserve prior flags.

This change reduces the rights requested for traversal. It does not authorize new roots, follow
symlinks, bypass sandbox checks or change media ownership. No Coder/Runner policy, allowlist, package
lock, semantic contract, credentials, database or artifact is changed by this prerequisite.

## Evidence and recovery

QA20260912164735Z-8601 reproduces actual read failure with a chmod0111 ancestor; listing is denied.
After the change, all29 secure-file tests pass (QA20260912164808Z-a81e), including the new read and
immutable publication case through that ancestor plus existing symlink/race/cleanup tests. Actual
sandbox primitive probe QA20260912164541Z-3be5 passed all12 observations with unchanged file bytes.
Full lint, actual frozen Runner commands and fresh independent review remain required.

Keep prior candidates, failed Runner receipts and fixture evidence. Rollback withdraws this isolated
candidate; it never grants parent directory enumeration. Platform-specific evidence is macOS only.
