# Sealed Python entrypoint prerequisite

2026-09-12. Main agent is sole supervised Coder in this isolated full clone. User authorized
continuous development while preserving Coder/Runner security. Original tree and previous candidates
remain intact. This follows the separate local CLI compatibility prerequisite; it does not add SD-1A scope.

## Purpose and observed defect

Runner commands must execute the frozen interpreter/dependencies. `ToolchainManager.prepare` copies
`.venv` and rebases symlinks, pyvenv.cfg and editable paths, but Python console-script shebangs retain
the original workspace path. Actual pytest/mypy/liveclip entrypoints in the prepared local candidate
all contain that absolute prefix. Thus a copied command can silently execute the original interpreter.

## Scope and plan

Only `tools/loop_engineering/toolchain.py`, cache environment and exact ancestor metadata rules in `sandbox.py`,
`apps/web/tsconfig.app.json`, `apps/web/tsconfig.node.json`, and the existing Loop unit test file may change, plus
ADR 032 and this plan. Do not change Make, dependencies, allowlist, role profiles, retry limits,
Gateway, media/data, or product source. Preserve deny-default, file-content/directory-listing limits,
source/evidence writes and external-network denial; only exact authorized-path ancestor metadata may be added. No other writing agent runs concurrently.

- [x] 2026-09-12: header fixture observes actual stale-interpreter FileNotFoundError, then succeeds after rebase with original interpreter absent.
- [x] Rebase only recognized Python entrypoint headers before sealing/hashing; preserve executable modes,
  original files and body bytes. Handle direct shebang and installer shell trampoline forms safely.
- [x] Reject unsupported unsafe local interpreter headers; new format-2 cache namespace/manifest prevents stale cache reuse, while source identity stays unchanged.
- [ ] Focused tests and lint; independent read-only review of the two-file delta and actual evidence.
- [ ] Record both reviewed prerequisites in the next formal SD-1A baseline and execute existing gates.

## Validation, decisions and recovery

Register each diagnostic in the original root QA pipeline before execution; append results with exact IDs.
Use a synthetic interpreter fixture to prove stale original entrypoints cannot supply a passing command.
Inspect real prepared entrypoints after the actual sealed toolchain is created. These probes do not replace
Runner/Gateway acceptance. New preparation fingerprints naturally separate corrected entrypoint bytes;
old immutable caches and run receipts are retained. Never patch an existing sealed cache in place.

The current cache reuse path also needs to distinguish relocation implementation identity: a cache created
by the old rewriter must not be reused solely because original package bytes match. Freeze a small explicit
toolchain format identity in cache location/manifest, independently of unchanged dependency lock identity.

Next: add the stale-interpreter counterexample, implement the minimum header relocation and cache identity,
then independently review before forming a new product baseline. No formal acceptance is claimed yet.

## Discoveries and current evidence

Initial red command ef43 had two valid failures and one fixture metadata-copy error. cfe5 confirmed
the two failures, but a copied signed macOS system binary exited SIGKILL, so that execution case is
excluded. The final header-only fixture uses an intact system-shell symlink (never production readiness)
and explicitly observes old-header failure before verifying corrected execution. eb6b caught a real
same-parent rename requirement after sealing: staging now sits in the versioned destination parent.

QA 20260912162800Z-337f passes all 53 Loop regressions in 10.67s. Candidate-local setup 0644 passes
with Python3.12.14/SQLite3.53.1 and unchanged locks. An ad hoc Ruff check passed but lacked a prior QA
request and is excluded as acceptance evidence; the full registered lint/Runner checks still follow.
The separate CLI compatibility review 01a09671-2270-7e41-ba6f-5863f13aa20c now PASSes with no findings;
its accepted process/truncation fixes and tests are included here as prerequisite baseline.

Next: registered full lint, actual deterministic Runner diagnostics on frozen dependencies, independent
read-only review against the accepted compatibility baseline, then SD-1A formal workflow.

Actual Runner diagnostic 20260912T162936Z-fd7f8335 preserved ERROR QA66fd before command execution: copied sealed node_modules prevented .vite creation. Real recorded pytest/mypy/liveclip headers correctly point to sealed format-2 Python. Scope now also includes private Node-copy preparation in the same toolchain.py: omit existing mutable caches, temporarily allow owner write on copied root only to create already-allowlisted .vite/.vite-temp, restore original root mode. Package modes/bytes and trusted cache remain unchanged. Added actual readonly-copy regression; no sandbox policy change. Ordinary lint also caught a local str/Path typing mismatch, corrected.

Actual Runner f0fd passes immutable snapshot preparation but fails writing .ruff_cache in source. Scope extended (parent/scope-extension-cache-locations.json) to direct Ruff/Mypy cache environment into existing Runner TMPDIR, and TypeScript build info into already-allowlisted node_modules/.vite. No sandbox profile rule or writable root changes. The two tsBuildInfoFile paths preserve the same typecheck and production compiler settings. Fresh tests, lint, real Runner and independent review required.

2026-09-12 16:40 UTC: actual lint QA4c25 passes Ruff/Mypy/schema, then Node cannot lstat HOME while canonicalizing an authorized path. Proposed HOME read policy now explicitly allows only existing content roots plus literal DIRECTORY ancestor metadata. Actual fixed-sandbox probe 20260912163951Z-6ad8 passes11 observations: required metadata/source/scratch/localhost allowed, HOME listing/unrelated metadata+data/source+QA writes/synthetic.env/external network denied with errno1. Scripts/fixtures unchanged. Source-policy test now uses an explicit synthetic HOME child so nested Runner private HOME does not invalidate its fixture premise. Fresh regression/lint/review and Runner verification follow.
