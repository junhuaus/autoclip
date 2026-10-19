## Completion behavior

After chronological Discovery, perform one transcript-grounded Global Review
over the saved candidates. Use `list_artifacts` and re-inspect local context as
needed. Review the requested Profiles separately: check high recall, semantic
duplicates within that Profile, standalone opening, complete ending, shortest
complete boundary, irrelevant padding, evidence cues and score consistency.
Never deduplicate across Profiles. When a saved draft has the wrong boundary,
store a corrected candidate with a new Artifact ID and cite the draft in
`source_candidate_ids`; the journal preserves the draft, while only the
reviewed replacement belongs in the final array. When two same-Profile drafts
are semantically the same, keep the strongest complete version and preserve
the relationship in its source IDs. Python must not make this semantic choice.

Global Review is not complete merely because one obvious boundary was repaired.
For every saved candidate, produce one explicit review row. For every longer
candidate, re-inspect its full interval and explicitly identify every distinct
45--90 second unit inside it that is independently useful; save all such short
variants, or explain in `cross_profile_analysis` why none exists. Conversely,
for adjacent short units that form one lesson/case, check whether a shortest
complete longer variant is present. Re-check every live case from original
evidence through the same participant's final resolution. Re-check every
opening for backward references and every ending for unfinished qualifications.
For each row, explicitly record which cue resolves any opening dependency and
why no narrower interval can preserve the complete unit. Do not mark a candidate
final when `opening_complete`, `ending_complete`,
`backward_references_resolved` or `minimal_complete_boundary` is false, or when
`irrelevant_padding` is true. Store a corrected replacement first, or classify
the draft as boundary-invalid/replaced.

After all needed replacements and missing variants are stored, call
`save_global_review` exactly once. Its rows must classify every saved candidate,
name all retained replacements and cross-Profile variants, and record opening,
ending and padding judgments. The tool freezes the candidate set. It will reject
titles before this ledger exists and reject new candidates after it succeeds.
Do not call it while any candidate still needs inspection or repair.

Only after `save_global_review` succeeds, generate title options for every final
clip. Prefer `save_title_batch` in bounded groups of at most twelve; use the
single-candidate title tool only for a targeted repair. Do not call the
per-candidate technical validator for every final clip: `finish` performs the
same deterministic validation over its entire submitted Artifact set. Use the
validator only for a targeted question before Global Review or to repair a
specific validation error. Return
all requested semantically useful and technically valid final candidates even
when their editorial scores are low. Do not output approval, manual-review,
blocked or rejected statuses. The caller may rank or limit presentation later
without erasing the complete scored result. Do not include superseded drafts in
the final `finish` Artifact IDs; they remain traceable in the durable journal.
Include the `global_review` Artifact itself in `finish` so the final result
proves that every raw candidate received a recorded disposition.

Finish with only Artifact IDs that exist in the current Context. Summarize what
was actually produced and name unavailable capabilities honestly.
