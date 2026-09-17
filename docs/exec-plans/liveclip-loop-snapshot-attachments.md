# Living ExecPlan: nested snapshot attachment compatibility

Sole Coder writes this full isolated candidate. Parent baseline manifest includes the
reviewed four-prerequisite source and exact unaccepted formal Coder test patch from
Run173817-eabcba0c/session01a096b6. Original dirty source/data and failed states remain.

- [x] Inspect actual mismatch: Git reports `.python`/`.venv` links as untracked source.
- [x] Add regression with actual project ignore rules, two-level snapshot, code mutation
  and replacement dependency attachment; old helper's synthetic ignores masked this.
- [x] Genuine setup 20260912174857Z-9d4c; red regression
  20260912175242Z-fa26 proves both cases fail on first snapshot fingerprint.
  Earlier 5f42 capture unavailable is recorded ERROR, not inferred as evidence.
- [x] Initial link-compatible correction reproduced nested ignore expansion (review
  01a096c1 P1, actual probe1129 and four red regressions703b). Final entries are
  root-anchored /.venv and /.python; no nested source files or links are hidden.
- [x] Green nested snapshot/control and inherited semantic-profile regressions:
  20260912175257Z-0655 passes196 tests.
- [x] Full lint: 8bf7 exposes E501/RUF043 in pending formal Coder test patch.
  Main recorded a bounded two-expression lint-only scope amendment; exact inherited
  bytes retained separately. No runtime change. 20260912175338Z-3a94 passes
  Ruff/format321, Mypy178, schema and TypeScript.
- [x] Initial frozen Runner1117/9de2 passes1156 Python/58 Web/two browser flows;
  source f1632c9a and sealed dependencies unchanged. This does not close review P1.
- [x] Final anchored correction passes200 focused regressions3ebd and full lintafd3.
- [ ] Fresh read-only final review and actual nested snapshot preflight.
- [ ] Final formal SD-1A lint/test and Gateway on the corrected snapshot. Reuse no
  old diagnostic PASS. Full next-run gates subsume repeating the same diagnostics.
- [ ] Prepare fresh formal SD-1A handoff with exact pending Coder test hashes.

Allowed edits: .gitignore, test_loop_engineering.py and these two documents.
Recorded amendment allows only the two lint fixes in test_semantic_profiles.py. Keep all
control-plane code, permissions, allowlist, fingerprints, budgets and role profiles
unchanged. No skipped gates, old-run edits, original publication or paid-model calls.
