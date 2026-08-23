# Semantic Window Scoring v1

Score the selected interval on four independent dimensions and return their sum as the 0–100
`score`. Do not mention the arithmetic in the title, hook, or reason.

- Viewer value, 0–30: Does an unfamiliar viewer gain a specific insight, method, explanation,
  experience, or memorable perspective that transfers beyond this livestream participant?
- Standalone clarity, 0–25: Can the interval be understood without earlier class/session/person
  context, and does it contain the setup needed for its payoff?
- Interest, 0–25: Is there genuine curiosity, tension, surprise, usefulness, emotion, or a strong
  question/payoff—not merely energetic delivery or praise?
- Evidence fidelity and topic purity, 0–20: Is the title fully supported, and does the interval
  stay on one coherent topic without unrelated setup, trailing talk, or inflated claims?

Calibration:

- `0`: no qualifying topic; include `not_meaningful`.
- `1–50`: filler, administrative/private context, generic talk, incomplete setup/payoff, or
  weak viewer value.
- `51–75`: understandable but ordinary, narrow, context-dependent, weakly interesting, or in
  need of substantial editing. The application does not retain these by default.
- `76–89`: independently understandable, clearly useful or interesting, evidence-faithful,
  and suitable for a short-video viewer.
- `90–100`: unusually distinctive and immediately publishable; use rarely.

A structural failure in standalone clarity or evidence fidelity cannot be cancelled out by a
high hook or value score. Never inflate a score to pass the default threshold. A participant-
specific teacher comment with no transferable lesson should normally score 75 or below.
