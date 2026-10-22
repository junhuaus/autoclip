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
  the same concept is the payoff, and a new concept after it is outside the candidate;
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

Boundary Review quality flags are cumulative: Python merges them with the review item's flags and
enforces every unresolved flag deterministically. Removing a flag from a replacement item never clears a
Boundary flag, so choose a status consistent with the merged flags.

Nested pairs. The payload's `nested_pairs` lists, from the initial review, every same-Profile pair of
`selected`/`manual_review` candidates that share a start or end cue so that one contains the other.
Return `nested_pair_decisions` with exactly one entry for each listed pair and no other entries; return
an empty array when `nested_pairs` is empty. Decide each pair on its content: containment or a shared
edge alone never establishes duplication.

- `duplicate`: both serve the same central objective. Prefer the shortest independently complete
  candidate as the representative, and include replacement items so that the other one is `rejected`
  (a `risk_discovery` candidate may instead be `blocked`) with `duplicate_of_candidate_id` naming the
  representative.
- `distinct_objective`: each has its own question, objective or conclusion. Neither may reference the
  other as its duplicate.

Give a concise reason for every decision.
