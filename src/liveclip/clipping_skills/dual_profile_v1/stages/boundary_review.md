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
acknowledgement such as “OK”; do not stop one cue before closure. The speaker's brief explanation of
their own equipment, microphone distance or placement, or of why moving closer helps listeners hear, is
part of the demonstration and not padding when it is attached to an immediate live vocal example.
Re-check and preserve every applicable risk under the main contract, including non-blocking ASR
uncertainty and sung lyrics.

“Shortest complete” still includes definitions and setup that the conclusion depends on. Do not trim a
mixed-voice comparison to its first summary sentence when earlier cues define the compared techniques.
When the candidate promises a comparison or choice among named techniques, retain the first local
introduction of those techniques and their defining property. A later sentence that merely repeats the
names or says their difference is small does not replace the earlier step label, enumeration and
definition. The repaired opening must support both the comparison premise and the eventual choice.
For a numbered curriculum keep the earliest included step label; for a live diagnosis keep the first
meaningful evaluated sample and stop at the final recommendation/closing, not at later unrelated chat.
A live diagnosis starts at the first transcribed cue of the evaluated sample: invitations and song or
exercise selection or negotiation before it are setup to trim, while a participant's own question about
their voice that the diagnosis answers, plus the immediate go-ahead, is a premise to keep. An edge may
extend into an untranscribed gap only when transcribed cues inside the interval show that the sample in
that gap is the one being evaluated; otherwise start at the first transcribed cue of the sample, and
never extend across setup on the assumption that an untranscribed gap holds audio.
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

For a numbered later chapter, an ordinal label is its independent premise when the chapter itself
defines and explains the included steps. Do not add `missing_required_prior_steps` solely because it
says “step five” or “step six”. For a focused comparison, remove a separable earlier taxonomy or general
overview when the comparison itself introduces all compared items and remains over the Profile minimum.
For a live diagnosis, do not stop after the first recommendation if the same uninterrupted exchange
continues with a retry, before/after evidence, causal distinction, or final confirmation that closes the
correction. An imperfectly transcribed lyric, song name or isolated vocal term does not block meaning
when the evaluated sample, diagnosis, correction and observed outcome remain understandable as a chain.
`material_interruption` requires unrelated semantic content that actually breaks the teaching or claim
logic; silence, an ASR gap, a vocal demonstration, a self-correction, writing the taught term on the
board, a single-cue audience thanks, greeting or name call-out that the speaker passes over without
leaving the topic, or the speaker's brief equipment or listening explanation attached to an immediate
live example is not by itself an interruption.
Interior audibility checks, connection lag and playback trouble, as described below, are such unrelated
content and count as `material_interruption`. So are interior calls to action and platform prompts (fan
badges, follows, likes, homepage plugs, gifts, requests for viewers to join on microphone), chat reading
and presentation troubleshooting (waiting for a pen or colour, glare, asking whether viewers can see),
even when brief; the single-cue exemption above never covers them.
`device_or_waiting_padding` requires explicit device/network/waiting content. An audibility check means
asking or answering whether someone can hear. Audibility checks, connection or network talk, connection
lag, switching networks and trouble playing back a recording are `device_or_waiting_padding` at an edge
of the interval. Inside the interval, between on-topic cues, the same content is `material_interruption`;
`device_or_waiting_padding` may be added alongside that interior flag, never used instead of it. A
speaker explaining how listeners can hear better is not an audibility check, and a voice that sticks,
cracks or lags, described as part of the teaching, is not connection lag.

Edge audit. Inspect the first and last cues of the interval separately. A topic announcement, a
reference to another video, post or session, and a remark that the speaker is resuming, continuing “as I
was saying” or going “step by step” are setup, not premises: they do not define a term, ask the question
the clip answers or state a step of the method. Calls to action, purchase/follow/like prompts, device,
microphone, network or waiting talk, chat reading and filler at either edge are padding whether or not
they are needed to reach the Profile minimum; the only exception is the speaker's brief equipment or
listening explanation described above. A reference to another video or post is setup when the kept
interval defines and demonstrates its own method. Trim such edge material when the remaining interval is
still within the Profile duration and independently complete. Otherwise keep the interval and name the
problem with `sales_or_cta_padding`, `device_or_waiting_padding` or `padded_with_irrelevant_content`;
unresolved padding flags are enforced deterministically. This edge audit never removes a
compared-technique introduction, definition or step label that the comparison or conclusion depends on.

A candidate whose central objective is the speaker's own credentials, qualifications, pricing, course
sales or schedule is not a teaching or highlight unit, even when no explicit purchase prompt appears. Do
not trim or repair it into one, and do not treat clearing a padding flag as resolving it: set
`central_objective_complete` to false, keep any evidenced `commercial_claim`, and state in
`review_reason` that its objective is self-promotion so Global Review rejects it. A brief credential or
course mention inside a real lesson does not make that lesson self-promotion.

Trimming an edge cue never resolves a dependency that the cue disclosed. If the kept interval still
relies on a sample, step or comparison half outside it, keep `context_dependent_opening` or
`missing_required_prior_steps`. A clip containing only the second half of a before/after comparison is
context-dependent.
A review item that keeps `context_dependent_opening` must set `opening_complete` to false; if the
opening is complete, do not keep that flag.

The Profile minimum must be met by on-topic content. If removing interior material that meets the
`material_interruption` threshold above (audience chat, comment reading, calls to action, platform
prompts, presentation troubleshooting or device talk), or edge setup kept only for duration, would leave
a clip that no longer satisfies the Profile duration minimum, flag `padded_with_irrelevant_content`. For
such interior material, flag `padded_with_irrelevant_content` alongside `material_interruption` (or
`topic_switch_inside`), never instead of it. Only a single-cue audience thanks, greeting or name
call-out that the speaker passes over without leaving the topic is neither flag and is not removed in
this test; calls to action, platform prompts, chat reading and presentation troubleshooting are removed
in it even when brief. A closing acknowledgement or address to the audience is neither padding nor
subtracted from the duration in this test.

Use `context_dependent_opening` only when the opening's meaning cannot be recovered from cues inside the
interval. A category, type or ordinal label that the clip itself contrasts, explains or demonstrates is
not a dependency on earlier content. At the ending, include the speaker's immediate application or
consequence of the same concept as its payoff, and stop before a new concept begins. A number, nickname
or ordinal attached to an item that the interval itself presents, contrasts or demonstrates is
recoverable even if it was coined earlier, including when it appears only in the conclusion; do not flag
it or extend the interval to its coinage. Flag a dependency only when the opening or the conclusion's
instruction depends on a definition, sample, step or comparison half that the interval never presents.
