# ADR 035: Managed dependency links in nested execution snapshots

Status: proposed isolated prerequisite, 2026-09-12.

Formal SD-1A Run20260912T173817Z-eabcba0c reached Planner READY and Coder IMPLEMENTED.
Coder01a096b6-347b-7f23-934e-a81b13a76948 added only authorized semantic-profile tests;
they were not executed. The trusted process then rejected the assurance snapshot:
its source fingerprint differed from the coding workspace. No acceptance/publication.

Actual Git untracked output includes `.python` and `.venv` symlinks attached after the
initial source snapshot. Directory-only ignore entries do not match these links.
The next snapshot correctly excludes managed dependencies and reattaches the sealed
toolchain, so the inconsistent ignore rules cause a fingerprint mismatch.

Change only the two root-anchored ignore entries to `/.venv` and `/.python`, covering
managed root directories and links while retaining nested same-named source files
and links in Git/fingerprint coverage. Do not waive
or redefine source/toolchain fingerprint checks, copy Coder dependency replacements,
modify blocked states or increase budgets. A regression uses the real project ignore
file, verifies coding-to-assurance round trips and source edits, and confirms a replaced
untrusted local dependency directory is ignored and rebound to the frozen toolchain.
Earlier synthetic tests used link-compatible ignore patterns and missed this failure.

Fresh review01a096c1 reported P1 on an initial unanchored correction. Separate real
Git probe1129 and four red unit cases703b confirmed the extra nested-file/link blind
spot. The final anchored correction addresses that finding without changing source
fingerprint logic. The initial full Runner1117/9de2 passed its frozen snapshot but
does not accept the P1 correction or replace final formal SD-1A gates.

The pending exact Coder test patch is inherited and recorded in the new candidate's
baseline manifest. It still needs independent SD-1A review and actual final tests.
Preserve the blocked run/session/workspace and all earlier receipts; use a new formal
Run only after this changed condition is verified and independently reviewed.
