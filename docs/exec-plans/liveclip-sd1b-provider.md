# SD-1B-B1: Preserve V5 lineage through provider and cache calls

Accepted and integrated in combined formal `20260913T072557Z-1fd20958` on2026-09-13.
See [accepted report](../verification/stable-delivery-sd1b-accepted-2026-09-13.md). Historical diagnostics below remain preserved.

## Outcome and scope

OpenAI, Codex CLI and the mock provider must return the complete typed V5 Discovery,
Topic Chain and Boundary result. Initial output and the sole repair must use the same
immutable request authority. Raw business JSON reaches the accepted A collector before
SDK parsing or model serialization can erase malformed JSON or field omissions.
The stage cache preserves every V5 field and rejects mismatched identities.

This package prepares provider/cache support. B2 then activates V9 together with Stage,
final result, persistence and reload; B1 alone does not close user-visible SD-1B.

Main owns this plan, the requirement, cache schema allowlist, source freeze and integration.
The sole isolated Coder may implement or repair these explicitly bounded paths:

- `src/liveclip/providers/llm/structured.py`
- `src/liveclip/providers/llm/semantic_lineage.py` (new provider context adapter if needed)
- `src/liveclip/pipeline/semantic_lineage.py` (shared cue-based validation only)
- `tests/unit/test_structured_repair_preflight.py`
- `tests/unit/test_semantic_lineage.py`
- `tests/unit/test_semantic_lineage_provider.py` (new)

Main extends `src/liveclip/pipeline/semantic_cache.py` before the formal freeze. Preserve
all V4 resources, four frozen V5 schemas, provider contracts for historical prompts,
runtime dispatch, config versions/defaults, dependency locks and Loop policy.

## Implementation

1. Dispatch the exact three V5 response classes before their inherited V4 classes.
   Check request stage, contract, schema, prompt identity and mini profile consistently.
   Reject malformed required request context before provider I/O; present empty context
   remains authoritative. Repair validates against `immutable_request`, never a model's
   replacement candidate, routes, risk scope or source interval.
2. Expose shared validation over actual `SemanticCue` records with their original IDs
   and absolute times. Existing whole-transcript APIs delegate to the same checks.
   Never make a fake excerpt `TranscriptDocument` that renumbers IDs. Full and local
   authority must agree on shared cue IDs/times. Preserve actual ownership, chain scope,
   durations and Boundary span/evidence constraints. Missing remote timing stays unknown.
3. OpenAI's existing raw-response capture precedes SDK parsing. Validate the actual
   captured business text on successful parsing as well as on `ValidationError`.
   A parsed object reserialization cannot replace missing original V5 text. Preserve
   incomplete/refusal/tool/multipart failure precedence and original part indices.
4. Codex applies the same strict raw collector before returning a typed result and after
   its sole repair. Every invalid-attempt path carries the exact response model and full
   indexed errors. Preserve duplicate JSON keys and nonfinite failures; never reduce them
   to a successful `json.loads` dictionary. Retain only existing redacted, bounded business
   evidence; no transport envelope, hidden reasoning or credential persistence.
5. Mock fixtures author V5 routes, source risks and treatments explicitly. They use the
   same validators and retain source flags plus sensitivity for uncertain treatments.
   Synthetic decisions never establish real content or risk-clearance acceptance.
6. Cache allowlist adds only `DiscoveryBatchOutputV5`, `TopicChainReviewV5` and
   `BoundaryReviewV5`. Historical key/record bytes remain unchanged. Store validated local
   Discovery identities; B2 namespaces once after fresh/cache resolution. Cache load is
   typed and identity-checked; the Stage context validator remains mandatory in B2.

Use the corrected A collector for defaults, duplicate claims, scope membership and full
error collection. Do not create a second copy of those business rules in the provider.

## Acceptance

- Valid raw V5 results survive OpenAI, Codex, mock and cache roundtrips without losing
  original IDs, many-to-many routes, nested risk evidence or treatments.
- Fake transport tests cover SDK parse failure and success, multipart/refusal/incomplete/
  unexpected output, strict duplicate keys/nonfinite JSON, optional defaults beside an
  independent schema error, more than 200 indexed errors, sole-repair success/failure,
  original part indices, immutable authority and existing redaction/failure precedence.
- Local cue fixtures start above ID 1 and exercise ownership, chain evidence scope,
  expansion, durations and conflicting shared cue facts. No fabricated timing authority.
- Cache tests exercise V5 roundtrip/tampering and exact historical compatibility.
- Existing V8 Python/Web/browser flows and newly generated synthetic mini artifacts pass
  fresh allowlisted sandbox Runner lint/test; inspect the current artifacts and full logs.
- Fresh read-only Planner/Reviewer/Tester/Gateway, exact-session isolated Coder, unchanged
  retry budgets and complete-log limits. Trusted publication requires current source,
  toolchain, evidence and original CAS. Local diagnostics alone never establish acceptance.

## Progress and recovery

- [x] Concrete provider/cache package prepared from inspected entry points and A API.
- [x] Bind terminal B12's exact corrected source and prepare a complete isolated candidate.
- [x] Implement the provider adapter, shared cue checks, mocks and main-owned cache change.
- [x] Concentrated diagnostics, formal gates, current artifact inspection and publication.
- [x] Continue immediately to B2 actual V9 runtime and reload flow.

No real or paid business-model batch, source-media mutation, migration, global config
change, commit, push or external publication is introduced. A failed call retains the
existing failure/retry/audit behavior. Terminal engineering runs and evidence remain intact.

## Packaging decision after user feedback

The user requested faster continuous development while preserving Coder/Runner safety.
B12 formal20260913T052721Z-85a1502f ended BLOCKED05:32:13 before any Coder edit: actual
snapshot proof rejected toolchain drift. Exact diff a4ab found only new standard-library
hmac/secrets bytecode caches; no removed/changed dependency content after normalizing the
expected embedded cache paths. All2046source hashes and431original CAS paths matched.
The failed proof and terminal budget are preserved; no accepted A result is claimed.

Continue with the bounded six-file Provider task from that exact source and carry all
26A findings and490regressions into combined acceptance. This changes package boundaries,
not product semantics or gate requirements. There is no separate unaccepted A publication.
The new package must satisfy A's L01–L10 plus B1 acceptance on one frozen source/toolchain.
Use project-local preflight before freezing; run subsequent trusted Python helpers with
bytecode writing disabled and verify the actual Coder snapshot before writes. Do not alter
the checked-in Loop policy, reset terminal runs, expand retry budgets or accept stale proof.

05:47UTC implementation diagnostic evidence: preparation7bbd verified2046inherited source
hashes/original431CAS; setupef17 PASS. Five local-cue casesfcef FAIL before shared extension;
ee2a495PASS after. First Provider integration57c3:6FAIL/530PASS; two Mock schema defects and
four tests' expected exception class corrected. Safe format/import corrections retained;
3c9244Provider tests PASS. Final combined946d747PASS29.29s, including actual fake OpenAI/
Codex first-call and sole-repair paths, multipart205indexed errors per part, three typed
cache roundtrips/tampering and historical V4 compatibility. Mypy327d and ruffeea0 PASS.
These are diagnostics only. No formal run, original code publication or actual V9 activation
yet. All26A findings remain pending combined formal revalidation, with A schema bytes frozen.

05:57UTC: freeze7fe1 PASS/all2050source paths, original431CAS and exact schemas; source
9fa7f78d28d3efd8a100ecdeed4f12014c160047b5f11a635388587c45cb9c09, toolchain
ecf59a5261bf95423c7914c5d5ece9443e4df4898cfdcaaa650e8f198f65e5c8.
Create1a29 verified the sealed tree before and after creation. Formal20260913T055146Z-84311696
started05:52:21; Planner READY05:55:19. Actual coding-1 observere02e PASS05:55:42 verifies
the complete source and unchanged toolchain. First Coder active; no acceptance or publication.

06:02UTC: exact Coder01a09955-f241-7fa3-83e9-870c67da94ee IMPLEMENTED06:01:07. Two allowed
files changed: copy caller-owned V5 request data before provider I/O/repair; four synthetic
OpenAI/Codex mutation regressions added. Coder verified syntax, not runtime tests. Reviewer
active. Outer8d51 verifies only those two source changes and all four frozen schema bytes;
assurance source7e15321275677842d1e89cf3bb4b0d90ceab59dfbdf2d37d5e565f8210184cd0.
Current artifact observers are running. No original publication or gate waiver.

06:05UTC terminal: Reviewer FAIL/one P2, Tester01a0995c-7f87-7870-9a75-c40f07eb9567
BLOCKED06:04:25 confirms logical-window identity is lost in request authority. Formal
outer5463 exit2/724.614s. No Runner/Gateway/current artifacts; observersd925/0773 correctly
failed when the run terminated. No original code published. Continue the correction with
actual V9 runtime under liveclip-sd1b-runtime.md; carry all existing acceptance obligations.

## Final accepted outcome

Combined A+B1+B2 and browser retention accepted as source39405cbd5683cbc88dba2d74fb7585c886fee3adc83e62b7a82f28e0b46c3809.
Publication6e23/33actual paths and post-integrationcc19 pass. All28findings are resolved
with current full Runner/artifact/Gateway evidence. Continue SD-2; real acceptance remains SD-6.
