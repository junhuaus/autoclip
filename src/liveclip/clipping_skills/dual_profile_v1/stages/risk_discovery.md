# Stage: Independent Risk Discovery

Re-read every supplied cue solely for recall of continuous, legal-duration risk-bearing claim chains.
This pass is independent of teaching-value Discovery: never score, select, deduplicate, or suppress a
candidate because it is unsuitable for publication. Emit every qualifying risk chain independently;
do not assume another Discovery pass already represented it. Same-Profile semantic duplication is a
later Global Review responsibility.

Start at the question, premise or enumeration that defines the risky claim. Include every category the
speaker analyzes and the final diagnosis, treatment, correction, guarantee, percentage or causal
conclusion. A later single diagnosis is incomplete when the speaker introduced multiple conditions. If
unavoidable greetings, sales, device handling or topic interruptions occur inside the continuous chain,
preserve the candidate and flag each interior interruption that breaks the claim logic as
`material_interruption` (or `topic_switch_inside` when another topic starts inside the chain) so Global
Review can route it to `blocked`. Interior content counts as `material_interruption` only when it
actually breaks the teaching or claim logic; a brief audience thanks, greeting, name call-out or
acknowledgement that the speaker passes over without leaving the topic is neither an interruption nor
padding. Padding flags describe edge material only: they may accompany an interior flag but never
replace it. Risk must not disappear merely because the interval cannot auto-publish.

The earliest rhetorical question can define the parent claim even when a brief greeting or audience
acknowledgement appears between that question and the category count. Preserve that question as the
left boundary; do not restart at “two problems”, “first”, or another enumeration answer merely to omit
the intervening greeting. Mark an interruption only when it breaks the claim logic as described above, and
in either case keep the complete question-to-enumeration-to-diagnosis chain.

When an overview enumerates multiple risky conditions and immediately proceeds to detailed diagnosis or
treatment of the first condition, emit a continuous parent candidate spanning the enumeration premise
through that detailed category's conclusion. Do not replace that parent with two disjoint candidates for
the overview and the detail. Narrow sub-candidates may coexist, but they do not make the parent chain
optional.

Every emitted candidate must have at least one evidenced risk tag, satisfy the requested Profile's
duration and ownership rules on real supplied cues, and use a new `candidate_id` beginning with `risk_`.
Do not pad a shorter statement to reach minimum duration, invent a cue, or emit an unrelated non-risk
teaching candidate. Keep the exact requested Profile,
`source_window_id`, evidence cues and cumulative risk tags.
