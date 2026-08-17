# ADR-018: Server-authorized Project discovery and private saved views

Status: accepted

Date: 2026-08-16

## Context

The professional dashboard must search and filter Projects without first loading a
workspace-wide collection into the browser. A Project result may be found through
its source filename, current selected clip title/Hook/transcript, assignee,
lifecycle or current release metadata. Private Project existence and aggregate
counts must remain unavailable after a membership or visibility revoke. Chinese
editors also need useful one- and two-character substring search, which SQLite
FTS5's default tokenizers do not provide consistently.

Saved filters are personal workflow state. They must not become shared Project
state, leak between accounts or silently overwrite a change from another tab.

## Decision

- The result unit is a Project. `ProjectDiscoveryService` and its SQLAlchemy
  repository own one canonical criteria model; Web, API and saved views reuse it.
- SQL begins with an authorized Project CTE: an explicit active membership, or
  authenticated read-only access to a `workspace` Project. System administrator
  status does not grant ordinary Project discovery access.
- Query matching uses parameterized SQLite `instr()` over NFKC/casefold UDFs.
  Current selected clips are joined only through the current Pipeline run and
  current EditPlan revision; release evidence uses the same current-revision
  fence. JSON hashtags are decoded by a bounded deterministic UDF before matching.
  We do not use FTS5 in v0.2 because its default tokenization would make short
  Chinese substring behavior inconsistent.
- Search returns bounded match evidence, unfiltered authorized dashboard facets,
  an exact filtered count and a page of sanitized Project snapshots. Page
  hydration is bounded by `limit`; no browser-side global Project scan occurs.
- Paging is stable keyset paging. The opaque cursor binds actor ID, canonical
  criteria fingerprint, sort, initial `evaluated_at`, last sort tuple and Project
  ID. All four sorts have an explicit Project-ID tie-breaker; due-time filters keep
  the first page's clock across later pages.
- Repository selection is repeated after Project hydration. If visibility,
  membership, current run/revision, page order, counts, facets or match evidence
  changed, the response fails with a safe retryable 409 instead of returning a
  mixed or stale snapshot.
- A disabled assignee is operationally unassigned. Text and explicit-assignee
  search never match a disabled identity, consistent with the Project card DTO.
- `saved_project_views` is owned by one workspace user, limited to 50 physical
  rows, and stores strict criteria JSON plus `criteria_schema_version="1"`.
  NFKC/trim/casefold names are unique per user. Creation supports
  `Idempotency-Key`; update and delete require exact integer version CAS. Other
  users receive 404, and one unsupported/corrupt local row cannot break listing
  of the user's remaining views.

## Consequences

Chinese substring search is correct and simple at the current local-workspace
scale, but it is not a relevance-ranked full-text index. Search performs a second
bounded selection read to close authorization/current-evidence races; concurrent
edits may therefore produce a deliberate 409 and UI retry. A future large
workspace can add a transactionally maintained normalized search table or a
Chinese-aware index behind the same application contract, with equivalence and
privacy tests, without changing Web authorization semantics.

Independent clip/release result screens and optimistic cross-Project bulk actions
remain separate later slices. This ADR does not create a global administrator
content-search bypass, store query history, or send transcript/search data to a
Provider.
