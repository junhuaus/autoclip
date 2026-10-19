# Profile: mini_lesson

Find direct, continuous teaching units strictly longer than 90,000 ms and no longer than 300,000 ms.
Inspect the complete supplied 600-second transcript context. A valid unit may be a complete lesson,
case, multi-step method, problem-analysis-demonstration-conclusion sequence, or live diagnosis and
correction loop. It must have one central objective and a closed ending. Do not mechanically concatenate
short candidates and do not add unrelated speech to exceed 90 seconds. A related short version is a
legal cross-Profile variant; use a stable semantic `variant_group_id` without suppressing either one.

When a numbered curriculum or method presents several consecutive steps that together fit within the
duration limit, emit the complete multi-step unit as its own candidate even if individual sub-lessons
are also useful. Include the numbered-step introduction, all promised steps and the explicit closing
marker. For a risk-bearing lesson, preserve the complete claim chain: its initial claim or category,
analysis/demonstration and conclusion or instruction. Do not emit only a safer fragment of that chain.

For a consecutive numbered curriculum, start at the earliest numbered step present in the supplied
context and continue through the last step that forms the promised unit; do not start at a later style
example and thereby omit earlier numbered steps. If the speaker announces several risks, problems or
categories, preserve that enumeration premise and all categories that the later analysis claims to
resolve.

A numbered curriculum may also contain natural chapters. A later consecutive chapter is independently
complete when it announces its own step label, defines every technique used in that chapter, demonstrates
or contrasts those techniques, and reaches its own takeaway. Do not mark such a chapter as missing prior
steps merely because its ordinal is not “first”; require earlier steps only when this chapter actually
depends on an unexplained result, exercise or term from them. Keep both the earlier chapter and the later
chapter when each satisfies the Profile contract and has a distinct objective.
