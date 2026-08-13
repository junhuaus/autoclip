# ADR-013: Workspace membership and local token identity

Status: accepted

Date: 2026-08-13

## Context

The Web home page must serve video editors as a multi-user Project workspace. A browser-side filter over the existing global Project list would disclose other users' Projects and could be bypassed by calling descendant run, clip, render or Delivery routes directly. LiveClip is still a local-first modular monolith and must not add an external identity service as a runtime prerequisite.

## Decision

SQLite stores `WorkspaceUser` identities and unique `ProjectMember` relationships with `owner`, `editor` or `reviewer` roles. Every Project has one `owner_id` and a matching owner membership. Existing Projects migrate to the configured local administrator without rebuilding or deleting media/domain rows.

FastAPI authenticates one caller per request. `LIVECLIP_API_TOKEN` maps to `LIVECLIP_WORKSPACE_USERNAME`; optional environment-only `LIVECLIP_WORKSPACE_TOKENS` maps additional usernames to distinct long Bearer tokens. Token values never enter SQLite, logs, API responses or the frontend bundle. The global token also remains the HMAC secret for short-lived signed media URLs, so member-token configuration requires it.

Project listing joins through membership. Every run, clip, render and Delivery operation resolves the owning Project and applies the same membership check before reading or mutating it. Inaccessible resources return not-found to avoid existence disclosure. The Project owner alone manages membership. `editor` and `reviewer` describe responsibility in v1; both otherwise share the existing Project workflow rather than duplicating business rules in adapters.

The React home page consumes only member-scoped DTOs and presents “我的项目”, workload counts, search/status filters, ownership, team size and the next action. It retains an entered token only in memory.

## Consequences

Each configured local collaborator sees only assigned Projects and can use the same API, Worker and application services. Existing single-user loopback installs continue to work without a token. Operators provision credentials in ignored local configuration and restart services; v1 does not provide passwords, cookie sessions, invitations, email identity or a remote identity provider. A future authorization policy may narrow editor/reviewer mutations without changing the membership or resource-isolation model.
