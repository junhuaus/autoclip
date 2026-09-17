# SD-4 B2 bounded acceptance — 2026-09-13

The one-bound immutable Delivery coordinator is accepted in isolated candidate
`b2_successor` only. Formal run `20260913T225754Z-b71bf00a` reached DONE:
fresh Planner READY, sole Coder session
`01a09d04-67c2-7c10-9147-de9d4124a25b` IMPLEMENTED, fresh Reviewer PASS
without findings, Tester READY, fixed Runner lint/test PASS and independent
Gateway PASS without blockers. The Coder changed only the completion repository,
delivery eligibility helper and focused integration tests. The trusted outer
process published those three paths into the isolated candidate after all gates.

Fixed lint QA `20260913T231507Z-a1b2` PASS in 25.193 seconds. Fixed test QA
`20260913T231533Z-cc53` PASS in 834.025 seconds: 2269 Python tests,
58 Web tests, one mock browser flow and one real local API/Worker/FFmpeg
browser flow. Both commands used source fingerprint
`747b7dded484fa640a0fcfa6943bb68c35557e3e6eed0344fbd2612fc4993541`,
sealed toolchain fingerprint
`608316b33f894762f45e0ad27471e596627f3295d4877a99407dd8e64e240e03`
and HEAD `6009b23859564b2bfdc193eee366afd990b9ef5d`; command-side source
and toolchain remained unchanged. The candidate root QA journals preserve
1006 unique request IDs and matching report sections. Main appended the two
accepted Runner records to the original append-only QA history.

Independent deterministic Gateway evaluation with retained-file checking
PASS had no reasons. The accepted candidate and read-only assurance snapshot
matched on all 2139 source paths and hashes. The separate retained-data audit
bound the final Coder source and three changed paths to 22 disposable SQLite
databases, current Alembic revision, `quick_check=ok`, zero FK errors, saved
intent/action/idempotency/Delivery IDs and five successful bound packages.
It verified manifest, ZIP, MP4/SRT and Asset bytes/hashes and actual ffprobe
video streams. The final audit SHA256 is
`bf44f9baa235c646bcb980870b224123bb3037b542a5e6531688daf95ea0f0f5`.
After DONE, Main copied 132 synthetic diagnostic files (131,920,031 bytes)
into the accepted candidate's ignored `.loop/diagnostics/b2-successor-accepted`
without copying pytest symlinks or changing the source fingerprint. The
copy receipt SHA256 is
`cad08beba3772b2f30a41fc6890cb1f0cc746078310303381e55ffd26e667661`.
These diagnostics support inspection; they do not replace fixed Runner gates.

The earlier B2 run `20260913T215934Z-1041ea6b` remains terminal BLOCKED
before Runner, with its Reviewer P1/P2 and Tester block preserved. This
successor inherited its final 2138-path Coder source exactly and used a new
Coder session and full gates. One derived baseline receipt field reported
2132 identical inherited paths by subtracting the newly added manifest; the
independent full-map comparison proves 2133. The bound outer count correction
records this nonfunctional bookkeeping error. Accepted-B1 and blocked-B2
per-path manifests, HEAD, QA roots and final source fingerprints matched;
the frozen formal candidate was not modified to conceal the discrepancy.

This bounded acceptance covers strict saved selection matching, current
authorization at effects and replay, one stable delivery action and immutable
Delivery ID/version, combined prior-version/lost-response recovery, compatible
replacement-master waits, configurable delivery retry allowance, nonempty
manifest/Asset/ZIP success and owned-lease artifact inspection with cancellation
and crash recovery. It does not claim persistent completion Worker dispatch,
public goal API/CLI, full SD-4, original-product publication, real Chinese
content/audio quality, cloud-model behavior or two-/four-hour performance.
C1 must wire the accepted coordinator into the persistent Worker and bootstrap;
C2 then supplies public commands and complete SD-4 acceptance.
