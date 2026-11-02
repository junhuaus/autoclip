# Stage: Profile Global Review Audit

Audit the supplied `initial_global_review` against the complete same-Profile candidate pool, boundary
facts, subtitles, context and evidence. Return only a compact `replacements` array containing the full
review item for each candidate whose initial decision must change. Omit every correct review item from
`replacements`; Python retains it unchanged. Candidate IDs in `replacements` must be unique and already
exist in the initial review. Also return a concise non-empty `audit_reason`. You may correct scores,
statuses, quality/risk tags and same-Profile duplicate references, but may not create candidates or change
Boundary intervals. Never deduplicate across Profiles.

The initial review may have been produced in bounded partitions. Treat all supplied candidates as one
same-Profile pool and perform cross-partition semantic deduplication here; partition membership is never
a reason to retain a true duplicate.

For every duplicate cluster, actively try to falsify the chosen representative. A representative is
invalid if another version supplies a required initiating premise, compared-term definition, evaluated
singing/speaking sample, correction/retry, before-after evidence, final recommendation or closing
confirmation that it omits. “Shortest” means shortest independently complete version, never merely the
fewest cues. Retain the complete version and mark narrower incomplete versions rejected duplicates.

Pay special attention to:

- expression/choice lessons whose conclusion depends on an earlier enumeration and explanation of the
  available techniques;
- nested expression/choice candidates where a later recap repeats the technique names but omits their
  first local step/chapter introduction and defining property. Retain the version with the first local
  introduction, enumeration and definition; minimum duration does not make a recap-only opening complete;
- focused comparisons hidden inside a broader taxonomy;
- focused warnings that start at a direct technique/question, explain the reason and close with an
  exception or applicability limit; an earlier general foundation list is not automatically a required
  premise, and the focused lesson is not a duplicate of the broader foundation lesson;
- nested candidates that share an ending where the later start is an explicit, self-contained question
  or technique introduction. If that later candidate contains the question, causal answer and closing
  exception/applicability limit, prefer it as the shortest complete representative. Do not require or
  prefer pre-question foundation merely because it adds useful pedagogy. Earlier material is required
  only when the answer explicitly depends on an otherwise undefined term, numbered step or comparison;
- natural later chapters in numbered curricula that define their own techniques and conclusion;
- multi-step units that explicitly restart with a local first-step statement such as “step one is X”.
  Treat that restart as the initiating premise for the enumerated unit even when earlier context contains
  a fuller general definition of X. Do not require the earlier definition when the retained unit names
  the first step, explains the role of the included steps, demonstrates the method and reaches its own
  conclusion. This rule does not make a recap-only comparison complete: a later list of technique names
  still needs the local defining property on which its comparison or choice depends;
- later chapters incorrectly marked as missing prior steps merely because they refer to an earlier
  technique. When the chapter locally names that technique, states its role and explains its combination
  with the current step, the reference is self-contained rather than a missing prerequisite. When you
  correct that error, do not repeat `missing_required_prior_steps` in your replacement item;
  status, flags and reason must agree with the merged flags described below;
- misapplied `context_dependent_opening`: use it only when the opening's meaning cannot be recovered
  from cues inside the interval. A category, type or ordinal label that the clip itself contrasts,
  explains or demonstrates is not a dependency; the speaker's immediate application or consequence of
  the same concept is the payoff, and a new concept after it is outside the candidate. A number,
  nickname or ordinal attached to an item that the interval itself presents, contrasts or demonstrates
  is recoverable even if it was coined earlier, including when it appears only in the conclusion; do not
  flag it or extend the interval to its coinage. Flag a dependency only when the opening or the
  conclusion's instruction depends on a definition, sample, step or comparison half that the interval
  never presents;
- audibility checks (asking or answering whether someone can hear), connection lag, or network or
  playback trouble left in a kept interval: at an edge they are padding; inside the interval, between
  on-topic cues, they are `material_interruption`, and a padding flag may be added alongside that
  interior flag, never used instead of it; a speaker's brief explanation of their own equipment or of
  how listeners hear better, attached to an immediate live example, is part of the demonstration,
  neither padding nor an interruption; trimming an edge never resolves a dependency the trimmed cue
  disclosed; a clip holding only the second half of a before/after comparison is context-dependent;
- live diagnosis loops where singing immediately before the diagnosis is the evaluated sample;
- risk chains whose opening question/category count or final qualification was trimmed;
- coherent lessons overblocked because a lyric, song name or isolated term is mistranscribed even though
  the central method and outcome remain understandable.

Risk-bearing coherent candidates normally remain `manual_review`; material interruption, padding,
missing premise, unclosed topic or truly meaning-blocking ASR must be `blocked` or `rejected`. Preserve
all cumulative risk evidence. A candidate that uniquely preserves a risk question, category count or
cumulative risk evidence must be `manual_review` or `blocked`, never `rejected`; it may be rejected only
when another `manual_review` or `blocked` representative preserves that same evidence. Do not let a
narrower later diagnosis replace an overview-to-first-category risk chain. Do not change a correct
initial decision merely to manufacture quantity.
An empty `replacements` array is valid only when the initial review has no completeness or representative
error after this audit.

Boundary Review quality flags are cumulative: Python merges them with the review item's flags. Removing
a flag from a replacement item never clears a Boundary flag, so choose a status consistent with the
merged flags.

Python enforces the merged quality flags in two classes. Gated flags (Python forces `blocked`):
`padded_with_irrelevant_content`, `sales_or_cta_padding`, `device_or_waiting_padding`,
`material_interruption`, `topic_switch_inside`, `topic_not_closed`, `asr_uncertain_blocks_meaning`.
Advisory flags (Python only forbids `selected`): `context_dependent_opening`,
`missing_required_prior_steps`, `source_title_mismatch`. An advisory flag alone never forces `blocked`.
When you judge a candidate whose only merged flags are advisory to be coherent and self-contained, keep
or make it `manual_review` and state the disagreement in `review_reason`; do not block it merely because
the flag exists.

Listed pairs. The payload's `audit_pairs` lists, from the initial review, same-Profile pairs of
`selected`/`manual_review` candidates in three kinds (`pair_kind`):

- `nested`: the two share a start or end cue so that one contains the other (`outer_candidate_id` is
  the containing candidate);
- `overlap`: neither contains the other, but they share at least half of the shorter candidate's
  duration (`outer_candidate_id` is the earlier-starting candidate);
- `containment`: one lies strictly inside the other and is a near-copy of it (`outer_candidate_id` is
  the containing candidate).

Return `nested_pair_decisions` with exactly one entry for each listed pair of any kind and no other
entries; return an empty array when `audit_pairs` is empty. Decide each pair on its content:
containment, a shared edge or overlap alone never establishes duplication. Python re-lists pairs after
applying your replacements, so also decide every pair your replacements create (for example by
promoting a candidate).

A pair whose precomputed `near_identical` field is true (Python sets it when the two end within the
boundary tolerance, when an `overlap` pair shares at least 90% of the shorter candidate, or when the
inner candidate of a `containment` pair lasts at least 90% of the outer one) is nearly the same media: do not keep both `selected`/`manual_review`. Decide `duplicate`
and keep one representative, unless you reject or block a member on its own merits. When an `overlap`
or `containment` pair is `duplicate`, the representative must stay `selected` or `manual_review`.

Each candidate's `persisted_discovery_gated_flags` lists the structural Discovery gated flags
(`material_interruption`, `topic_switch_inside`, `topic_not_closed`, `asr_uncertain_blocks_meaning`)
that Python will keep in final routing, so a `selected` or `manual_review` candidate with any of them
will be blocked: never choose it as a duplicate representative or keep it as the retained member of a
pair. Discovery padding flags (`padded_with_irrelevant_content`, `sales_or_cta_padding`,
`device_or_waiting_padding`) are never persisted: they follow Boundary Review, the edge authority. Do not
block a candidate, or change its status "to match routing", because Discovery raised a padding flag that
Boundary Review cleared; judge it on its merits and the merged flags.

A candidate with `duplicate_of_candidate_id` must end `rejected` or `blocked`, never `selected` or
`manual_review`; both are non-output. Python routing only downgrades: it blocks `selected` and
`manual_review` candidates that carry gated or persisted flags and never changes a `rejected` row
(except that a rejected `risk_discovery` candidate is kept as `blocked`), so flags never require a
duplicate to be `blocked`. When both members of a listed pair carry
`persisted_discovery_gated_flags`, neither can be the representative: decide `distinct_objective`
without a duplicate reference, and Python blocks both (for a `near_identical` pair, set both to
`blocked` yourself); or, when another candidate without persisted flags serves the same objective,
mark both as duplicates of that representative.

When overlapping or nested versions serve the same objective, keep the shortest independently complete
version. Material that only one version adds beyond the shared objective (chat, waiting, equipment or
playback trouble, another topic) is a reason to reject that version as the duplicate, not to keep it.

- `duplicate`: both serve the same central objective. Prefer the shortest independently complete
  candidate as the representative, and include replacement items so that the other one is `rejected`
  or `blocked` with `duplicate_of_candidate_id` naming the representative.
  When both candidates of a listed pair are duplicates of the same third representative (for example
  in a cluster of three versions of one lesson), the pair is also `duplicate`: each may reference that
  shared representative instead of the other.
- `distinct_objective`: each has its own question, objective or conclusion. Neither may reference the
  other as its duplicate.

Give a concise reason for every decision.
