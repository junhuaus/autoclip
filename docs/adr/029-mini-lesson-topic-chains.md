# ADR-029: Mini-lesson Topic Chains

Status: accepted

Date: 2026-09-11

## Context

The existing `semantic_windowed` transport is optimized for one continuous 45--90-second highlight.
A complete teaching objective can last 90--300 seconds and cross several 120-second logical windows
and more than one four-window Discovery batch. Enlarging the old maximum would leave every Agent call
with only a partial lesson; a single 180-second boundary review also cannot recover a 270-second unit.
Using time gaps, overlap or transcript similarity to merge these parts would move semantic judgment
into Python and create false joins between adjacent questions.

## Decision

Retain `short_highlight` as the default 45/60/90-second Profile and add the explicit `mini_lesson`
90/180/300-second Profile. The two Profiles have independent candidate generation, scoring, risk
gates and Top-N ceilings and may retain short/long variants from one source topic.

Mini-lesson Discovery keeps the 120-second logical window, 60-second step, four-window batch and
240-second start-ownership contract. In addition to high-recall candidates, it emits per-window
left/right boundary facts and traceable Topic Fragments. An open report on either side schedules one
approximately 180-second Link Review. Only an Agent response with both `same_topic` and
`same_central_objective` joins two Fragments. If that response says the right side remains open, the
next boundary is scheduled, allowing a Chain to span any number of local reviews.

Python assembles the explicit positive-link graph, checks IDs/cues and sends each resulting Topic
Chain to an Agent. It never creates semantic edges from time adjacency, gap duration, overlap,
keywords, punctuation or text similarity. A Chain above 300 seconds must be rejected unless the Agent
identifies one or more natural, independently complete teaching subunits and supplies split evidence.

Each candidate receives its own Boundary Review with local context and one Profile-local Global
Review. The first release accepts one continuous source interval only. Mini-lesson score dimensions
sum deterministically to 100, a total of 75 fails, blocking quality facts cannot be compensated,
structured risk determines automatic/manual/blocked publication, and Top-N runs last. Only automatic
results become EditPlan revisions and FFmpeg work. All other results and every transformation remain
in Schema v4 audit data.

Every Discovery batch, Link Review, Topic Chain, Boundary Review and Profile Global Review uses an
independent immutable cache identity containing source hash, Profile, local subject ID, model and
settings, Prompt hash and Schema version. A failed local output therefore does not require replaying
successful siblings or the full livestream.

## Consequences

Long lessons are reconstructed by a sequence of bounded semantic decisions rather than one full-
transcript call or one overlarge prompt. The design makes calls only where open boundary evidence
requires them and increases call count in exchange for smaller failure domains and complete audit
provenance. Adjacent independent topics remain separate even when their timestamps touch.

Historical Pipeline configs and short-highlight paths remain readable and default to
`short_highlight`. Mini-lesson output is isolated below `output/mini_lessons`. Manual, blocked and
rejected mini lessons have no automatic media output. Multi-interval montage and jump cuts remain a
future, separately named Profile rather than an implicit behavior of `mini_lesson`.
