# SD-1B-A: Pure versioned lineage and risk contract

Accepted and integrated in combined formal `20260913T072557Z-1fd20958` on2026-09-13.
See [accepted report](../verification/stable-delivery-sd1b-accepted-2026-09-13.md). Historical diagnostics below remain preserved.

## Purpose and context

A mini-lesson original must remain traceable through every Chain,natural unit and final
outcome,and earlier risks must remain attributable during Boundary repair. This package
establishes the pure contract used by the following runtime integration package. It does
not by itself close the user-visible SD-1B flow or change current pipeline dispatch.

Accepted SD-1A source eb507a42/formal195929 is preserved under
`.loop/development/sd1a-mini-artifacts-20260912/`;27code/config paths and21supporting docs
were published with CAS/backups. Current main docs supersede archived handoffs. Branch
liveclip-v2/loop-engineering,HEAD6009b23859564b2bfdc193eee366afd990b9ef5d remains dirty.
Use a complete isolated clone of accepted source plus current main docs,not HEAD-only
clone or direct Loop on the original data-bearing tree.

## Scope,architecture and ownership

ADR041 freezes semantic-v5-lineage-v1,V5 wire and three semantic_topic_chain_v2 stage
prompts. Quality-v2 and existing V4 structures/validators remain compatibility authorities.
Pure pipeline helpers must not import providers,DB,subprocess or application services.
New prompts use only model-authored semantic decisions; code has no keyword classifier.
One Coder owns the exact task's new module,tests,prompt bundle and four generated schemas.
Main owns this plan,ADR,requirement,STATUS,shared integration and final publication.

No config/default dispatch,cache,provider,stage,entrypoint,legacy schema/prompt,dependency,
Make,Loop policy or real-data change. SD-1B-B follows serially for actual runtime integration.

## Milestones and concrete work

- [x] 2026-09-12: SD-1A acceptance and exact original integration verified3989; original
  loop-doctor c4e9 READY and18optional ASR packages restored at original locked versions.
- [x] 2026-09-12: ADR041 freezes routing,typed risk evidence,final-span accounting and ledger.
- [x] Complete2031-path candidate and14new-file scope frozen under sd1b-contract-20260912;
  setup675b and actual current-root Doctor pass.
- [x] Pure contract implemented in isolated candidates; current490focused tests pass.
  Duplicate risk/chain authority and inverse-edge counterexamples are locally corrected; findings await formal revalidation.
- [x] Fresh Planner/Coder/Reviewer validate the complete corrected contract.
- [x] Fresh Reviewer/Tester and required allowlisted Runner lint/test pass on one snapshot.
- [x] Inspect real generated contract artifacts and inherited current mini/browser output;
  Gateway accepts exact evidence,then trusted original CAS publication.
- [x] Freeze SD-1B-B config/cache/provider/Stage/result integration; keep SD-1B open until done.

## Tests and acceptance

L01 many sources/chains/units and mixed final outcomes; L02 missing/unknown/duplicate/
cross-chain and forward/reverse disagreement; L03 source rejection and chain_new;
L04 zero/manual/blocked/Top-N outcomes; L05 complete typed risk attribution/accounting;
L06 final-span repair/expansion and flag retention; L07 JSON/payload/ledger roundtrip,
no typed serialization loss; L08 historical bytes/identities unchanged; L09 complete
partial-JSON errors including more than200errors; L10 four generated schemas and new
prompt/repair hashes match resources without enabling runtime dispatch.

Tests must use actual strict Pydantic JSON parsing for bad wire examples,not unchecked
model_copy to bypass Schema. All semantic claims remain fixture/model-authored. Assert
actual identities,edges,terminal partitions and serialized risk records,not just counts.

Formal commands are existing lint→make lint and test→make test,required. Local targeted
commands after files exist: `.venv/bin/pytest -q tests/unit/test_semantic_lineage.py
tests/unit/test_semantic_lineage_prompts.py`; diagnostics never replace formal evidence.
Original/accepted snapshots stay read-only during active formal roles and Runner. Every
QA command is requested before execution and appended under a new ID; retain failures.

## Recovery,decisions and risks

No migration or runtime call is introduced. A failed contract load/validation yields
explicit errors,not a guessed graph or risk clearance. Retain source IDs,all errors and
input authority for the next package's sole repair. Never overwrite historical resources.
Keep completed/blocked runs and budgets; exact recorded Coder resume only,no --last.

Risks: silently losing subclass fields,miscounting derived units as Discovery,mapping only
the first unit,clearing risk on a stale span,and treating empty output as missing data.
ADR041 and L01–L10 test these cases. Large legal authorities are never silently truncated;
request budgeting will fail explicitly in SD-2 when needed.

Next unambiguous action: implement the bounded Provider/cache package from exact B12 source
under the sole isolated Coder. Carry all A findings and tests into combined A + B1 gates;
no unaccepted A publication. Then continue B2 actual V9 runtime. See the Provider ExecPlan
for the user-feedback-driven packaging decision and unchanged safety requirements.

## Outcomes

Implemented only in isolated candidate; not yet formally accepted or published. Config9 is reserved only; actual current PipelineRunConfig
remains v8. No real-model,media-content,performance or complete SD-1B claim is made.

## Current evidence and recovery

B11 formal20260913T051023Z-75d5012f naturally BLOCKED05:19:11 after Reviewer FAIL/
two P2 and Tester BLOCKED. Coder made no edits; source11e5b63e. Complete role logs preserved;
outer0549 exit2/520.067s. No Runner/Gateway/publication. All terminal budgets remain intact.

B12 preparationed2c verified2045inherited hashes/original431CAS; all14targets still absent.
Main sole Coder under stable plan4.2 retained every duplicate source-risk/chain claim.
Known positive memberships remain mandatory; exclusions require every claim to exclude.
Forward/reverse graph membership, risk flags, evidence and provenance use all claims.
Conflicting duplicate diagnostics and original wire indices remain; no schema/runtime change.
Before39ba:10FAIL/476PASS. Intermediate0400 exposed an ambiguous order-length bug, corrected
by comparing only identities unique in both orders. Final focused test evidence is in
main-correction-record.json;490PASS, mypy/ruff/format pass. These are diagnostic only.

The current status replaces repeated historical progress. The full prior plan and evidence
pointers remain in [the B1–B11 archive](../verification/history/sd1b-contract-through-b11-2026-09-12.md).

05:28UTC freeze9365 PASS/all2046source hashes, original431CAS/four schemas and nested
sealed snapshots; sourceb62e947d,toolchaincfd9ae3f/cacheb3b018bee8a8c4d3. Formal052721-85a1502f
created8c98 and started05:27:28. Current Planner active/actual coding proof pending. Final
focused5bf6 490PASS15.33s,mypy3f02/ruff4159/format4f52. Original docs changed after freeze only.

05:33UTC B12 terminal BLOCKED05:32:13: Planner READY01a0993c-213b-7081-a666-91fbae68a7e5/
777278B; Coder BLOCKED01a0993f-cb99-7350-bb1d-16ef1b17c47d/no edits/302772B. Observeraa4f
rejected sealed-toolchain path drift. Read-only dcc9/a4ab proves identical sourceb62e947d,
only two added standard-library bytecode files(hmac,secrets), no dependency content removal/
change after embedded-cache-path normalization. Old sealed toolchaincfd9ae3f intact; actual
766c8cc1. No proof/state mutation, Reviewer/Runner/Gateway or current artifacts. Outer1cc2
exit2/285.188s retained. Following the user's speed feedback, carry A into the bounded B1
Provider package and require combined full acceptance before any original code publication.

## Final accepted outcome

Combined A+B1+B2 and browser retention accepted as source39405cbd5683cbc88dba2d74fb7585c886fee3adc83e62b7a82f28e0b46c3809.
Publication6e23/33actual paths and post-integrationcc19 pass. All28findings are resolved
with current full Runner/artifact/Gateway evidence. Continue SD-2; real acceptance remains SD-6.
