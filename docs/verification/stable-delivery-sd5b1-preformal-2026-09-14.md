# SD-5 B1 isolated preformal baseline

Status: preparation only; no B1 formal Coder, Runner, Gateway, acceptance
or original publication. Accepted predecessor is
[SD-5 A](stable-delivery-sd5a-accepted-2026-09-14.md), formal
`20260914T091046Z-d9794226` DONE.

Trusted Main cloned exactly 2180 accepted SD-5 A repository source paths,
HEAD `6009b23859564b2bfdc193eee366afd990b9ef5d`, and all 1017 QA
request/report IDs into the isolated `a_candidate`. The original retained
75 ignored local evaluation paths which were deliberately not copied.
No input media, real Project data, credentials or old `.loop` state entered
the candidate. The [full accepted-source map](stable-delivery-sd5b1-clone-source.json)
is a byte-identical role-visible copy of the trusted clone receipt, SHA-256
`85bb0435850960a0fa19dc50ed3e4e0e95e42d7c5a08b3bf4469a173cba9d89e`.
The receipt records the accepted-source fingerprint, QA hashes, sealed
toolchain fingerprint and accepted SD-5 A publication receipt hash. Later
Main-owned B1 contract edits are intentionally not claimed as accepted
SD-5 A paths; the formal Loop run must seal their new exact fingerprint.

Main froze [ADR047](../adr/047-observable-completion-progress.md), the
[bounded B1 requirement](../requirements/stable-delivery-sd5b1-progress-draft.md),
strict Python/Web DTO, composite per-attempt progress table and Alembic
revision `c84f5d1a702e`. Local diagnostic `make lint` passed (Ruff,
format, MyPy over 199 sources, schema comparison and Web typecheck); 21
unit/migration tests passed. `make loop-doctor` returned READY for this
candidate and three fixed command IDs. These commands were not fixed Runner
evidence and establish no B1 runtime behavior. Formal implementation,
fault tests, current browser/media inspection and independent source
audit remain required before exact publication.
