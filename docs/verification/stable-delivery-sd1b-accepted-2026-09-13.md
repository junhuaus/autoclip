# SD-1B engineering acceptance — 2026-09-13 PDT

Accepted and integrated. Formal `20260913T072557Z-1fd20958` reached DONE with fresh independent roles and
same-source/toolchain Runner gates. Trusted revalidation657a and original CAS88af preceded
publication6e23:33actual code/test changes,22new files, within the37-path scope. Four scope
paths were unchanged. Post-integrationcc19 verifies453original code paths, unchanged locks,
historical archives and all18optional local-ASR package versions. No commit or push occurred.

New mini requests now use V9/result5 with complete source and risk lineage, persisted
rough/final validation, exact cache identities and recovery checks. Other new algorithms
retain V8; historical V2–V8 fields/fingerprints remain exact. This is synthetic engineering
acceptance. SD-2 through SD-7, including real content/model/audio/hardware acceptance, remain open.

## Accepted identity

- HEAD: `6009b23859564b2bfdc193eee366afd990b9ef5d`, branch liveclip-v2/loop-engineering.
- Source: `39405cbd5683cbc88dba2d74fb7585c886fee3adc83e62b7a82f28e0b46c3809`.
- Toolchain: `954cb20d915a8e23e9a416718700e75b49efa37611831b5edfb9dce51d747bbe`.
- Assurance: `/Users/junhuaxu/Library/Caches/LiveClip/loop-toolchains/7f1a58aee6718594/executions/20260913T072557Z-1fd20958/assurance-1-1`.
- Current test execution: `/Users/junhuaxu/Library/Caches/LiveClip/loop-toolchains/7f1a58aee6718594/executions/20260913T072557Z-1fd20958/20260913T073301Z-fdae`.
- Full records: `.loop/development/sd1b-retained-browser-evidence-20260913/`.
- Publication receipt: `.loop/development/sd1b-retained-browser-evidence-20260913/original-publication-20260913T074611Z/receipt.json`; contains exact before/after hashes
  and retained backups for every replaced original file.

| Role | Exact session | Verdict | Complete capture bytes |
| --- | --- | --- | --- |
| planner | `01a099a8-ca94-7731-9d93-4b4286eca808` | READY | 136939 |
| coder | `01a099ab-1e49-74b1-8551-e4a0d93c6414` | IMPLEMENTED | 155827 |
| reviewer | `01a099ac-985b-79d0-8cb6-e372b2a16dbe` | PASS | 150038 |
| tester | `01a099ad-d48d-7a13-b809-a3f32217ffb4` | READY | 36628 |
| gateway | `01a099b4-ea76-7f02-89cf-0da16a244c1b` | PASS | 310656 |

Coder returned IMPLEMENTED/no edits. Reviewer PASS/no findings; Gateway independently
revalidated all28carried contract/provider/retention findings with no unresolved P0/P1/P2.
The accepted snapshot and all terminal history remain intact. No safety/budget expansion.

## Deterministic checks and actual artifacts

| Command | QA ID | Result | Complete log SHA-256 |
| --- | --- | --- | --- |
| lint | `20260913T073234Z-1477` | PASS, 27.544s | `44c990715bfe8d13d9952cbc12fa92099b4ec29fc2e1a1c703d441cd4ca6cb76` |
| test | `20260913T073301Z-fdae` | PASS, 382.509s | `2972d61a595ded9965b15b939421dd89c883ce45795e87693349d018ab23c61e` |

1818Python tests pass with13warnings in315.09s;58Web tests and two browser flows pass
(11.4s mock UI,23.0s actual local API/leased Worker/SQLite/FFmpeg). Before/after source,
HEAD and toolchain match. The actual tests cover V9 configuration/import/lease/StageWork,
complete source/chain/reverse-unit/risk authority, five actual quality outcome groups,
zero candidates, six rehashed persistent Stage faults and cross-generation cache recovery.

Current mini observer5450 and independent Gateway verify both eight-file manifests:

| Configuration | Product run | Manifest SHA-256 |
| --- | --- | --- |
| V8 | `7729dde2cc714799b7310ca9b06d6ff4` | `0f129a671121b1ccf05c63d7dfb92b76312b60061c651782e8ff71ed1c300220` |
| V9 | `3e63dfbe98724c2eaa912c3293f6993b` | `19807d0613e100a70a3db96ab4d6f52e4cd4a2295fe5ea3d16953fb238eb1f3a` |

Each125-second generated input yields a120-second H264/AAC MP4 and12valid clip-relative
SRT cues. Complete rough/edit/transcript/quality/contact artifacts and redacted terminal
SQLite audit are hash-bound. V9 has6succeeded stages/tasks,8attempts from recovery, one
candidate/revision and23assets; V8 has6attempts. The current source/graph/ledger/partition/
persistent ID bindings pass. Main and Gateway actually viewed both0.5/60/119.5s contacts.

The real-browser product run is `7e596db61a9f4c7ba7d83e9a4fe01c20`.
Its current command prints the retained manifest under
`apps/web/playwright-report/browser-packages/<runId>/manifest.json`; its two verified ZIP
snapshots survive scratch cleanup. Manifest SHA-256:
`6dcafb8c124457f5c03f823e7c70bb66e14aa9d7660f40d9c083ff0a4711d84c`.
The manifest binds run/project/config/source, sizes and hashes; both internal manifests
and all4delivery/9release checksum entries pass. Independent inspection1aca also validates
22terminal failed-state SQLite fixtures,66redacted JSON records and90indexed part errors.
The unique browser video fully decodes (8seconds,H264/AAC,twoSRTcues). Main viewed its preview
and all four current browser screenshots; Gateway viewed the screenshots and mini contacts.

Exact artifacts and observations: current-mini-inspection.json, current-mini-visual-review.json,
formal-artifacts/retention.json, formal-inspection/receipt.json and
current-browser-visual-review.json beneath the full-record directory above. Hashes bind all
observations to this exact test; no prior run or local diagnostic substitutes.

## Preserved failures and correction

Prior runtime formal20260913T063915Z-e72e391f remains terminal BLOCKED. Its final Reviewer
and Runner passed, but Gateway could not find browser ZIPs after normal cleanup. Main's
outer copies were real but not discovered by that role. The concrete three-file repair
retains the exact pinned/validated ZIP bytes inside final Runner reports with no-follow
dirfds, exclusive creation and atomic manifest-last publication. Unitb09d11PASS, mypyd174,
actual browserd9d4 and independent after-cleanupdfea prove that prerequisite before this
fresh full run. Formatting diagnostic68da is preserved; SQL literal wrappingc527 passes.

Outer closure48f6 initially compared artifact containment to the assurance workspace;
Runner stores artifacts in a separate correlated execution snapshot. Corrected657a compares
the actual execution root and additionally verifies its source fingerprint. No formal
state, source, test result or acceptance criterion changed; no finding closed on the failure.

Earlier A/B1/runtime failures, exact sessions and retry budgets remain preserved in the
historical plans and [status archive](history/sd1b-status-before-browser-retention-2026-09-13.md).
No terminal run was revived and no stale PASS used. Original source media, user data,
credentials, optional ASR environment and unrelated dirty code remain unchanged.

## Recovery and next work

Use [mini recovery](../mini-lesson-recovery.md), [Loop recovery](../loop-engineering.md) and
the [stable-delivery plan](../exec-plans/liveclip-stable-delivery.md). Current retry resumes
processing; durable delivery intention is still SD-4. Remote exactly-once is not claimed.
Next implement [SD-2](../exec-plans/liveclip-sd2-semantic-transport.md) from this accepted
source, then bounded queues/readiness, durable completion and shared presets/progress.
Synthetic colors/mock ASR/LLM do not establish real semantic quality or audible output.
Real batches still require recorded input/cost/time boundaries and actual inspection.
