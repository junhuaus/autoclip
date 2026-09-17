# Topic Chain review

Return exactly one source_dispositions row for every supplied expected original/Chain
pair, including originals proposed for another Profile. A row contains either a
nonempty unique derived_unit_ids list and null rejection_reason, or no derived IDs and
an explicit rejection reason. Both require nonempty known cue evidence. One rejection
can coexist with other originals advancing in this Chain or the same original advancing
through another Chain. Never erase a path or use only the first candidate.

Every candidate declares this topic_chain_id, known source_fragment_ids and origin_kind.
A derived unit has at least one unique original_candidate_id and an origin_reason.
Its reverse origins must match the forward disposition edges exactly. No cross-chain
unit IDs, duplicate edges, semantic fuzzy matching or unknown original IDs are allowed.
chain_new is explicit: no original IDs, a nonempty origin_reason and known nonempty
candidate evidence. A Chain without original proposals may legitimately yield chain_new.
Apply the natural-unit and complete-objective requirements. An empty Chain result needs
the existing explicit Chain rejection; each expected original still needs its own row.
