# Stage: Profile Global Review

Review every candidate exactly once. You see only this Profile's candidate pool, complete candidate
subtitles, boundary result, source window, evidence cues, risk evidence and local context; do not rescan
the livestream. Perform semantic deduplication only inside this Profile. A duplicate must remain as a
`rejected` audit row (a `risk_discovery` record is retained as `blocked`) and reference its retained
representative; containment or time overlap alone is not duplication.

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

A candidate whose central objective is the speaker's own credentials, qualifications, pricing, course
sales or schedule is not a teaching or highlight unit: mark it `rejected` (Python retains a
`risk_discovery` record as `blocked`), not merely flagged or sent to `manual_review`, even when no
explicit purchase prompt appears and no padding flag remains. A brief credential or course mention
inside a real lesson does not make that lesson self-promotion.

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

Use `context_dependent_opening` only when the opening's meaning cannot be recovered from cues inside the
interval. A category, type or ordinal label that the clip itself contrasts, explains or demonstrates is
not a dependency on earlier content. The speaker's immediate application or consequence of the same
concept is the candidate's payoff, not padding; a new concept after it is outside the candidate. Each
candidate carries a structural `discovery_pass`; treat `risk_discovery` candidates as dedicated risk
records. Boundary Review quality flags are cumulative: Python merges them with yours, so omitting a
Boundary flag from your item never clears it. A number,
nickname or ordinal attached to an item that the interval itself presents, contrasts or demonstrates is
recoverable even if it was coined earlier, including when it appears only in the conclusion; do not flag
it or extend the interval to its coinage. Flag a dependency only when the opening or the conclusion's
instruction depends on a definition, sample, step or comparison half that the interval never presents.
Audibility checks (asking or answering whether someone can hear), connection lag and network or playback
trouble are padding at an edge of the interval. Inside the interval, between on-topic cues, they are
`material_interruption`; a padding flag may be added alongside that interior flag, never used instead
of it. Inside the interval, calls to action and platform prompts (requests for fan badges, follows,
likes or gifts, homepage plugs, requests for viewers to join on microphone), chat reading and
presentation troubleshooting (waiting for a pen or colour, glare, asking whether viewers can see) are
`material_interruption` too, even when brief, and are subtracted when testing the Profile duration
minimum; only a single-cue audience thanks, greeting or name call-out that the speaker passes over
without leaving the topic, including a single-cue thanks for a gift or follow, is exempt, and writing
the taught term on the board is part of the lesson.
A speaker's brief explanation of their own equipment or of how listeners hear better, attached
to an immediate live example, is part of the demonstration: neither padding nor an interruption.
Trimming an edge never resolves a dependency the trimmed cue disclosed: a clip holding only the second
half of a before/after comparison is context-dependent. The Profile minimum must be met by on-topic
content, not by chat, calls to action, greetings or device talk.

Python enforces the merged quality flags in two classes. Gated flags (Python forces `blocked`):
`padded_with_irrelevant_content`, `sales_or_cta_padding`, `device_or_waiting_padding`,
`material_interruption`, `topic_switch_inside`, `topic_not_closed`, `asr_uncertain_blocks_meaning`.
Advisory flags (Python only forbids `selected`): `context_dependent_opening`,
`missing_required_prior_steps`, `source_title_mismatch`. An advisory flag alone never forces `blocked`.
When you agree that it applies, route the candidate by the rules above (a missing required premise is
`blocked` or `rejected`). When you judge a candidate whose only merged flags are advisory to be coherent
and self-contained, use `manual_review` and state the disagreement in `review_reason`; do not block it
merely because the flag exists.

Python also persists a Discovery gated flag that Boundary Review did not resolve by trimming an edge,
but only a structural one (`material_interruption`, `topic_switch_inside`, `topic_not_closed`,
`asr_uncertain_blocks_meaning`). Boundary Review also resolves a Discovery `topic_not_closed` without
trimming when its own item clears that flag and attests a complete opening, ending, central objective
and shortest boundary. Discovery padding flags (`padded_with_irrelevant_content`,
`sales_or_cta_padding`, `device_or_waiting_padding`) are not persisted: they follow Boundary Review, the
edge authority. When Boundary Review cleared a Discovery padding flag, judge the candidate on its merits
and the merged flags; do not block it merely because Discovery raised that padding flag.

For a choice or expression lesson, the opening enumeration of available techniques and the explanation
that their difference is small are required premises for a later “choose by intended sound” conclusion.
Do not retain a shorter duplicate that begins only at the conclusion and drops those premises. For a
live diagnosis, sung or spoken example cues immediately preceding the first diagnostic statement are the
evaluated sample, starting at its first transcribed cue unless transcribed cues inside the interval show
that an earlier untranscribed sample is the one evaluated (earlier invitations and song or exercise
negotiation are setup; a participant's own question about their voice that the diagnosis answers is a
premise); a candidate starting at the diagnosis is incomplete when another candidate includes that
sample. Retain the complete sample-to-diagnosis-to-correction-to-closing version even when it is longer.
Do not mark a coherent correction chain as meaning-blocked merely because a lyric, song name or isolated
technique word is mistranscribed while the method and outcome remain understandable.

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
