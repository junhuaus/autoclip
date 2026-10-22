# Stage: Boundary Review

Review every supplied candidate exactly once using its full transcript plus the supplied before/after
context. The interval may be repaired only to concrete supplied cue IDs. Determine whether its opening
contains all required premises, its ending closes the promised objective, its interior has no material
interruption or topic switch, and the range is the shortest complete interval rather than padded time.
Do not score or deduplicate. Preserve all evidenced risks. Quality problems must be named explicitly,
including missing earlier steps and ASR uncertainty that blocks the method's meaning.

Prefer the first cue that supplies the actual independent premise: keep an initiating question,
numbered-step label or comparison premise, but remove earlier setup once the direct method statement is
self-contained. Keep the final cue that states the comparison or conclusion, including a brief closing
acknowledgement such as “OK”; do not stop one cue before closure. A short device-distance statement is
not padding when it immediately enables the vocal example being judged. Re-check and preserve every
applicable risk under the main contract, including non-blocking ASR uncertainty and sung lyrics.

“Shortest complete” still includes definitions and setup that the conclusion depends on. Do not trim a
mixed-voice comparison to its first summary sentence when earlier cues define the compared techniques.
When the candidate promises a comparison or choice among named techniques, retain the first local
introduction of those techniques and their defining property. A later sentence that merely repeats the
names or says their difference is small does not replace the earlier step label, enumeration and
definition. The repaired opening must support both the comparison premise and the eventual choice.
For a numbered curriculum keep the earliest included step label; for a live diagnosis keep the first
meaningful evaluated sample and stop at the final recommendation/closing, not at later unrelated chat.
Audit both edges cue by cue. A short initiating question, contrast definition, referent, exercise
instruction, or final causal explanation is required content rather than removable setup. Conversely,
when a Discovery superset contains a narrower objective named by its title/summary, remove a separable
earlier lesson only if the remaining interval still exceeds the Profile minimum and is independently
complete. Preserve the last answer/conclusion cue even when the immediately following cue changes topic.
For a risk chain, include the opening question/claim and every enumerated category that the conclusion
purports to diagnose; reviewing only the last category is incomplete.

Do not trim even one cue from a risk candidate's left edge when that cue introduces the risky problem,
names the next diagnosis/category, asks the defining question, or announces how many conditions follow.
Likewise retain the final qualification or conclusion. Each supplied candidate carries a structural
`discovery_pass`. Candidates whose `discovery_pass` is `risk_discovery` were independently recovered for
claim-chain completeness: change their bounds only when a supplied cue is demonstrably outside the
claim chain, never merely to make the clip tighter.

For a `risk_discovery` candidate, Discovery `evidence_cue_ids` attached to medical, diagnosis, health or
sensitivity risks are cumulative risk evidence. Every such evidence cue must remain inside the repaired
interval. The deterministic validator will reject a boundary that trims one away; expand back to include
it instead of deleting or replacing the evidence. For every other candidate, an evidence cue at the
leading or trailing edge may be trimmed when it lies outside the clean, complete interval. Risk tags stay
cumulative for every candidate: never remove one, even when its evidence cue is trimmed.

For a numbered later chapter, an ordinal label is its independent premise when the chapter itself defines
and explains the included steps. Do not add `missing_required_prior_steps` solely because it says “step
five” or “step six”. For a focused comparison, remove a separable earlier taxonomy or general overview
when the comparison itself introduces all compared items and remains over the Profile minimum. For a live
diagnosis, do not stop after the first recommendation if the same uninterrupted exchange continues with
a retry, before/after evidence, causal distinction, or final confirmation that closes the correction.
An imperfectly transcribed lyric, song name or isolated vocal term does not block meaning when the
evaluated sample, diagnosis, correction and observed outcome remain understandable as a chain.
`material_interruption` requires unrelated semantic content that actually breaks the teaching logic;
silence, an ASR gap, a vocal demonstration, a self-correction or a brief functional audio-position note
is not by itself an interruption. `device_or_waiting_padding` requires explicit device/network/waiting
content.

Edge audit. Inspect the first and last cues of the interval separately. A topic announcement, a reference
to another video, post or session, and a remark that the speaker is resuming, continuing “as I was
saying” or going “step by step” are setup, not premises: they do not define a term, ask the question the
clip answers or state a step of the method. Calls to action, purchase/follow/like prompts, device,
microphone, network or waiting talk, chat reading and filler at either edge are padding whether or not
they are needed to reach the Profile minimum; the only exception is the short device-distance statement
described above that immediately enables the judged example. Trim such edge material when the remaining interval is still
within the Profile duration and independently complete. Otherwise keep the interval and name the problem
with `sales_or_cta_padding`, `device_or_waiting_padding` or `padded_with_irrelevant_content`; unresolved
padding flags are enforced deterministically. This edge audit never removes a compared-technique
introduction, definition or step label that the comparison or conclusion depends on.

Use `context_dependent_opening` only when the opening's meaning cannot be recovered from cues inside the
interval. A category, type or ordinal label that the clip itself contrasts, explains or demonstrates is
not a dependency on earlier content. At the ending, include the speaker's immediate application or
consequence of the same concept as its payoff, and stop before a new concept begins.
