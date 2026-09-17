# ADR037: Semantic failure audit routing and multipart business evidence

Status: bounded isolated correction design,2026-09-12. Main is the sole Coder.

Formal184158-6de530c3 is terminal BLOCKED after1plan/1code, Reviewer multipart P2 and
Tester; no Runner/Gateway/publication. Preserve exact source2f863899 and Coder01a096ef.
Main also reproduced P1 with25a4: a runs/gNNN audit manifest cannot pass existing
validate_task_diagnostic_relative_path, which fail_stage calls before its transaction.
Do not change the task diagnostic validator or lease checks to accept arbitrary paths.

Keep per-subject immutable Assets below runs/gNNN/semantic-audit; publish the committed
manifest inside the existing .attempts/<task>/<lease>/diagnostics directory and return
that attempt-owned path. Existing AssetStore fencing and immutable publication apply to
both. Verify actual repository failure recording and reload TaskAttempt/Stage/Run outcome,
not only the direct semantic helper. Diagnostic-preserving cleanup must retain the manifest.

For current contract only, extract all message/output_text parts with stable output/content
indices and keep their individual text in audit, excluding headers, reasoning and other
transport fields. Preserve single-output repair behavior. Ambiguous multiple outputs cannot
silently select one or gain extra repair calls. Available business parts survive incomplete,
unexpected/cardinality and SDK validation failure paths. Persisted parts use the same
credential redaction; embedded business JSON text must not bypass key-based redaction.
Legacy contracts, frozen wire formats/prompts, locks, policies, role permissions, budgets,
original code/data and all previous audit evidence stay unchanged. Full formal gates remain
required after independently reviewed verified correction.
