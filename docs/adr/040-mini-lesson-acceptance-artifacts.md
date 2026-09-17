# ADR040: Retain synthetic mini-lesson acceptance artifacts

Status: bounded isolated acceptance correction, 2026-09-12.

Formal193445-7c87836e passed independent Reviewer, Tester and actual same-source
Runner lint/test (1212 Python,58 Web,two browser flows), but Gateway blocked it:
its 125-second synthetic mini integration flow left no retained MP4/SRT/quality
report after Runner scratch cleanup. Short browser packages are separate evidence.
Preserve that terminal state and all seven prior budgets and evidence.

Extend only the existing mini integration test. Keep its real persistent
PipelineService/StageTaskRunner/SQLite/FFmpeg flow and mock ASR/LLM. Explicitly
assert v8/current quality contract, persisted configuration fingerprint, semantic
run/source identity, unchanged source media,90–300 second output, valid independent
SRT timeline, H264/AAC, successful full decode and the report's media hash.

Copy the known fixture's MP4,SRT,quality report/contact sheet,rough candidates,
edit plans and transcript to the fixed ignored apps/web/playwright-report/mini-lesson
root, qualified by the trusted generated run UUID. This directory is already in
the checked-in Runner writable allowlist and survives later Playwright cleanup of
test-results. No sandbox, Runner command, permission, dependency or production
changes are required. Use existing bounded no-follow immutable file publication;
write the hash manifest last so incomplete copies are never acceptance evidence.

The manifest identifies synthetic engineering evidence, exact run/project/source,
persisted configuration and every file hash. The enclosing fresh Runner execution
and QA record supply source/toolchain identity; external review must correlate both.
Do not mark visual inspection passed automatically. A reviewer must read the actual
quality report/SRT, inspect the image/media and bind the retained path/hashes to the
same formal Runner execution. Synthetic media does not establish real semantic
quality, hardware performance or SD-6 paid/real-media acceptance.

Sole Coder writes only this ADR, its ExecPlan and the existing integration test.
Complete inherited production/control-plane source stays unchanged. Fresh independent
review and full formal roles/Runner/Gateway are required before exact CAS integration.

Diagnostics72aa:313 related tests passed; full lint4d00 and Doctor6694 passed.
Independent b5c1 inspected seven retained files and full-decodes the120-second
H264/AAC MP4;12 SRT cues stay within duration. Contact sheet actually viewed.
These current local diagnostics precede, and cannot replace, formal Runner gates.
