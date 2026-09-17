# ADR038: Response-state precedence before business Schema parsing

Status: isolated bounded correction,2026-09-12. Main is sole Coder.

Formal185855-fabb9e22 is terminal BLOCKED after1plan/1code, Reviewer incomplete+Schema-invalid
P2 and Tester; no Runner/Gateway/publication. Preserve52e0fb5a and exact Coder01a09700.

For current contract only, extract the minimal response failure state before SDK business
parsing. Keep the existing priority: non-completed status, refusal, unexpected output or
ambiguous multiple business texts, then ordinary business Schema/domain errors. SDK
ValidationError must not replace an already observed response failure with OUTPUT_INVALID
and accidentally grant semantic repair. Keep available sole/indexed business text, Schema
errors, actual phase/failure code, call linkage and existing credential redaction. Never
retain transport headers or reasoning. Historical provider behavior and sole-output repair
remain unchanged; no extra retries, budget/policy/wire/Prompt changes.

Seventeen actual SDK audit variants cover initial/repair non-completed responses with
Schema-valid/invalid single/multipart business text; initial/repair refusal and unexpected
output plus Schema errors; ambiguous completed outputs; invalid repair and repair budget. Exercise actual SDK transport,
existing fenced audit Assets, handler exception mapping and real StageTaskRunner/repository
failure persistence. Set fixture task retries to zero to isolate semantic call counts; do
not claim this changes production stage retry policy (SD-3 remains separate).

Only structured.py, test_semantic_profiles.py and this ADR/ExecPlan are writable. All previous
states/evidence and original source/data stay intact. Independent review and new full formal
gates remain mandatory after verified correction; no unconditional restart or budget reset.

Actual evidence: corrected REDbcbd reproduces four precedence failures; firstfe46 was a
fixture binding error. Broad492f exposed an old synthetic envelope missing its already
completed parsed status; the fixture now models a consistent envelope.299 targeted37df PASS.
Seventeen real SQLite terminal states and51redacted JSON artifacts inspected with project
Python/SQLite fae2; system SQLite ea92 could not open these DBs and is not evidence.
Full lint40b8 PASS and Doctor5eeb READY. Fresh independent review follows.
All diagnostic failures remain recorded.
