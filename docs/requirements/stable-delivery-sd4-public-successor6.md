# SD-4 C2 sixth successor: exact retained evidence closure

Continue from terminal BLOCKED `20260914T030913Z-7a67521a` without
rewriting its history. Planner READY, exact sole Coder
`01a09de7-c264-7413-8c31-6af7077cb402` IMPLEMENTED with no edits,
Reviewer FAIL three P2s, Tester BLOCKED, and Runner/Gateway/accepted QA
empty. Trusted Main clones all 2183 frozen source paths at
`45795e81f82f56761c09643342397c18568ad87c8965b649709f2a3ef0099eda`,
same HEAD, 1008 original accepted QA IDs and no copied input media. Never
resume an earlier Coder session or use `--last`.

The remaining evidence gaps are concrete. First, both protected verifier
paths accepted a Task self-dependency, missing stage edge or substitution
with another existing Task because they checked only referenced-ID
existence. Main now requires six uniquely ordered Stages, one-to-one
Stage/Task bindings and the exact ingest → preprocess → transcribe →
candidates → edit → proxy_render dependency chain; completion and Delivery
Tasks have no stage dependency. Regression mutations cover self, missing
and wrong-existing edges. Second, the retained Asset generation and
edit-plan revision fields were unchecked. Main now binds every Asset to
the run generation; render Assets bind the selected clip, edit-plan
revision and project revision epoch; nonrender kinds have explicit null
rules, while Delivery Assets bind the project revision epoch. A real
same-run wrong-stage producer and wrong-generation/revision/epoch mutations
must fail. Third, the post-cleanup verifier hashed only manifest-listed
files. Main now enumerates every package entry without following links,
requires the exact manifest inventory plus the manifest itself and one
assets directory, rejects extra files/directories/symlinks, and scans all
retained text Assets and ZIP text members for credential, raw lease token
or signed URL leakage. A captured synthetic browser fixture and focused
tests cover each mutation. ZIP and retained Asset SRT are parsed into
real nonempty, valid timestamped cues; media bytes and MP4 full decode
remain required.

Main owns the protected fixture, post-cleanup verifier, regression fixture
and tests, requirement, STATUS/ExecPlan, QA and publication. The fresh
sole Coder may edit only `apps/web/e2e-real/completion-goal-real.spec.ts`
if a substantive browser authorization correction remains. Preserve the
page-context authorized Delivery fetch and byte SHA-256, closed observer
before persisted manual wait and reconnect, one project/run/intent/Delivery,
and disabled sensitive browser recording. It must return BLOCKED instead
of editing protected files. No API permission weakening or source-media
mutation is allowed.

Require fresh read-only Planner/Reviewer/Tester/Gateway, one explicit sole
isolated Coder session, existing two-plan/three-code budgets and the
unchanged checked-in argv allowlist Runner in its deny-default macOS
sandbox. Reviewer PASS must close all three P2s and the earlier lineage
finding; Tester READY must specify actual Python/Web/mock/legacy and
completion browser phases. Fixed Runner lint/test PASS must share one
unchanged sealed source/toolchain; zero exit alone is insufficient. Gateway
PASS cannot override missing, mutated, stale or uncorrelated deterministic
evidence, unresolved P0/P1 or budgets.

Only after DONE, Main independently inspects the **current Runner
execution's** retained v2 package after identity-bound SQLite/media
cleanup, including exact no-follow file inventory, every Asset hash and
producer graph, manual selection/Delivery, strict raw marker chronology,
authorized page ZIP bytes and bound Asset hash/size, member checksums,
parseable SRT, full MP4 decode and complete text leakage scan. Earlier
local probes cannot substitute. Then append only newly accepted QA IDs,
trusted CAS-publish the exact SD-4 code scope and update API, recovery,
Solution/ADR, ExecPlan/STATUS and acceptance report. This remains synthetic
engineering acceptance. Do not process or modify read-only
`input/8-30.ts` or claim real provider/content/audio/hardware success.
