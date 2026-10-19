## Title behavior

Generate titles only after the candidate boundary and best available subtitle
are stable. Titles are a dedicated output, not the candidate-discovery label.
Create three to five alternatives for an ordinary viewer with no technical
background. Prefer a clear problem, result, contrast, mistake or curiosity gap.
Use natural currently popular vocabulary supplied in Context, but never insert
a trend word that changes the source meaning.

Avoid course-catalog wording, unexplained professional jargon and claims not
supported by exact cues. Prefer `save_title_batch` for up to twelve final
candidates at a time; every batch item stores one primary choice, alternatives,
style labels, separate title scores, rationales and grounding cue IDs in its own
`title_options` Artifact. Use `save_title_options` only for a targeted single
candidate or repair. Title appeal never changes the underlying clip score.
