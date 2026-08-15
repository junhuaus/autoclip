# ADR-014: v0.2 identity, lifecycle and editor handoff boundaries

Status: accepted for staged implementation

Date: 2026-08-13

## Context

LiveClip v0.1 is a functioning local clipping system with environment-token identities and Project membership. Professional multi-user operation now requires real login, administrator-managed users, explicit Project visibility, a business lifecycle beyond processing state and selective handoff to Jianying/CapCut or publishing workflows. Treating those as extra fields in the browser would not provide authorization, auditability or recoverability.

## Decision

v0.1 remains the `0.1.0` compatibility baseline. v0.2 is delivered in independent migrations and milestones.

Authentication becomes local account plus opaque server-side session. Password verifiers use a memory-hard scheme and never leave the credential service. Browser sessions use an HttpOnly SameSite cookie; personal access tokens are separate, hashed and scopeable for CLI/API. The v0.1 environment-token map is a bootstrap/migration bridge, not the long-term user store.

Implementation status (2026-08-15): local accounts and opaque sessions are implemented. Scoped personal access-token lifecycle is still staged and is not claimed as tested; CLI/API compatibility currently retains only the bounded v0.1 environment-token bridge. When PAT work is authorized, it must follow the separate/hashed/scoped decision above rather than repurposing browser sessions.

System role (`administrator`/ordinary member), Project role (`owner`, `editor`, `reviewer`, `viewer`) and Project visibility (`private`, `workspace`) are separate dimensions. New Projects are private. All resource authorization is centralized in application policy and applied before descendant repository access. Administrator override is explicit and audited.

Project business lifecycle is stored separately from Pipeline, Render, Review and Delivery technical state. Central transitions reconcile technical facts but retain the human workflow states, actor, reason, assignment and due-date history.

Editor export is a new immutable `EditPackage`, not an overloaded formal Delivery. A package snapshots a user-selected set of current revision/render Assets. The first interchange contract is clean MP4 plus matched plain UTF-8 SRT, portable metadata and checksums. Native Jianying draft generation is excluded until a stable public contract and real import verification exist. Platform release planning is a separate `ReleaseItem` model and never implies automatic posting.

## Consequences

The design supports safe local team operation and incremental delivery without reprocessing existing media. It adds credential/session lifecycle, authorization policy, audit and migration complexity. Cookie-based Web auth requires CSRF defenses for unsafe methods; session revocation must be checked on every request. Export and release schemas require versioning and exact Asset/revision fences. Existing v0.1 API-token clients remain available during migration but are visibly deprecated for browser login.
