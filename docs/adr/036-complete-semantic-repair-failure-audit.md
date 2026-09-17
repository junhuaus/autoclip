# ADR036: Complete semantic repair errors and durable failure audit

Status: isolated SD-1A correction design, 2026-09-12.

Formal180403-1d68be2d is terminal BLOCKED after Reviewer2 FAIL/P2 and Tester BLOCKED,
using1plan/2code cycles. Preserve exact session01a096cd and assurance936445f0. This
new complete candidate changes the two identified conditions; no old state/budget or
Loop policy change, no original publication, no unconditional fresh-run retry.

For current semantic-v4-quality-v2 only, retain all available, deduplicated Schema and
cross-field errors. No100/200-count or per-message silent truncation. Preserve the
historical behavior for older contracts. Repair remains a single attempt; before either
provider starts that repair, count serialized instructions, wrapped payload, response
schema, configured output reserve and safety margin against the existing configured
context ratio. Copy only token settings for repair accounting; do not introduce unrelated
clip-duration validation into older Provider constructors. An oversized complete request fails explicitly with zero repair calls;
this is not a claim that SD-2's all-stage transport/budget work is complete.

Every failed V4 subject in a new-contract run gets its own immutable JSON audit asset,
reserved and committed through the existing AssetStore with the exact lease/generation
fence before raising the stage error. Include original/repaired business JSON, complete
available errors, repair phase records, request/contract/prompt identity and linked call
IDs. Keep every concurrent subject, not only first_error; retain successful sibling cache.
Paths are deterministic trusted hash paths, never model-supplied paths. Reuse existing
recursive redaction plus exact configured credential removal; never store response
headers, credentials or hidden reasoning. No new DB table or migration.

Each subject artifact respects existing bounded immutable publication; inability to
publish is an explicit failure, never a successful or silently truncated audit. Use the
existing diagnostic_relative_path channel to locate a committed manifest of all failed
subjects where feasible. Historical runs/artifacts/caches remain readable and unmodified.

Acceptance: >100 Schema and >200 combined errors reach actual OpenAI/Codex repair; valid
repair succeeds, invalid stays one repair, over-budget invokes no repair. Reload durable
failure artifacts to verify initial and repaired evidence, multiple failed subjects,
redaction, exact fencing, no-clobber and sibling-cache recovery. Independent review and
fresh full formal gates remain necessary after this changed condition is verified.

For non-validation OpenAI response failures, preserve any available extracted business output
with the actual failure code and initial/repair phase. An incomplete response is not successful,
and its audit must not silently omit already available output. Headers/reasoning stay excluded.
