# Atomic scoring

Return five independent 0–4 judgments for each candidate. Do not calculate or
return a total, percentage, rank, threshold decision, or selection outcome.

## Shared scale

- **0 — absent or contradicted:** the quality is missing or evidence points in
  the opposite direction.
- **1 — weak:** a trace exists, but a standalone viewer receives little value.
- **2 — mixed:** usable evidence exists alongside a material weakness.
- **3 — strong:** the dimension is clearly satisfied with only minor weakness.
- **4 — exceptional:** unusually clear, compelling, complete, and useful; use 4
  sparingly.

Score each dimension separately. A strong dimension cannot erase a structural
publishability blocker.

## Dimensions

### `content_value`

Measure the substance a viewer gains.

- 0: no coherent substance.
- 1: filler, generic chatter, procedure without viewer value, or bare reaction.
- 2: understandable but familiar, thin, or weakly supported.
- 3: specific and genuinely useful, interesting, or memorable.
- 4: unusually insightful, consequential, or distinctive in this source.

### `hook_strength`

Measure whether the candidate's own opening and proposition create immediate,
truthful curiosity. Context cannot be counted as if it appears in the clip.

- 0: no understandable or faithful entry.
- 1: slow setup or unclear relevance.
- 2: serviceable opening with moderate curiosity.
- 3: clear promise, tension, surprise, or direct viewer relevance.
- 4: exceptionally immediate and compelling without distortion.

### `standalone_completeness`

Measure whether the candidate itself has enough premise, claim or answer, and
payoff for a viewer encountering it alone.

- 0: unintelligible fragment.
- 1: missing the central premise, question, answer, or conclusion.
- 2: main idea is recoverable but one material component is weak.
- 3: self-contained thought with only minor roughness.
- 4: naturally complete argument, explanation, or story beat.

### `evidence_fidelity`

Measure how confidently candidate text supports the assessed claim without
outside facts or reconstruction.

- 0: contradicts the claim or is unintelligible.
- 1: mostly relies on reconstruction or ambiguous ASR.
- 2: core claim exists but important wording is uncertain.
- 3: clearly supported with only minor uncertainty.
- 4: explicit, precise support with no material extrapolation.

### `editorial_utility`

Measure whether an editor can use the candidate itself as a short-video moment
without inventing substance.

- 0: no publishable unit.
- 1: substantial reconstruction is required.
- 2: usable after meaningful editorial work.
- 3: readily usable with normal copy editing.
- 4: already shaped like a strong, distinctive beat.

The deterministic system later applies weights 30/20/20/15/15. That fact does
not authorize the model to calculate or reveal the total.
