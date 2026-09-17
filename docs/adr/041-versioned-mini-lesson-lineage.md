# ADR041: Versioned mini-lesson source lineage and risk evidence

Status: implemented, formally accepted and integrated in 20260913T072557Z-1fd20958; see SD-1B accepted report.
Date: 2026-09-12 PDT. Owner: main orchestrator and its one isolated integration Coder.
Baseline: accepted SD-1A eb507a42, formal195929 DONE; original27code/config publication477b.

## Decision and purpose

Every original Discovery proposal must have all of its paths through Topic Chains,
natural units and actual final outcomes recorded. Risks must retain source identity and
cue evidence through regeneration and boundary repair. Semantic judgments belong to
models; Python checks structured claims,reference scope,completeness and consistency.

Introduce a separate `semantic-v5-lineage-v1` contract, V5 lineage wire models and new
`semantic_topic_chain_v2` Discovery,Topic Chain and Boundary prompt resources. Keep the
accepted `semantic-v4-quality-v2` quality contract. Historical v2–v8 configs,V4 models,
V1 prompts,cache keys and Deliveries are frozen. This package changes no runtime default
or dispatch. The following SD-1B-B package will freeze explicit config/cache/stage identity
before integrating the contract; config9 is reserved,not implemented by this decision.

## Original sources and structural routing

A V5 Discovery candidate carries the existing proposal fields plus typed `risks`,replacing
V4's free-string `risk_flags`. Each risk has a safe local risk ID,an existing RiskFlagV4,
nonempty reason and known nonempty cue evidence. Do not classify or convert historical
free strings. Batch namespacing preserves all candidate,fragment,window,risk and related
references without collisions; include the owning proposal in risk identity. A trusted
attributed risk record adds original candidate,batch,window and fragment provenance.
Model-generated identifiers remain data and never become executable paths or commands.

Route every original proposal to every chain intersecting its declared fragment IDs.
All referenced fragments/chains must exist,IDs must be unique,and every original has a
route. This is reference routing,not semantic matching. Include originals not suggested
for mini_lesson; their model-authored rejection is still a terminal path.

For each expected source/chain pair,the chain model returns exactly one disposition:
nonempty unique derived unit IDs OR an explicit rejection reason with known cue evidence.
Every derived unit has `origin_kind=derived|chain_new`,explicit original source IDs and
nonempty origin reason. Derived units require at least one source; chain_new requires
none and uses its existing known candidate evidence to support the new proposal.
Forward disposition references and unit reverse origins must match exactly. Unknown,
missing,duplicate,cross-chain or inconsistent edges fail. Preserve every chain-to-unit
edge; never retain only candidates[0]. Existing chain/natural-split validation still applies.

A rejected source/chain pair can coexist with successful paths for the same original in
other chains. A chain with only fragments and no original proposal may generate chain_new
units. Zero sources/fragments/chains/units is legitimate; do not manufacture candidates.

## Source risks and the final Boundary span

Boundary receives immutable attributed risks from all declared origins/participating chain
and from every original risk whose evidence intersects the entire allowed Boundary context.
Do not filter solely by unit origin IDs or its pre-repair interval. Include risks needed
to assess chain_new units and possible boundary expansion. Source risk IDs and their
original evidence stay unchanged in payloads,repair,cache and final lineage records.

Boundary supplies exactly one treatment for every provided risk ID,with reason and known
cue evidence. Unknown,missing and repeated risk IDs fail. Treatments:

- applies: retain the source's typed flag in the model-provided Boundary risk_flags.
- uncertain: retain that flag and require the model-provided sensitivity_review flag;
  the existing manual/blocked gate then applies. Never silently add flags.
- outside_final_span: all original risk evidence is outside the actual final span.
- resolved_in_context: require model-authored reason and known evidence inside the final
  span. Code validates references and scope,not whether the semantic reasoning is true.
- dropped_candidate: only for content_decision=drop; every provided risk is explicitly
  accounted for and no nonexistent final span is invented. Non-drop forbids this treatment.

Treatments are evaluated against the FINAL proposed span,including a repair. A changed
span cannot reuse stale outside/resolved accounting. Apply the existing current quality,
reference,duration,content and risk gates without relaxing them. Additional Boundary risk
flags remain valid; Global still unions Boundary/Global flags so retained risk cannot vanish.
Several risk IDs can share one typed flag; check each ID independently.

## Final ledger and counts

Build a typed V5 ledger from validated original proposals,chains,source dispositions,units,
risk authorities/treatments and the actual final selected/manual/blocked/rejected/
top_n_excluded partition. Every unit appears exactly once in that partition. Expand every
source→chain→unit path; explicitly rejected pairs end without a unit. Every original gets
one source record with all terminal paths. Record chain_new unit outcomes separately.
Reject incomplete or unknown final partitions rather than guessing a disposition.

Retain explicitly typed V5 originals/units/risk records in serialization. Do not assume
Pydantic serialization through V4-typed fields will retain subclass additions. Count
original Discovery proposals independently from derived units and terminal paths. Mixed
outcomes and many-to-many graphs are valid; a valid empty ledger reports explicit zeros.
Do not rewrite historical V4 statistics to make old artifacts look like the new contract.

## Validation, errors and package boundary

Pure helpers build authority payloads and collect all available new-contract violations,
including determinable partial-JSON contradictions alongside Schema errors. No100/200-error
cap or first-error-only shortcut; no best-effort model result,fallback or implicit semantic
repair. Provider integration remains SD-1B-B and must use SD-1A's sole repair,audit and
pre-call budget mechanisms. The pure contract cannot grant extra model calls.

SD-1B-A adds pure models/validators/builders,new immutable prompts/schemas and tests only.
No application config,provider,cache,stage,entrypoint,Make,lock or control-plane edits.
Main freezes this contract and explicitly delegates generation of the four named new
schemas to the single isolated Coder; ownership and final integration remain with main.
The formal task specifies exact file ownership and required Runner lint/test.

SD-1B-B connects the new contract to actual mini runs and demonstrates a synthetic full
flow with complete ledger and risk carry-through. SD-1B is incomplete until that package
passes new same-source gates. Real/paid content acceptance remains SD-6.

Acceptance update2026-09-13: [combined report](../verification/stable-delivery-sd1b-accepted-2026-09-13.md).
The preceding pending/diagnostic language records the decision at that historical point;
current implementation is integrated. Real content/model/audio/hardware acceptance remains SD-6.
