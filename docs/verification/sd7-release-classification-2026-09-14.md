# SD-7 release classification — independent evidence pass

Prepared 2026-09-14 against branch `liveclip-v2/loop-engineering`, HEAD
`6009b23859564b2bfdc193eee366afd990b9ef5d`, after accepted SD-5 B2
publication. This is a section-level evidence inventory, not the final
per-clause Product Spec verifier or a release approval. The current original
worktree has accepted uncommitted code and documentation. Product code has
not been changed by this pass.

| Product Spec area | Classification today | Direct evidence and limit |
| --- | --- | --- |
| Apple Silicon/Python/Node/FFmpeg/SQLite Doctor | Actually run on this host | Original `make doctor` QA `20260914234349Z-3478` READY. FFmpeg 8.1.2 lacks text filters; Pillow overlay fallback and VideoToolbox encode were observed. This is one host, not a clean install. |
| Installation and `make dev` operator lifecycle | Unverified as a fresh install | Local project dependencies already exist. Real Chrome fixtures launched API/Web/Worker, but a fresh `make setup` and normal `make dev` stop/restart were not run for this release. |
| Allowed-root ingest and immutable source reference | Implemented and tested; actual read-only inventory | Source SHA/size/duration for `input/8-30.ts` were verified without mutation (SD-6 inventory QA `20260913122428Z-e03f`); allowed-root and mutation regressions are part of the accepted test suite. Full 110-minute pipeline ingest was not run in SD-6. |
| Preprocess and ASR providers | Local MLX actually called on a 30-second real-source slice | MLX smoke QA `20260914234828Z-5d3d`, pinned local model, nine segments, no word timing. No current full-source Chinese accuracy or repeated-run score. OpenRouter/OpenAI ASR were not called with a regenerated Key. |
| Semantic Discovery, Boundary, Global Review and mini-lesson contracts | Implemented and tested with Mock/invalid-response fixtures | Formal SD-1A–SD-5 B2 reports and original focused tests cover deterministic validation, repair limits, lineage and recovery. One Codex smoke on synthetic text QA `20260914234954Z-ee7d` proves the tool-disabled editorial channel only. Real-source per-profile stability and quality remain unverified. |
| Clean render, SRT and Delivery ZIP | Actually run on synthetic media | Original `make demo` QA `20260914234410Z-3c86`: three candidates, 12-second 1080×1920 H.264/AAC final master, full decode, viewed contact sheet and ZIP hashes/CRC. Formal B2 real-service Chrome accepted 22 Asset rows and current package lineage. Real-content picture/audio/listening remain unverified. |
| Durable Completion, separate Worker, read-only reconnect and selection | Actually run on synthetic disposable fixtures | [Accepted SD-5 B2](stable-delivery-sd5b2-accepted-2026-09-14.md) formal lint/e2e/full test and independent current artifacts; 2425 Python/78 Web/Mock and two real Chrome cases. Original full `make test` QA `20260914T235154Z-d6b3` is running and has no verdict yet. |
| API/Web authorization, media by Asset ID and secret redaction | Implemented and tested on disposable fixtures | Accepted B2 real Chrome checked current session, denial, CSRF/replay and canonical ZIP; current product tests exercise server-side authorization. No credential value is used or exposed in this report. |
| Database backup/restore and no-clobber recovery | Tested; operational drill pending | Existing `tests/integration/test_database_backup.py` covers WAL, integrity, symlink and no-overwrite. A separate disposable CLI/Project/Completion/Asset drill is prepared but not yet run. |
| 2–4 hour performance and real quality acceptance | Gap in evidence | Supplied `8-30.ts` is 110m34s; the longest inventoried `input/*.ts` is under two hours. No distinct 2h/4h source, frozen human labels, full-source repeated profile batch or human listening/visual sign-off exists. Both Completion presets remain experimental. |
| Cloud smoke | Unverified, conditional | Doctor found a local OpenRouter configuration but did not establish a regenerated Key. The previously exposed Key is ineligible and was not used. Product Spec requires cloud smoke only with valid available configuration. |

Source of truth: [Product Spec](../PRODUCT_SPEC.md), [SD-6 real acceptance plan](../exec-plans/liveclip-sd6-real-acceptance.md), [SD-7 plan](../exec-plans/liveclip-sd7-release-recovery.md), `qa/pipeline.jsonl` and `qa/test-report.md`. The last two are append-only evidence; a test request alone is not a PASS.

Remaining verifier work: close the original full-test QA entry, execute the
disposable recovery and backup/restore drills, then split each Product Spec
clause into a direct `implemented / tested / actually run / unverified / gap /
risk` finding with one evidence path. Do not promote a section-level test
result to an untested real content, cloud or long-input clause.
