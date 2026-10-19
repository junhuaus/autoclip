# Stage: Discovery Coverage Audit

Independently re-read every supplied cue and audit the existing Discovery candidates for recall and
natural-boundary omissions. This is still Discovery: do not score, Top-N, globally deduplicate, hide
risk or decide publication status. Emit only additional candidates that recover an omitted complete
unit or a materially better semantic boundary; do not copy an existing interval unchanged.

A contained unit is not automatically a duplicate. Emit the contained version when it has its own
question, teaching objective and conclusion, satisfies this Profile's duration contract, and the
existing superset spends material time on a broader prerequisite or a different lesson. In particular,
a focused comparison may coexist with a longer taxonomy that contains it. Leave the later same-Profile
semantic deduplication decision to Global Review.

Pay special attention to: the premise or definition removed from a short comparison; a complete
numbered multi-step curriculum represented only by later sub-lessons; a live diagnosis missing its
evaluated sample, before/after correction or closing advice; and a risk claim chain missing its opening
enumeration or one of its analyzed categories. Apply all Profile duration, ownership, boundary and risk
rules from the main Discovery contract.

Treat a missing boundary premise or conclusion as material even when it is only a few cues long. For a
demonstration, recover the instruction or contrast immediately before the example and the explanatory
payoff immediately after it. For a risk enumeration, walk left to the question or opening claim that
defines the list, then include every analyzed category and the final recommendation; a later single
diagnosis is not an adequate substitute for the complete claim chain. If an additional idea cannot form
a legal-duration interval on real cue boundaries without unrelated padding, omit it instead of expanding
it with greetings, CTA, sales, waiting, device setup or another topic.

Risk recall is an exception to publication-worthiness, not to cue or duration truth. When a continuous
legal-duration claim chain contains medical/health/absolute/sensitivity risk, emit it even if unavoidable
internal sales, greeting, device or topic interruptions mean it will later be `blocked`. Attach the
corresponding quality flags and risk evidence; never omit the chain merely because it is unsuitable for
automatic publication. Do not add unrelated material just to make a shorter risk statement reach the
Profile minimum.

Every new `candidate_id` must start with `audit_` and be unique from every ID listed in
`existing_candidates`. Keep the exact requested Profile and `source_window_id`.

The deterministic ownership rule is mandatory on this audit pass. Read the supplied
`ownership_interval` literally: every emitted candidate's real start cue timestamp must be greater than
or equal to `ownership_interval.start_ms` and strictly less than `ownership_interval.end_ms`. The wider
context is evidence only. If an omitted unit starts outside that half-open interval, emit nothing for it
from this window and leave it to the window that owns its start. Never move or truncate a candidate's
semantic start merely to force it into this window's ownership interval.
