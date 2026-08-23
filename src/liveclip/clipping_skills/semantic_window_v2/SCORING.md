# Semantic Window Scoring v2

Return the sum of four independently considered dimensions as `score`:

- Viewer value, 0–30: transferable insight, method, explanation or experience.
- Standalone clarity, 0–25: required setup and payoff are present without outside context.
- Interest, 0–25: genuine curiosity, usefulness, tension, emotion or memorable perspective.
- Evidence fidelity and topic purity, 0–20: title is supported and the interval stays coherent.

Calibration:

- `0`: no qualifying topic; include `not_meaningful`.
- `1–50`: filler, private context, generic talk or incomplete thought.
- `51–75`: understandable but ordinary, context-dependent or in need of substantial editing.
- `76–89`: independently clear, useful or interesting, and evidence-faithful.
- `90–100`: unusually distinctive and immediately publishable; use rarely.

Do not inflate a score to pass the threshold. Structural clarity or evidence failure cannot be
cancelled by a strong hook. Prefer the target duration, but never penalize a necessary interval
solely for using more time up to the configured maximum.
