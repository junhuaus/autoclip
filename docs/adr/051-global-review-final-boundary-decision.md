# ADR051: Global Review decides the supplied final Boundary interval

Status: accepted and published 2026-09-16.
Date: 2026-09-15 PDT. Owner: Main and one isolated Coder.

## Context

Real mini attempt 5 completed all model stages and produced two 90-second candidates. Boundary Review
had already repaired the second candidate to cues 88--126. Global Review accepted that exact interval,
scored it 86, but repeated `content_decision=repair_boundary`. The deterministic V4/V5 validator first
requires Global Review to score the exact supplied Boundary interval and then advances only `keep`;
`repair_boundary` therefore hit `content_keep_gate`. The output was structurally valid, so the one
Schema repair was neither applicable nor invoked.

## Decision

Clarify the current Global Review Prompt: Boundary Review has already produced the interval supplied to
this stage. Global Review evaluates that interval independently. It returns `keep` when that supplied
interval is acceptable and `drop` when it is not. It must not copy Boundary Review's historical
`repair_boundary` value or request a second boundary repair. Historical schemas and validators remain
unchanged for replay compatibility.

This is a Prompt-only contract correction. It does not alter semantic scores, risks, quality gates,
publication status, duration rules, retry counts, model settings, candidate selection or Delivery.

## Consequences

Direct prompt-contract tests protect both composed profiles and prompt identity. Formal acceptance needs
fresh Planner, sole isolated Coder, Reviewer, Tester, fixed Runner lint/e2e/full-test and Gateway on one
sealed source. A later bounded real run is separate evidence; this correction cannot turn manual or
unsafe material into an automatic Delivery.

Formal successor 5 `20260916T223427Z-6f412cde` reached DONE with sole Coder
`01a0ac5f-ece1-7b12-96f5-75a0647fb631`, fresh read-only assurance roles,
fixed Runner lint/E2E/full-test PASS and Gateway PASS on source fingerprint
`1752f61cb22243f7e96598b1950663160c1aecb27ab94f9d041c2fee278ebc21`.
Trusted Main audited and published the accepted paths by compare-and-swap.
Postpublication direct Prompt tests passed 18/18. This acceptance remains
engineering evidence; mini Delivery still requires a separately guarded real
run.
