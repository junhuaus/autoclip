# Highlight Agent Skill v2 — iteration 2 frozen design

Status: frozen before any iteration-2 generator output; no such output exists.

This directory is a new immutable research namespace. It may read the three
frozen development inputs and the frozen v1 baseline Skill from iteration 1,
but it must never overwrite iteration-1 experiments, Judge runs, viewers, or
reports. The three sources are now exposed development data. A passing result
can advance only to a new multi-genre holdout; it cannot change production.

## Objective

Retain free Topic discovery and exact evidence binding while correcting the
iteration-1 failure modes: weak portfolio precision, low editorial readiness,
loss of source voice, low repeat stability, and excessive model-call topology.

The frozen normal topology is:

```text
all frozen candidates
  -> Stage A CombinedDiscovery (one model Call)
  -> Stage B deterministic quality-adaptive selection
  -> Stage C SelectedCopy (one model Call; skipped for an empty portfolio)
  -> deterministic evidence, accounting, safety, and receipt Gates
```

There are at most two normal model Calls per Pipeline. A Pipeline may consume at
most one model repair in total, and never more than one repair at either Stage.
Pre-model infrastructure failures are separately bounded and do not consume
model-attempt budget. Unsafe tool events,
unknown IDs, path/hash drift, and cross-candidate evidence fail permanently.
Every attempted model turn, including a failed repair, must be completion-bound
with elapsed-time and usage metadata so the efficiency gate uses total cost.

## Stage A — CombinedDiscovery

One response must contain:

- an assessment for every input candidate exactly once and in input order;
- a freely discovered Topic inventory covering every assessable candidate
  exactly once and no unusable candidate;
- exactly one `core` member per Topic, with other members classified only as
  `same_claim` or materially distinct `alternate_angle`.

Candidate assessment keeps independent concepts separate:

- `disposition`: `assessable` or `unusable`;
- `standalone_publishability`: `ready` or `not_ready`;
- generic publishability blockers such as missing premise/question, unfinished
  payoff, unreliable ASR, essential missing visuals, or unsafe/private content;
- `editorial_value`: `distinctive`, `solid`, `thin`, or `null` for unusable;
- five anchored 0–4 atomic scores: content value, hook strength, standalone
  completeness, evidence fidelity, and editorial utility;
- assessment confidence plus evidence/content-risk flags.

The model never returns a Topic ID, total, rank, timestamp, path, command, or
selection decision. Topic identity, time, score, rank, and selection remain
deterministic. The Stage-A candidate count is at most 60 and its canonical
payload is at most 128 KiB. Oversize input fails closed and is never silently
split into a third normal model Call.

## Stage B — deterministic selection

The five atomic weights stay 30/20/20/15/15. Interval IoU remains 0.45 and
normalized text Jaccard remains 0.65.

A base-qualified candidate must satisfy all of:

- assessable and standalone-publishable `ready`, with no blocker;
- completeness and evidence fidelity at least 3;
- editorial value `solid` or `distinctive`;
- content value, hook strength, and editorial utility at least 2;
- deterministic weighted score at least 65/100.

Selection first takes the best non-conflicting qualified representative from
each Topic, then only true `alternate_angle` members. `same_claim` is never a
second selection from one Topic. Ranking uses weighted score, frozen upstream
rule score, source start, then candidate ID.

The desired minimum is eight and the maximum is twelve. If the frozen
qualification, Topic-distinctness, and overlap Gates leave fewer than eight
selectable candidates, the result stays underfilled and records
`underfilled_due_to_quality=true`; “quality” in this field names the complete
frozen quality/diversity Gate, and thresholds are never relaxed to fill a quota.
Positions 9–12 require `editorial_value=distinctive`, all five atomic scores at
least 3, a new Topic or material alternate angle, and no overlap. Thus extra
quantity must be earned by uniformly strong evidence.

## Stage C — SelectedCopy

Stage C preserves source rhetoric instead of forcing a third-person summary.
For every selected candidate in deterministic order it returns:

- editor-facing title and hook;
- an `evidence_quote` whose normalized text is a continuous substring of that
  candidate and contains at least eight content characters;
- an extractive `source_sentence` whose normalized text is a continuous
  substring of the evidence quote and also contains at least eight content characters;
- a concise script description and grounded keywords.

For both nested evidence Gates, matching may ignore only punctuation, spacing,
Unicode width/case, and normalization-safe combining forms. The returned text
must not change person, modality, negation, question form, condition, number, or
conclusion. ASR damage is rejected in Stage A rather than guessed away here. The
deterministic selection receipt supplies the selection reason.

## Development evaluation

The primary matrix remains three unique source hashes, two repeats, and two
fresh opaque arms: frozen v1 and iteration 2, both `gpt-5.6-sol / medium`.
Candidate order remains fixed, so repeats measure sampling stability only.
Sol High is disabled. The experiment therefore contains 12 Pipelines, six v1
normal Calls, and at most twelve iteration-2 normal Calls before repair.

Two anonymous Judges (`gpt-5.6-sol / max` and `gpt-5.6-terra / max`) each assess
four systems per source. Exactly six Judge Calls are planned. System order is
counterbalanced between Judges, while each system's highlight order is retained
so portfolio coherence is observable. Private arm/repeat mapping remains sealed
until all 6/6 Judge receipts are complete. Human review is frozen as
diagnostic-not-required for this development run, with the waiver hash committed
before generation; it cannot be promoted to a post-hoc human pass.

Every highlight-level and system-level 0–4 dimension has an explicit frozen
anchor. The invalid per-output subjective `stability_x4` construct is replaced by
`portfolio_coherence_x4`; repeat stability is computed only after unblinding via
candidate Jaccard and interval F1. Judge semantic-opportunity coverage is named
and reported separately from deterministic relative selected-union candidate
coverage. Quality aggregation uses exact rational arithmetic without per-system
integer flooring; display rounding is `ROUND_HALF_UP` to three decimals and is
never used by a gate.

## Frozen development gates

Structural, accounting, safety, receipt, and anonymity gates must pass 100%.
Iteration 2 must also satisfy all of:

- zero outward exact-quote/source-sentence failures;
- dual-Judge source-first quality delta versus fresh v1 at least -2/100;
- precision and editorial-readiness deltas each at least -2/100 and absolute
  iteration-2 values each at least 75/100;
- worst unique-source quality delta at least -5/100;
- candidate Jaccard and interval F1 each no worse than v1 by more than 0.05;
- source-first completion-bound elapsed-time and reported-token ratios each at
  most 3x: total the two repeats within each unique source/arm, compute that
  source's iteration-2/fresh-v1 ratio, then equal-macro-average source ratios;
- at most two normal model Calls per iteration-2 Pipeline.

An underfilled iteration-2 portfolio remains valid product output but fails this
development advancement gate. Mean absolute dual-Judge Pipeline-score difference
must be at most 10 points, and every source/arm difference must be at most 20;
exceeding either threshold makes the run inconclusive. No third Judge may be
added after observing disagreement.

Judge disagreement is reported, not repaired with an unplanned third Judge.
Any incomplete or inconclusive hard gate rejects advancement. Passing all gates
means only `advance_iteration2_to_frozen_holdout`. Other terminal states are
`reject_iteration2` and `inconclusive_iteration2`. Production remains unchanged.

The future holdout must contain at least six source hashes across at least three
content genres, none used to design this iteration. A failed holdout becomes
development data; another production claim then requires a new holdout.
