# ADR 032: Relocate Python console entrypoints before sealing

Date: 2026-09-12. Status: proposed; isolated prerequisite pending review.

## Context

The deterministic Runner promises frozen project dependencies. Its copied Python console scripts
still contain absolute shebangs to the original workspace interpreter. Existing symlink, pyvenv.cfg
and editable-path relocation does not rewrite those headers. Real pytest/mypy/liveclip entrypoints
show this prefix, so executing their copied files can use unfrozen original dependencies.

## Decision

During trusted toolchain preparation, rebase recognized local `.venv/bin/python[version]` headers
before hashing and sealing. Support direct shebangs and the installer's `/bin/sh` Python trampoline,
using shell quoting for the relocated interpreter. Preserve executable mode and all body bytes;
reject unsupported local headers, nonlocal trampolines and unsafe direct destination shebangs.
This does not execute, evaluate or accept code from model output.

Toolchain format 2 uses a distinct versioned cache namespace and requires its explicit manifest
version, so old caches with stale console scripts cannot be reused solely because source locks and
package bytes match. Stage beside the final destination for an atomic same-parent rename after sealing.
Source and copied fingerprints are still compared before rewriting; rewritten bytes are frozen in
the snapshot fingerprint. No existing cache or receipt is edited in place.

Actual preparation also exposed a filesystem-mode issue when copying sealed Node dependencies.
Omit the already designated mutable `.vite`/`.vite-temp` contents from the private copy, temporarily
enable owner write only on its root to create fresh private cache directories, then restore that root's
original mode. Package files and the trusted source remain read-only and unchanged. This changes no
sandbox allowlist and grants no new writable paths to a command.

The first actual sandboxed lint reached Ruff, which correctly refused to create its default cache
in the protected source root. Set Ruff/Mypy cache environment paths beneath the existing private
Runner scratch, and set both TypeScript build-info paths beneath existing `.vite`. The compiler
settings, checks, Make argv and content/write/network limits remain unchanged. Generated cache files cannot
be mistaken for source changes or require a new writable root.

The next actual lint passed all Python checks but Node failed `lstat` on the user HOME ancestor.
Use deny-default read rules: retain full reads outside HOME and within the same three authorized roots,
and allow only `file-read-metadata` on exact directory ancestors of those roots. HOME directory listing,
unrelated file metadata/data, source/QA writes, synthetic `.env` reads and external network remain denied.
This avoids granting ancestor contents simply to canonicalize an authorized child path. The existing
protected-file denials and write/network rules stay intact. Official Codex's
[platform profile](https://github.com/openai/codex/blob/main/codex-rs/sandboxing/src/restricted_read_only_platform_defaults.sbpl)
also distinguishes ancestor metadata traversal from content access; our exact limits are verified locally.

Fixed synthetic probe QA 20260912163951Z-6ad8 passed all 11 positive/negative checks against the actual
macOS sandbox; forbidden operations return PermissionError errno1. Original fixtures and script hashes
remain unchanged. Evidence is retained under parent `sandbox-probe-20260912T163951Z`; it is a sandbox
authority diagnostic, not a new allowlist command or formal five-role acceptance.

Runner argv allowlist, deny-default sandbox, credential filtering, protected evidence, source snapshot,
role authority, repair budgets and Gateway correlation remain unchanged. Make and package locks do not
change. The same required lint/test commands must pass against the corrected execution environment.

## Evidence and limitations

The unit counterexample proves the stale header fails after removing its original interpreter, then
the relocated header succeeds with original still absent. Its header-only fixture uses the intact
signed system shell to avoid copying macOS protected executable metadata; production readiness still
rejects escaping symlinks. Separate tests cover quoted trampoline paths, body CRLF preservation,
executable modes and legacy manifest rejection. Actual frozen Python/console execution and independent
review remain required. No cloud, real-video or final product acceptance is implied.

## Recovery

Withdraw only the isolated candidate if this prerequisite fails. Retain old source baselines, caches,
failed probes and QA entries. Create a new formal run only after the changed prerequisite is reviewed
and verified; never change a blocked run state, relax sandbox rules or substitute original dependencies.
