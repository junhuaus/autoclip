## Boundary and relationship behavior

Begin at the earliest cue needed for a new viewer to understand the point. End
at the first cue that completes the payoff. Do not pad to a minimum with another
topic. Use one continuous source interval unless a future configured Profile
explicitly permits another representation.

Audit openings literally. An opening that says or implies "the first few
steps", "the next step", "these two", "this method", "as I just said", or a
similar backward reference is not standalone unless the required referent is
inside the clip. Expand to the premise when the Profile permits it; otherwise
discard that boundary and look for a later self-contained unit. A conclusion
about categories must include the cue that identifies the relevant categories.
For a diagnosis, include enough original question/performance to make the later
verdict intelligible; do not begin only at the verdict.

Do not treat a backward reference as resolved merely because the clip later
contains a useful exercise. The viewer must learn what the referenced steps,
categories, comparison side or prior claim actually are. For phrases such as
"前三步", "这两个", "刚才那个" or an equivalent dependency, write down the
referent cues during Global Review. If no such cues are inside the candidate,
the opening is incomplete and the candidate must be replaced or classified as
boundary-invalid. A high score cannot cure that defect.

Before fixing an opening, inspect the immediately preceding local cues. A short
orientation sentence, comparison premise or category name remains necessary
even when a pause, song demonstration or ASR gap separates it from the first
detailed explanation. Start at that premise when it establishes what is being
demonstrated; do not start at the first dense sentence merely to improve pace.

Audit endings in the same way. A first improvement is not necessarily the end
of a case when the same participant immediately continues testing or asks why.
Include the comparison, correction result, final qualification and natural
sign-off when they are part of the same teaching loop. Conversely, stop before
the next viewer, sales transition, greeting, CTA, device operation or unrelated
lesson. Never use those items to reach minimum duration.

When adjacent candidates are parts of one teaching structure, inspect their
joint Context. Keep the useful shorter versions and, when a configured Profile
can contain the complete interval, also create a longer variant. Relate variants
through `save_clip_candidate` arguments such as `variant_group_id` and
`source_candidate_ids`.
Containment across Profiles is not duplication.

Use the shortest complete boundary for each Profile. A long variant that joins
two adjacent parts of one teaching structure should begin at the first premise
of that structure, not at an earlier taxonomy, greeting or setup that the
lesson does not need. It should end after the last necessary conclusion, not
after only the first sub-answer. Do not broaden a candidate merely because the
Profile allows more time.

For every proposed long final, test at least one tighter inner interval: remove
each leading setup block and each trailing block in turn and ask whether the
central lesson remains independently complete. If a tighter interval still
contains the premise, all comparison sides and the conclusion while meeting the
Profile duration, save that tighter replacement. Taxonomy, greetings, CTA,
waiting, device talk, unrelated examples and repeated setup are padding even
when they are topically adjacent. Conversely, when a general overview names the
parts that the detailed lesson then teaches, include that overview if omitting
it would make the detailed section's structure or claims unclear.

The six-step vocal lesson around the accepted regression source is an example
of a general rule, not a timestamp rule: separately useful early and late steps
may coexist with one complete lesson when the configured duration permits it.
Never hard-code benchmark timestamps or expected candidate counts.
