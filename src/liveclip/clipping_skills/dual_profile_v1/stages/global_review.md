# Stage: Profile Global Review

Review every candidate exactly once. You see only this Profile's candidate pool, complete candidate
subtitles, boundary result, source window, evidence cues, risk evidence and local context; do not rescan
the livestream. Perform semantic deduplication only inside this Profile. A duplicate must remain as a
`rejected` audit row and reference its retained representative; containment or time overlap alone is not
duplication.

The service may partition a large Profile pool to keep structured responses reliable. When
`review_partition` is present, review every supplied candidate exactly once and deduplicate within that
partition. Do not invent decisions for unseen partitions. The subsequent Profile Global Review Audit
receives the merged complete pool and is authoritative for cross-partition semantic deduplication.

When two candidates really are semantic duplicates, retain the shortest independently complete,
unpadded boundary. Do not retain a superset merely because it has a broader title, more examples or a
higher provisional score. A contained candidate with a distinct question/objective/conclusion is a
separate lesson and must not be rejected as the broader candidate's duplicate. Never choose a version
that drops the evaluated sample, initiating premise or final recommendation when another version supplies
the complete chain.

The payload de-duplicates repeated subtitle bytes: each candidate's `context_refs` lists cue IDs for its
before, complete-candidate and after sections, and `cue_catalog` contains the actual cue objects shared
by those references. Resolve every reference against that catalog before judging the candidate.

Assign one comparable 0–100 score and one status: `selected`, `manual_review`, `blocked` or `rejected`.
`selected` requires score strictly greater than 75, a complete shortest boundary, no quality flag and no
manual/blocking risk. Risky but coherent material should normally be `manual_review`; meaning-blocking
ASR, missing required premises, an unclosed topic, padding or material interruption must be `blocked` or
`rejected`. Do not create candidates or change the final Boundary interval. Titles, hooks and summaries
must preserve the speaker's actual stance.

Do not infer missing prerequisites from a numbered ordinal alone: a later chapter is independently
complete when it defines its own included techniques and reaches its own conclusion. Treat garbled names
or individual vocal terms as non-blocking `asr_uncertain` when the surrounding explanation still makes
the method and conclusion understandable; use `asr_uncertain_blocks_meaning` only when a viewer cannot
recover the central instruction at all. When duplicate candidates describe a live correction, retain the
one that includes the evaluated sample, correction, retry/before-after evidence and final confirmation.

A local reference to an earlier technique or “as just explained” is not itself a missing prerequisite.
If the candidate locally names the required technique, states its role, explains how it combines with
the current step and reaches the chapter conclusion, it is independently understandable. Apply
`missing_required_prior_steps` only when the omitted material contains an actual instruction, result or
definition without which the current method cannot be understood or performed.

For a choice or expression lesson, the opening enumeration of available techniques and the explanation
that their difference is small are required premises for a later “choose by intended sound” conclusion.
Do not retain a shorter duplicate that begins only at the conclusion and drops those premises. For a live
diagnosis, sung or spoken example cues immediately preceding the first diagnostic statement are the
evaluated sample; a candidate starting at the diagnosis is incomplete when another candidate includes
that sample. Retain the complete sample-to-diagnosis-to-correction-to-closing version even when it is
longer. Do not mark a coherent correction chain as meaning-blocked merely because a lyric, song name or
isolated technique word is mistranscribed while the method and outcome remain understandable.

When nested choice candidates both repeat the compared names, prefer the one that contains their first
local introduction and defining property: for example the step/chapter label, the initial enumeration,
and the support or sound-quality definition before the later “differences are small” recap. A later recap
that merely repeats names is not a substitute for that first definition, even if it still meets minimum
duration. Reject the recap-only version, not the dependency-complete version.

Risk tags are cumulative evidence. Re-check the full referenced cue catalog and add any missed tag, but
never remove one supplied by Discovery or Boundary Review. A coherent candidate with review risks such
as lyrics, participant audio, health advice or non-blocking ASR uncertainty should normally remain
`manual_review`, not be rejected merely because of the risk.

A risk candidate that uniquely preserves an initiating risk question, category count or cumulative
risk evidence must remain auditable as `manual_review` or `blocked`. If it is incomplete, interrupted or
padded, use `blocked`; do not use `rejected` unless another `manual_review` or `blocked` representative
preserves the same initiating premise and cumulative risk evidence. A narrower later diagnosis does not
replace an earlier overview-to-first-category risk chain.
